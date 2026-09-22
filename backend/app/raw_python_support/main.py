"""Raw Python application entry point; also importable in a notebook."""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os

from .config import DEFAULT_ENVIRONMENT, environment
from .core import Context, execute_with_policy, resolve
# CONNECTOR_IMPORT
from .registry import EVENT_STARTERS, STARTERS, TASKS
from .diagnostics import check_runtime
from .qualification import qualify


async def run_task(task_id: str, payload=None, environment_name: str = DEFAULT_ENVIRONMENT):
    properties, resources = environment(environment_name)
    context = Context(payload if payload is not None else {}, properties, resources, environment_name=environment_name)
    return await TASKS[task_id](context)


async def run_application(environment_name: str = DEFAULT_ENVIRONMENT):
    enabled = os.environ.get('FABRIC_ENABLED_STARTERS')
    ids = [task_id for task_id in STARTERS if not enabled or task_id in json.loads(enabled)]
    if not ids: raise ValueError('No Starter Tasks are enabled')
    # ACKNOWLEDGEMENT_CAPABILITY_START
    async def acknowledge_delivery(technology: str, listener_key: str, delivery_id: str, success: bool):
        if technology == 'sap':
            await asyncio.to_thread(connectors.acknowledge_sap, listener_key, delivery_id, success)
        else:
            connectors.acknowledge_jms(listener_key, delivery_id, success)
    # ACKNOWLEDGEMENT_CAPABILITY_END
    async def receive_forever(task_id: str):
        activity_id, kind, config, name = EVENT_STARTERS[task_id]
        delay = 1.0
        while True:
            properties, resources = environment(environment_name)
            context = Context({}, properties, resources, environment_name=environment_name)
            delivery_id = listener_key = technology = None
            try:
                output = await execute_with_policy(kind, config, context, activity_id, name)
                delay = 1.0
                available = output is not None and (not isinstance(output, dict) or
                    bool(output.get('scheduledTime') or output.get('count') or output.get('received') or output.get('messages') or output.get('body') is not None))
                if available:
                    if kind == 'sap' and isinstance(output, dict):
                        delivery_id = output.pop('_sapDeliveryId', None)
                        listener_key = output.pop('_sapListenerKey', None)
                        technology = 'sap'
                    elif kind in {'ems', 'jms'} and isinstance(output, dict):
                        delivery_id = output.pop('_jmsDeliveryId', None)
                        listener_key = output.pop('_jmsListenerKey', None)
                        technology = 'jms'
                        context.transport.update({'replyTo': output.get('replyTo') or (output.get('headers') or {}).get('JMSReplyTo'),
                                                  'correlationId': output.get('correlationId') or (output.get('headers') or {}).get('JMSCorrelationID')})
                    if delivery_id and listener_key:
                        context.transport.update({'deliveryId': delivery_id, 'listenerKey': listener_key,
                                                  'technology': technology, 'functionName': output.get('functionName'), 'completed': False})
                    await TASKS[task_id](context, start_after=activity_id, event_output=output)
                    if delivery_id and listener_key and not context.transport.get('completed'):
                        await acknowledge_delivery(technology, listener_key, delivery_id, True)
                else:
                    await asyncio.sleep(.1)
                if kind == 'sap' and isinstance(output, dict) and output.get('mock'):
                    await asyncio.sleep(.1)
                if kind == 'timer':
                    repeat_value = resolve(config.get('repeatEnabled', False), context)
                    repeat = repeat_value.lower() in {'true', '1', 'yes', 'on'} if isinstance(repeat_value, str) else bool(repeat_value)
                    mode = str(resolve(config.get('scheduleMode') or '', context)).lower()
                    if not repeat and mode != 'cron':
                        return
                    if repeat and mode != 'cron':
                        unit = {'seconds': 1, 'minutes': 60, 'hours': 3600, 'days': 86400}.get(str(resolve(config.get('unit') or 'minutes', context)).lower(), 60)
                        await asyncio.sleep(max(1, float(resolve(config.get('interval') or 1, context)) * unit))
            except asyncio.CancelledError:
                if delivery_id and listener_key and not context.transport.get('completed'):
                    await acknowledge_delivery(technology, listener_key, delivery_id, False)
                raise
            except Exception:
                if delivery_id and listener_key and not context.transport.get('completed'):
                    try: await acknowledge_delivery(technology, listener_key, delivery_id, False)
                    except Exception: logging.exception('%s delivery rejection failed', technology)
                logging.exception('Starter %s failed; retrying in %s seconds', task_id, delay)
                await asyncio.sleep(delay)
                delay = min(30.0, delay * 2)
    # HTTP_CAPABILITY_START
    http_ids = [task_id for task_id in ids if task_id in EVENT_STARTERS and EVENT_STARTERS[task_id][1] in {'http_listener', 'rest', 'soap'}]
    jobs = [receive_forever(task_id) if task_id in EVENT_STARTERS else run_task(task_id, environment_name=environment_name)
            for task_id in ids if task_id not in http_ids]
    if http_ids:
        from .inbound_http import serve_http
        jobs.append(serve_http(http_ids, environment_name))
    # HTTP_CAPABILITY_END
    return await asyncio.gather(*jobs)


async def managed_run(awaitable):
    """Keep async connector shutdown on the loop that owns the clients."""
    try:
        return await awaitable
    finally:
        # ASYNC_CONNECTOR_CLOSE_START
        pass
        # ASYNC_CONNECTOR_CLOSE_END


def main() -> int:
    parser = argparse.ArgumentParser(description='Run the generated Python application')
    parser.add_argument('--environment', default=os.environ.get('FABRIC_ENVIRONMENT', DEFAULT_ENVIRONMENT))
    parser.add_argument('--task', choices=list(TASKS), help='Run one task, including a Sub Task')
    parser.add_argument('--input', default='{}', help='JSON input for --task')
    parser.add_argument('--check', action='store_true', help='Validate target runtime dependencies without starting the application')
    parser.add_argument('--qualify-task', choices=list(TASKS), help='Run repeatable live-provider qualification against one task')
    parser.add_argument('--iterations', type=int, default=100)
    parser.add_argument('--concurrency', type=int, default=1)
    parser.add_argument('--duration-seconds', type=float, default=0)
    parser.add_argument('--max-error-rate', type=float, default=0)
    parser.add_argument('--max-p95-ms', type=float, default=0)
    parser.add_argument('--max-memory-growth-mb', type=float, default=0)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
    try:
        if args.check:
            report = check_runtime()
            print(json.dumps(report, indent=2, default=str))
            return 0 if report['ready'] else 2
        if args.qualify_task:
            payload = json.loads(args.input)
            report = asyncio.run(managed_run(qualify(lambda: run_task(args.qualify_task, payload, args.environment),
                iterations=args.iterations, concurrency=args.concurrency, duration_seconds=args.duration_seconds,
                max_error_rate=args.max_error_rate, max_p95_ms=args.max_p95_ms,
                max_memory_growth_mb=args.max_memory_growth_mb)))
            print(json.dumps(report, indent=2, default=str))
            return 0 if report['passed'] else 3
        if args.task:
            print(json.dumps(asyncio.run(managed_run(run_task(args.task, json.loads(args.input), args.environment))), default=str))
        else:
            asyncio.run(managed_run(run_application(args.environment)))
            # A one-shot starter is still a managed application when launched
            # by Control Plane. Notebook/CLI invocation returns immediately.
            if os.environ.get('FABRIC_DEPLOYMENT_ID'):
                asyncio.run(asyncio.Event().wait())
    except Exception:
        logging.exception('Python application failed')
        return 1
    finally:
        # CONNECTOR_CLOSE_START
        connectors.close_sap()
        connectors.close_jms()
        # CONNECTOR_CLOSE_END
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
