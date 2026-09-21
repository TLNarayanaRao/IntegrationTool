"""Raw Python application entry point; also importable in a notebook."""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import re
import ssl
import urllib.parse

from .config import DEFAULT_ENVIRONMENT, environment
from .core import Context, execute_with_policy, resolve
from . import connectors
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
    async def acknowledge_delivery(technology: str, listener_key: str, delivery_id: str, success: bool):
        if technology == 'sap':
            await asyncio.to_thread(connectors.acknowledge_sap, listener_key, delivery_id, success)
        else:
            connectors.acknowledge_jms(listener_key, delivery_id, success)
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
    async def serve_http(task_ids: list[str]):
        properties, resources = environment(environment_name)
        servers = []
        grouped: dict[tuple[str, int, bool, str, str], list[tuple[str, str, str, dict, str]]] = {}
        for task_id in task_ids:
            activity_id, kind, config, name = EVENT_STARTERS[task_id]
            resource = resources.get(str(config.get('resourceId') or ''))
            connection = resolve(resource.config, Context({}, properties, resources, environment_name=environment_name)) if resource else {}
            host, port = str(connection.get('host') or '0.0.0.0'), int(connection.get('port') or 8080)
            tls = str(connection.get('tlsEnabled', connection.get('scheme') == 'https')).lower() in {'true', '1', 'yes', 'on'}
            certificate, key = str(connection.get('certificateFile') or ''), str(connection.get('privateKeyFile') or '')
            grouped.setdefault((host, port, tls, certificate, key), []).append((task_id, activity_id, kind, config, name))
        for (host, port, tls, certificate, key), routes in grouped.items():
            compiled_routes = []
            for task_id, activity_id, kind, config, name in routes:
                path = str(config.get('path') or '/'); path = path if path.startswith('/') else '/' + path
                methods = config.get('methods') or config.get('method') or 'POST'
                methods = methods if isinstance(methods, list) else [item for item in str(methods).replace(' ', '').split(',') if item]
                parameter_names = re.findall(r'\{([^}/]+)\}', path)
                pattern = re.compile('^' + re.sub(r'\{[^}/]+\}', r'([^/]+)', path) + '$')
                compiled_routes.append(({str(method).upper() for method in methods}, pattern, parameter_names, task_id, activity_id, kind, config))
            async def client_connected(reader: asyncio.StreamReader, writer: asyncio.StreamWriter, compiled_routes=compiled_routes):
                try:
                    request_line = (await asyncio.wait_for(reader.readline(), timeout=30)).decode('iso-8859-1').strip()
                    parts = request_line.split()
                    if len(parts) != 3: raise ValueError('Malformed HTTP request line')
                    method, raw_target, _ = parts
                    headers, header_bytes = {}, 0
                    while True:
                        line = await asyncio.wait_for(reader.readline(), timeout=30); header_bytes += len(line)
                        if header_bytes > 65536: raise ValueError('HTTP headers exceed 64 KiB')
                        if line in {b'\r\n', b'\n', b''}: break
                        name, value = line.decode('iso-8859-1').split(':', 1); headers[name.strip()] = value.strip()
                    maximum = max(1024 ** 2, int(os.environ.get('FABRIC_HTTP_MAX_BODY_BYTES', 64 * 1024 ** 2)))
                    length = int(headers.get('Content-Length') or 0)
                    if length > maximum: raise OverflowError(f'HTTP payload exceeds {maximum} bytes')
                    raw_body = await asyncio.wait_for(reader.readexactly(length), timeout=300) if length else b''
                    target = urllib.parse.urlsplit(raw_target); route = None; match = None
                    for candidate in compiled_routes:
                        candidate_match = candidate[1].match(target.path)
                        if candidate_match and method.upper() in candidate[0]: route, match = candidate, candidate_match; break
                    if route is None:
                        status, value, response_headers = 404, {'error': 'No matching integration listener'}, {}
                    else:
                        _, _, parameter_names, task_id, activity_id, kind, config = route
                        text = raw_body.decode('utf-8', errors='replace')
                        try: body = json.loads(text) if 'json' in headers.get('Content-Type', '').lower() and text else text
                        except ValueError: body = text
                        event = {'body': body, 'headers': headers, 'query': dict(urllib.parse.parse_qsl(target.query, keep_blank_values=True)),
                                 'pathParameters': dict(zip(parameter_names, match.groups())), 'method': method.upper(),
                                 'path': target.path, 'remote': writer.get_extra_info('peername')}
                        if kind == 'soap': event['envelope'] = text; event['operation'] = config.get('operationName')
                        context = Context(event, properties, resources, environment_name=environment_name)
                        result = await TASKS[task_id](context, start_after=activity_id, event_output=event)
                        response = result if isinstance(result, dict) else {'body': result}
                        status, response_headers, value = int(response.get('statusCode') or 200), response.get('headers') or {}, response.get('body', response)
                    if isinstance(value, (dict, list)):
                        body_bytes, content_type = json.dumps(value, default=str).encode(), 'application/json'
                    else: body_bytes, content_type = ('' if value is None else str(value)).encode(), 'text/plain; charset=utf-8'
                    reasons = {200:'OK', 201:'Created', 202:'Accepted', 204:'No Content', 400:'Bad Request', 404:'Not Found', 413:'Payload Too Large', 500:'Internal Server Error'}
                    response_headers = {str(k): str(v) for k, v in response_headers.items()}
                    response_headers.setdefault('Content-Type', content_type); response_headers['Content-Length'] = str(len(body_bytes)); response_headers['Connection'] = 'close'
                    writer.write((f'HTTP/1.1 {status} {reasons.get(status, "OK")}\r\n' + ''.join(f'{k}: {v}\r\n' for k, v in response_headers.items()) + '\r\n').encode('iso-8859-1') + body_bytes)
                    await writer.drain()
                except OverflowError as error:
                    body = json.dumps({'error': str(error)}).encode(); writer.write(b'HTTP/1.1 413 Payload Too Large\r\nContent-Type: application/json\r\nConnection: close\r\nContent-Length: ' + str(len(body)).encode() + b'\r\n\r\n' + body)
                except Exception as error:
                    logging.exception('Inbound request failed'); body = json.dumps({'error': str(error)}).encode(); writer.write(b'HTTP/1.1 500 Internal Server Error\r\nContent-Type: application/json\r\nConnection: close\r\nContent-Length: ' + str(len(body)).encode() + b'\r\n\r\n' + body)
                finally:
                    try: await writer.drain()
                    except Exception: pass
                    writer.close(); await writer.wait_closed()
            ssl_context = None
            if tls:
                if not certificate or not key: raise RuntimeError(f'HTTPS listener {host}:{port} requires certificateFile and privateKeyFile')
                ssl_context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH); ssl_context.load_cert_chain(certificate, key)
            server = await asyncio.start_server(client_connected, host, port, ssl=ssl_context); servers.append(server)
            logging.info('Inbound integration listener ready on %s://%s:%s', 'https' if tls else 'http', host, port)
        try: await asyncio.Event().wait()
        finally:
            for server in servers: server.close()
            await asyncio.gather(*(server.wait_closed() for server in servers))
    http_ids = [task_id for task_id in ids if task_id in EVENT_STARTERS and EVENT_STARTERS[task_id][1] in {'http_listener', 'rest', 'soap'}]
    jobs = [receive_forever(task_id) if task_id in EVENT_STARTERS else run_task(task_id, environment_name=environment_name)
            for task_id in ids if task_id not in http_ids]
    if http_ids: jobs.append(serve_http(http_ids))
    return await asyncio.gather(*jobs)


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
            report = asyncio.run(qualify(lambda: run_task(args.qualify_task, payload, args.environment),
                iterations=args.iterations, concurrency=args.concurrency, duration_seconds=args.duration_seconds,
                max_error_rate=args.max_error_rate, max_p95_ms=args.max_p95_ms,
                max_memory_growth_mb=args.max_memory_growth_mb))
            print(json.dumps(report, indent=2, default=str))
            return 0 if report['passed'] else 3
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
    finally:
        connectors.close_sap()
        connectors.close_jms()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
