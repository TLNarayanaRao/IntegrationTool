"""Repeatable live-provider qualification and soak runner for exported apps."""
from __future__ import annotations

import asyncio
import math
import statistics
import time
import tracemalloc
from typing import Any, Awaitable, Callable


def _percentile(values: list[float], percentile: float) -> float:
    if not values: return 0.0
    ordered = sorted(values); position = (len(ordered) - 1) * percentile
    lower, upper = math.floor(position), math.ceil(position)
    return ordered[lower] if lower == upper else ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


async def qualify(run: Callable[[], Awaitable[Any]], *, iterations: int = 100, concurrency: int = 1,
                  duration_seconds: float = 0, max_error_rate: float = 0,
                  max_p95_ms: float = 0, max_memory_growth_mb: float = 0) -> dict[str, Any]:
    """Exercise the actual selected task and produce machine-readable evidence."""
    iterations, concurrency = max(1, int(iterations)), max(1, int(concurrency))
    counter, lock, latencies, errors = 0, asyncio.Lock(), [], []
    started = time.perf_counter(); deadline = started + duration_seconds if duration_seconds > 0 else None
    tracemalloc.start(); memory_before = tracemalloc.get_traced_memory()[0]
    async def worker():
        nonlocal counter
        while True:
            async with lock:
                if counter >= iterations and (deadline is None or time.perf_counter() >= deadline): return
                if deadline is not None and time.perf_counter() >= deadline and counter >= iterations: return
                counter += 1; sequence = counter
            call_started = time.perf_counter()
            try: await run()
            except Exception as error: errors.append({'sequence': sequence, 'type': type(error).__name__, 'message': str(error)})
            finally: latencies.append((time.perf_counter() - call_started) * 1000)
    await asyncio.gather(*(worker() for _ in range(concurrency)))
    memory_after, memory_peak = tracemalloc.get_traced_memory(); tracemalloc.stop()
    elapsed = time.perf_counter() - started; total = len(latencies); error_rate = len(errors) / total if total else 1.0
    report = {'passed': True, 'iterations': total, 'concurrency': concurrency, 'durationSeconds': elapsed,
              'throughputPerSecond': total / elapsed if elapsed else 0, 'successes': total - len(errors),
              'failures': len(errors), 'errorRate': error_rate,
              'latencyMs': {'min': min(latencies, default=0), 'mean': statistics.fmean(latencies) if latencies else 0,
                            'p50': _percentile(latencies, .50), 'p95': _percentile(latencies, .95),
                            'p99': _percentile(latencies, .99), 'max': max(latencies, default=0)},
              'memory': {'beforeBytes': memory_before, 'afterBytes': memory_after, 'peakBytes': memory_peak,
                         'growthBytes': memory_after - memory_before}, 'errors': errors[:100], 'thresholdFailures': []}
    if error_rate > max_error_rate: report['thresholdFailures'].append(f'errorRate {error_rate:.6f} exceeds {max_error_rate:.6f}')
    if max_p95_ms > 0 and report['latencyMs']['p95'] > max_p95_ms: report['thresholdFailures'].append(f'p95 latency exceeds {max_p95_ms:g} ms')
    if max_memory_growth_mb > 0 and report['memory']['growthBytes'] > max_memory_growth_mb * 1024 * 1024: report['thresholdFailures'].append(f'memory growth exceeds {max_memory_growth_mb:g} MiB')
    report['passed'] = not report['thresholdFailures']
    return report

