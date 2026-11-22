#!/usr/bin/env python3
"""Render actual standalone plugin controls with fixtures in an offscreen window."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time

from runtime_qml import ROOT, CARD_IDS, fixture


CARD_INFO = {
    "wind": {"title": "Wind", "value": "15 km/h", "detail": "From S · 170°", "direction": 170},
    "humidity": {"title": "Humidity", "value": "75 %", "detail": "Moisture in the air", "reading": 75},
    "uv": {"title": "UV index", "value": "2", "detail": "Today’s peak · forecast", "reading": 2},
    "sun": {"title": "Sunrise / sunset", "value": "07:30 / 17:20", "detail": "City local time", "progress": 0.6},
    "pressure": {"title": "Pressure", "value": "1012 hPa", "detail": "At ground level", "reading": 1012},
    "visibility": {"title": "Visibility", "value": "10.0 km", "detail": "Viewing distance · forecast"},
    "precipitation": {"title": "Precipitation", "value": "0.1 mm", "detail": "Recent rain / snow amount"},
    "air": {"title": "Air quality", "value": "24", "detail": "Fair · EU AQI"},
    "pollen": {"title": "Pollen", "value": "2 grains/m³", "detail": "Highest type · forecast"},
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--radar-fixture", type=Path, help="Existing radar JSON with local tile URLs; no network")
    parser.add_argument("--plugin", type=Path, default=ROOT)
    parser.add_argument("--only", action="append", choices=["NotificationSettings", "Radar", "CityList", "WeatherCards", "WeatherCards-edit"], help="Render only selected controls; repeatable")
    args = parser.parse_args()
    source = args.plugin
    controls = args.only or ["NotificationSettings", "Radar", "CityList", "WeatherCards", "WeatherCards-edit"]
    data = fixture()
    for name in controls:
        component = name.partition("-")[0]
        if not (source / (component + ".qml")).exists():
            if args.only:
                raise SystemExit(f"Missing component: {component}")
            continue
        output = ROOT / "qa" / (name + ".png")
        with tempfile.TemporaryDirectory(prefix="pixel-weather-render-") as tmp:
            base = Path(tmp)
            for directory in ("Commons", "Ui"):
                (base / directory).symlink_to(Path("/usr/share/omarchy/shell") / directory, target_is_directory=True)
            plugin = base / "plugin"
            shutil.copytree(source, plugin, ignore=shutil.ignore_patterns("__pycache__", "tests", ".git", "reports", "qa", ".github"))
            # A tiny local SVG is a visible fixture, not claimed to be live radar.
            (base / "tile.svg").write_text('''<svg xmlns="http://www.w3.org/2000/svg" width="256" height="256"><rect width="256" height="256" fill="#e8efeb"/><path d="M0 150L256 30M80 0L220 256M0 90L256 200" stroke="#fff" stroke-width="12"/><path d="M0 240L256 50" stroke="#abd4e5" stroke-width="20"/></svg>''')
            tile = (base / "tile.svg").as_uri()
            stamp = int(time.time() // 3600 * 3600)
            radar = {"now": stamp, "latitude": 45.75, "longitude": 4.85, "zoom_level": 1, "radius_km": 100,
                     "west": 4.3, "east": 5.4, "south": 45.35, "north": 46.15, "width": 432, "height": 240,
                     "tiles": [{"left": 0, "top": 0, "source": tile}, {"left": 256, "top": 0, "source": tile}],
                     "rain": {"provider_name": "DWD", "source_url": "https://www.dwd.de/", "step_minutes": 5, "now_index": 1,
                              "frames": [{"time": stamp + (i - 1) * 600, "kind": "past" if i <= 1 else "future",
                                          "tiles": [{"left": 0, "top": 0, "width": 432, "height": 240, "source": tile}]} for i in range(3)]},
                     "wind": {"provider_name": "", "source_url": "", "step_minutes": 0, "now_index": -1, "frames": []}}
            if args.radar_fixture:
                radar = json.loads(args.radar_fixture.read_text())
            (plugin / "radar.py").write_text("import json,sys\nprint(json.dumps(" + repr({"settings": {"rain_enabled": True, "wind_enabled": True, "zoom_level": 1}}) + " if sys.argv[1] != 'load' else " + repr(radar) + "))\n")
            if name == "NotificationSettings":
                init = '''item.expanded = true; item.config = {enabled:true, rain:true, wind:true, uv:true, daily:true, quiet_enabled:true}; item.primaryCityName = "Lyon"'''
            elif name == "Radar":
                init = '''item.city = {name:"Lyon",latitude:45.75,longitude:4.85}; item.active = true'''
            elif name == "CityList":
                init = "item.cities = " + json.dumps(data["cities"], ensure_ascii=False) + "; item.currentCity = " + json.dumps(data["city"]) + "; item.primaryCity = " + json.dumps(data["primary_city"])
            else:
                init = "item.order = " + json.dumps(CARD_IDS) + "; item.hidden = ['air','pollen']; item.active = true; item.editing = " + ("true" if name.endswith("-edit") else "false") + "; item.cardInfo = function(id) { var map = " + json.dumps(CARD_INFO, ensure_ascii=False) + "; return map[id] }"
            checks = ""
            if component == "WeatherCards":
                visible = CARD_IDS if name.endswith("-edit") else [key for key in CARD_IDS if key not in ("air", "pollen")]
                checks = '''
        var expected = ''' + json.dumps([CARD_INFO[key]["title"] for key in visible], ensure_ascii=False) + '''
        var visibleTitles = []
        function collect(item) {
          if (item.visible && typeof item.text === "string" && cardTitles.indexOf(item.text) >= 0) visibleTitles.push(item.text)
          for (var i = 0; item.children && i < item.children.length; i++) collect(item.children[i])
        }
        collect(control.item)
        if (visibleTitles.length !== expected.length || expected.some(function(title) { return visibleTitles.indexOf(title) < 0 })) {
          console.error("QA_FAIL: card visibility", JSON.stringify(visibleTitles)); Qt.exit(1); return
        }
        console.warn("QA_CARDS_PASS: expected visible cards", visibleTitles.length)
'''
            (base / "shell.qml").write_text('''import QtQuick
import QtQuick.Window
import Quickshell
import qs.Commons as Commons
import "plugin" as Weather
ShellRoot {
  property var cardTitles: ''' + json.dumps([CARD_INFO[key]["title"] for key in CARD_IDS], ensure_ascii=False) + '''
  Window {
    id: window
    visible: true
    width: 460
    height: 1200
    color: Commons.Color.background
    Rectangle { anchors.fill: parent; color: Commons.Color.background }
    Loader {
      id: control
      x: 14; y: 14; width: parent.width - 28
      source: Qt.resolvedUrl("plugin/''' + component + '''.qml")
      onLoaded: { item.width = width; ''' + init + ''' }
    }
    Timer {
      interval: 1100; running: true
      onTriggered: {
        if (!control.item) { console.error("QA_FAIL: control did not load"); Qt.exit(1); return }
        if (typeof control.item.step === "function" && control.item.frames.length > 1) {
          var r = control.item
          if (r.frames.length < 2) { console.error("QA_FAIL: radar frames not loaded"); Qt.exit(1); return }
          var previous = r.frameIndex
          r.step(-1)
          if (r.frameIndex !== (previous - 1 + r.frames.length) % r.frames.length) {
            console.error("QA_FAIL: radar previous-frame control"); Qt.exit(1); return
          }
          r.playing = true
          r.active = false
          if (r.playing) { console.error("QA_FAIL: hidden radar still playing"); Qt.exit(1); return }
          r.active = true
          if (typeof r.selectFrame === "function") {
            var readyIndex = r.frames.findIndex(function(frame) { return frame.images && frame.images.length > 0 })
            r.selectFrame(Math.max(0, readyIndex), false, false)
          } else r.frameIndex = r.frames.length - 1
          console.warn("QA_MAP_PASS: frame stepping and playback stop on closure")
        }
''' + checks + '''
        if (control.item.implicitHeight < 1 || control.item.implicitHeight > 2000) {
          console.error("QA_FAIL: invalid control height", control.item.implicitHeight); Qt.exit(1); return
        }
        window.height = control.item.implicitHeight + 28
        console.warn("QA_CONTROL_HEIGHT", control.item.implicitHeight)
        capture.start()
      }
    }
    Timer {
      id: capture; interval: 200
      onTriggered: window.contentItem.grabToImage(function(result) {
        if (!result.saveToFile(''' + json.dumps(str(output)) + ''')) { console.error("QA_FAIL: capture failed"); Qt.exit(1); return }
        console.warn("QA_PASS: rendered ''' + name + '''")
        Qt.quit()
      })
    }
  }
}
''')
            env = os.environ.copy()
            env.update(QT_QPA_PLATFORM="offscreen", QT_QUICK_BACKEND="software", XDG_STATE_HOME=str(base / "state"))
            proc = subprocess.run(["timeout", "5s", "quickshell", "--no-color", "-p", str(base)], env=env,
                                  text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=10)
            (ROOT / "qa" / (name + "-render.log")).write_text(proc.stdout)
            print(proc.stdout, end="")
            if proc.returncode or "QA_PASS:" not in proc.stdout or "WARN scene:" in proc.stdout or "ERROR" in proc.stdout:
                raise SystemExit(1)


if __name__ == "__main__":
    main()
