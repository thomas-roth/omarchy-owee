#!/usr/bin/env python3
"""Check map coverage and timezone UI with local assets and native Omarchy controls.

No weather API, installed plugin, or user preference is touched. The radar
backend is replaced in the disposable copy, and all XDG writable paths are
isolated. Requires the Omarchy reference runtime used by the other GUI checks.
"""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
from zoneinfo import ZoneInfo

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
SHELL = Path("/usr/share/omarchy/shell")


def clock(stamp, zone):
    return datetime.fromtimestamp(stamp, zone).strftime("%d/%m %H:%M")


def prepare(base):
    for name in ("Commons", "Ui", "services"):
        (base / name).symlink_to(SHELL / name, target_is_directory=True)
    plugin = base / "plugin"
    plugin.mkdir()
    for source in ROOT.iterdir():
        if source.is_file() and source.suffix in (".qml", ".js", ".py", ".json"):
            shutil.copy2(source, plugin / source.name)
    # Exercise actual watchdog termination without extending the GUI suite by 50s.
    name, watchdog = "Radar.qml", "interval: 90000"
    text = (plugin / name).read_text()
    assert text.count(watchdog) == 1, "Production radar watchdog must remain 90 seconds"
    (plugin / name).write_text(text.replace(watchdog, "interval: 1000"))
    pictures = {}
    for name, content in {
        "opaque": '<rect width="256" height="256" fill="black"/>',
        "clear": '<rect width="256" height="256" fill="black" opacity="0"/>',
        "base": '<rect width="256" height="256" fill="#cad7d7"/>',
    }.items():
        picture = base / (name + ".svg")
        picture.write_text('<svg xmlns="http://www.w3.org/2000/svg" width="256" height="256">' + content + '</svg>')
        pictures[name] = picture.as_uri()
    stamp = int(time.time())
    tokyo = ZoneInfo("Asia/Tokyo")
    local = datetime.fromtimestamp(stamp, tokyo).isoformat(timespec="minutes")
    future = stamp + 3600
    future_local = datetime.fromtimestamp(future, tokyo).isoformat(timespec="minutes")
    tiles = [{"left": left, "top": 0, "width": 256, "height": 256, "source": pictures["base"]} for left in (0, 256)]
    frame_tiles = [{"left": 0, "top": 0, "width": 432, "height": 240, "source": pictures["clear"]}]

    def radar_meta(frame_pictures, status=None):
        value = {"kind": "meta", "settings": {"enabled": True, "rain_enabled": True, "wind_enabled": True, "zoom_level": 1},
                 "now": stamp,
                 "latitude": 45.75, "longitude": 4.85, "zoom_level": 1, "radius_km": 100,
                 "west": 4.3, "east": 5.4, "south": 45.35, "north": 46.15,
                 "width": 432, "height": 240, "tiles": tiles,
                 "rain": {"provider_name": "DWD", "source_url": "https://www.dwd.de/", "step_minutes": 5,
                          "now_index": 0, "stale": False, "frames": [
                              {"time": stamp, "kind": "past", "local_time": local, "timezone": "Asia/Tokyo",
                               "tiles": [dict(piece, source=frame_pictures[0]) for piece in frame_tiles]},
                              {"time": future, "kind": "future", "local_time": future_local, "timezone": "Asia/Tokyo",
                               "tiles": [dict(piece, source=frame_pictures[1]) for piece in frame_tiles]}]},
                 "wind": {"provider_name": "Open-Meteo", "source_url": "https://open-meteo.com/", "step_minutes": 15,
                          "now_index": 0, "stale": False, "frames": []}}
        if status:
            value.update(status=status[0], reason=status[1], tiles=[], frames=[], latitude=90, longitude=12,
                         rain={key: [] if key == "frames" else value["rain"][key] for key in value["rain"]},
                         wind={key: [] if key == "frames" else value["wind"][key] for key in value["wind"]})
        return value

    radar_default = radar_meta([pictures["clear"], pictures["clear"]])
    # The newest frame failed to render; the view must fall back to the nearest
    # complete frame instead of showing an empty map.
    radar_partial = radar_meta(["", pictures["clear"]])
    radar_missing = radar_meta([missing := (base / "missing-after-backend-response.png").as_uri()] * 2)
    radar_corrupt = radar_meta([corrupt := (base / "corrupt.png").as_uri()] * 2)
    (base / "corrupt.png").write_bytes(b"not a valid PNG")
    polar = radar_meta(["", ""], ("unsupported", "projection_limit"))
    fixtures = {"radarDefault": radar_default, "radarPartial": radar_partial,
                "radarMissing": radar_missing, "radarCorrupt": radar_corrupt,
                "polar": polar,
                "radarCityIso": local, "radarFutureIso": future_local,
                "radarCityClock": clock(stamp, tokyo)}
    (plugin / "coverage-data.json").write_text(json.dumps(fixtures))
    (plugin / "radar.py").write_text('''import json,sys,time
from pathlib import Path
data=json.loads(Path(__file__).with_name("coverage-data.json").read_text())
state=Path(__file__).with_name("coverage-radar-state.json")
default={"rain_enabled":True,"wind_enabled":True,"zoom_level":1}
current=json.loads(state.read_text()) if state.exists() else dict(default)
if sys.argv[1]=="load":
    city=json.loads(sys.argv[2])
    if city["latitude"]==44:time.sleep(30)
    if abs(city["latitude"])>85.05112878:
        print(json.dumps(data["polar"]))
    elif city.get("modes")==["wind"]:
        meta=data["radarDefault"]
        wind={"provider_name":"Open-Meteo","source_url":"https://open-meteo.com/","step_minutes":15,"now_index":0,"stale":False,
              "frames":[{"time":meta["now"],"kind":"past","points":[[45.75,4.85,3,180,0]],
                         "local_time":data["radarCityIso"],"timezone":"Asia/Tokyo"}]}
        print(json.dumps(dict(meta,wind=wind)))
    else:
        print(json.dumps(data["radarDefault"]))
        for index in range(len(data["radarDefault"]["rain"]["frames"])):
            print(json.dumps({"kind":"frame","index":index,"tiles":data["radarDefault"]["rain"]["frames"][index]["tiles"]}))
    print(json.dumps({"kind":"done","partial":False,"message":""}))
else:
    if sys.argv[1]=="configure":
        value=json.loads(sys.argv[2])
        for key in ("rain_enabled","wind_enabled","zoom_level"):
            if key in value:current[key]=value[key]
        state.write_text(json.dumps(current))
    print(json.dumps({"settings":current}))
''')
    (base / "shell.qml").write_text((HERE / "tst_coverage.qml").read_text().replace("@@FIXTURES@@", json.dumps(fixtures)))


def main():
    if not shutil.which("quickshell") or not (SHELL / "Commons").is_dir():
        raise SystemExit("QA_COVERAGE_FAIL: native Omarchy/Quickshell reference runtime required")
    with tempfile.TemporaryDirectory(prefix="owee-coverage-test-") as temporary:
        base = Path(temporary)
        prepare(base)
        env = os.environ.copy()
        env.update(QT_QPA_PLATFORM="offscreen", QT_QUICK_BACKEND="software", TZ="UTC",
                   XDG_STATE_HOME=str(base / "state"), XDG_CACHE_HOME=str(base / "cache"),
                   XDG_CONFIG_HOME=str(base / "config"), XDG_DATA_HOME=str(base / "data"),
                   PYTHONDONTWRITEBYTECODE="1")
        try:
            result = subprocess.run(["quickshell", "--no-color", "-p", str(base)], env=env,
                                    text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=25)
        except subprocess.TimeoutExpired as error:
            raise SystemExit("QA_COVERAGE_FAIL: GUI timeout after 25 seconds") from error
        output = result.stdout
        report = ROOT / "reports" / "coverage.log"
        report.parent.mkdir(exist_ok=True)
        report.write_text(output)
        failures = [line for line in output.splitlines() if "ERROR" in line or "QA_COVERAGE_FAIL" in line]
        if result.returncode or failures or "QA_COVERAGE_PASS" not in output:
            print("\n".join(output.splitlines()[-60:]))
            raise SystemExit(result.returncode or 1)
        print("\n".join(line.strip() for line in output.splitlines() if "QA_COVERAGE_" in line))
        print("QA_COVERAGE_ISOLATION_PASS: local assets, mocked backends, isolated XDG paths; no API or user-state writes")


if __name__ == "__main__":
    main()
