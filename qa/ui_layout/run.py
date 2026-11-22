#!/usr/bin/env python3
"""Exercise the complete layout in real Quickshell, with isolated local fixtures.

The popup content is reparented to an offscreen Window in a disposable copy.
Real Omarchy controls receive mouse and wheel events through QtTest.TestEvent.
The layer-shell container alone is doubled: Quickshell does not provide a
PanelWindow backend on Qt's offscreen platform. Native container loading is
covered separately by qa/runtime_qml.py on the user's Wayland session.
No installed plugin, user preferences, network service or notification is used.
"""
import argparse
import datetime as dt
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "qa"))
from runtime_qml import fixture


BACKEND = r'''import json,sys,time
from pathlib import Path
base=Path(__file__).parent
name=Path(sys.argv[0]).stem
action=sys.argv[1] if len(sys.argv)>1 else 'load'
arg=sys.argv[2] if len(sys.argv)>2 else None
with (base/'backend-trace.jsonl').open('a') as log: log.write(json.dumps({'name':name,'action':action,'arg':arg})+'\n')
state=base/'fixture-state.json'
data=json.loads(state.read_text())
if name=='weather':
    if action=='air':
        city=json.loads(arg);key=f"{city['latitude']:.5f},{city['longitude']:.5f}"
        print(json.dumps({'city_key':key,'air':data['data'].get('air',{}),'capabilities':{},'updated':int(time.time())}));sys.exit()
    if action in ('notify','notify-test'):
        print(json.dumps({'notification_status':{'sent':True}}));sys.exit()
    if action=='search':
        print(json.dumps({'results':[{'name':'Rennes','latitude':48.11,'longitude':-1.68,'country':'France'}]}));sys.exit()
    if action=='unit':data['unit']=arg
    if action=='auto':data['auto_refresh']=arg!='off'
    if action=='notifications':data['notifications'].update(json.loads(arg))
    if action=='select':data['city']=json.loads(arg)
    if action=='primary':
        candidate=next(c for c in data['cities'] if f"{c['latitude']:.5f},{c['longitude']:.5f}"==arg)
        data['primary_city']=candidate
        data['primary']={key:data[key] for key in ('city','data','updated','stale')}
        data['primary']['city']=candidate
    state.write_text(json.dumps(data))
    print(json.dumps(data));sys.exit()
settings={'enabled':True,'zoom_level':1}
if name=='forecast_map':settings['layer']='precipitation'
if action in ('settings','configure'):
    if action=='configure' and arg:
        change=json.loads(arg)
        settings.update({key:value for key,value in change.items() if key in ('enabled','zoom_level')})
    print(json.dumps({'settings':settings}));sys.exit()
tile=(base/'map.svg').as_uri()
overlay=(base/'overlay.svg').as_uri()
now=int(time.time())
if name=='radar':
    frames=[{'time':now-7200+i*300,'kind':'past' if now-7200+i*300<=now else 'future',
             'tiles':[{'left':0,'top':0,'width':432,'height':240,'source':''}]} for i in range(49)]
    wind=[{'time':now-7200+i*900,'kind':'past' if now-7200+i*900<=now else 'future',
           'points':[[52.2+0.5*r/4,13.0+0.9*c/6,5+(r*7+c)%25,225+(r*7+c)*3%90,10+(r+c)%30] for r in range(5) for c in range(7)]} for i in range(17)]
    print(json.dumps({'kind':'meta','settings':settings,'now':now,'latitude':48.85,'longitude':2.35,
      'zoom_level':1,'radius_km':100,'west':2.2,'east':2.5,'south':48.65,'north':49.05,
      'width':432,'height':240,'tiles':[{'left':0,'top':0,'width':256,'height':256,'source':tile},{'left':256,'top':0,'width':256,'height':256,'source':tile}],
      'rain':{'provider_name':'DWD','source_url':'https://www.dwd.de/','step_minutes':5,'now_index':24,'stale':False,'frames':frames},
      'wind':{'provider_name':'Open-Meteo','source_url':'https://open-meteo.com/','step_minutes':15,'now_index':8,'stale':False,'frames':wind}}))
    for index in range(49):
        print(json.dumps({'kind':'frame','index':index,'tiles':[{'left':0,'top':0,'width':432,'height':240,'source':overlay}]}))
    print(json.dumps({'kind':'done','partial':False,'message':''}))
    sys.exit()
start=(now//3600+1)*3600
times=[start+i*10800 for i in range(4)]
selected=json.loads(arg)['time'] if action=='frame' else times[0]
frames=[{'time':stamp,'images':[{'left':0,'top':0,'width':432,'height':240,'source':overlay}] if stamp==selected else []} for stamp in times]
print(json.dumps({'settings':settings,'width':432,'height':240,'tiles':[{'left':0,'top':0,'source':tile},{'left':256,'top':0,'source':tile}],
 'frames':frames,'selected_time':selected,'run_time':now-6*3600,'updated':now,'stale':False,
 'title':'1-hour precipitation','unit':'mm / 1 h','model':'GDPS','provider':'ECCC GeoMet','resolution':'15 km',
 'layers':[{'id':'precipitation','title':'Precipitation'},{'id':'temperature','title':'Temperature'},{'id':'clouds','title':'Clouds'}],
 'legend':{'source':(base/'legend.svg').as_uri(),'width':260,'height':54,'caption':'Local test data'}}))
'''

CONTAINER = '''import QtQuick
Item {
  id: root
  property var anchorItem: null
  property var owner: null
  property var bar: null
  property bool open: false
  property bool centerOnBar: false
  property real contentWidth: 460
  property real contentHeight: 760
  property real verticalContentInset: 0
  property var focusTarget: null
  property Component content: null
  property bool contentRequested: false
  readonly property Item loadedContent: loader.item
  function fittedContentWidth(value) { return value }
  function fittedContentHeight(value, cap) {
    return (cap !== undefined && Number(cap) > 0 && Number(value) > Number(cap)) ? Number(cap) : Number(value)
  }
  function ensureContent() { contentRequested=true;return loader.item }
  Loader {
    id: loader
    active: root.contentRequested
    sourceComponent: root.content
    onLoaded: {
      item.width=Qt.binding(function(){return root.contentWidth})
      item.height=Qt.binding(function(){return root.contentHeight})
    }
  }
}
'''


def prepare(base, plugin, output):
    shell = Path("/usr/share/omarchy/shell")
    for name in ("Commons", "Ui", "services"):
        (base / name).symlink_to(shell / name, target_is_directory=True)
    destination = base / "plugin"
    shutil.copytree(plugin, destination, ignore=shutil.ignore_patterns("__pycache__", "tests", ".git", "reports", "qa", ".github"))
    data = fixture()
    data["notifications"]["enabled"] = False
    data["updated"] = int(time.time())
    start = dt.datetime(2026, 11, 13)
    hours = [(start + dt.timedelta(hours=i)).strftime("%Y-%m-%dT%H:%M") for i in range(48)]
    data["data"]["hourly"].update(time=hours, temperature_2m=[5+(i%8) for i in range(48)],
        weather_code=([2,3,61,0]*12), is_day=[1]*48,
        precipitation_probability=([0,10,20,65,75,45,20,0]*6), visibility=[10000]*48)
    data["data"]["daily"].update(time=[(start+dt.timedelta(days=i)).strftime("%Y-%m-%d") for i in range(10)],
        weather_code=[2,61,3,0,71,45,2,3,61,0], temperature_2m_min=[3,4,1,-2,-1,0,2,3,4,3],
        temperature_2m_max=[12,10,9,5,4,6,8,11,12,10], precipitation_probability_max=[20,75,10,0,60,10,20,10,55,0])
    (destination / "fixture-state.json").write_text(json.dumps(data, ensure_ascii=False))
    for name in ("weather.py", "radar.py", "forecast_map.py"):
        (destination / name).write_text(BACKEND)
    (destination / "map.svg").write_text('<svg xmlns="http://www.w3.org/2000/svg" width="256" height="256"><rect width="256" height="256" fill="#e8efeb"/><path d="M0 150L256 30M80 0L220 256M0 90L256 200" stroke="#fff" stroke-width="12"/><path d="M0 240L256 50" stroke="#abd4e5" stroke-width="20"/></svg>')
    (destination / "overlay.svg").write_text('<svg xmlns="http://www.w3.org/2000/svg" width="432" height="240"><ellipse cx="235" cy="120" rx="150" ry="65" fill="#52a9d2" opacity="0.45"/></svg>')
    (destination / "legend.svg").write_text('<svg xmlns="http://www.w3.org/2000/svg" width="260" height="54"><rect x="8" y="8" width="244" height="18" fill="#52a9d2"/><text x="8" y="44" font-size="12">0                  5                  20 mm</text></svg>')
    panel_path = destination / "Panel.qml"
    panel = panel_path.read_text()
    hook = ('  manageIpc: false\n'
            '  readonly property var qaScope: popup.loadedContent\n'
            '  property var qaCards: null\n  property var qaRadar: null')
    panel = panel.replace("  manageIpc: false", hook, 1)
    panel = panel.replace("Component.onCompleted: root.refresh()", "Component.onCompleted: { root.refresh(); popup.ensureContent() }", 1)
    panel = panel.replace("    open: root.opened", "    open: false", 1)
    panel = panel.replace("  KeyboardPanel {", "  LayoutPanel {", 1)
    (destination / "LayoutPanel.qml").write_text(CONTAINER)
    for component, property_name in (("WeatherCards", "qaCards"), ("Radar", "qaRadar")):
        panel, count = re.subn(r"(?m)^(\s*)" + component + r"\s*\{", lambda m: m.group(0)+"\n"+m.group(1)+"  Component.onCompleted: root."+property_name+" = this", panel, count=1)
        if count != 1:
            raise RuntimeError(f"Missing {component} integration seam")
    panel_path.write_text(panel)
    qml = (HERE / "tst_layout.qml").read_text().replace("@@OUTPUT@@", json.dumps(str(output)))
    (base / "shell.qml").write_text(qml)
    return destination


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plugin", type=Path, default=ROOT)
    parser.add_argument("--output", type=Path, default=HERE)
    parser.add_argument("--scale", type=float, default=1)
    args = parser.parse_args()
    if not 0.5 <= args.scale <= 3:
        parser.error("--scale must be between 0.5 and 3")
    args.output.mkdir(parents=True, exist_ok=True)
    required = ("HourlyForecast.qml", "DailyForecast.qml", "MetricIcon.qml")
    for name in required:
        if not (args.plugin / name).exists():
            raise SystemExit(f"UI still being prepared: missing {name}")
    with tempfile.TemporaryDirectory(prefix="pixel-weather-layout-") as temporary:
        base = Path(temporary)
        plugin = prepare(base, args.plugin, args.output.resolve())
        # Give real mouse/keyboard tests a deterministic busy window. Only this
        # disposable layout fixture is delayed; shared fixtures remain unchanged.
        backend_path = plugin / "weather.py"
        backend_path.write_text(backend_path.read_text().replace(
            "if name=='weather':\n", "if name=='weather':\n    if action=='load':time.sleep(0.3)\n", 1))
        env = os.environ.copy()
        env.update(QT_QPA_PLATFORM="offscreen", QT_QUICK_BACKEND="software", QT_SCALE_FACTOR=str(args.scale),
                   XDG_STATE_HOME=str(base / "state"), XDG_CACHE_HOME=str(base / "cache"))
        proc = subprocess.run(["timeout", "90s", "quickshell", "--no-color", "-p", str(base)], env=env,
                              text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=100)
        (args.output / "test.log").write_text(proc.stdout)
        print(proc.stdout, end="")
        trace_path = plugin / "backend-trace.jsonl"
        trace = [json.loads(line) for line in trace_path.read_text().splitlines()] if trace_path.exists() else []
        (args.output / "backend-trace.json").write_text(json.dumps(trace, indent=2, ensure_ascii=False)+"\n")
        errors = [line for line in proc.stdout.splitlines() if "ERROR" in line or "QA_FAIL" in line]
        if proc.returncode or errors or "QA_UI_LAYOUT_PASS" not in proc.stdout:
            raise SystemExit(1)
        loads = [row for row in trace if row["name"] == "weather" and row["action"] == "load"]
        if len(loads) != 3:
            raise SystemExit(f"QA_FAIL: expected startup, mouse and keyboard loads, got {len(loads)}")
        print("QA_UI_REFRESH_PASS: mouse and keyboard each refresh once; busy clicks do not queue work")
        from PIL import Image, ImageChops
        before = Image.open(args.output / "precipitation-before.png").convert("RGB")
        after = Image.open(args.output / "precipitation-after.png").convert("RGB")
        if before.size != after.size or ImageChops.difference(before, after).getbbox() is None:
            raise SystemExit("QA_FAIL: changing hourly precipitation did not redraw the bar")
        print("QA_UI_PRECIPITATION_PASS: isolated bar pixels change with precipitation probability")
        print("QA_UI_ISOLATION_PASS: fixture processes only; no user state, HTTP or notifications")


if __name__ == "__main__":
    main()
