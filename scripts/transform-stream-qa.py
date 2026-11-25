"""Audit complete streaming task flows and sample the actual interpreter RSS."""
import argparse
import asyncio
import csv
import importlib.util
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))
from app.models import Project
import psutil

spec = importlib.util.spec_from_file_location('stream_qa_flow', ROOT / 'scripts/flow-throughput.py')
flow = importlib.util.module_from_spec(spec); spec.loader.exec_module(flow)


async def main(args):
    out = Path(args.output_dir).resolve(); out.mkdir(parents=True, exist_ok=True)
    if (out / 'input.csv').exists() or (out / 'summary.json').exists(): raise ValueError('Use a fresh QA output directory')
    source = out / 'input.csv'
    with source.open('w', encoding='utf-8', newline='') as handle:
        writer = csv.writer(handle); writer.writerow(['seq', 'name'])
        for index in range(args.records): writer.writerow([str(index), ' name-' + str(index) + ' '])
    reports = []
    for kind in ('mapper', 'script_transform'):
        for mode in ('run', 'debug', 'python-direct', 'python-engine'):
            target = out / (kind + '-' + mode + '.jsonl')
            config = {'streamEnabled': True, 'streamInputFile': str(source), 'streamOutputFile': str(target),
                'streamInputFormat': 'csv', 'streamTimeoutSeconds': 600,
                'mappings': [{'target': 'seq', 'source': '${input.seq}'},
                             {'target': 'name', 'source': '${input.name}', 'functions': ['trim', 'upperCase']}],
                'libraries': {'qa::Names': 'fun normalize(value) = upper(trim(value))'},
                'script': '%mina 2.0\nimport normalize from qa::Names\noutput application/json\n---\n{seq: payload.seq, name: normalize(payload.name)}',
                'sourceSchemaId': 'contract', 'targetSchemaId': 'contract'}
            schema = {'type': 'object', 'required': ['seq', 'name'], 'properties': {'seq': {'type': 'string'}, 'name': {'type': 'string'}}, 'additionalProperties': False}
            nodes = [{'id': 's', 'name': 'Start', 'type': 'start'}, {'id': 'work', 'name': 'Transform', 'type': kind, 'config': config}, {'id': 'e', 'name': 'End', 'type': 'end'}]
            project = Project.model_validate({'id': 'stream-qa', 'name': 'Stream-QA', 'schemas': [{'id': 'contract', 'name': 'record.json', 'content': json.dumps(schema)}],
                'tasks': [{'id': 'main', 'name': 'Main', 'kind': 'subtask', 'activities': nodes, 'transitions': [
                    {'id': str(i), 'source': a['id'], 'target': b['id']} for i, (a, b) in enumerate(zip(nodes, nodes[1:]))]}]})
            executor = flow.Executor(mode, project, str(out / (kind + '-' + mode + '.log')))
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
                result = await asyncio.wait_for(executor.execute('main', {}), 610)
                assert result['recordsWritten'] == args.records
                verified = 0
                with target.open(encoding='utf-8') as handle:
                    for index, line in enumerate(handle):
                        value = json.loads(line)
                        assert value == {'seq': str(index), 'name': 'NAME-' + str(index)}, (kind, mode, index)
                        verified += 1
                assert verified == args.records
            finally:
                stopped = True; await monitor
                await executor.close()
            elapsed = time.monotonic() - started
            report = {'family': kind, 'mode': mode, 'passed': verified == args.records and elapsed <= 600,
                'records': verified, 'elapsedSeconds': elapsed, 'deadlineSeconds': 600,
                'actualInterpreterIdentified': True, 'baselineRssMiB': baseline / 1048576,
                'peakRssMiB': max(samples or [baseline]) / 1048576,
                'scope': 'Start -> streamed transform with source/target schema validation -> End; generated archive startup/import, output readback and cleanup included',
                'limitations': 'RSS samples describe this bounded workload, not proof of no leaks or a long-duration soak'}
            reports.append(report)
            (out / (kind + '-' + mode + '.json')).write_text(json.dumps(report, indent=2) + '\n')
            print(json.dumps(report), flush=True)
    summary = {'passed': all(row['passed'] for row in reports), 'recordsPerCase': args.records, 'results': reports}
    (out / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')
    return 0 if summary['passed'] else 1


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--records', type=int, default=100000)
    parser.add_argument('--output-dir', required=True)
    args = parser.parse_args()
    if args.records < 1: parser.error('Positive record count required')
    sys.exit(asyncio.run(main(args)))
