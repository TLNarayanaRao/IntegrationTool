"""Run controlled SAP JCo throughput, failover, and soak qualification.

This script deliberately requires an operator-supplied JSON file. It never
contains or prints SAP credentials. Run it only against an approved QA system.
"""
from __future__ import annotations

import argparse
import concurrent.futures
from collections import deque
import json
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from app.sap import SapAdapter  # noqa: E402


def percentile(values: list[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, round((len(ordered) - 1) * fraction))]


def main() -> int:
    parser = argparse.ArgumentParser(description="Qualify SAP JCo calls using the exact target JCo/ECC environment")
    parser.add_argument("--config", required=True, type=Path, help="Operator-owned JSON configuration")
    parser.add_argument("--output", type=Path, default=Path("sap-soak-report.json"))
    parser.add_argument("--target-calls", type=int, default=0, help="Require this many successes within durationSeconds")
    args = parser.parse_args()
    if args.target_calls < 0:
        parser.error('--target-calls must be nonnegative')
    specification = json.loads(args.config.read_text(encoding="utf-8"))
    connection = dict(specification.get("connection") or {})
    operation = str(specification.get("operation") or "invoke_rfc_bapi")
    if operation in {'idoc_listener', 'rfc_bapi_listener', 'reply_rfc_bapi'}:
        parser.error('Inbound SAP qualification needs a deployed listener and an SAP-side sender. This runner invokes activities directly.')
    activity = {**connection, **(specification.get("activity") or {}), "mode": "external"}
    payload = specification.get("payload") or {}
    duration = max(1, int(specification.get("durationSeconds") or 60))
    concurrency = max(1, min(128, int(specification.get("concurrency") or 4)))
    inject_every = max(0, int(specification.get("terminateWorkerEveryCalls") or 0))
    adapter, lock = SapAdapter(), threading.Lock()
    # Instrumentation must not create apparent runtime growth in a long soak.
    latencies = deque(maxlen=10000)
    errors = deque(maxlen=1000)
    completed = failed = 0
    target_elapsed = None
    latency_total = 0.0
    latency_min, latency_max = float('inf'), 0.0
    started_at, started_mono = time.time(), time.monotonic()
    deadline = started_mono + duration

    def invoke_once() -> None:
        nonlocal completed, failed, latency_total, latency_min, latency_max, target_elapsed
        began = time.perf_counter()
        try:
            adapter.execute(operation, activity, payload)
            elapsed = (time.perf_counter() - began) * 1000
            with lock:
                completed += 1; latencies.append(elapsed)
                latency_total += elapsed
                latency_min = min(latency_min, elapsed)
                latency_max = max(latency_max, elapsed)
                count = completed
                if count == args.target_calls:
                    target_elapsed = time.monotonic() - started_mono
            if inject_every and count % inject_every == 0:
                with adapter._state_lock:
                    worker = next((item for pool in adapter.client_pools.values() for item in pool if item.process.poll() is None), None)
                if worker is not None:
                    worker.process.terminate()
        except Exception as exc:
            with lock:
                failed += 1
                errors.append({"time": time.time(), "type": exc.__class__.__name__, "message": str(exc)[:1000]})

    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency, thread_name_prefix="sap-soak") as executor:
            pending: set[concurrent.futures.Future] = set()
            while time.monotonic() < deadline or pending:
                while time.monotonic() < deadline and len(pending) < concurrency:
                    pending.add(executor.submit(invoke_once))
                done, pending = concurrent.futures.wait(pending, timeout=1, return_when=concurrent.futures.FIRST_COMPLETED)
    finally:
        worker_pids = [worker.process.pid for pool in adapter.client_pools.values() for worker in pool]
        adapter.close_all()
    finished_at = time.time()
    report = {
        "startedAtEpoch": started_at, "finishedAtEpoch": finished_at, "durationSeconds": finished_at - started_at,
        "operation": operation, "concurrency": concurrency, "successfulCalls": completed, "failedCalls": failed,
        "throughputPerSecond": completed / max(0.001, finished_at - started_at),
        "latencyMilliseconds": {"minimum": latency_min if completed else 0, "mean": latency_total / completed if completed else 0,
            "p50": percentile(latencies, .50), "p95": percentile(latencies, .95), "p99": percentile(latencies, .99), "maximum": latency_max},
        "quantileSampleLimit": 10000, "quantileScope": "Latest successful calls; min/mean/max cover all successful calls",
        "workerProcessIds": worker_pids, "failureInjectionEveryCalls": inject_every, "errors": list(errors),
        "errorSampleLimit": 1000, "targetCalls": args.target_calls, "targetCompletionSeconds": target_elapsed,
        "passed": completed > 0 and failed == 0 and (not args.target_calls or target_elapsed is not None and target_elapsed <= duration),
    }
    args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"SAP qualification report: {args.output.resolve()}")
    print(json.dumps({key: report[key] for key in ("successfulCalls", "failedCalls", "throughputPerSecond", "latencyMilliseconds", "passed")}, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
