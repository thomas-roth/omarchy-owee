#!/usr/bin/env python3
"""Manual live-source cartography gate, with no personal state and a 90s deadline.

Radar uses one coverage mask rather than preloading an animation. DWD checks
one observed and one forecast frame. Wind checks one hourly frame. Projection
and coverage limits are tested honestly.
"""
import argparse
import json
from pathlib import Path
import signal
import sys
import tempfile
import time
from urllib.parse import parse_qs, unquote, urlsplit

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))
import radar
from endurance import atomic_json, source_digest, utc_now
from international import runtime_versions

LYON = {"name": "Lyon", "latitude": 45.75, "longitude": 4.85, "timezone": "Europe/Paris"}
ERFURT = {"name": "Erfurt", "latitude": 50.98, "longitude": 11.03, "timezone": "Europe/Berlin"}
POLE = {"name": "North Pole", "latitude": 90, "longitude": 0, "timezone": "Etc/GMT"}
DEADLINE_SECONDS = 90


class ProbeDeadline(BaseException):
    pass


def alarm(*_):
    raise ProbeDeadline("Global live-map probe deadline exceeded (%d seconds)" % DEADLINE_SECONDS)


def local_png(uri):
    parsed = urlsplit(uri)
    if parsed.scheme != "file" or parsed.netloc:
        raise ValueError("Expected a local validated map image")
    return Path(unquote(parsed.path)).read_bytes()


def dwd_png(uri, expected=None):
    data = local_png(uri)
    size = radar.png_size(data)
    expected = expected or (radar.DWD_WIDTH, radar.DWD_HEIGHT)
    if size != expected:
        raise ValueError("DWD image is %s, expected %s" % (size, expected))
    return size


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, default=ROOT / "reports/live-maps.json")
    args = parser.parse_args()
    before, files = source_digest(ROOT)
    started = utc_now()
    clock = time.monotonic()
    records = []
    failures = []
    original = (radar.STATE, radar.CACHE, radar.download)
    previous_handler = signal.signal(signal.SIGALRM, alarm)
    signal.setitimer(signal.ITIMER_REAL, DEADLINE_SECONDS)
    try:
        with tempfile.TemporaryDirectory(prefix="owee-live-maps-", ignore_cleanup_errors=True) as temporary:
            base = Path(temporary)
            radar.STATE = base / "state"
            radar.CACHE = base / "cache"

            def case(place, provider, callback):
                record = {"place": place, "provider": provider}
                try:
                    record.update(callback())
                    record["status"] = "passed"
                except Exception as error:
                    record.update(status="failed", error=str(error)[:250])
                    failures.append(place + "/" + provider + ": " + str(error)[:250])
                records.append(record)

            def polar_rainviewer():
                radar.configure({"enabled": True, "zoom": 3, "source": "rainviewer", "layer": "rain"})
                result = radar.load(POLE)
                valid = (result.get("status") == "unsupported" and result.get("reason") == "projection_limit"
                         and result.get("latitude") == 90 and result.get("longitude") == 0)
                if not valid:
                    raise ValueError("Polar projection limit moved or misrepresented the selected point")
                return {"selected_point_preserved": True, "reason": result.get("reason")}

            def polar_dwd():
                radar.configure({"enabled": True, "zoom": 3, "source": "dwd", "layer": "rain"})
                result = radar.load(POLE)
                valid = (result.get("status") == "unsupported" and result.get("reason") == "coverage_limit"
                         and result.get("latitude") == 90 and result.get("longitude") == 0)
                if not valid:
                    raise ValueError("DWD coverage limit moved or misrepresented the selected point")
                return {"selected_point_preserved": True, "reason": result.get("reason")}

            def rainviewer_frames():
                radar.configure({"enabled": True, "zoom": 3, "source": "rainviewer", "layer": "rain"})
                manifest, stale = radar.manifest()
                frames = manifest["radar"]["past"]
                uri = radar.tile(f"{radar.RADAR_HOST}/v2/coverage/0/256/3/"
                                 f"{LYON['latitude']}/{LYON['longitude']}/0/0_0.png")
                if not uri or not radar.valid_png(local_png(uri)):
                    raise ValueError("Radar coverage mask unavailable or invalid")
                if stale:
                    raise ValueError("Radar manifest is stale")
                result = radar.load(LYON)
                base_ready = all(tile.get("source") for tile in result["tiles"])
                if not base_ready:
                    raise ValueError("OpenStreetMap basemap incomplete")
                if not result["frames"]:
                    raise ValueError(result.get("error", "No radar frames"))
                return {"past_frames": len(frames), "coverage_mask_png_verified": True,
                        "render_frames": len(result["frames"]),
                        "coverage_interpretation": "Mask obtained; this does not imply dry weather"}

            def dwd_rain():
                radar.configure({"enabled": True, "zoom": 6, "source": "dwd", "layer": "rain"})
                result = radar.load(ERFURT)
                frames = result["frames"]
                past = [frame for frame in frames if not frame["forecast"]]
                if not past:
                    raise ValueError(result.get("error", "DWD returned no observed frame"))
                steps = {b["time"] - a["time"] for a, b in zip(frames, frames[1:])}
                if steps - {radar.DWD_STEP}:
                    raise ValueError("DWD frame steps are %s, expected %d" % (sorted(steps), radar.DWD_STEP))
                sizes = {dwd_png(frame["image"]) for frame in frames if frame.get("image")}
                if not all(tile.get("source") for tile in result["tiles"]):
                    raise ValueError("OpenStreetMap basemap incomplete")
                # The nowcast layer is fetched on demand even when the timeline is still warming.
                bounds = radar.mercator_bounds(ERFURT["latitude"], ERFURT["longitude"], 6)
                _, future = radar.dwd_times()
                nowcast = radar.dwd_image(radar.dwd_url(radar.DWD_FUTURE_LAYER, future[0], bounds), True, True)
                if not nowcast:
                    # One transient render failure should not fail the probe.
                    for marker in (radar.CACHE / "dwd-").glob("*.miss"):
                        marker.unlink(missing_ok=True)
                    time.sleep(2)
                    nowcast = radar.dwd_image(radar.dwd_url(radar.DWD_FUTURE_LAYER, future[0], bounds), True, True)
                if not nowcast:
                    raise ValueError("DWD nowcast frame unavailable")
                sizes.add(dwd_png(nowcast))
                return {"frames": len(frames), "observed": len(past),
                        "nowcast_verified": True, "step_seconds": radar.DWD_STEP,
                        "png_sizes": sorted(sizes), "warming": result.get("warming", False)}

            def dwd_wind():
                radar.configure({"enabled": True, "zoom": 6, "layer": "wind"})
                result = radar.load(ERFURT)

                def steps_of(value):
                    found = value["frames"]
                    return {b["time"] - a["time"] for a, b in zip(found, found[1:])}

                frames, steps = result["frames"], steps_of(result)
                if not frames or (steps and steps != {3600}):
                    # A transient render failure leaves a gap or an empty map.
                    for marker in (radar.CACHE / "dwd-wind-").glob("*.miss"):
                        marker.unlink(missing_ok=True)
                    time.sleep(2)
                    result = radar.load(ERFURT)
                    frames, steps = result["frames"], steps_of(result)
                if not frames:
                    raise ValueError(result.get("error", "DWD returned no wind frame"))
                if steps and steps != {3600}:
                    raise ValueError("Wind frame steps are %s, expected 3600" % sorted(steps))
                sizes = {dwd_png(frame["image"], (radar.WIND_WIDTH, radar.WIND_HEIGHT)) for frame in frames}
                if not all(tile.get("source") for tile in result["tiles"]):
                    raise ValueError("OpenStreetMap basemap incomplete")
                return {"frames": len(frames), "step_seconds": 3600, "png_sizes": sorted(sizes),
                        "warming": result.get("warming", False)}

            def wind_outside_germany():
                radar.configure({"enabled": True, "zoom": 3, "layer": "wind"})
                result = radar.load(LYON)
                if result.get("status") != "unsupported" or result.get("reason") != "coverage_limit":
                    raise ValueError("Wind layer claimed coverage outside Germany")
                return {"reason": result.get("reason")}

            case("North Pole", "RainViewer", polar_rainviewer)
            case("North Pole", "DWD", polar_dwd)
            case("Lyon", "RainViewer", rainviewer_frames)
            case("Erfurt", "DWD rain", dwd_rain)
            case("Erfurt", "DWD wind", dwd_wind)
            case("Lyon", "DWD wind", wind_outside_germany)
    except ProbeDeadline as error:
        failures.append(str(error))
    except Exception as error:
        failures.append("Probe setup: " + str(error)[:250])
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous_handler)
        radar.STATE, radar.CACHE, radar.download = original
    after, _ = source_digest(ROOT)
    if before != after:
        failures.append("Source changed during live qualification; rerun on the final commit")
    expected = 6
    report = {"kind": "live_maps", "status": "passed" if not failures else "failed", "passed": not failures,
              "started_at": started, "finished_at": utc_now(), "elapsed_seconds": round(time.monotonic() - clock, 3),
              "source_sha256": before, "source_sha256_after": after, "source_files": files, "runtime": runtime_versions(),
              "cases": records, "failures": failures, "personal_state_accessed": False,
              "deadline_seconds": DEADLINE_SECONDS,
              "expected_cases": expected, "completed_cases": len(records)}
    if len(records) != expected:
        report["passed"] = False
        report["status"] = "failed"
        report["failures"].append("Not all planned live cases completed")
    args.report.parent.mkdir(parents=True, exist_ok=True)
    atomic_json(args.report, report)
    print(json.dumps({"status": report["status"], "cases": len(records),
                      "elapsed_seconds": report["elapsed_seconds"], "failures": report["failures"]}))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
