import contextlib
import importlib.util
import io
import json
from pathlib import Path
import struct
import tempfile
import time
import unittest
from unittest.mock import patch
import zlib

spec = importlib.util.spec_from_file_location("pixel_radar", Path(__file__).resolve().parents[1] / "radar.py")
r = importlib.util.module_from_spec(spec)
spec.loader.exec_module(r)


def png(size=256):
    def chunk(kind, body):
        return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body) & 0xffffffff)
    width, height = size if isinstance(size, tuple) else (size, size)
    sample_x, sample_y = min(width, 256), min(height, 256)
    raw = b"".join(b"\x00" + bytes([50, 100, 200, 180]) * sample_x for _ in range(sample_y))
    return (r.PNG + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


def rect_png(width, height):
    """A genuinely sized image, unlike png() which fakes mismatched dimensions."""
    def chunk(kind, body):
        return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body) & 0xffffffff)
    raw = b"".join(b"\x00" + bytes([50, 100, 200, 180]) * width for _ in range(height))
    return (r.PNG + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


def wind_payload():
    now = int(time.time())
    start = (now - 3 * 3600) // 900 * 900
    times = [r.iso_offset(start + index * 900) for index in range(29)]
    return [{"latitude": 45.0 + row // 7 * 0.25, "longitude": 4.0 + row % 7 * 0.25,
             "minutely_15": {"time": times, "wind_speed_10m": [10.0] * len(times),
                             "wind_direction_10m": [225.0] * len(times), "wind_gusts_10m": [20.0] * len(times)}}
            for row in range(35)]


def api(stamp=None, nowcast=()):
    stamp = int(time.time()) - 600 if stamp is None else stamp
    return {"host": r.RADAR_HOST,
            "radar": {"past": [{"time": stamp, "path": f"/v2/radar/{stamp}"}], "nowcast": list(nowcast)}}


def stream(city, action="load"):
    """Run one backend action and return its streamed NDJSON lines."""
    output = io.StringIO()
    with contextlib.redirect_stdout(output):
        r.main([action, json.dumps(city)])
    return [json.loads(line) for line in output.getvalue().splitlines() if line.strip()]


class RadarTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.old = r.STATE, r.CACHE
        r.STATE = Path(self.temp.name) / "state"
        r.CACHE = Path(self.temp.name) / "cache"
        self.city = {"name": '<img src="https://evil.test/tracker">', "latitude": 45.75, "longitude": 4.85}

    def tearDown(self):
        r.STATE, r.CACHE = self.old
        self.temp.cleanup()

    def test_disabled_radar_never_contacts_rain_sources(self):
        r.configure({"enabled": False})
        with patch.object(r, "download", side_effect=OSError("offline")) as download:
            lines = stream(self.city)
        meta = lines[0]
        self.assertEqual(meta["settings"]["enabled"], False)
        self.assertEqual(meta["rain"]["frames"], [])
        self.assertTrue(all(line["kind"] != "frame" for line in lines))
        for call, _ in download.call_args_list:
            url = call[0]
            self.assertFalse(any(host in url for host in ("rainviewer", "brightsky", "dwd.de")), url)

    def test_settings_are_bounded_and_persisted_separately(self):
        r.save_json(r.STATE / "settings.json", {"cities": [self.city]})
        prefs = r.configure({"enabled": True, "zoom_level": 2})
        self.assertEqual(r.settings(), prefs)
        self.assertEqual(r.read_json(r.STATE / "settings.json", {})["cities"], [self.city])
        for change in ({"enabled": "yes"}, {"zoom_level": 4}, {"zoom_level": True}, []):
            with self.assertRaises(ValueError):
                r.configure(change)

    def test_old_zoom_setting_migrates_to_the_same_extent(self):
        r.save_json(r.STATE / "radar-settings.json", {"zoom": 6})
        self.assertEqual(r.settings()["zoom_level"], 0)
        r.save_json(r.STATE / "radar-settings.json", {"zoom": 3})
        self.assertEqual(r.settings()["zoom_level"], -2)
        r.save_json(r.STATE / "radar-settings.json", {"zoom": 99})
        self.assertEqual(r.settings()["zoom_level"], 1)

    def test_rain_and_wind_switch_separately_and_legacy_enabled_seeds_both(self):
        # A stored plain `enabled` seeds both sequences once.
        r.save_json(r.STATE / "radar-settings.json", {"enabled": False})
        prefs = r.settings()
        self.assertFalse(prefs["rain_enabled"] or prefs["wind_enabled"])
        self.assertFalse(prefs["enabled"])
        r.configure({"rain_enabled": True})
        prefs = r.settings()
        self.assertTrue(prefs["rain_enabled"] and not prefs["wind_enabled"])
        self.assertFalse(prefs["enabled"])
        # A legacy `enabled` change still moves both sequences together.
        r.configure({"enabled": True})
        prefs = r.settings()
        self.assertTrue(prefs["rain_enabled"] and prefs["wind_enabled"] and prefs["enabled"])
        for change in ({"rain_enabled": "yes"}, {"wind_enabled": 1}):
            with self.assertRaises(ValueError):
                r.configure(change)

    def test_load_skips_disabled_or_unrequested_sequences(self):
        fetched = []

        def fake_wind(*args, **kwargs):
            fetched.append("wind")
            return {"provider_name": "Open-Meteo", "source_url": "", "step_minutes": 15,
                    "now_index": -1, "frames": []}

        def fake_rain(*args, **kwargs):
            fetched.append("rain")
            raise ValueError("no rain")

        def fake_download(url, limit, idle=8):
            return b"{}"

        r.save_json(r.STATE / "radar-settings.json", {"rain_enabled": False, "wind_enabled": True})
        with patch.object(r, "wind_timeline", fake_wind), \
             patch.object(r, "dwd_timeline", fake_rain), \
             patch.object(r, "rainviewer_timeline", fake_rain), \
             patch.object(r, "download", fake_download), \
             patch.object(r, "tile", lambda *args, **kwargs: ""):
            lines = stream(dict(self.city, modes=["rain"]))
            self.assertNotIn("wind", fetched)
            self.assertTrue(lines[0]["rain"].get("disabled"))
            self.assertTrue(lines[0]["wind"].get("disabled"))
            fetched.clear()
            lines = stream(dict(self.city, modes=["wind"]))
            self.assertEqual(fetched, ["wind"])
            self.assertFalse(lines[0]["wind"].get("disabled"))
            self.assertTrue(lines[0]["rain"].get("disabled"))

    def test_bad_coordinates_and_nonfinite_values_are_rejected(self):
        for lat, lon in ((91, 1), (0, 181), (float("nan"), 1), (0, float("inf"))):
            with self.assertRaises(ValueError):
                r.coordinates({"latitude": lat, "longitude": lon})

    def test_extent_follows_the_shared_zoom_model_and_tiles_stay_on_the_grid(self):
        self.assertAlmostEqual(r.extent(45.75, 4.85, 1)["radius_km"], 100.0)
        self.assertAlmostEqual(r.extent(45.75, 4.85, 0)["radius_km"], 150.0)
        self.assertAlmostEqual(r.extent(45.75, 4.85, 3)["radius_km"], 150 / 1.5 ** 3)
        ext = r.extent(0.0, 0.0, 1)
        layout = r.tile_layout(0.0, 0.0, ext["tile_zoom"], 256)
        self.assertTrue(layout)
        count = 2 ** ext["tile_zoom"]
        self.assertTrue(all(0 <= t["x"] < count and 0 <= t["y"] < count for t in layout))
        self.assertTrue(all(t["left"] < 432 and t["left"] + t["width"] > 0
                            and t["top"] < 240 and t["top"] + t["height"] > 0 for t in layout))

    def test_manifest_refuses_forecast_paths_host_injection_and_future(self):
        now = int(time.time())
        for value in (
            {"host": "https://evil.test", "radar": api()["radar"]},
            {"host": r.RADAR_HOST, "radar": {"past": [{"time": now, "path": "/../../passwd"}]}},
            api(now + 3600),
            api(now - 90000),
            {"host": r.RADAR_HOST, "radar": {"past": [{"time": now, "path": "/v2/radar/x?redirect=evil"}]}},
        ):
            with self.assertRaises(ValueError):
                r.validate_manifest(value)
        value = api(now - 600)
        value["radar"]["nowcast"] = [{"time": now + 600, "path": f"/v2/radar/{now+600}"},
                                     {"time": now + 9000, "path": f"/v2/radar/{now+9000}"}]
        result = r.validate_manifest(value)
        self.assertEqual(len(result["radar"]["past"]), 1)
        self.assertEqual([frame["time"] for frame in result["radar"]["nowcast"]], [now + 600])
        value["radar"]["past"][0]["path"] = "/v2/radar/cd6d910dedfd"
        self.assertEqual(r.validate_manifest(value)["radar"]["past"][0]["path"], "/v2/radar/cd6d910dedfd")

    def test_viewport_wraps_dateline_refuses_poles_and_only_loads_visible_tiles(self):
        for lat, lon in ((45.75, 4.85), (85, 180), (-85, -180), (0, 0)):
            tiles = r.viewport(lat, lon, 6)
            self.assertLessEqual(len(tiles), 6)
            self.assertTrue(all(0 <= t["x"] < 64 and 0 <= t["y"] < 64 for t in tiles))
            self.assertTrue(all(t["left"] < 432 and t["left"] + 256 > 0 and t["top"] < 240 and t["top"] + 256 > 0 for t in tiles))
        for lat in (-90, 90):
            with self.assertRaises(ValueError): r.viewport(lat, 0, 6)

    def test_png_validation_rejects_html_huge_dimensions_truncation(self):
        self.assertTrue(r.valid_png(png()))
        self.assertTrue(r.valid_png(rect_png(432, 240)))
        for content in (b"<html>error</html>", png(8192), png()[:-12], png() + b"bad"):
            self.assertFalse(r.valid_png(content))

    def test_live_load_and_cached_offline_manifest_keep_animation(self):
        r.configure({"enabled": True, "zoom_level": 1})
        response = api()
        stamp = response["radar"]["past"][0]["time"] - 600
        response["radar"]["past"].insert(0, {"time": stamp, "path": f"/v2/radar/{stamp}"})
        def download(url, limit, idle=8):
            if url == r.MANIFEST_URL:
                return json.dumps(response).encode()
            if "open-meteo" in url:
                return json.dumps(wind_payload()).encode()
            return png()
        with patch.object(r, "download", side_effect=download) as fetch:
            lines = stream(self.city)
            meta = lines[0]
            self.assertEqual(len(meta["rain"]["frames"]), 2)
            self.assertTrue(meta["tiles"] and all(tile["source"].startswith("file://") for tile in meta["tiles"]))
            frames = [line for line in lines if line["kind"] == "frame"]
            self.assertEqual(len(frames), 2)
            self.assertTrue(all(tile["source"].startswith("file://") for line in frames for tile in line["tiles"]))
            self.assertFalse(lines[-1]["partial"])
            first_calls = fetch.call_count
            stream(self.city)
            self.assertEqual(fetch.call_count, first_calls)
        path = r.CACHE / "manifest.json"
        import os
        os.utime(path, (time.time() - 600, time.time() - 600))
        with patch.object(r, "download", side_effect=OSError("offline")) as fetch:
            lines = stream(self.city)
            self.assertTrue(lines[-1]["stale"])
            self.assertEqual(len(lines[0]["rain"]["frames"]), 2)
            self.assertEqual(fetch.call_count, 1)

    def test_german_location_uses_the_dwd_timeline_with_future_frames(self):
        r.configure({"enabled": True, "zoom_level": 1})
        now = time.time()
        stamps = [now - 7200 + step * 300 for step in range(47) if now - 7200 + step * 300 <= now]
        stamps += [now + (step + 1) * 300 for step in range(3)]
        timeline = {"radar": [{"timestamp": r.iso_offset(stamp),
                               "source": f"RADARCOMP::RV::{r.iso_offset(now)}"} for stamp in stamps]}
        def download(url, limit, idle=8):
            return json.dumps(timeline).encode() if "brightsky" in url else png()
        city = {"name": "Berlin", "latitude": 52.52, "longitude": 13.405, "timezone": "Europe/Berlin"}
        with patch.object(r, "download", side_effect=download), \
             patch.object(r, "dwd_area", return_value=True):
            lines = stream(city)
        rain = lines[0]["rain"]
        self.assertEqual(rain["provider_name"], "DWD")
        self.assertEqual(rain["step_minutes"], 5)
        kinds = {frame["kind"] for frame in rain["frames"]}
        self.assertEqual(kinds, {"past", "future"})
        self.assertEqual(len(lines[0]["rain"]["frames"][0]["tiles"]), 1)
        self.assertTrue(all(line["kind"] == "frame" for line in lines[1:-1]))

    def test_now_is_snapped_to_five_minute_steps(self):
        r.configure({"enabled": True, "zoom_level": 1})
        base = (int(time.time()) + 150) // 300 * 300
        stamps = [base - 7200 + step * 300 for step in range(49)]
        timeline = {"radar": [{"timestamp": r.iso_offset(stamp),
                               "source": f"RADARCOMP::RV::{r.iso_offset(base)}"} for stamp in stamps]}
        def download(url, limit, idle=8):
            return json.dumps(timeline).encode() if "brightsky" in url else png()
        city = {"name": "Berlin", "latitude": 52.52, "longitude": 13.405, "timezone": "Europe/Berlin"}
        with patch.object(r, "download", side_effect=download), \
             patch.object(r, "dwd_area", return_value=True), \
             patch.object(r.time, "time", return_value=base + 143):
            lines = stream(city)
        rain = lines[0]["rain"]
        self.assertEqual(lines[0]["now"], base)
        self.assertEqual(rain["frames"][rain["now_index"]]["time"], base)
        self.assertEqual(rain["frames"][rain["now_index"]]["kind"], "past")
        self.assertTrue(all(frame["time"] % 300 == 0 for frame in rain["frames"]))

    def test_wind_now_is_snapped_to_fifteen_minute_steps(self):
        r.configure({"enabled": True, "zoom_level": 1})
        grid = (int(time.time()) // 900) * 900
        stamps = [grid - 4 * 3600 + step * 900 for step in range(33)]
        series = [{"latitude": 52.4 + row * 0.05, "longitude": 13.3,
                   "time": [r.iso_offset(stamp) for stamp in stamps],
                   "speed": [10.0] * len(stamps),
                   "direction": [225.0] * len(stamps),
                   "gust": [20.0] * len(stamps)}
                  for row in range(4)]
        timeline = {"radar": [{"timestamp": r.iso_offset(grid + 600),
                               "source": f"RADARCOMP::RV::{r.iso_offset(grid)}"}]}
        def download(url, limit, idle=8):
            return json.dumps(timeline).encode() if "brightsky" in url else png()
        city = {"name": "Berlin", "latitude": 52.52, "longitude": 13.405, "timezone": "Europe/Berlin"}
        with patch.object(r, "download", side_effect=download), \
             patch.object(r, "dwd_area", return_value=True), \
             patch.object(r, "wind_grid", return_value=series), \
             patch.object(r.time, "time", return_value=grid + 530):
            lines = stream(city)
        wind = lines[0]["wind"]
        # now = grid + 530 snaps to the 15 minute grid at grid + 900: the
        # timeline opens on that frame and it reads "now", not "-10 min".
        self.assertEqual(wind["frames"][wind["now_index"]]["time"], grid + 900)
        self.assertEqual(wind["frames"][wind["now_index"]]["kind"], "past")
        self.assertEqual(len(wind["frames"]), 17)
        self.assertTrue(all(frame["time"] % 900 == 0 for frame in wind["frames"]))

    def test_polar_location_reports_an_unsupported_projection(self):
        with patch.object(r, "download") as download:
            lines = stream({"name": "Pole", "latitude": 89.0, "longitude": 0.0})
        meta = lines[0]
        self.assertEqual(meta["status"], "unsupported")
        self.assertEqual(meta["reason"], "projection_limit")
        self.assertEqual(meta["rain"]["frames"], [])
        self.assertEqual(meta["wind"]["frames"], [])
        download.assert_not_called()

    def test_osm_tiles_are_cached_for_at_least_seven_days(self):
        url = r.OSM_HOST + "/6/32/20.png"
        with patch.object(r, "download", return_value=png()) as fetch:
            result = r.tile(url, osm=True)
            import os
            path = Path(result.removeprefix("file://"))
            os.utime(path, (time.time() - 6 * 86400, time.time() - 6 * 86400))
            self.assertEqual(r.tile(url, osm=True), result)
            self.assertEqual(fetch.call_count, 1)

    def test_rate_limit_is_shared_and_fails_without_sleeping(self):
        r.save_json(r.CACHE / "requests.json", [time.time()] * 90)
        with self.assertRaises(OSError):
            with r.rate_guard():
                pass

    def test_pressure_prunes_radar_before_protected_osm_tiles(self):
        base = r.CACHE / "osm-" / "base.png"
        radar = r.CACHE / "radar-" / "frame.png"
        r.save_bytes(base, png())
        r.save_bytes(radar, png())
        with patch.object(r, "MAX_CACHE_BYTES", len(png()) + 1):
            r.prune_cache()
        self.assertTrue(base.exists())
        self.assertFalse(radar.exists())

    def test_full_osm_quota_refuses_new_download_without_evicting_recent_tiles(self):
        base = r.CACHE / "osm-" / "protected.png"
        r.save_bytes(base, png())
        with patch.object(r, "OSM_CACHE_BYTES", len(png()) + 1), patch.object(r, "download") as download:
            self.assertIsNone(r.tile(r.OSM_HOST + "/6/33/20.png", osm=True))
            download.assert_not_called()
        self.assertTrue(base.exists())

    def test_missing_images_stream_as_partial_and_are_never_painted(self):
        r.configure({"enabled": True})
        with patch.object(r, "manifest", return_value=(api(), False)), patch.object(r, "tile", return_value=None):
            lines = stream(self.city)
        frames = [line for line in lines if line["kind"] == "frame"]
        self.assertTrue(frames)
        self.assertTrue(any(any(not tile["source"] for tile in line["tiles"]) for line in frames))
        self.assertTrue(lines[-1]["partial"])
        self.assertTrue(lines[-1]["message"])

    def test_redirect_to_untrusted_host_is_rejected(self):
        with self.assertRaises(ValueError):
            r.SafeRedirect().redirect_request(None, None, 302, "Found", {}, "https://evil.test/tile.png")

    def test_radar_qml_uses_only_plain_text_and_local_images(self):
        qml = (Path(__file__).resolve().parents[1] / "Radar.qml").read_text()
        self.assertNotIn("Text {", qml.replace("PText {", ""))
        self.assertIn("SplitParser", qml)
        self.assertIn("OpenStreetMap contributors", qml)
        self.assertIn("RainViewer", qml)
        self.assertIn("DWD", qml)
        self.assertIn("Open-Meteo", qml)
        self.assertIn('property string mode: "rain"', qml)

    def test_panel_wires_radars_register_pages_and_keybinds(self):
        panel = (Path(__file__).resolve().parents[1] / "Panel.qml").read_text()
        self.assertIn('"nav-radars"', panel)
        self.assertIn('mapPage: "rain"', panel)
        self.assertIn("togglePlayback()", panel)
        self.assertIn("stepFrames(", panel)
        self.assertIn("zoomBy(", panel)
        self.assertIn("Qt.Key_Space", panel)
        self.assertIn("Qt.Key_2", panel)


if __name__ == "__main__":
    unittest.main()
