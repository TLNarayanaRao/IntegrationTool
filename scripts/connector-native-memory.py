"""Isolate cryptography thread-memory growth without MINA, SSH or test servers.

Test-only dependencies: psutil and cryptography. No credentials or network needed.
Each control runs in a fresh process, after warm-up. A failed gate is evidence to
investigate the dependency/platform; it must not be hidden by forced RSS trimming.
"""
from __future__ import annotations

import argparse
import gc
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import tracemalloc


def probe(mode, iterations):
    import cryptography
    from cryptography.hazmat.backends.openssl.backend import backend
    from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
    import psutil

    process = psutil.Process()
    workers = None
    if mode == 'managed-crypto-thread':
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
        from app.sftp import _TransportWorkers
        workers = _TransportWorkers(4)

    def operation():
        if mode != 'empty-thread':
            first = X25519PrivateKey.generate()
            second = X25519PrivateKey.generate()
            first.exchange(second.public_key())

    def once():
        if mode == 'same-thread':
            operation()
        elif workers is not None:
            workers.submit(operation, 10).done.wait(10)
        else:
            thread = threading.Thread(target=operation)
            thread.start()
            thread.join()

    def measure():
        gc.collect()
        return {'rssBytes': process.memory_info().rss,
                'handles': process.num_handles() if hasattr(process, 'num_handles') else process.num_fds(),
                'threads': process.num_threads(),
                'pythonBytes': tracemalloc.get_traced_memory()[0],
                'uncollectable': sum(item['uncollectable'] for item in gc.get_stats())}

    for _ in range(500):
        once()
    tracemalloc.start()
    baseline = measure()
    samples = []
    for index in range(iterations):
        once()
        if (index + 1) % 1000 == 0:
            samples.append({'iterations': index + 1, **measure()})
    final = measure()
    tracemalloc.stop()
    return {'mode': mode, 'iterations': iterations, 'baseline': baseline, 'final': final,
            'samples': samples, 'rssGrowthMiB': (final['rssBytes'] - baseline['rssBytes']) / 1024**2,
            'pythonGrowthMiB': (final['pythonBytes'] - baseline['pythonBytes']) / 1024**2,
            'cryptography': cryptography.__version__, 'openssl': backend.openssl_version_text(),
            'python': sys.version, 'platform': sys.platform}


def main(args):
    if args.child:
        print(json.dumps(probe(args.child, args.iterations)))
        return 0
    results = []
    modes = ['empty-thread', 'same-thread', 'crypto-thread']
    if args.managed:
        modes.append('managed-crypto-thread')
    for mode in modes:
        completed = subprocess.run([sys.executable, str(Path(__file__).resolve()),
                                    '--child', mode, '--iterations', str(args.iterations)],
                                   capture_output=True, text=True, check=True,
                                   creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        results.append(json.loads(completed.stdout))
    controls = max(item['rssGrowthMiB'] for item in results[:2])
    excess = results[-1]['rssGrowthMiB'] - controls
    report = {'results': results, 'excessThreadGrowthMiB': excess,
              'gateMode': results[-1]['mode'],
              'maximumExcessMiB': args.maximum_excess_mib,
              'status': 'failed' if excess > args.maximum_excess_mib else 'passed'}
    target = Path(args.report)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(f"NATIVE THREAD PROBE {report['status'].upper()}: {excess:.2f} MiB excess; {target}")
    return 1 if report['status'] == 'failed' else 0


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--child', choices=('empty-thread', 'same-thread', 'crypto-thread', 'managed-crypto-thread'))
    parser.add_argument('--managed', action='store_true', help='Gate the MINA bounded-worker path, retaining the raw upstream control')
    parser.add_argument('--iterations', type=int, default=4000)
    parser.add_argument('--maximum-excess-mib', type=float, default=4)
    parser.add_argument('--report', default='tmp/connector-native-memory.json')
    args = parser.parse_args()
    if args.iterations <= 0 or args.maximum_excess_mib < 0:
        parser.error('Iterations must be positive and the growth limit nonnegative')
    sys.exit(main(args))
