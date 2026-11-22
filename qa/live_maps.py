#!/usr/bin/env python3
"""Manual live-source cartography gate, with no personal state and a 30s deadline.

The rain radar streams its newest frames from RainViewer and the DWD timeline
is checked for its five minute cadence without downloading the whole
animation. Projection limits are tested honestly.
"""
import argparse
import contextlib
import io
import json
from pathlib import Path
import signal
import sys
import tempfile
import time
from urllib.parse import parse_qs,unquote,urlsplit

sys.dont_write_bytecode=True
HERE=Path(__file__).resolve().parent
ROOT=HERE.parent
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(HERE))
import radar
from endurance import atomic_json,source_digest,utc_now
from international import runtime_versions

LYON={"name":"Lyon","latitude":45.75,"longitude":4.85,"timezone":"Europe/Paris"}
BERLIN={"name":"Berlin","latitude":52.52,"longitude":13.405,"timezone":"Europe/Berlin"}
POLE={"name":"North Pole","latitude":90,"longitude":0,"timezone":"Etc/GMT"}


class ProbeDeadline(BaseException):pass


def alarm(*_):raise ProbeDeadline("Global live-map probe deadline exceeded (30 seconds)")


def streamed(loader,city):
    output=io.StringIO()
    with contextlib.redirect_stdout(output):loader(city)
    return [json.loads(line) for line in output.getvalue().splitlines() if line.strip()]


def local_png(uri):
    parsed=urlsplit(uri)
    if parsed.scheme!="file" or parsed.netloc:raise ValueError("Expected a local validated map image")
    return Path(unquote(parsed.path)).read_bytes()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report",type=Path,default=ROOT/"reports/live-maps.json")
    args=parser.parse_args()
    before,files=source_digest(ROOT);started=utc_now();clock=time.monotonic()
    records=[];failures=[]
    original=(radar.STATE,radar.CACHE)
    previous_handler=signal.signal(signal.SIGALRM,alarm)
    signal.setitimer(signal.ITIMER_REAL,30)
    try:
        with tempfile.TemporaryDirectory(prefix="owee-live-maps-") as temporary:
            base=Path(temporary)
            radar.STATE=base/"state"
            radar.CACHE=base/"cache/radar"
            radar.configure({"rain_enabled":True,"wind_enabled":True,"zoom_level":1})
            result=streamed(radar.load,POLE)[0]
            valid=result.get("status")=="unsupported" and result.get("reason")=="projection_limit" and result.get("latitude")==90
            records.append({"place":"North Pole","provider":"RainViewer","status":result.get("status"),"selected_point_preserved":valid})
            if not valid:failures.append("polar projection limit moved or misrepresented the selected point")
            try:
                lines=streamed(radar.load,LYON)
                meta=lines[0];rain=meta["rain"];done=lines[-1]
                past=[frame for frame in rain["frames"] if frame["kind"]=="past"]
                if rain["provider_name"]!="RainViewer":raise ValueError("Worldwide radar provider mismatch")
                if len(past)<6:raise ValueError("Too few observed radar frames")
                frames=[line for line in lines if line.get("kind")=="frame"]
                if not frames:raise ValueError("No radar frame streamed to the interface")
                sizes=[radar.png_size(local_png(tile["source"])) for tile in frames[0]["tiles"]]
                if not all(size in radar.VALID_SIZES for size in sizes):raise ValueError("Radar tile is not a valid image")
                if not all(tile.get("source") for tile in meta["tiles"]):raise ValueError("OpenStreetMap basemap incomplete")
                if done.get("stale"):raise ValueError("Radar manifest is stale")
                if done.get("partial") or done.get("message"):raise ValueError(done.get("message") or "Radar load is partial")
                wind=meta["wind"]
                if wind["provider_name"]!="Open-Meteo" or not wind["frames"]:raise ValueError("Wind grid unavailable")
                if not all(len(frame.get("points",[]))==35 for frame in wind["frames"]):raise ValueError("Wind grid is incomplete")
                records.append({"place":"Lyon","provider":"RainViewer + Open-Meteo","status":"passed",
                    "past_frames":len(past),"future_frames":len(rain["frames"])-len(past),
                    "streamed_frames":len(frames),"wind_frames":len(wind["frames"]),
                    "tile_png_sizes":sizes,"basemap_png_verified":True})
            except Exception as error:failures.append("RainViewer: "+str(error)[:250])
            try:
                frames,now_index=radar.dwd_timeline(BERLIN,time.time())
                steps={b["time"]-a["time"] for a,b in zip(frames,frames[1:])}
                now=time.time()
                if steps!={300}:raise ValueError("DWD timeline is not in five minute steps")
                if now_index<0 or frames[-1]["time"]<=now:raise ValueError("DWD timeline lacks prediction frames")
                if frames[now_index]["time"]-frames[0]["time"]<6900:raise ValueError("DWD timeline lacks two hours of observations")
                records.append({"place":"Berlin","provider":"DWD","status":"passed","frames":len(frames),
                    "now_index":now_index,"step_seconds":300,
                    "window_seconds":frames[-1]["time"]-frames[0]["time"]})
            except Exception as error:failures.append("DWD: "+str(error)[:250])
    except ProbeDeadline as error:failures.append(str(error))
    except Exception as error:failures.append("Probe setup: "+str(error)[:250])
    finally:
        signal.setitimer(signal.ITIMER_REAL,0);signal.signal(signal.SIGALRM,previous_handler)
        radar.STATE,radar.CACHE=original
    after,_=source_digest(ROOT)
    if before!=after:failures.append("Source changed during live qualification; rerun on the final commit")
    report={"kind":"live_maps","status":"passed" if not failures else "failed","passed":not failures,
        "started_at":started,"finished_at":utc_now(),"elapsed_seconds":round(time.monotonic()-clock,3),
        "source_sha256":before,"source_sha256_after":after,"source_files":files,"runtime":runtime_versions(),
        "cases":records,"failures":failures,"personal_state_accessed":False,"deadline_seconds":30,
        "expected_cases":3,"completed_cases":len(records)}
    if report["completed_cases"]<report["expected_cases"]:
        report["passed"]=False;report["status"]="failed";report["failures"].append("Not all planned live cases completed")
    args.report.parent.mkdir(parents=True,exist_ok=True);atomic_json(args.report,report)
    print(json.dumps({"status":report["status"],"cases":len(records),"elapsed_seconds":report["elapsed_seconds"],"failures":report["failures"]}))
    return 0 if report["passed"] else 1


if __name__=="__main__":raise SystemExit(main())
