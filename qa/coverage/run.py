#!/usr/bin/env python3
"""Check map coverage and timezone UI with local assets and native Omarchy controls.

No weather API, installed plugin, or user preference is touched. Both backend
commands are replaced in the disposable copy, and all XDG writable paths are
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
    for name in ("Radar.qml",):
        text = (plugin / name).read_text()
        assert text.count("interval: 50000") == 1, "Production map watchdog must remain 50 seconds"
        (plugin / name).write_text(text.replace("interval: 50000", "interval: 1000"))
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
    tiles = [{"left": left, "top": 0, "source": pictures["base"]} for left in (0, 256)]
    frame = {"time": stamp, "tiles": [pictures["clear"]] * 2,
             "local_time": local, "timezone": "Asia/Tokyo"}

    def radar(mask, status="available"):
        return {"latitude": 45.75, "longitude": 4.85, "tiles": tiles,
                "frames": [frame], "coverage_status": status,
                "coverage_tiles": [{"left": left, "top": 0, "source": pictures[mask]} for left in (0, 256)]}

    opaque, clear = radar("opaque"), radar("clear")
    partial = radar("clear")
    partial["coverage_tiles"][1]["source"] = ""
    unknown = radar("opaque", "unknown")
    fallback = radar("opaque", "unknown")
    fallback["frames"] = [{**frame, "local_time": "not-a-timestamp"}]
    missing = (base / "missing-after-backend-response.png").as_uri()
    (base / "corrupt.png").write_bytes(b"not a valid PNG")
    corrupt = (base / "corrupt.png").as_uri()
    radar_missing = {**clear, "frames": [{**frame, "tiles": [missing] * 2}]}
    radar_corrupt = {**clear, "frames": [{**frame, "tiles": [corrupt] * 2}]}
    polar = {"status": "unsupported", "reason": "projection_limit", "latitude": 90,
             "longitude": 12, "frames": [], "tiles": [], "coverage_tiles": [],
             "coverage_status": "unsupported"}
    fixtures = {"opaque": opaque, "clear": clear, "partial": partial, "unknown": unknown,
                "fallback": fallback, "polar": polar, "radarMissing": radar_missing,
                "radarCorrupt": radar_corrupt, "radarCityClock": clock(stamp, tokyo),
                "radarDesktopClock": clock(stamp, timezone.utc)}
    (plugin / "coverage-data.json").write_text(json.dumps(fixtures))
    (plugin / "radar.py").write_text('''import json,sys,time
from pathlib import Path
data=json.loads(Path(__file__).with_name("coverage-data.json").read_text())
if sys.argv[1]=="load":
    city=json.loads(sys.argv[2])
    if city["latitude"]==44:time.sleep(30)
    output=data["polar"] if abs(city["latitude"])>85.05112878 else data["opaque"]
else:output={"settings":{"enabled":True,"zoom":6}}
print(json.dumps(output))
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
