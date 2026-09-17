"""Raw Python application entry point; also importable in a notebook."""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os

from .config import environment
from .core import Context
from .registry import STARTERS, TASKS


async def run_task(task_id: str, payload=None, environment_name: str = 'local'):
    properties, resources = environment(environment_name)
    context = Context(payload if payload is not None else {}, properties, resources)
    return await TASKS[task_id](context)


async def run_application(environment_name: str = 'local'):
    enabled = os.environ.get('FABRIC_ENABLED_STARTERS')
    ids = [task_id for task_id in STARTERS if not enabled or task_id in json.loads(enabled)]
    if not ids: raise ValueError('No Starter Tasks are enabled')
    return await asyncio.gather(*(run_task(task_id, environment_name=environment_name) for task_id in ids))


def main() -> int:
    parser = argparse.ArgumentParser(description='Run the generated Python application')
    parser.add_argument('--environment', default=os.environ.get('FABRIC_ENVIRONMENT', 'local'))
    parser.add_argument('--task', choices=list(TASKS), help='Run one task, including a Sub Task')
    parser.add_argument('--input', default='{}', help='JSON input for --task')
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
    try:
        if args.task:
            print(json.dumps(asyncio.run(run_task(args.task, json.loads(args.input), args.environment)), default=str))
        else:
            asyncio.run(run_application(args.environment))
            # A one-shot starter is still a managed application when launched
            # by Control Plane. Notebook/CLI invocation returns immediately.
            if os.environ.get('FABRIC_DEPLOYMENT_ID'):
                asyncio.run(asyncio.Event().wait())
    except Exception:
        logging.exception('Python application failed')
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
