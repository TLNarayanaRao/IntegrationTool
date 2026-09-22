"""Inbound HTTP, REST, and SOAP hosting, included only when the project needs it."""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import ssl
import urllib.parse

from .config import environment
from .core import Context, resolve
from .registry import EVENT_STARTERS, TASKS


async def serve_http(task_ids: list[str], environment_name: str):
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
