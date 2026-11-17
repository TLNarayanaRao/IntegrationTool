"""Verify the saved Studio AI Mapper QA project through all execution formats.

Use a project JSON captured after the browser review/Save mapper steps. This
does not generate replacement mapping rules, so it audits what Studio saved.
"""
import argparse
import asyncio
import copy
import importlib.util
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))
from app.models import Project


async def verify(project_file, folder):
    project = Project.model_validate(json.loads(project_file.read_text(encoding='utf-8-sig')))
    folder.mkdir(parents=True, exist_ok=True)
    spec = importlib.util.spec_from_file_location('saved_mapper_flow', ROOT / 'scripts/flow-throughput.py')
    flow = importlib.util.module_from_spec(spec); spec.loader.exec_module(flow)
    source = {'purchases': [{'id': 1, 'items': [{'sku': 'A', 'qty': 2}, {'sku': 'B', 'qty': 3}]},
                            {'id': 2, 'items': [{'sku': 'C', 'qty': 4}]}],
              'first_name': 'Ada', 'tags': ['fast', 'safe']}
    expected = {'orders': [{'id': 1, 'lines': [{'productCode': 'A', 'quantity': 2}, {'productCode': 'B', 'quantity': 3}]},
                           {'id': 2, 'lines': [{'productCode': 'C', 'quantity': 4}]}],
                'firstName': 'Ada', 'tags': ['fast', 'safe']}
    authored = copy.deepcopy(expected); authored['firstName'] = 'Authored'
    for order in authored['orders']: order['id'] = 99
    cases = [('nested', source, expected), ('ambiguous', {'billing': {'id': 11}, 'shipping': {'id': 22}}, {'id': 22}),
             ('existing', source, authored)]
    if any(task.id == 'ui-run' for task in project.tasks): cases.append(('ui-run', {}, expected))
    results = []
    for mode in ('run', 'debug', 'python-direct', 'python-engine'):
        executor = flow.Executor(mode, project, str(folder / (mode + '.log')))
        started = time.perf_counter()
        try:
            await executor.start()
            for task, payload, wanted in cases:
                # Studio drives starter Debug events interactively. Audit its
                # called subtask here; the browser test covers listener setup.
                if task == 'ui-run' and mode == 'debug': continue
                output = await executor.execute(task, payload)
                assert output == wanted, (mode, task, output, wanted)
                results.append({'mode': mode, 'task': task, 'passed': True, 'output': output})
        finally: await executor.close()
        print(mode, 'passed', sum(item['mode'] == mode for item in results), 'saved flows in', round(time.perf_counter() - started, 3), 'seconds', flush=True)
    report = {'passed': True, 'scope': 'Actual browser-saved rules; complete flows; every output value audited',
              'results': results, 'limitations': 'Synthetic local data; functional verification, not a service soak or latency benchmark'}
    (folder / 'summary.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    if (args.output_dir / 'summary.json').exists(): parser.error('Choose a fresh output directory')
    asyncio.run(verify(args.project, args.output_dir))
