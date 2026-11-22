import importlib.util
import json
import math
from datetime import datetime, timezone
from pathlib import Path
import re
import struct
import tempfile
import time
import unittest
from unittest.mock import patch
from urllib.parse import unquote
import zlib

spec = importlib.util.spec_from_file_location("pixel_radar", Path(__file__).resolve().parents[1] / "radar.py")
r = importlib.util.module_from_spec(spec)
spec.loader.exec_module(r)


def png(size=256):
    def chunk(kind, body):
        return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body) & 0xffffffff)
    sample = min(size, 256)
    raw = (b"\x00" + bytes([50, 100, 200, 180]) * sample) * sample
    return (r.PNG + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


def png_rect(width, height):
    def chunk(kind, body):
        return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body) & 0xffffffff)
    raw = (b"\x00" + bytes([50, 100, 200, 180]) * width) * height
    return (r.PNG + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


def api(stamp=None):
    stamp = int(time.time()) - 600 if stamp is None else stamp
    return {"host": r.RADAR_HOST, "radar": {"past": [{"time": stamp, "path": f"/v2/radar/{stamp}"}]}}


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

    def test_disabled_radar_never_contacts_network(self):
        with patch.object(r, "download") as download:
            result = r.main(["load", json.dumps(self.city)])
            self.assertFalse(result["settings"]["enabled"])
            self.assertEqual(result["frames"], [])
            download.assert_not_called()

    def test_settings_are_bounded_and_persisted_separately(self):
        r.save_json(r.STATE / "settings.json", {"cities": [self.city]})
        prefs = r.configure({"enabled": True, "zoom": 7})
        self.assertEqual(r.settings(), prefs)
        self.assertEqual(r.read_json(r.STATE / "settings.json", {})["cities"], [self.city])
        for change in ({"enabled": "yes"}, {"zoom": 11}, {"zoom": 2}, {"zoom": True}, []):
            with self.assertRaises(ValueError):
                r.configure(change)

    def test_dwd_allows_close_zoom_but_rainviewer_stays_at_seven(self):
        self.assertEqual(r.configure({"enabled": True, "zoom": 10})["zoom"], 10)
        self.assertEqual(r.configure({"zoom": 7})["zoom"], 7)
        tiles = r.viewport(52.52, 13.405, 10)
        self.assertTrue(4 <= len(tiles) <= 6)
        self.assertTrue(all(0 <= tile["x"] < 2 ** 10 for tile in tiles))
        narrow = r.mercator_bounds(52.52, 13.405, 7)
        tight = r.mercator_bounds(52.52, 13.405, 10)
        self.assertLess(tight[2] - tight[0], (narrow[2] - narrow[0]) / 4)
        prefs = {"enabled": True, "zoom": 10, "source": "rainviewer", "layer": "rain"}
        urls = []
        def record_tile(url, *args):
            urls.append(url)
            return "file:///tmp/base.png"
        with patch.object(r, "manifest", return_value=(
                {"host": r.RADAR_HOST, "radar": {"past": []}}, False)), \
                patch.object(r, "tile", side_effect=record_tile), \
                patch.object(r, "prune_cache"):
            result = r.load_rainviewer({"latitude": 45.75, "longitude": 4.85}, prefs)
        self.assertTrue(result["tiles"])
        self.assertTrue(urls)
        self.assertTrue(all("/7/" in url for url in urls))
        self.assertTrue(any("/256/7/" in url for url in urls))

    def test_bad_coordinates_and_nonfinite_values_are_rejected(self):
        for lat, lon in ((91, 1), (0, 181), (float("nan"), 1), (0, float("inf"))):
            with self.assertRaises(ValueError):
                r.coordinates({"latitude": lat, "longitude": lon})

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
        value["radar"]["nowcast"] = [{"time": now + 600, "path": f"/v2/radar/{now+600}"}]
        self.assertEqual(len(r.validate_manifest(value)["radar"]["past"]), 1)
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
        for content in (b"<html>error</html>", png(8192), png()[:-12], png() + b"bad"):
            self.assertFalse(r.valid_png(content))

    def test_live_load_and_cached_offline_manifest_keep_animation(self):
        r.configure({"enabled": True})
        response = api()
        stamp = response["radar"]["past"][0]["time"] - 600
        response["radar"]["past"].insert(0, {"time": stamp, "path": f"/v2/radar/{stamp}"})
        def download(url, limit):
            return json.dumps(response).encode() if url == r.MANIFEST_URL else png()
        with patch.object(r, "download", side_effect=download) as fetch:
            result = r.load(self.city)
            self.assertEqual(len(result["frames"]), 2)
            self.assertFalse(result["stale"])
            self.assertTrue(all(tile["source"].startswith("file://") for tile in result["tiles"]))
            first_calls = fetch.call_count
            r.load(self.city)
            self.assertEqual(fetch.call_count, first_calls)
        path = r.CACHE / "manifest.json"
        import os
        os.utime(path, (time.time() - 600, time.time() - 600))
        with patch.object(r, "download", side_effect=OSError("offline")) as fetch:
            result = r.load(self.city)
            self.assertTrue(result["stale"])
            self.assertEqual(len(result["frames"]), 2)
            self.assertEqual(fetch.call_count, 1)

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
        r.save_json(r.CACHE / "requests.json", [time.time()] * r.REQUESTS_PER_MINUTE)
        with self.assertRaises(r.RateLimited):
            with r.rate_guard():
                pass

    def test_rate_limited_frame_is_not_recorded_as_a_missing_frame(self):
        # The provider never saw this call, so a miss marker would hide the
        # frame for five minutes and leave a gap in the timeline.
        url = r.dwd_url(r.DWD_FUTURE_LAYER, 1_800_000_000, (1.0, 2.0, 3.0, 4.0))
        with patch.object(r, "download", side_effect=r.RateLimited("busy")):
            self.assertIsNone(r.dwd_image(url, future=True))
        self.assertEqual(list((r.CACHE / "dwd-").glob("*.miss")), [])

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

    def test_partial_frames_are_not_shown_with_missing_tiles(self):
        r.configure({"enabled": True})
        with patch.object(r, "manifest", return_value=(api(), False)), patch.object(r, "tile", return_value=None):
            result = r.load(self.city)
        self.assertEqual(result["frames"], [])
        self.assertTrue(result["partial"])
        self.assertIn("error", result)

    def test_redirect_to_untrusted_host_is_rejected(self):
        with self.assertRaises(ValueError):
            r.SafeRedirect().redirect_request(None, None, 302, "Found", {}, "https://evil.test/tile.png")

    def test_dwd_is_offered_as_a_radar_source(self):
        self.assertIn("dwd", r.SOURCES)
        source = {"name": "Berlin", "latitude": 52.52, "longitude": 13.405}
        self.assertTrue(r.dwd_covers(source))
        self.assertFalse(r.dwd_covers(self.city))
        self.assertFalse(r.dwd_covers({"latitude": "x", "longitude": 1}))
        self.assertEqual(r.settings()["source"], "auto")
        self.assertEqual(r.configure({"source": "dwd"})["source"], "dwd")
        for change in ({"source": "elsewhere"}, {"source": None}):
            with self.assertRaises(ValueError):
                r.configure(change)

    def test_wind_layer_setting_and_hourly_frames(self):
        self.assertEqual(r.settings()["layer"], "rain")
        self.assertEqual(r.configure({"layer": "wind"})["layer"], "wind")
        with self.assertRaises(ValueError):
            r.configure({"layer": "snow"})
        self.assertEqual(r.configure({"layer": "rain"})["layer"], "rain")
        now = 1_800_000_123
        times = r.wind_times(now)
        self.assertEqual(len(times), r.WIND_FRAMES)
        self.assertTrue(all(b - a == 3600 for a, b in zip(times, times[1:])))
        url = r.wind_url(times[0], (1.0, 2.0, 3.0, 4.0))
        self.assertIn("Icon_reg025_fd_sl_UV10M", url)
        self.assertIn("TIME=", url)
        self.assertIn("WIDTH=" + str(r.WIND_WIDTH), url)
        self.assertIn("HEIGHT=" + str(r.WIND_HEIGHT), url)

    def test_wind_load_returns_hourly_forecast_frames(self):
        source = {"name": "Berlin", "latitude": 52.52, "longitude": 13.405, "timezone": "Europe/Berlin"}
        calls = []
        with patch.object(r, "tile", return_value="file:///tmp/base.png"), \
                patch.object(r, "wind_image", return_value="file:///tmp/wind.png"), \
                patch.object(r, "prefetch_dwd", side_effect=lambda urls, forecast=True: calls.append(list(urls))), \
                patch.object(r, "prune_cache"):
            result = r.load_wind(source, {"enabled": True, "zoom": 6, "source": "auto", "layer": "wind"})
        self.assertEqual(result["layer"], "wind")
        self.assertEqual(result["model"], "ICON")
        self.assertEqual(len(result["frames"]), r.WIND_FRAMES)
        self.assertTrue(all(frame["forecast"] is True for frame in result["frames"]))
        self.assertFalse(result["warming"])
        self.assertEqual(calls, [])

    def test_wind_load_warms_missing_hours_in_the_background(self):
        source = {"name": "Berlin", "latitude": 52.52, "longitude": 13.405, "timezone": "Europe/Berlin"}
        calls = []
        with patch.object(r, "tile", return_value="file:///tmp/base.png"), \
                patch.object(r, "wind_image", return_value=None), \
                patch.object(r, "prefetch_dwd", side_effect=lambda urls, forecast=True: calls.append((list(urls), forecast))), \
                patch.object(r, "prune_cache"):
            result = r.load_wind(source, {"enabled": True, "zoom": 6, "source": "auto", "layer": "wind"})
        self.assertEqual(result["frames"], [])
        self.assertTrue(result["warming"])
        self.assertEqual(len(calls), 1)
        self.assertEqual(len(calls[0][0]), r.WIND_FRAMES)
        self.assertFalse(calls[0][1])

    def test_dwd_prefetch_warms_the_frames_nearest_the_present_first(self):
        # A cold timeline must become playable before the older hours arrive.
        source = {"name": "Berlin", "latitude": 52.52, "longitude": 13.405, "timezone": "Europe/Berlin"}
        calls = []

        def image(url, future, network=True, deadline=None):
            return None

        with patch.object(r, "tile", return_value="file:///tmp/base.png"), \
                patch.object(r, "dwd_image", side_effect=image), \
                patch.object(r, "prefetch_dwd", side_effect=lambda urls: calls.append(list(urls))), \
                patch.object(r, "prune_cache"):
            r.load_dwd(source, {"enabled": True, "zoom": 6, "source": "dwd"})
        ordered = calls[0]
        self.assertEqual(len(ordered), r.DWD_PAST_FRAMES - 1 + r.DWD_FUTURE_FRAMES)
        self.assertIn("LAYERS=dwd%3A" + r.DWD_FUTURE_LAYER, ordered[0])
        self.assertIn("LAYERS=dwd%3A" + r.DWD_PAST_LAYER, ordered[1])
        stamps = []
        for url in ordered[:6]:
            match = re.search(r"TIME=([^&]+)", url)
            stamp = datetime.strptime(unquote(match.group(1)), "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
            stamps.append(stamp)
        # The first six renders all sit within a quarter of an hour of the present.
        self.assertLessEqual((max(stamps) - min(stamps)).total_seconds(), 2400)

    def test_wind_load_retries_a_dropped_burst_once(self):
        # DWD can drop the first render while a radar prefetch is busy. One
        # short sequential retry keeps the first paint out of an error.
        source = {"name": "Berlin", "latitude": 52.52, "longitude": 13.405, "timezone": "Europe/Berlin"}
        attempts = []

        def image(url, network=True, deadline=None):
            if not network:
                return None
            attempts.append(url)
            return "file:///tmp/wind.png" if len(attempts) > 1 else None

        with patch.object(r, "tile", return_value="file:///tmp/base.png"), \
                patch.object(r, "wind_image", side_effect=image), \
                patch.object(r, "prefetch_dwd"), \
                patch.object(r, "prune_cache"):
            result = r.load_wind(source, {"enabled": True, "zoom": 6, "source": "auto", "layer": "wind"})
        self.assertEqual(len(attempts), 2)
        self.assertEqual(len(result["frames"]), 1)
        self.assertNotIn("error", result)

    def test_wind_outside_germany_is_unsupported(self):
        paris = {"name": "Paris", "latitude": 48.85, "longitude": 2.35}
        result = r.load_wind(paris, {"enabled": True, "zoom": 6, "source": "auto", "layer": "wind"})
        self.assertEqual(result["status"], "unsupported")
        self.assertEqual(result["reason"], "coverage_limit")

    def test_dwd_frames_use_five_minute_steps_and_cover_past_and_near_future(self):
        now = 1_800_000_000
        past, future = r.dwd_times(now)
        self.assertEqual(len(past), r.DWD_PAST_FRAMES)
        self.assertEqual(len(future), r.DWD_FUTURE_FRAMES)
        self.assertEqual(r.DWD_STEP, 300)
        self.assertTrue(all(stamp % r.DWD_STEP == 0 for stamp in past + future))
        self.assertTrue(all(b - a == r.DWD_STEP for a, b in zip(past, past[1:])))
        self.assertTrue(all(b - a == r.DWD_STEP for a, b in zip(future, future[1:])))
        self.assertLess(past[-1], now)
        self.assertGreater(future[0], past[-1])
        # The DWD analysis layer covers two hours of observations; the product
        # layer publishes up to two hours ahead.
        self.assertEqual(past[-1] - past[0], 2 * 3600)
        self.assertEqual(future[-1] - past[-1], 2 * 3600)

    def test_dwd_bounds_match_the_tile_viewport(self):
        min_x, min_y, max_x, max_y = r.mercator_bounds(52.52, 13.405, 6)
        for value in (min_x, min_y, max_x, max_y):
            self.assertLess(abs(value), 20_037_508.35)
        self.assertLess(min_x, max_x)
        self.assertLess(min_y, max_y)
        radius = 6378137.0
        longitude = ((min_x + max_x) / 2) / radius * 180 / math.pi
        latitude = math.degrees(2 * math.atan(math.exp((min_y + max_y) / 2 / radius)) - math.pi / 2)
        self.assertAlmostEqual(longitude, 13.405, places=3)
        self.assertAlmostEqual(latitude, 52.52, places=3)

    def test_dwd_url_is_bounded_to_the_german_wms(self):
        url = r.dwd_url(r.DWD_PAST_LAYER, 1_800_000_000, (1.0, 2.0, 3.0, 4.0))
        self.assertTrue(url.startswith(r.DWD_WMS + "?"))
        self.assertIn("LAYERS=dwd%3ARadar_wn-analysis_1x1km_ger", url)
        self.assertIn("BBOX=1.00%2C2.00%2C3.00%2C4.00", url)
        self.assertIn("TIME=2027-01-15T08%3A00%3A00Z", url)
        self.assertIn("maps.dwd.de", r.ALLOWED_HOSTS)
        self.assertIn("CRS=EPSG%3A3857", url)
        self.assertIn("WIDTH=864", url)
        self.assertIn("HEIGHT=480", url)

    def test_dwd_failed_forecast_frames_are_not_retried_immediately(self):
        url = r.dwd_url(r.DWD_FUTURE_LAYER, 1_800_000_000, (1.0, 2.0, 3.0, 4.0))
        with patch.object(r, "download", side_effect=OSError("busy")) as fetch:
            self.assertIsNone(r.dwd_image(url, future=True))
            self.assertIsNone(r.dwd_image(url, future=True))
            self.assertEqual(fetch.call_count, 1)
        with patch.object(r, "download", return_value=png_rect(r.DWD_WIDTH, r.DWD_HEIGHT)) as fetch:
            self.assertIsNone(r.dwd_image(url, future=True))
            self.assertEqual(fetch.call_count, 0)
        marker = next((r.CACHE / "dwd-").glob("*.miss"))
        marker.touch()
        old = time.time() - r.DWD_RETRY - 1
        import os
        os.utime(marker, (old, old))
        with patch.object(r, "download", return_value=png_rect(r.DWD_WIDTH, r.DWD_HEIGHT)) as fetch:
            self.assertTrue(r.dwd_image(url, future=True).startswith("file://"))
            self.assertEqual(fetch.call_count, 1)
        self.assertFalse(marker.exists())

    def test_dwd_raster_images_are_cached_and_validated(self):
        url = r.dwd_url(r.DWD_PAST_LAYER, 1_800_000_000, (1.0, 2.0, 3.0, 4.0))
        with patch.object(r, "download", return_value=png_rect(r.DWD_WIDTH, r.DWD_HEIGHT)) as fetch:
            first = r.dwd_image(url, future=False)
            second = r.dwd_image(url, future=False)
            self.assertEqual(first, second)
            self.assertEqual(fetch.call_count, 1)
        self.assertTrue(first.startswith("file://"))
        with patch.object(r, "download", return_value=png_rect(256, 256)) as fetch:
            self.assertIsNone(r.dwd_image(url + "&invalid=1", future=False))
            self.assertEqual(fetch.call_count, 1)

    def test_dwd_mask_removes_grey_and_magenta_but_keeps_rain(self):
        pixels = bytearray()
        for colour in ((255, 255, 255, 0), (126, 126, 126, 77), (251, 0, 255, 255),
                       (176, 64, 176, 255), (1, 153, 52, 255)):
            pixels.extend(colour)
        data = r.encode_rgba(5, 1, pixels)
        cleaned = r.strip_dwd_mask(data)
        self.assertTrue(r.valid_png(cleaned, (5, 1)))
        decoded = r.decode_rgba(cleaned)
        self.assertIsNotNone(decoded)
        self.assertEqual([decoded[2][i + 3] for i in range(0, 20, 4)], [0, 0, 0, 0, 255])
        rain = r.encode_rgba(4, 1, bytearray([1, 153, 52, 255] * 4))
        self.assertEqual(r.strip_dwd_mask(rain), rain)

    def test_dwd_missing_forecast_frames_are_warmed_in_the_background(self):
        source = {"name": "Berlin", "latitude": 52.52, "longitude": 13.405, "timezone": "Europe/Berlin"}
        calls = []
        def image(url, future, network=True, deadline=None):
            return None if future else "file:///tmp/frame.png"
        with patch.object(r, "tile", return_value="file:///tmp/base.png"), \
                patch.object(r, "dwd_image", side_effect=image), \
                patch.object(r, "prefetch_dwd", side_effect=lambda urls: calls.append(list(urls))), \
                patch.object(r, "prune_cache"):
            result = r.load_dwd(source, {"enabled": True, "zoom": 6, "source": "dwd"})
        self.assertEqual(len(result["frames"]), r.DWD_PAST_FRAMES)
        self.assertEqual(len(calls), 1)
        self.assertEqual(len(calls[0]), r.DWD_FUTURE_FRAMES)
        self.assertTrue(all(url.startswith(r.DWD_WMS + "?") for url in calls[0]))

    def test_dwd_first_paint_asks_only_for_the_newest_observation(self):
        source = {"name": "Berlin", "latitude": 52.52, "longitude": 13.405, "timezone": "Europe/Berlin"}
        network_calls = []
        def image(url, future, network=True, deadline=None):
            if network:
                network_calls.append(future)
            return "file:///tmp/frame.png"
        with patch.object(r, "tile", return_value="file:///tmp/base.png"), \
                patch.object(r, "dwd_image", side_effect=image), \
                patch.object(r, "prefetch_dwd"), \
                patch.object(r, "prune_cache"):
            r.load_dwd(source, {"enabled": True, "zoom": 6, "source": "dwd"})
        # The nowcast layer is the slow render; it must not hold the first paint.
        self.assertEqual(network_calls, [False])

    def test_first_paint_budget_is_shorter_than_the_full_request_budget(self):
        source = (Path(__file__).resolve().parents[1] / "radar.py").read_text()
        self.assertIn("FIRST_PAINT_SECONDS = 10", source)
        self.assertIn("@request_budget(FIRST_PAINT_SECONDS)", source)
        self.assertLess(r.FIRST_PAINT_SECONDS, r.REQUEST_SECONDS)

    def test_radar_preloads_while_the_panel_shows_another_page(self):
        root = Path(__file__).resolve().parents[1]
        qml = (root / "Radar.qml").read_text()
        panel = (root / "Panel.qml").read_text()
        for marker in ("property bool preload: false",
                       "if ((active || preload) && settingsLoaded && radarEnabled",
                       "onPreloadChanged: {",
                       "if (!(root.active || root.preload) || !root.radarEnabled) warmTimer.stop()"):
            self.assertIn(marker, qml)
        self.assertIn('preload: root.opened && root.activePage!=="radar" && !root.searching', panel)

    def test_dwd_load_returns_one_raster_image_per_frame(self):
        source = {"name": "Berlin", "latitude": 52.52, "longitude": 13.405, "timezone": "Europe/Berlin"}
        with patch.object(r, "tile", return_value="file:///tmp/base.png"), \
                patch.object(r, "dwd_image", return_value="file:///tmp/frame.png"), \
                patch.object(r, "prune_cache"):
            result = r.load_dwd(source, {"enabled": True, "zoom": 6, "source": "dwd"})
        self.assertEqual(result["render"], "raster")
        self.assertEqual(result["provider"], "DWD")
        self.assertEqual(len(result["frames"]), r.DWD_PAST_FRAMES + r.DWD_FUTURE_FRAMES)
        self.assertTrue(all(frame["image"].startswith("file://") for frame in result["frames"]))
        self.assertEqual(result["default_index"], r.DWD_PAST_FRAMES - 1)
        self.assertTrue(result["forecast"] is True)
        self.assertFalse(result["partial"])

    def test_auto_source_uses_dwd_inside_germany_only(self):
        r.configure({"enabled": True, "source": "auto"})
        berlin = {"name": "Berlin", "latitude": 52.52, "longitude": 13.405}
        with patch.object(r, "load_dwd", return_value={"frames": []}) as dwd, \
                patch.object(r, "load_rainviewer", return_value={"frames": []}) as rain:
            r.load(berlin)
            r.load(self.city)
        self.assertEqual(dwd.call_count, 1)
        self.assertEqual(rain.call_count, 1)
        self.assertFalse(r.dwd_covers({"name": "Paris", "latitude": 48.85, "longitude": 2.35}))

    def test_radar_qml_exposes_sources_raster_frames_and_playback_keys(self):
        root = Path(__file__).resolve().parents[1]
        qml = (root / "Radar.qml").read_text()
        panel = (root / "Panel.qml").read_text()
        for marker in ('objectName: "radar-source"', 'value:"auto"', 'value:"dwd"',
                       'objectName: "radar-layer"', 'value:"rain"', 'value:"wind"',
                       'root.togglePlayback()', 'Commons.Util.readingKey(event)',
                       'root.currentFrame.image', 'followPresent',
                       'root.frameIndex >= root.frames.length - 1',
                       'Math.min(frames.length - 1, frameIndex + delta)',
                       'raster ? rasterImage.status', 'focusViewport', 'selectLayer',
                       'root.zoomBy(1)', 'root.zoomBy(-1)', 'root.showPresent()'):
            self.assertIn(marker, qml)
        for marker in ('letter === "1"', 'letter === "2"', 'letter === "R"',
                       'letter === "W"', 'textEntryFocused', 'root.showMapLayer("rain")',
                       'root.showMapLayer("wind")', 'root.zoomRadar(1)', 'root.zoomRadar(-1)'):
            self.assertIn(marker, panel)
        for gone in ('letter === "M"', 'nav-maps', 'text: "Maps"', 'letter === "F"',
                     'Weather · W'):
            self.assertNotIn(gone, panel)
        self.assertIn('objectName: "nav-radar"; text: "Radar"', panel)
        self.assertIn('tooltipText: "Weather · 1"', panel)
        self.assertIn('tooltipText: "Radar · 2"', panel)

    def test_zoom_stops_at_seven_for_rainviewer_and_ten_for_dwd(self):
        qml = (Path(__file__).resolve().parents[1] / "Radar.qml").read_text()
        for marker in ("readonly property int maxZoom: wind || dwdSource ? 10 : 7",
                       "enabled: root.zoom < root.maxZoom",
                       "Math.min(root.zoom + 1, root.maxZoom)",
                       "if (zoom > maxZoom) zoom = maxZoom"):
            self.assertIn(marker, qml)

    def test_radar_opens_at_the_present_frame_and_stays_paused(self):
        qml = (Path(__file__).resolve().parents[1] / "Radar.qml").read_text()
        self.assertNotIn("autoPlayPending", qml)
        self.assertIn("if (root.followPresent) root.showPresent()", qml)
        self.assertIn("var present = Number(radar.default_index)", qml)
        self.assertIn("present >= 0 && present < frames.length ? present : Math.max(0, frames.length - 1)", qml)
        self.assertIn("followPresent = true\n    warmPolls = 0\n    playing = false", qml)

    def test_panel_card_fits_the_hourly_forecast_and_the_radar(self):
        panel = (Path(__file__).resolve().parents[1] / "Panel.qml").read_text()
        for marker in ("readonly property real pageContentHeight",
                       "hourlySection.implicitHeight",
                       "radarPanel.implicitHeight",
                       "contentHeight: fittedContentHeight(root.pageContentHeight)",
                       "id: hourlySection", "id: radarPanel"):
            self.assertIn(marker, panel)

    def test_radar_hides_caption_lines_and_labels_layer_keys(self):
        root = Path(__file__).resolve().parents[1]
        qml = (root / "Radar.qml").read_text()
        panel = (root / "Panel.qml").read_text()
        self.assertNotIn("clockLabel", qml)
        self.assertNotIn("framesLabel", qml)
        self.assertNotIn("Radar coverage is unverified here", qml)
        self.assertNotIn("Rain nowcast from", panel)
        for marker in ('{value:"rain",label:"Rain",tooltip:"Rain · R"}',
                       '{value:"wind",label:"Wind",tooltip:"Wind · W"}',
                       'tooltipText: "Previous frame · Left"',
                       'tooltipText: "Next frame · Right"',
                       '"Play · Space"',
                       '"Pause · Space"',
                       'tooltipText: "Zoom out · −"',
                       'tooltipText: "Zoom in · +"'):
            self.assertIn(marker, qml)

    def test_wind_map_uses_native_resolution_barbs(self):
        root = Path(__file__).resolve().parents[1]
        source = (root / "radar.py").read_text()
        self.assertIn("WIND_WIDTH, WIND_HEIGHT = 432, 240", source)
        self.assertIn('"WIDTH": str(WIND_WIDTH)', source)
        self.assertIn('"HEIGHT": str(WIND_HEIGHT)', source)
        self.assertIn("valid_png(data, (WIND_WIDTH, WIND_HEIGHT))", source)

    def test_wind_map_dims_the_basemap_and_paints_light_barbs(self):
        root = Path(__file__).resolve().parents[1]
        qml = (root / "Radar.qml").read_text()
        panel = (root / "Panel.qml").read_text()
        source = (root / "radar.py").read_text()
        for marker in ("property string windSummary",
                       "visible: root.raster && root.wind",
                       'color: "#000000"',
                       "opacity: 0.5",
                       'text: "Now " + root.windSummary',
                       "elide: Text.ElideRight"):
            self.assertIn(marker, qml)
        # The barbs are restyled in the backend, so the map needs no shader.
        self.assertNotIn("ShaderEffectSource", qml)
        self.assertNotIn("MultiEffect", qml)
        self.assertIn("import wind_style", source)
        self.assertIn("data = wind_style.restyle(data)", source)
        self.assertIn("readonly property string windSummary", panel)
        self.assertIn("windSummary: root.windSummary", panel)

    def test_wind_style_turns_black_barbs_white(self):
        import struct
        import zlib
        import wind_style

        def chunk(kind, body):
            return (struct.pack(">I", len(body)) + kind + body
                    + struct.pack(">I", zlib.crc32(kind + body) & 0xffffffff))

        def png(rows):
            header = struct.pack(">IIBBBBB", 2, 1, 8, 6, 0, 0, 0)
            raw = b"".join(b"\x00" + row for row in rows)
            return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header)
                    + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))

        black = png([bytes([0, 0, 0, 80, 0, 0, 0, 0])])
        styled = wind_style.restyle(black)
        self.assertNotEqual(styled, black)
        offset, data = 8, bytearray()
        while offset + 12 <= len(styled):
            length = struct.unpack(">I", styled[offset:offset + 4])[0]
            kind = styled[offset + 4:offset + 8]
            if kind == b"IDAT":
                data.extend(styled[offset + 8:offset + 8 + length])
            offset += length + 12
        raster = zlib.decompress(bytes(data))
        self.assertEqual(raster[1:5], b"\xff\xff\xff\x78")
        self.assertEqual(raster[5:9], b"\x00\x00\x00\x00")
        # A second pass must not lift the alpha again.
        self.assertEqual(wind_style.restyle(styled), styled)

    def test_radar_time_has_no_forecast_suffix(self):
        qml = (Path(__file__).resolve().parents[1] / "Radar.qml").read_text()
        self.assertNotIn("· forecast", qml)
        self.assertIn('readonly property string frameTime: frames.length > frameIndex ? dateTime(frames[frameIndex]) : "—"', qml)

    def test_radar_shows_a_legend_picture_instead_of_explanatory_text(self):
        root = Path(__file__).resolve().parents[1]
        qml = (root / "Radar.qml").read_text()
        for marker in ('objectName: "radar-legend-toggle"',
                       'label: root.legendExpanded ? "Hide legend" : "Legend"',
                       'objectName: "radar-legend"',
                       'Qt.resolvedUrl(wind ? "assets/legend-wind.png" : "assets/legend-rain.png")',
                       'source: root.legendSource'):
            self.assertIn(marker, qml)
        for gone in ("About this radar", "detailsText", "providerCaption", "providerName",
                     "providerUrl", "DWD radar covers Germany. The timeline",
                     "Auto uses DWD radar in Germany and RainViewer elsewhere."):
            self.assertNotIn(gone, qml)
        self.assertIn('{value:"auto",label:"Auto",tooltip:"Uses DWD radar in Germany and RainViewer elsewhere"}', qml)
        for name in ("legend-rain.png", "legend-wind.png"):
            self.assertEqual(r.png_size((root / "assets" / name).read_bytes()), (864, 190))

    def test_dwd_raster_is_painted_above_the_basemap(self):
        # The basemap tiles are opaque, so a raster layer declared before them
        # would never be visible.
        qml = (Path(__file__).resolve().parents[1] / "Radar.qml").read_text()
        tiles = qml.index("model: root.radar.tiles || []")
        raster = qml.index("id: rasterImage")
        self.assertLess(tiles, raster)

    def test_radar_controls_return_keyboard_focus_to_the_map(self):
        # Space must always control playback, even after a control was clicked.
        qml = (Path(__file__).resolve().parents[1] / "Radar.qml").read_text()
        button = qml.index("component RadarButton: Ui.Button")
        column = qml.index("Column {", button)
        self.assertIn("onClicked: Qt.callLater(root.focusViewport)", qml[button:column])
        self.assertIn("onPressedChanged: if (!pressed) Qt.callLater(root.focusViewport)", qml)

    def test_radar_play_answers_while_the_timeline_warms(self):
        # A cold DWD view can hold one frame for several seconds. The button and
        # the Space key must arm playback instead of ignoring the user.
        qml = (Path(__file__).resolve().parents[1] / "Radar.qml").read_text()
        self.assertIn('enabled: root.frames.length > 0 && root.imageReady; onClicked: root.togglePlayback()', qml)
        self.assertIn("if (frames.length < 2) { followPresent = true; playing = true; return }", qml)
        self.assertIn("root.frames.length > Number(root.radar.default_index) + 1", qml)
        self.assertIn('objectName: "radar-warming"', qml)
        self.assertIn("Playback starts as soon as the next frame arrives.", qml)
        self.assertIn("if (root.frames.length < 2) root.playing = false", qml)

    def test_radar_polls_and_keeps_playing_while_the_timeline_warms(self):
        qml = (Path(__file__).resolve().parents[1] / "Radar.qml").read_text()
        start = qml.index('objectName: "radar-warm-timer"')
        self.assertIn("interval: 3000", qml[start:start + 300])
        self.assertIn("repeat: true", qml[start:start + 300])
        self.assertIn("if (!warmTimer.running) root.playing = false", qml)
        self.assertIn("root.warmPolls >= 60", qml)

    def test_dwd_prefetch_warms_frames_in_parallel(self):
        # At a close zoom one DWD frame takes seconds; warming them in sequence
        # left the timeline with too few frames to play.
        source = (Path(__file__).resolve().parents[1] / "radar.py").read_text()
        self.assertIn("DWD_PREFETCH_WORKERS = 6", source)
        start = source.index("def prefetch_dwd(")
        end = source.index("\ndef osm_room(", start)
        body = source[start:end]
        self.assertIn("ThreadPoolExecutor(max_workers=DWD_PREFETCH_WORKERS)", body)
        self.assertNotIn("for url in urls:", body)
        # A short second round repairs the frames the busy first burst drops.
        self.assertIn("retries = [url for url in urls if missing(url)]", body)
        self.assertIn("ThreadPoolExecutor(max_workers=3)", body)

    def test_radar_qml_uses_only_plain_text_and_local_images(self):
        qml = (Path(__file__).resolve().parents[1] / "Radar.qml").read_text()
        self.assertNotIn("Text {", qml.replace("PText {", ""))
        self.assertIn('root.active && root.radarEnabled', qml)
        self.assertIn('text: "© OpenStreetMap ↗"', qml)
        self.assertIn('Qt.openUrlExternally("https://www.openstreetmap.org/copyright")', qml)
        self.assertIn('RainViewer', qml)


if __name__ == "__main__":
    unittest.main()
