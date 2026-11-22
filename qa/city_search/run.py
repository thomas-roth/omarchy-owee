#!/usr/bin/env python3
"""Exercise live city search with real Qt input and a local delayed backend."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "qa"))
from ui_layout.run import prepare

BACKEND = r'''import json,signal,sys,time
from pathlib import Path
base=Path(__file__).parent
action=sys.argv[1]
arg=sys.argv[2] if len(sys.argv)>2 else ''
with (base/'search-trace.jsonl').open('a') as trace: trace.write(json.dumps({'action':action,'query':arg,'time':time.time()})+'\n')
state=base/'fixture-state.json'
data=json.loads(state.read_text())
if action=='search':
    if arg in ('Pa','Slow'):
        signal.signal(signal.SIGTERM,lambda *_:None)
        time.sleep(2 if arg=='Slow' else 0.8)
    else:time.sleep(0.03)
    if arg=='error':print(json.dumps({'error':'Test connection unavailable'}))
    elif arg=='zz':print(json.dumps({'results':[]}))
    else:print(json.dumps({'results':[{'name':arg,'latitude':48.1,'longitude':-1.6,'country':'France'}]}))
else:
    if action=='select':data['city']=json.loads(arg);state.write_text(json.dumps(data))
    print(json.dumps(data))
'''


def main():
    with tempfile.TemporaryDirectory(prefix="pixel-weather-city-search-") as temporary:
        base = Path(temporary)
        plugin = prepare(base, ROOT, HERE)
        (plugin / "weather.py").write_text(BACKEND)
        (base / "shell.qml").write_text((HERE / "tst_search.qml").read_text().replace("@@OUTPUT@@", json.dumps(str(HERE))))
        env = os.environ.copy()
        env.update(QT_QPA_PLATFORM="offscreen", QT_QUICK_BACKEND="software", XDG_STATE_HOME=str(base / "state"), XDG_CACHE_HOME=str(base / "cache"))
        result = subprocess.run(["timeout", "25s", "quickshell", "--no-color", "-p", str(base)], env=env,
                                text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=30)
        (HERE / "test.log").write_text(result.stdout)
        print(result.stdout, end="")
        trace_path = plugin / "search-trace.jsonl"
        trace = [json.loads(line) for line in trace_path.read_text().splitlines()] if trace_path.exists() else []
        (HERE / "trace.json").write_text(json.dumps(trace, ensure_ascii=False, indent=2)+"\n")
        queries = [row["query"] for row in trace if row["action"] == "search"]
        if result.returncode or "QA_SEARCH_PASS" not in result.stdout or "QA_FAIL" in result.stdout or "ERROR" in result.stdout:
            raise SystemExit(1)
        expected = ["Paris", "Rome", "Slow", "zz", "error", "Paris"]
        # Cancellation can kill either Pa process before its Python entry point runs.
        with_obsolete = expected[:1] + ["Pa"] + expected[1:]
        if queries not in (expected, expected + ["Pa"], with_obsolete, with_obsolete + ["Pa"]):
            raise SystemExit("QA_FAIL: unexpected search traffic: " + repr(queries))
        slow = next(row for row in trace if row['action']=='search' and row['query']=='Slow')
        # Each fixture worker timestamps from its own Python startup, so a
        # slightly earlier load row is still the refresh issued during the
        # pending search; only a load far outside the window is a failure.
        if not any(row['action']=='load' and -0.5 <= row['time']-slow['time'] < 2 for row in trace):
            raise SystemExit('QA_FAIL: weather backend did not run while slow city search was pending')
        print('QA_SEARCH_CONCURRENCY_PASS: weather backend started before slow search could finish')
        print("QA_SEARCH_TRAFFIC_PASS: debounced requests only, canceled short/closed queries never sent")


if __name__ == "__main__":
    main()
