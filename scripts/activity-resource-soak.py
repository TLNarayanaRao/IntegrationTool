"""Bounded concurrent local-activity soak; does not qualify remote providers.

Run with the backend environment plus openpyxl and psutil. The report records
the actual duration, counts, failures, RSS, Python heap, handles and threads.
No explicit garbage collection is used to improve measurements.
"""
import argparse
import asyncio
from functools import partial
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import statistics
import sys
import tempfile
import threading
import time
import tracemalloc

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
import psutil
from openpyxl import Workbook
from app.data_formats import execute_format
from app.dataweave import execute as dataweave
from app.mapper import execute as mapper
from app.runtime import WorkflowRuntime
from app.raw_python_support.activities import excel_read, python_invoke

execute_format = partial(execute_format, payload=None)


def run(seconds, warmup, output):
    stop = threading.Event()
    counts, errors, guard = Counter(), [], threading.Lock()
    runtime = WorkflowRuntime()
    process = psutil.Process()
    tracemalloc.start(1)
    with tempfile.TemporaryDirectory(prefix='mina-activity-soak-') as folder:
        file = Path(folder) / 'records.xlsx'
        book = Workbook()
        sheet = book.active
        sheet.append(['id', 'customer.name'])
        for number in range(20): sheet.append([number, 'Customer'])
        book.save(file)
        book.close()
        cfg = {'filePath': str(file), 'maximumRows': 5}

        def formats():
            records = [{'id': 1, 'description': 'MINA, "hello"\nnext line café'}]
            flat = {'fields': 'id,description', 'fieldTypes': 'integer,string', 'header': True}
            text = execute_format('flat', 'render', {**flat, 'records': records})['text']
            assert execute_format('flat', 'parse', {**flat, 'text': text})['records'] == records
            assert execute_format('json', 'parse', {'jsonString': '{"id":1}'}) == {'id': 1}
            execute_format('json', 'render', {'value': records})
            execute_format('xml', 'parse', {'xmlString': '<records><id>1</id></records>'})
            execute_format('xml', 'render', {'value': {'id': 1}, 'rootElement': 'records'})

        def mapping():
            value = mapper({'name': 'customer'}, [{'target': 'name', 'source': '${name}'}])
            assert value['name'] == 'customer'
            result = dataweave('%dw 2.0\noutput application/json\n---\n{ name: upper(payload.name) }', payload={'name': 'customer'})
            assert result['name'] == 'CUSTOMER'

        def excel():
            assert runtime.read_excel(cfg)['workbook']['sheets'][0]['rowCount'] == 5
            assert excel_read(cfg)['workbook']['sheets'][0]['rowCount'] == 5

        def worker(name, action):
            try:
                while not stop.is_set():
                    action()
                    with guard: counts[name] += 1
            except Exception as error:
                with guard: errors.append({'family': name, 'error': repr(error)})
                stop.set()

        def python_worker():
            async def execute():
                config = {'sourceCode': 'def transform(value):\n    return value + 1', 'function': 'transform', 'parameters': [41]}
                while not stop.is_set():
                    assert (await runtime.python_worker(config, None))['result'] == 42
                    assert (await python_invoke(config, None))['result'] == 42
                    with guard: counts['python'] += 1
            try: asyncio.run(execute())
            except Exception as error:
                with guard: errors.append({'family': 'python', 'error': repr(error)})
                stop.set()

        def snapshot(elapsed):
            current, peak = tracemalloc.get_traced_memory()
            return {'seconds': round(elapsed, 2), 'rssMiB': process.memory_info().rss / 1048576,
                'heapMiB': current / 1048576, 'heapPeakMiB': peak / 1048576,
                'handles': process.num_handles() if hasattr(process, 'num_handles') else process.num_fds(),
                'threads': process.num_threads()}

        samples = []
        started = time.monotonic()
        with ThreadPoolExecutor(max_workers=8, thread_name_prefix='mina-activity-soak') as pool:
            futures = [pool.submit(worker, name, action) for name, action in
                [('formats', formats)] * 2 + [('mapper-dataweave', mapping)] * 2 + [('excel', excel)] * 2]
            futures += [pool.submit(python_worker) for _ in range(2)]
            try:
                while time.monotonic() - started < warmup + seconds and not stop.is_set():
                    elapsed = time.monotonic() - started
                    if elapsed >= warmup: samples.append(snapshot(elapsed - warmup))
                    stop.wait(min(5, max(.01, warmup + seconds - elapsed)))
            finally:
                stop.set()
                for future in futures: future.result(timeout=60)
        final = snapshot(time.monotonic() - started - warmup)
        runtime.close_publishers()
    tracemalloc.stop()
    first = samples[0] if samples else final
    tail = samples[len(samples)//2:]
    def slope(key):
        if len(tail) < 2: return 0
        xs, ys = [s['seconds'] / 60 for s in tail], [s[key] for s in tail]
        mean_x, mean_y = statistics.mean(xs), statistics.mean(ys)
        return sum((x-mean_x)*(y-mean_y) for x,y in zip(xs,ys)) / sum((x-mean_x)**2 for x in xs)
    growth = {key: final[key] - first[key] for key in ('rssMiB', 'heapMiB', 'handles', 'threads')}
    gates = {'noErrors': not errors, 'duration': final['seconds'] >= seconds - 1,
        'rssGrowth': growth['rssMiB'] <= 64, 'heapGrowth': growth['heapMiB'] <= 8,
        'handles': growth['handles'] <= 8, 'threads': growth['threads'] <= 2,
        'lateRssSlope': slope('rssMiB') <= .5, 'allFamilies': all(counts[name] for name in ('formats', 'mapper-dataweave', 'excel', 'python'))}
    report = {'passed': all(gates.values()), 'gates': gates, 'measuredSeconds': final['seconds'], 'warmupSeconds': warmup,
        'workers': 8, 'counts': dict(counts), 'errors': errors, 'growth': growth,
        'lateRssMiBPerMinute': slope('rssMiB'), 'final': final, 'samples': samples,
        'scope': 'Local XML/JSON/flat parse-render, Mapper, DataWeave, source/Direct Excel and Python. No remote provider claims.'}
    Path(output).parent.mkdir(parents=True, exist_ok=True)
    Path(output).write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps({key: value for key, value in report.items() if key != 'samples'}, indent=2), flush=True)
    return report['passed']


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--seconds', type=float, default=600)
    parser.add_argument('--warmup', type=float, default=30)
    parser.add_argument('--output', default='tmp/activity-resource-soak.json')
    args = parser.parse_args()
    if args.seconds <= 0 or args.warmup < 0: parser.error('seconds must be positive and warmup nonnegative')
    sys.exit(0 if run(args.seconds, args.warmup, args.output) else 1)
