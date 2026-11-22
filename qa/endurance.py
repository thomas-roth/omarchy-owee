#!/usr/bin/env python3
"""Observe one isolated OWEE process for a real elapsed endurance interval.

The production UI uses local fixture workers and images. No installed widget,
personal settings, notification daemon or public API is modified. A short run
can pass as a smoke test but cannot produce a qualified 12-hour report.
"""
from __future__ import annotations

import argparse
import collections
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import selectors
import shutil
import signal
import statistics
import subprocess
import tempfile
import time

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
FULL_DURATION = 12 * 60 * 60
FULL_CYCLES = 1000
MIB = 1024 * 1024
CODE_SUFFIXES = {".qml", ".js", ".py", ".sh", ".yml", ".yaml", ".toml"}
EXCLUDED_PARTS = {".git", "reports", "__pycache__", ".cache", ".venv"}
STOP_REQUESTED = False


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def source_digest(root):
    """Hash runtime, test and release code; exclude generated evidence."""
    digest = hashlib.sha256()
    files = []
    for path in sorted(Path(root).rglob("*")):
        relative = path.relative_to(root)
        if any(part in EXCLUDED_PARTS for part in relative.parts) or not path.is_file():
            continue
        if path.suffix not in CODE_SUFFIXES and relative.as_posix() not in ("manifest.json", "requirements-dev.txt"):
            continue
        content = path.read_bytes()
        digest.update(relative.as_posix().encode() + b"\0" + content + b"\0")
        files.append(relative.as_posix())
    return digest.hexdigest(), files


def atomic_json(path, payload):
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, ensure_ascii=False, allow_nan=False) + "\n")
    temporary.replace(path)


def tree_usage(pid):
    """Include living children and CPU of children already reaped by parents."""
    pending = [pid]
    seen = set()
    rss = ticks = count = 0
    while pending:
        current = pending.pop()
        if current in seen:
            continue
        seen.add(current)
        try:
            stat = Path(f"/proc/{current}/stat").read_text()
            fields = stat[stat.rfind(")") + 2:].split()
            ticks += sum(int(fields[index]) for index in (11, 12, 13, 14))
            rss += int(fields[21]) * os.sysconf("SC_PAGE_SIZE")
            count += 1
            pending.extend(int(value) for value in Path(f"/proc/{current}/task/{current}/children").read_text().split())
        except (OSError, ValueError, IndexError):
            continue
    return {"rss_bytes": rss, "cpu_ticks": ticks, "processes": count}


def _stop(signum, frame):
    global STOP_REQUESTED
    STOP_REQUESTED = True


def prepare_fixture(base, plugin, output):
    spec = importlib.util.spec_from_file_location("owee_endurance_layout", HERE / "ui_layout/run.py")
    layout = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(layout)
    destination = layout.prepare(base, plugin, output)
    backend = (destination / "weather.py").read_text()
    # Only the disposable fixture's worker receives these fault modes.
    fault_prefix = '''import json,sys
from pathlib import Path
if len(sys.argv)>2 and sys.argv[1]=='load' and sys.argv[2].startswith('qa-'):
    base=Path(__file__).parent
    mode=sys.argv[2]
    with (base/'backend-trace.jsonl').open('a') as log:log.write(json.dumps({'name':'weather','action':'load','arg':mode})+'\\n')
    if mode=='qa-malformed':print('{');sys.exit(0)
    if mode=='qa-exit':sys.exit(17)
    data=json.loads((base/'fixture-state.json').read_text())
    if mode=='qa-offline':data.update(stale=True,error='Simulated offline fixture')
    if mode=='qa-partial':
        data['data']['current']['relative_humidity_2m']=None
        data['data']['hourly']['precipitation_probability']=[None]*len(data['data']['hourly']['time'])
        data['data']['daily']['uv_index_max']=[None]*len(data['data']['daily']['time'])
    print(json.dumps(data));sys.exit(0)
'''
    (destination / "weather.py").write_text(fault_prefix + backend)
    guard = base / "guard"
    guard.mkdir()
    (guard / "sitecustomize.py").write_text('''import json,os,socket
def deny(*args,**kwargs):
    with open(os.environ['OWEE_NETWORK_GUARD_LOG'],'a') as log:log.write(json.dumps({'attempt':'python_socket'})+'\\n')
    raise OSError('OWEE endurance forbids network access')
socket.create_connection=deny
socket.getaddrinfo=deny
socket.socket.connect=deny
socket.socket.connect_ex=deny
''')
    blocked_bin = base / "bin"
    blocked_bin.mkdir()
    for name in ("notify-send", "curl", "wget"):
        path = blocked_bin / name
        path.write_text("#!/bin/sh\nprintf '%s\\n' 'forbidden subprocess' >> \"$OWEE_FORBIDDEN_COMMAND_LOG\"\nexit 99\n")
        path.chmod(0o755)
    return destination, guard, blocked_bin


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plugin", type=Path, default=ROOT)
    parser.add_argument("--report-dir", type=Path, default=ROOT / "reports" / ("endurance-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")))
    parser.add_argument("--duration-seconds", type=float, default=FULL_DURATION)
    parser.add_argument("--interval-seconds", type=float, default=40)
    parser.add_argument("--minimum-cycles", type=int, default=FULL_CYCLES)
    args = parser.parse_args(argv)
    if not math.isfinite(args.duration_seconds) or args.duration_seconds < 5:
        parser.error("--duration-seconds must be finite and at least 5")
    if not math.isfinite(args.interval_seconds) or args.interval_seconds < 1:
        parser.error("--interval-seconds must be finite and at least 1")
    if args.minimum_cycles < 1 or args.minimum_cycles > math.ceil(args.duration_seconds / args.interval_seconds):
        parser.error("--minimum-cycles must fit the requested duration and interval")
    plugin = args.plugin.resolve()
    output = args.report_dir.resolve()
    if not plugin.is_dir() or not (plugin / "manifest.json").is_file():
        parser.error("--plugin must contain manifest.json")
    if output.exists() and not output.is_dir():
        parser.error("--report-dir must be a directory")
    if output.exists() and any(output.iterdir()):
        parser.error("--report-dir must be empty to preserve earlier evidence")
    output.mkdir(parents=True, exist_ok=True)
    if not shutil.which("quickshell"):
        parser.error("quickshell is required")
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, _stop)
    initial_digest, digest_files = source_digest(plugin)
    try:
        commit = subprocess.run(["git", "-C", str(plugin), "rev-parse", "HEAD"], capture_output=True, text=True, timeout=5).stdout.strip() or None
    except (OSError, subprocess.TimeoutExpired):
        commit = None
    start = time.monotonic()
    started_at = utc_now()
    warmup = min(20 * args.interval_seconds, 0.1 * args.duration_seconds)
    failures = []
    completed = 0
    closed = False
    closed_since = None
    closed_total = 0.0
    last_progress = start
    last_event = None
    last_summary = start - 60
    baseline_samples = []
    final_samples = collections.deque(maxlen=20)
    idle_cpu_seconds = idle_elapsed_seconds = 0.0
    previous_sample = None
    ready = False
    proc = None
    summary = {
        "status": "running", "qualified": False, "kind": "qualification" if args.duration_seconds >= FULL_DURATION and args.minimum_cycles >= FULL_CYCLES else "smoke",
        "started_at": started_at, "requested_duration_seconds": args.duration_seconds,
        "requested_minimum_cycles": args.minimum_cycles, "interval_seconds": args.interval_seconds,
        "source_sha256": initial_digest, "source_files": digest_files, "git_commit": commit,
        "isolated": True, "network_allowed": False, "notifications_allowed": False,
        "platform": "offscreen", "renderer": "software", "container": "isolated layer-shell fixture",
        "stage": "preparing",
    }
    atomic_json(output / "summary.json", summary)
    with tempfile.TemporaryDirectory(prefix="owee-endurance-") as temporary:
        base = Path(temporary)
        try:
            fixture, guard, blocked_bin = prepare_fixture(base, plugin, output)
        except Exception as error:
            summary.update(status="failed", finished_at=utc_now(), elapsed_seconds=0,
                           completed_cycles=0, failures=["fixture preparation failed: " + str(error)])
            atomic_json(output / "summary.json", summary)
            print(json.dumps({"status": "failed", "qualified": False, "failures": summary["failures"]}), flush=True)
            return 1
        qml = (HERE / "endurance_shell.qml").read_text().replace("@@INTERVAL_MS@@", str(round(args.interval_seconds * 1000)))
        (base / "shell.qml").write_text(qml)
        env = os.environ.copy()
        env.update(QT_QPA_PLATFORM="offscreen", QT_QUICK_BACKEND="software", QT_SCALE_FACTOR="1",
                   XDG_STATE_HOME=str(base / "state"), XDG_CACHE_HOME=str(base / "cache"),
                   XDG_CONFIG_HOME=str(base / "config"), XDG_DATA_HOME=str(base / "data"),
                   PYTHONDONTWRITEBYTECODE="1", PYTHONPATH=str(guard),
                   OWEE_NETWORK_GUARD_LOG=str(output / "network-attempts.jsonl"),
                   OWEE_FORBIDDEN_COMMAND_LOG=str(output / "forbidden-commands.log"),
                   PATH=str(blocked_bin) + os.pathsep + env.get("PATH", ""),
                   http_proxy="http://127.0.0.1:9", https_proxy="http://127.0.0.1:9",
                   HTTP_PROXY="http://127.0.0.1:9", HTTPS_PROXY="http://127.0.0.1:9",
                   ALL_PROXY="http://127.0.0.1:9", all_proxy="http://127.0.0.1:9", NO_PROXY="", no_proxy="")
        try:
            # Qualification measures the child lifetime, excluding fixture preparation.
            start = time.monotonic()
            started_at = utc_now()
            last_progress = start
            last_summary = start - 60
            summary["started_at"] = started_at
            proc = subprocess.Popen(["quickshell", "--no-color", "-p", str(base)], env=env,
                                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, start_new_session=True)
            summary["pid"] = proc.pid
            summary["stage"] = "running"
            selector = selectors.DefaultSelector()
            os.set_blocking(proc.stdout.fileno(), False)
            selector.register(proc.stdout, selectors.EVENT_READ)
            buffer = b""
            next_sample = start
            ticks_per_second = os.sysconf("SC_CLK_TCK")
            with (output / "quickshell.log").open("wb") as logfile, (output / "events.jsonl").open("a") as eventlog, (output / "telemetry.jsonl").open("a") as telemetry:
                while True:
                    now = time.monotonic()
                    elapsed = now - start
                    if STOP_REQUESTED:
                        failures.append("interrupted")
                        break
                    for key, _ in selector.select(timeout=0.15):
                        chunk = os.read(key.fileobj.fileno(), 262144)
                        if not chunk:
                            continue
                        logfile.write(chunk); logfile.flush()
                        buffer += chunk
                        while b"\n" in buffer:
                            raw, buffer = buffer.split(b"\n", 1)
                            line = raw.decode("utf-8", "replace")
                            if "ERROR" in line or "WARN scene:" in line or "QA_FAIL" in line:
                                failures.append(line[-1000:])
                            marker = "OWEE_ENDURANCE_EVENT "
                            if marker not in line:
                                continue
                            try:
                                event = json.loads(line.split(marker, 1)[1])
                            except ValueError:
                                failures.append("invalid endurance event")
                                continue
                            event["elapsed_seconds"] = elapsed
                            eventlog.write(json.dumps(event) + "\n"); eventlog.flush()
                            last_event = event
                            last_progress = now
                            if event["event"] == "ready":
                                ready = True
                            if event["event"] == "cycle_started":
                                if closed_since is not None:
                                    closed_total += now - closed_since
                                closed = False; closed_since = None
                            if event["event"] == "cycle_complete":
                                completed = max(completed, event["cycle"])
                                closed = True; closed_since = now
                            if event["event"] == "failed":
                                failures.append(event.get("message", "QML cycle failed"))
                    if failures:
                        break
                    if proc.poll() is not None:
                        failures.append("quickshell exited unexpectedly: " + str(proc.returncode))
                        break
                    if not ready and elapsed > 30:
                        failures.append("fixture startup stalled")
                        break
                    if ready and not closed and now - last_progress > 2 * args.interval_seconds + 10:
                        failures.append("cycle stalled")
                        break
                    if now >= next_sample:
                        usage = tree_usage(proc.pid)
                        sample = {"elapsed_seconds": elapsed, "time": utc_now(), "closed": closed,
                                  "cycles": completed, **usage}
                        if previous_sample is not None:
                            seconds = elapsed - previous_sample["elapsed_seconds"]
                            cpu_delta = max(0, usage["cpu_ticks"] - previous_sample["cpu_ticks"]) / ticks_per_second
                            sample["cpu_percent"] = cpu_delta / seconds * 100 if seconds > 0 else 0
                            if (closed and previous_sample["closed"] and elapsed >= warmup
                                    and closed_since is not None and now - closed_since >= 2):
                                idle_cpu_seconds += cpu_delta
                                idle_elapsed_seconds += seconds
                        if closed and elapsed >= warmup:
                            if len(baseline_samples) < 20:
                                baseline_samples.append(usage["rss_bytes"])
                            final_samples.append(usage["rss_bytes"])
                        telemetry.write(json.dumps(sample) + "\n"); telemetry.flush()
                        previous_sample = sample
                        next_sample = now + 0.5
                    if elapsed >= args.duration_seconds and closed and completed >= args.minimum_cycles:
                        break
                    if elapsed > args.duration_seconds + 2 * args.interval_seconds + 10:
                        failures.append("insufficient completed cycles by deadline")
                        break
                    if now - last_summary >= 60:
                        summary.update(elapsed_seconds=elapsed, completed_cycles=completed, last_progress_at=utc_now(), last_event=last_event)
                        atomic_json(output / "summary.json", summary)
                        print(json.dumps({"status": "running", "elapsed_seconds": round(elapsed, 1), "cycles": completed, "pid": proc.pid}), flush=True)
                        last_summary = now
            selector.close()
        except Exception as error:
            failures.append(type(error).__name__ + ": " + str(error))
        finally:
            if proc is not None:
                try:
                    os.killpg(proc.pid, signal.SIGTERM)
                    proc.wait(timeout=5)
                except (ProcessLookupError, subprocess.TimeoutExpired):
                    try:
                        os.killpg(proc.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    proc.wait(timeout=5)
                # The parent may exit before one of its subprocesses: clear the group too.
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            trace_path = fixture / "backend-trace.jsonl"
            if trace_path.exists():
                shutil.copy2(trace_path, output / "backend-trace.jsonl")
                try:
                    trace = [json.loads(line) for line in trace_path.read_text().splitlines()]
                    if any(row.get("action") in ("notify", "notify-test") for row in trace):
                        failures.append("notification action attempted")
                    if any(row.get("name") not in ("weather", "radar") for row in trace):
                        failures.append("unknown fixture worker")
                except ValueError:
                    failures.append("invalid fixture trace")
            else:
                failures.append("fixture backend trace missing")
    elapsed = time.monotonic() - start
    if closed_since is not None:
        closed_total += time.monotonic() - closed_since
    final_digest, _ = source_digest(plugin)
    if final_digest != initial_digest:
        failures.append("source_changed_during_run")
    for name in ("network-attempts.jsonl", "forbidden-commands.log"):
        path = output / name
        if path.exists() and path.stat().st_size:
            failures.append("forbidden external activity: " + name)
    baseline = statistics.median(baseline_samples) if baseline_samples else None
    final_rss = statistics.median(final_samples) if final_samples else None
    memory_limit = baseline + max(0.2 * baseline, 20 * MIB) if baseline is not None else None
    if final_rss is None or memory_limit is None:
        failures.append("insufficient closed-state memory samples")
    elif final_rss > memory_limit:
        failures.append("resident memory exceeded warmed baseline allowance")
    idle_cpu = idle_cpu_seconds / idle_elapsed_seconds * 100 if idle_elapsed_seconds > 0 else None
    if idle_cpu is None:
        failures.append("insufficient closed-state CPU samples")
    elif idle_cpu > 1:
        failures.append("closed-state CPU exceeded 1 percent of one core")
    if elapsed < args.duration_seconds or completed < args.minimum_cycles:
        failures.append("real-duration or minimum-cycle requirement not met")
    if closed_total < 0.5 * elapsed:
        failures.append("panel was not idle for the majority of the run")
    summary.update(status="interrupted" if STOP_REQUESTED else "failed" if failures else "passed",
                   qualified=not failures and args.duration_seconds >= FULL_DURATION and elapsed >= FULL_DURATION and completed >= FULL_CYCLES,
                   finished_at=utc_now(), elapsed_seconds=elapsed, completed_cycles=completed,
                   source_sha256_after=final_digest, failures=list(dict.fromkeys(failures)),
                   closed_seconds=closed_total, closed_fraction=closed_total / elapsed if elapsed else 0,
                   memory_baseline_bytes=baseline, memory_final_bytes=final_rss,
                   memory_limit_bytes=memory_limit, idle_cpu_percent=idle_cpu,
                   idle_cpu_sample_seconds=idle_elapsed_seconds, last_event=last_event)
    atomic_json(output / "summary.json", summary)
    print(json.dumps({key: summary[key] for key in ("status", "qualified", "elapsed_seconds", "completed_cycles", "failures")}), flush=True)
    return 130 if STOP_REQUESTED else 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
