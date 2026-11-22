#!/usr/bin/env python3
"""Run a plugin QML smoke test against real Omarchy components, without mapping a popup.

Only a disposable copy is changed: backend processes return fixtures and the
lazy popup is requested on completion. Installed plugin/preferences stay intact.
"""
import argparse
import copy
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile


ROOT = Path(__file__).resolve().parents[1]
CARD_IDS = ["wind", "humidity", "uv", "sun", "pressure", "visibility", "precipitation", "air", "pollen"]


def fixture():
    result = {
        "city": {"name": "Paris", "latitude": 48.85, "longitude": 2.35},
        "unit": "C", "auto_refresh": False, "updated": 1794560400, "stale": False,
        "cities": [{"name": "Lyon", "latitude": 45.75, "longitude": 4.85},
                   {"name": "Paris", "latitude": 48.85, "longitude": 2.35},
                   {"name": '<img src="https://example.invalid/probe"> Ville', "latitude": 1, "longitude": 2}],
        "cards": CARD_IDS, "hidden_cards": ["air", "pollen"],
        "notifications": {"enabled": True, "daily": True, "rain": True, "wind": True, "uv": True},
        "data": {
            "current": {"time": "2026-11-13T14:00", "temperature_2m": 22, "apparent_temperature": 21,
                        "weather_code": 2, "is_day": 1, "relative_humidity_2m": 75, "wind_speed_10m": 15,
                        "wind_direction_10m": 170, "surface_pressure": 1012, "precipitation": 0.1},
            "hourly": {"time": [f"2026-11-13T{h:02}:00" for h in range(24)],
                       "temperature_2m": [12]*24, "precipitation_probability": [65]*24,
                       "weather_code": [2]*24, "visibility": [10000]*24, "is_day": [1]*24},
            "daily": {"time": ["2026-11-13", "2026-11-14"], "temperature_2m_max": [15, 16],
                      "temperature_2m_min": [8, 9], "weather_code": [2, 3], "uv_index_max": [2, 2],
                      "precipitation_probability_max": [65, 10],
                      "sunrise": ["2026-11-13T07:30"], "sunset": ["2026-11-13T17:20"]},
            "air": {"european_aqi": 24, "grass_pollen": 2}, "timezone": "Europe/Paris"
        }
    }
    primary_city = {"name": "Lyon", "latitude": 45.75, "longitude": 4.85}
    primary = {key: copy.deepcopy(result[key]) for key in ("data", "updated", "stale")}
    primary["city"] = primary_city
    primary["data"]["current"].update(temperature_2m=3, apparent_temperature=1, weather_code=0, is_day=0)
    result.update(primary_city=primary_city, primary=primary)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("plugin", nargs="?", type=Path, default=ROOT)
    parser.add_argument("--log", type=Path, default=ROOT / "qa/runtime-qml.log")
    parser.add_argument("--expected-version", default=json.loads((ROOT / "manifest.json").read_text())["version"], help="Manifest version under test")
    args = parser.parse_args()
    version = json.loads((args.plugin / "manifest.json").read_text())["version"]
    if version != args.expected_version:
        raise SystemExit(f"Unexpected plugin version: {version}, expected {args.expected_version}")
    shell = Path(os.environ.get("OMARCHY_PATH", "/usr/share/omarchy")) / "shell"
    with tempfile.TemporaryDirectory(prefix="pixel-weather-qa-") as tmp:
        base = Path(tmp)
        for directory in ("Commons", "Ui", "services"):
            (base / directory).symlink_to(shell / directory, target_is_directory=True)
        plugin = base / "plugin"
        shutil.copytree(args.plugin, plugin, ignore=shutil.ignore_patterns("__pycache__", "tests", ".git", "reports", "qa", ".github"))
        data = fixture()
        stub = "#!/usr/bin/env python3\nimport json\nprint(" + repr(json.dumps(data, ensure_ascii=False)) + ")\n"
        (plugin / "weather.py").write_text(stub)
        # Avoid radar/network and preference effects if the new component exists.
        (plugin / "radar.py").write_text("#!/usr/bin/env python3\nprint('{\"settings\":{\"rain_enabled\":false,\"wind_enabled\":false,\"zoom_level\":1},\"rain\":{\"frames\":[]},\"wind\":{\"frames\":[]}}')\n")
        forecast_calls = base / "forecast-calls.jsonl"
        (plugin / "forecast_map.py").write_text(
            "#!/usr/bin/env python3\nimport json,sys\n"
            + "with open(" + repr(str(forecast_calls)) + ", 'a') as log: log.write(json.dumps(sys.argv[1:])+'\\n')\n"
            + "print('{\"settings\":{\"enabled\":false,\"zoom\":6,\"layer\":\"precipitation\"},\"frames\":[]}')\n")
        panel = plugin / "Panel.qml"
        qml = panel.read_text()
        qml = qml.replace('  manageIpc: false', '  manageIpc: false\n  readonly property var qaPopupContent: popup.loadedContent', 1)
        marker = "Component.onCompleted: root.refresh()"
        if marker not in qml:
            raise RuntimeError("Panel completion hook changed; review smoke harness")
        qml = qml.replace(marker, "Component.onCompleted: { root.refresh(); popup.ensureContent() }", 1)
        has_cards = (plugin / "WeatherCards.qml").exists()
        if has_cards:
            # Disposable hook: reach the real embedded editor inside lazy popup content.
            qml = qml.replace('  manageIpc: false', '  manageIpc: false\n  property var qaCards: null', 1)
            qml = qml.replace('          WeatherCards {', '          WeatherCards {\n            id: qaEmbeddedCards\n            Component.onCompleted: root.qaCards = qaEmbeddedCards', 1)
        has_forecast = (plugin / "ForecastMap.qml").exists()
        if has_forecast:
            qml = qml.replace('  manageIpc: false', '  manageIpc: false\n  property var qaForecast: null', 1)
            qml = qml.replace('          ForecastMap {', '          ForecastMap {\n            id: qaEmbeddedForecast\n            Component.onCompleted: root.qaForecast = qaEmbeddedForecast', 1)
        panel.write_text(qml)
        optional = ""
        checks = '''
    var p = panelLoader.item
    var viewport = findNamed(p.qaPopupContent, "weather-viewport")
    if (!viewport) { console.error("QA_FAIL: viewport missing"); Qt.exit(1); return }
    viewport.contentY = 300
    var oldSerial = p.openingSerial
    p.prepareOpening()
    if (viewport.contentY !== 0 || p.openingSerial !== oldSerial + 1) { console.error("QA_FAIL: opening retains scroll"); Qt.exit(1); return }
    console.warn("QA_OPENING_SCROLL_PASS: reopening restores hero visibility")
    var icon = findNamed(barLoader.item, "weather-bar-icon")
    var temperature = findNamed(barLoader.item, "weather-bar-temperature")
    var button = findNamed(barLoader.item, "weather-bar-button")
    var optical = findNamed(barLoader.item, "weather-bar-optical")
    if (!icon || icon.code !== 0 || !icon.night || temperature
        || !button || !optical || Math.abs(Math.max(optical.paintedWidth, optical.paintedHeight) - Commons.Style.bar.iconSize) > 0.1
        || Math.abs(button.implicitWidth - Commons.Style.bar.statusSlot) > 0.1
        || button.implicitHeight !== Commons.Style.bar.sizeHorizontal
        || button.tooltipText !== "Weather: 3°C, feels 1°C") {
      console.error("QA_FAIL: bar icon, tooltip or measured width", icon ? icon.code : null, icon ? icon.night : null,
                    temperature ? temperature.text : null, button ? button.implicitWidth : null,
                    button ? button.implicitHeight : null, button ? button.tooltipText : null,
                    optical ? optical.paintedWidth : null, optical ? optical.paintedHeight : null,
                    Commons.Style.bar.iconSize, Commons.Style.bar.statusSlot, Commons.Style.bar.sizeHorizontal); Qt.exit(1); return
    }
    console.warn("QA_BAR_PASS: native button, night icon, tooltip with felt temperature and icon-only layout")
    button.bar = verticalBar
    Qt.callLater(function() {
      if (!button.vertical || button.implicitWidth !== 32 || button.implicitHeight < optical.height) {
        console.error("QA_FAIL: vertical bar layout"); Qt.exit(1); return
      }
      console.warn("QA_BAR_VERTICAL_PASS: icon stacked in native button")
    })
    if (p.cityName !== "Paris" || p.current.temperature_2m !== 22 || p.primaryCityName !== "Lyon"
        || p.primaryCurrent.temperature_2m !== 3 || p.label !== "☾ 3°") {
      console.error("QA_FAIL: primary city and consulted city mixed", p.cityName, p.label); Qt.exit(1); return
    }
    console.warn("QA_PRIMARY_PASS: Paris panel 22°C and Lyon bar 3°C remain separate")
'''
        if has_forecast:
            checks += '''
    if (!p.qaForecast || p.qaForecast.city.name !== "Paris" || p.qaForecast.active !== false
        || p.qaForecast.forecastEnabled !== false || p.qaForecast.settingsLoaded !== true) {
      console.error("QA_FAIL: forecast map did not receive the consulted city or is active while popup closed"); Qt.exit(1); return
    }
    console.warn("QA_FORECAST_PASS: forecast map loaded for Paris and inactive while popup closed")
'''
        if (plugin / "NotificationSettings.qml").exists():
            optional += '''
  Loader {
    id: notificationSettings
    source: Qt.resolvedUrl("plugin/NotificationSettings.qml")
    onLoaded: {
      item.width = 440
      item.expanded = true
      item.config = {enabled:true, rain:true, wind:true, uv:true, daily:true, quiet_enabled:true}
      item.primaryCityName = "Lyon"
    }
  }
'''
            checks += '''
    if (!notificationSettings.item || !notificationSettings.item.expanded || !notificationSettings.item.config.enabled) {
      console.error("QA_FAIL: notification controls not instantiated"); Qt.exit(1); return
    }
    if (!hasText(notificationSettings.item, "Lyon") || !hasText(notificationSettings.item, "Bar & notification city")) {
      console.error("QA_FAIL: notifications do not identify the primary city"); Qt.exit(1); return
    }
'''
        if (plugin / "CityList.qml").exists():
            optional += '''
  Loader {
    id: cityList
    source: Qt.resolvedUrl("plugin/CityList.qml")
    onLoaded: { item.width = 440; item.cities = fixture.cities; item.currentCity = fixture.city; item.primaryCity = fixture.primary_city }
  }
'''
            checks += '''
    if (!cityList.item || !hasText(cityList.item, "Paris") || !hasText(cityList.item, "Lyon")) {
      console.error("QA_FAIL: city chooser not instantiated"); Qt.exit(1); return
    }
    if (!plainMarkup(cityList.item)) { console.error("QA_FAIL: city markup reached a rich-text sink"); Qt.exit(1); return }
'''
        if (plugin / "WeatherCards.qml").exists():
            optional += '''
  Loader {
    id: weatherCards
    source: Qt.resolvedUrl("plugin/WeatherCards.qml")
    onLoaded: {
      item.width = 440; item.order = fixture.cards; item.hidden = fixture.hidden_cards; item.editing = true; item.active = true
      item.cardInfo = function(id) { return {title:id, value:"12", detail:"Controlled fixture"} }
    }
  }
'''
            checks += '''
    if (!weatherCards.item || weatherCards.item.order.length !== 9 || !weatherCards.item.editing) {
      console.error("QA_FAIL: card editor not instantiated"); Qt.exit(1); return
    }
'''
        finish = '''
    console.warn("QA_PASS: Panel instantiated with lazy content and weather fixture")
    Qt.quit()
'''
        if has_cards:
            finish = '''
    var wind = findNamed(p.qaCards, "card-wind")
    if (!wind || wind.info.value !== "15 km/h") {
      console.error("QA_FAIL: embedded card did not receive consulted weather", wind); Qt.exit(1); return
    }
    var changed = JSON.parse(JSON.stringify(p.result))
    changed.data.current.temperature_2m = 28
    changed.data.current.wind_speed_10m = 37
    changed.data.current.relative_humidity_2m = 31
    p.result = changed
    Qt.callLater(function() {
      var updatedWind = findNamed(p.qaCards, "card-wind")
      var humidity = findNamed(p.qaCards, "card-humidity")
      var humidityVisual = findNamed(p.qaCards, "visual-humidity")
      if (!humidityVisual || humidityVisual.reading !== 31 || !humidityVisual.known) {
        console.error("QA_FAIL: humidity illustration did not follow the consulted city update"); Qt.exit(1); return
      }
      if (!updatedWind || updatedWind.info.value !== "37 km/h" || !humidity || humidity.info.value !== "31 %"
          || p.current.temperature_2m !== 28 || p.primaryCurrent.temperature_2m !== 3 || p.label !== "☾ 3°") {
        console.error("QA_FAIL: card weather binding froze or primary city changed"); Qt.exit(1); return
      }
      console.warn("QA_CARDS_REACTIVE_PASS: consulted weather updated cards while primary city stayed stable")
      var missing = JSON.parse(JSON.stringify(p.result))
      missing.data.current.relative_humidity_2m = null
      missing.data.current.surface_pressure = null
      missing.data.current.wind_direction_10m = null
      missing.data.current.is_day = 0
      missing.data.daily.uv_index_max = [null]
      p.result = missing
      Qt.callLater(function() {
        if (findNamed(p.qaCards, "visual-humidity").known || findNamed(p.qaCards, "visual-pressure").known
            || findNamed(p.qaCards, "visual-uv").known || isFinite(findNamed(p.qaCards, "visual-wind").direction)
            || isFinite(findNamed(p.qaCards, "visual-sun").dayProgress)) {
          console.error("QA_FAIL: missing readings or night time invented a measurement marker"); Qt.exit(1); return
        }
        console.warn("QA_MEASUREMENT_EMPTY_PASS: missing readings and night time leave indicators empty")
        console.warn("QA_PASS: Panel instantiated with lazy content and weather fixture")
        Qt.quit()
      })
    })
'''
        (base / "shell.qml").write_text('''//@ pragma OmarchyLoadPatch
import QtQuick
import Quickshell
import qs.Commons as Commons
import "plugin" as Weather
ShellRoot {
  property QtObject verticalBar: QtObject {
    property bool vertical: true
    property int barSize: 32
    property string fontFamily: "monospace"
    property color barForeground: "white"
    property color urgent: "red"
    property bool foregroundAnimationEnabled: false
    function hideTooltip(item) {}
    function registerClickTarget(item) {}
    function unregisterClickTarget(item) {}
  }
  property var fixture: ''' + json.dumps(data, ensure_ascii=False) + '''
  function hasText(item, phrase) {
    if (typeof item.text === "string" && item.text.indexOf(phrase) >= 0) return true
    for (var i = 0; item.children && i < item.children.length; i++) if (hasText(item.children[i], phrase)) return true
    return false
  }
  function plainMarkup(item) {
    if (typeof item.text === "string" && item.text.indexOf("<img") >= 0 && item.textFormat !== Text.PlainText) return false
    for (var i = 0; item.children && i < item.children.length; i++) if (!plainMarkup(item.children[i])) return false
    return true
  }
  function findNamed(item, name) {
    if (!item) return null
    if (item.objectName === name) return item
    for (var i = 0; item.children && i < item.children.length; i++) {
      var found = findNamed(item.children[i], name)
      if (found) return found
    }
    return null
  }
  Loader { id: panelLoader; source: Qt.resolvedUrl("plugin/Panel.qml"); onLoaded: console.warn("QA_LOADED", item) }
  Loader { id: barLoader; source: Qt.resolvedUrl("plugin/BarWidget.qml") }
''' + optional + '''
  property Timer finishTimer: Timer { interval: 1500; running: true; onTriggered: {
    if (!panelLoader.item || !panelLoader.item.result.data) { console.error("QA_FAIL: fixture not loaded"); Qt.exit(1); return }
''' + checks + finish + '''
  } }
}
''')
        env = os.environ.copy()
        env.update(QT_QPA_PLATFORM="wayland", QT_QUICK_BACKEND="software", XDG_STATE_HOME=str(base / "state"))
        proc = subprocess.run(["timeout", "5s", "quickshell", "--no-color", "-p", str(base)], env=env,
                              text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=15)
        print(proc.stdout, end="")
        verification_notes = ["QA_VERSION_PASS: " + version]
        errors = [line for line in proc.stdout.splitlines() if any(token in line for token in
                  ("WARN scene:", "ERROR", "QA_FAIL"))]
        if has_forecast:
            calls = [json.loads(line) for line in forecast_calls.read_text().splitlines()] if forecast_calls.exists() else []
            if not calls or any(not call or call[0] != "settings" for call in calls):
                errors.append("QA_FAIL: disabled/closed forecast map attempted an action other than settings: " + repr(calls))
            else:
                verification_notes.append("QA_FORECAST_NETWORK_PASS: disabled map only read settings; no download action")
        args.log.write_text(proc.stdout + "\n".join(verification_notes) + "\n")
        for note in verification_notes:
            print(note)
        if proc.returncode != 0 or "QA_PASS:" not in proc.stdout or errors:
            if errors:
                print("\n".join(errors))
            raise SystemExit(1)


if __name__ == "__main__":
    main()
