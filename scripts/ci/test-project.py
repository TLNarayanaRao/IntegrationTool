"""Run a saved MINA test suite against Studio runtime code and both Python formats."""
import argparse
import asyncio
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'backend'))

from app.integration_libraries import studio_project_input
from app.main import _environment_values
from app.project_import import MAX_IMPORT_BYTES, project_payload
from app.raw_python import engine_python_files, raw_python_files
from app.runtime import WorkflowRuntime


async def run_studio(project, case, environment, timeout):
    runtime = WorkflowRuntime()
    task = next(task for task in project.tasks if task.id == case['task'])
    result = await asyncio.wait_for(runtime.run(
        task, case.get('input', {}), {item.id: item for item in project.resources},
        _environment_values(project, environment), project=project, environment=environment), timeout)
    if result.status != 'completed':
        raise ValueError('Runtime execution failed')
    return result.output


def run_package(root, command, case, environment, timeout):
    result = subprocess.run(
        [sys.executable, *command, '--environment', environment, '--task', case['task'],
         '--input', json.dumps(case.get('input', {}), allow_nan=False)],
        cwd=root, capture_output=True, text=True, encoding='utf-8', timeout=timeout,
        env={**os.environ, 'PYTHONUTF8': '1'}, check=False)
    if result.returncode:
        raise ValueError('Archive execution failed')
    return json.loads(result.stdout)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('project', type=Path)
    parser.add_argument('suite', type=Path)
    parser.add_argument('--environment', default='local')
    parser.add_argument('--timeout', type=int, default=30)
    args = parser.parse_args()
    try:
        if not 1 <= args.timeout <= 300:
            raise ValueError('Timeout must be between 1 and 300 seconds')
        with args.project.open('rb') as source:
            project = studio_project_input(json.loads(project_payload(source.read(MAX_IMPORT_BYTES + 1), args.project.name)))
        if args.suite.stat().st_size > 1024 * 1024:
            raise ValueError('Test suite exceeds 1 MiB')
        suite = json.loads(args.suite.read_text(encoding='utf-8'))
        cases = suite.get('cases') if isinstance(suite, dict) else None
        task_ids = {task.id for task in project.tasks}
        if not isinstance(cases, list) or not 1 <= len(cases) <= 100 or any(
            not isinstance(case, dict) or case.get('task') not in task_ids or 'expected' not in case or
            not isinstance(case.get('input', {}), dict) for case in cases
        ):
            raise ValueError('Each of 1 to 100 cases needs a valid task ID, object input, and expected output')
        if args.environment not in project.properties:
            raise ValueError('Test environment is missing from the project')
        profiles = {args.environment: [prop.model_dump() for prop in project.properties[args.environment]]}
        failures = 0
        with tempfile.TemporaryDirectory(prefix='mina-tests-') as directory:
            runners = []
            for name, compiler, command in (
                ('Direct Python', raw_python_files, ['run.py']),
                ('Engine Python', engine_python_files, ['-m', 'application.main']),
            ):
                root = Path(directory) / name
                for entry, body in compiler(project.model_dump(), profiles).items():
                    path = root / entry
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(body)
                runners.append((name, root, command))
            for index, case in enumerate(cases, start=1):
                for name, root, command in [('Run', None, None), *runners]:
                    try:
                        output = (asyncio.run(run_studio(project, case, args.environment, args.timeout)) if root is None
                                  else run_package(root, command, case, args.environment, args.timeout))
                        if json.dumps(output, sort_keys=True, allow_nan=False) != json.dumps(case['expected'], sort_keys=True, allow_nan=False):
                            raise ValueError('Output differs from expected')
                    except (ValueError, TimeoutError, subprocess.TimeoutExpired) as exc:
                        print(f'FAIL case {index} ({name}): {exc}', file=sys.stderr)
                        failures += 1
                    else:
                        print(f'PASS case {index} ({name})')
        return int(bool(failures))
    except (ValueError, OSError, KeyError, TypeError) as exc:
        print(f'MINA test suite could not run: {exc}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
