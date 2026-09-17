"""Python-native deployment entry point for full-fidelity exported workflows.

The bundled execution engine is the same Python engine Studio uses. The
project, tasks, resources, and profiles are constructed by Python modules;
no Fabric JSON descriptor or source DSL is read at runtime.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
from pathlib import Path
from typing import Any

from .engine.models import effective_event_activities
from .engine.runtime import WorkflowRuntime
from .engine.sap import sap_adapter
from .project import build_project


LOG = logging.getLogger('integrationfabric.python')
RUNTIME = WorkflowRuntime()


def _secrets() -> dict[str, Any]:
    values: dict[str, Any] = {}
    source = os.environ.get('FABRIC_SECRET_FILE')
    if source:
        values.update(json.loads(Path(source).read_text(encoding='utf-8')))
    inline = os.environ.get('FABRIC_SECRET_VALUES')
    if inline:
        values.update(json.loads(inline))
    return values


def prepare(environment: str):
    project = build_project()
    if environment not in project.properties:
        raise ValueError(f'Unknown packaged environment {environment!r}')
    project.active_environment = environment
    secrets = _secrets()
    for prop in project.properties[environment]:
        if prop.key in secrets or prop.key in os.environ:
            prop.value = secrets.get(prop.key, os.environ.get(prop.key))
    for resource in project.resources:
        for field in list(resource.config):
            key = f'resources.{resource.id}.config.{field}'
            if key in secrets or key in os.environ:
                resource.config[field] = secrets.get(key, os.environ.get(key))
    return project


def _properties(project, environment: str) -> dict:
    return {value.key: value.value for value in project.properties[environment]}


def _record(result) -> None:
    for entry in result.logs:
        LOG.log(getattr(logging, str(entry.get('level', 'INFO')).upper(), logging.INFO),
                json.dumps(entry, ensure_ascii=False, default=str))


async def run_task(task_id: str, payload: Any = None, environment_name: str = 'local') -> Any:
    """Callable directly from a notebook or other Python host."""
    project = prepare(environment_name)
    task = next((item for item in project.tasks if item.id == task_id), None)
    if task is None: raise ValueError(f'Unknown task: {task_id}')
    result = await RUNTIME.run(task, {} if payload is None else payload, {item.id: item for item in project.resources},
                               _properties(project, environment_name), project=project)
    _record(result)
    if result.status != 'completed':
        raise RuntimeError(f'Task {task.name} failed: {result.logs[-1]["message"] if result.logs else "unknown error"}')
    return result.output


def _event_available(output: Any) -> bool:
    if not isinstance(output, dict): return output is not None
    if output.get('scheduledTime'): return True
    if 'received' in output: return bool(output['received'])
    if 'count' in output: return int(output.get('count') or 0) > 0
    if output.get('messages'): return True
    return bool(output.get('MessageID') or output.get('messageId') or output.get('body') is not None)


def _listener_context(project, task, resources, properties, environment: str) -> dict:
    return {'input': {}, 'vars': {}, 'last': {}, 'resources': resources, 'properties': properties,
            'project': project, 'runtime': RUNTIME, 'logs': [], 'activities': {},
            'tasks': {task.id: {'name': task.name, 'activities': {}}},
            'context': {'taskId': task.id, 'activityId': '', 'environment': environment},
            'transport': {}}


async def _receive_forever(project, task, event, environment: str) -> None:
    resources = {item.id: item for item in project.resources}
    properties = _properties(project, environment)
    cfg = RUNTIME.resolve(event.config, {'properties': properties, 'input': {}, 'last': {}, 'vars': {}, 'context': {}})
    sap = event.type == 'sap'
    workers = max(1, min(64, int(cfg.get('maxConcurrentIdocs') or cfg.get('maximumConnections') or 8))) if sap else 1
    receive_lock = asyncio.Lock()

    async def worker(index: int):
        retry_delay = 1.0
        while True:
            context = _listener_context(project, task, resources, properties, environment)
            delivery_id = listener_key = None
            transport: dict[str, Any] = {}
            try:
                if sap:
                    async with receive_lock:
                        output = await RUNTIME.execute_with_policy(event, context)
                else:
                    output = await RUNTIME.execute_with_policy(event, context)
                retry_delay = 1.0
                if not _event_available(output):
                    await asyncio.sleep(max(.1, float(cfg.get('pollInterval') or 1)) if event.type == 'file' else .1)
                    continue
                if sap and isinstance(output, dict):
                    delivery_id = output.pop('_sapDeliveryId', None)
                    listener_key = output.pop('_sapListenerKey', None)
                    transport = {'deliveryId': delivery_id, 'listenerKey': listener_key,
                                 'functionName': output.get('functionName'), 'operation': event.config.get('operation'),
                                 'invocationProtocol': output.get('invocationProtocol')}
                result = await RUNTIME.run(task, output, resources, properties, event.id, project,
                                           event_output=output, transport=transport)
                _record(result)
                if delivery_id and listener_key and not transport.get('completed'):
                    sap_adapter.acknowledge_idoc(listener_key, delivery_id, result.status == 'completed')
                if event.type == 'timer':
                    repeat = bool(cfg.get('repeatEnabled'))
                    cron = str(cfg.get('scheduleMode') or '').lower() == 'cron'
                    if not repeat and not cron: return
                    if repeat and not cron:
                        unit = {'seconds': 1, 'minutes': 60, 'hours': 3600, 'days': 86400}.get(str(cfg.get('unit') or 'minutes').lower(), 60)
                        await asyncio.sleep(max(1, float(cfg.get('interval') or 1) * unit))
                elif event.type == 'file':
                    await asyncio.sleep(max(.1, float(cfg.get('pollInterval') or 1)))
            except asyncio.CancelledError:
                if delivery_id and listener_key and not transport.get('completed'):
                    sap_adapter.acknowledge_idoc(listener_key, delivery_id, False)
                raise
            except Exception:
                if delivery_id and listener_key and not transport.get('completed'):
                    try: sap_adapter.acknowledge_idoc(listener_key, delivery_id, False)
                    except Exception: LOG.exception('SAP rollback failed')
                LOG.exception('%s listener failed; retrying in %s seconds', event.name, retry_delay)
                await asyncio.sleep(retry_delay)
                retry_delay = min(30.0, retry_delay * 2)

    try:
        await asyncio.gather(*(worker(index) for index in range(workers)))
    finally:
        if sap:
            resource = resources.get(cfg.get('resourceId'))
            sap_cfg = {**RUNTIME.resolve(resource.config, {'properties': properties, 'input': {}, 'last': {}, 'vars': {}, 'context': {}}), **cfg} if resource else cfg
            try: sap_adapter.stop_listener(sap_cfg)
            except Exception: LOG.exception('SAP listener shutdown failed')


async def _serve_http(project, listeners, environment: str) -> None:
    from fastapi import FastAPI, Request
    from fastapi.responses import JSONResponse, Response
    import uvicorn
    app = FastAPI()
    resources = {item.id: item for item in project.resources}
    properties = _properties(project, environment)
    for task, event in listeners:
        path = str(RUNTIME.resolve(event.config.get('path', '/'), {'properties': properties, 'input': {}, 'last': {}, 'vars': {}, 'context': {}}))
        methods = event.config.get('methods') or event.config.get('method') or 'POST'
        methods = [part.strip().upper() for part in (methods if isinstance(methods, list) else str(methods).split(','))]
        async def endpoint(request: Request, _task=task, _event=event):
            raw = await request.body()
            try: body = json.loads(raw) if raw else None
            except (ValueError, UnicodeDecodeError): body = raw.decode(errors='replace')
            payload = {'body': body, 'method': request.method, 'path': request.url.path,
                       'query': dict(request.query_params), 'headers': dict(request.headers),
                       'pathParameters': dict(request.path_params)}
            result = await RUNTIME.run(_task, payload, resources, properties, _event.id, project)
            _record(result)
            if result.status != 'completed': return JSONResponse({'status': 'failed'}, status_code=500)
            output = result.output
            if output.get('__httpResponse'):
                value = output.get('body')
                return JSONResponse(value, status_code=int(output.get('statusCode') or 200), headers=output.get('headers') or {}) if isinstance(value, (dict, list)) else Response(str(value or ''), status_code=int(output.get('statusCode') or 200), headers=output.get('headers') or {})
            return JSONResponse(output)
        app.add_api_route(path, endpoint, methods=methods)
        LOG.info('HTTP listener ready: %s %s', ','.join(methods), path)
    port = int(os.environ.get('FABRIC_HTTP_PORT') or 8787)
    server = uvicorn.Server(uvicorn.Config(app, host=os.environ.get('FABRIC_HTTP_HOST', '0.0.0.0'), port=port, log_level='info'))
    await server.serve()


async def run_application(environment_name: str = 'local') -> None:
    project = prepare(environment_name)
    enabled = os.environ.get('FABRIC_ENABLED_STARTERS')
    enabled_ids = set(json.loads(enabled)) if enabled else None
    starters = [task for task in project.tasks if task.kind == 'starter' and (enabled_ids is None or task.id in enabled_ids)]
    if not starters:
        if not os.environ.get('FABRIC_DEPLOYMENT_ID'):
            raise ValueError('No Starter Tasks are enabled')
        LOG.info('All Starter Tasks are stopped; Python application remains idle')
        await asyncio.Event().wait()
    jobs = []
    http_listeners = []
    for task in starters:
        events = effective_event_activities(task.activities, task.transitions)
        event = events[0] if events and events[0].type != 'start' else None
        if event is None:
            jobs.append(run_task(task.id, {}, environment_name))
        elif event.type in ('http_listener', 'rest', 'soap'):
            http_listeners.append((task, event))
        else:
            jobs.append(_receive_forever(project, task, event, environment_name))
    if http_listeners: jobs.append(_serve_http(project, http_listeners, environment_name))
    await asyncio.gather(*jobs)
    if os.environ.get('FABRIC_DEPLOYMENT_ID'):
        await asyncio.Event().wait()


def main() -> int:
    parser = argparse.ArgumentParser(description='Run an exported Python integration application')
    parser.add_argument('--environment', default=os.environ.get('FABRIC_ENVIRONMENT', 'local'))
    parser.add_argument('--task', help='Run an individual task')
    parser.add_argument('--input', default='{}')
    args = parser.parse_args()
    logging.basicConfig(level=os.environ.get('FABRIC_LOG_LEVEL', 'INFO'), format='%(asctime)s %(levelname)s %(message)s')
    try:
        if args.task:
            print(json.dumps(asyncio.run(run_task(args.task, json.loads(args.input), args.environment)), default=str))
        else:
            asyncio.run(run_application(args.environment))
    except KeyboardInterrupt:
        return 0
    except Exception:
        LOG.exception('Python application failed')
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
