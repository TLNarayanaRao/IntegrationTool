"""Qualify a bulk indexed join through complete MINA task execution paths."""
import argparse
import asyncio
import importlib.util
import json
from pathlib import Path
import sys
import time
import psutil

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))
from app.models import Project

spec = importlib.util.spec_from_file_location('standards_flow', ROOT / 'scripts/flow-throughput.py')
flow = importlib.util.module_from_spec(spec); spec.loader.exec_module(flow)


async def measure(args):
    out = Path(args.output_dir).resolve()
    if (out / 'summary.json').exists(): raise ValueError('Use a fresh output directory')
    out.mkdir(parents=True, exist_ok=True)
    payload = {'left': [{'id': index} for index in range(args.records)], 'right': [{'key': index} for index in range(args.records)]}
    nodes = [{'id': 's', 'type': 'start', 'name': 'Start'}, {'id': 'm', 'type': 'mapper', 'name': 'Join-records', 'config': {'mappings': [
        {'target': 'joined', 'source': 'joinRecords(${input.left}, ${input.right}, ["/id"], ["/key"], "inner")'}]}}, {'id': 'e', 'type': 'end', 'name': 'End'}]
    project = Project.model_validate({'id': 'mapper-standards', 'name': 'Mapper-standards', 'tasks': [{'id': 'main', 'name': 'Main', 'kind': 'subtask',
        'activities': nodes, 'transitions': [{'id': str(index), 'source': a['id'], 'target': b['id']} for index, (a, b) in enumerate(zip(nodes, nodes[1:]))]}]})
    reports = []
    for mode in ('run', 'debug', 'python-direct', 'python-engine'):
        executor = flow.Executor(mode, project, str(out / (mode + '.log')))
        started = time.monotonic(); samples = []; stopped = False
        await executor.start()
        process = psutil.Process(executor.interpreter_pid)
        baseline = process.memory_info().rss
        async def sample():
            while not stopped:
                try: samples.append(process.memory_info().rss)
                except psutil.Error: break
                await asyncio.sleep(.05)
        monitor = asyncio.create_task(sample())
        try:
            result = await asyncio.wait_for(executor.execute('main', payload), 600)
            rows = result['joined']
            if len(rows) != args.records: raise AssertionError('Join record count mismatch')
            for index, row in enumerate(rows):
                if row != {'left': {'id': index}, 'right': {'key': index}}: raise AssertionError('Join payload/order mismatch')
        finally:
            stopped = True; await monitor; await executor.close()
        elapsed = time.monotonic() - started
        report = {'mode': mode, 'passed': elapsed <= 600, 'inputRecordsPerSide': args.records,
            'uniqueJoinedRecordsVerified': len(rows), 'elapsedSeconds': elapsed, 'deadlineSeconds': 600,
            'baselineRssMiB': baseline / 1048576, 'sampledPeakRssMiB': max(samples or [baseline]) / 1048576,
            'actualInterpreterIdentified': True,
            'scope': 'Start -> one bulk Mapper joinRecords -> End; archive generation/startup/IPC, full output audit and cleanup included',
            'limitations': 'Bulk collection processing, not per-message orchestration or a long-duration memory soak'}
        reports.append(report)
        (out / (mode + '.json')).write_text(json.dumps(report, indent=2) + '\n')
        print(json.dumps(report), flush=True)
    summary = {'passed': all(row['passed'] for row in reports), 'results': reports}
    (out / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')
    return 0 if summary['passed'] else 1


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--records', type=int, default=100000)
    parser.add_argument('--output-dir', required=True)
    args = parser.parse_args()
    if not 1 <= args.records <= 100000: parser.error('Record count must be between 1 and 100000')
    sys.exit(asyncio.run(measure(args)))
