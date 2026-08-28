from __future__ import annotations
import asyncio, csv, ftplib, io, json, os, re, shutil, sqlite3, uuid
from datetime import datetime, timezone
from pathlib import Path
import httpx
from .models import Activity, ProcessDefinition, Project, RunResult
from .mapper import execute as execute_mapping
from .sap import sap_adapter

class RuntimeErrorWithLogs(Exception): pass

class WorkflowRuntime:
    def __init__(self):
        self.messages: dict[str, list[dict]] = {}

    async def run(self, process: ProcessDefinition, initial: dict, resources=None, properties=None, entry_activity_id=None, project: Project | None=None) -> RunResult:
        run_id, logs = str(uuid.uuid4()), []
        context = {'input': initial, 'vars': {}, 'last': initial, 'resources': resources or {}, 'properties': properties or {}, 'project': project, 'runtime': self, 'logs': logs}
        activity_by_id = {a.id: a for a in process.activities}
        incoming = {t.target for t in process.transitions}
        starts = [activity_by_id[entry_activity_id]] if entry_activity_id in activity_by_id else ([a for a in process.activities if a.type == 'start'] or [a for a in process.activities if a.id not in incoming])
        if len(starts) != 1:
            return RunResult(run_id=run_id, status='failed', output={}, logs=[{'level':'ERROR','message':'Process must have exactly one Start activity'}])
        current = starts[0]
        try:
            for _ in range(len(process.activities) + 1):
                self.log(logs, 'INFO', f'Executing {current.name}', current.id)
                error = None
                try: context['last'] = await self.execute_with_policy(current, context)
                except Exception as exc: error = exc
                outgoing = [t for t in process.transitions if t.source == current.id]
                if current.type in ('end', 'http_response'): break
                if error:
                    chosen = next((t for t in outgoing if t.type == 'error'), None)
                    if not chosen: raise error
                    context['last'] = {'error': str(error), 'activityId': current.id}
                else:
                    chosen = next((t for t in outgoing if t.type == 'success_condition' and self.condition(t.condition, context)), None)
                    chosen = chosen or next((t for t in outgoing if t.type == 'success'), None)
                    chosen = chosen or next((t for t in outgoing if t.type == 'success_no_match'), None)
                if not chosen: raise RuntimeErrorWithLogs(f'{current.name} has no matching outgoing transition')
                current = activity_by_id[chosen.target]
            return RunResult(run_id=run_id, status='completed', output=context['last'] if isinstance(context['last'], dict) else {'result': context['last']}, logs=logs)
        except Exception as exc:
            self.log(logs, 'ERROR', str(exc), current.id)
            return RunResult(run_id=run_id, status='failed', output={}, logs=logs)

    def log(self, logs, level, message, activity_id=None):
        logs.append({'time': datetime.now(timezone.utc).isoformat(), 'level': level, 'message': message, 'activityId': activity_id})

    async def execute_with_policy(self, activity: Activity, ctx: dict):
        policy = self.resolve(activity.config.get('errorPolicy', {}), ctx)
        advanced = self.resolve({
            'logPayload': '${properties.advanced.logPayload}',
            'retryEnabled': '${properties.advanced.retryEnabled}',
            'retryCount': '${properties.advanced.retryCount}',
            'retryIntervalSeconds': '${properties.advanced.retryIntervalSeconds}',
            **activity.config.get('advanced', {})
        }, ctx)
        log_payload = self.as_bool(advanced.get('logPayload', False))
        outbound_retry = self.is_outbound(activity) and self.as_bool(advanced.get('retryEnabled', False))
        legacy_retry = policy.get('action') == 'retry'
        advanced_count = advanced.get('retryCount')
        advanced_interval = advanced.get('retryIntervalSeconds')
        retry_count = int(3 if advanced_count in (None, '') else advanced_count) if outbound_retry else int(policy.get('retryCount', 0) or 0)
        attempts = retry_count + 1 if outbound_retry or legacy_retry else 1
        retry_delay = float(60 if advanced_interval in (None, '') else advanced_interval) if outbound_retry else float(policy.get('retryDelay', 0) or 0) / 1000
        if log_payload:
            self.log(ctx.setdefault('logs', []), 'INFO', f'{activity.name} input payload: {self.payload_text(ctx.get("last"))}', activity.id)
        for attempt in range(attempts):
            try:
                result = await self.execute(activity, ctx)
                if activity.config.get('outputName'): ctx['vars'][activity.config['outputName']] = result
                if log_payload:
                    self.log(ctx.setdefault('logs', []), 'INFO', f'{activity.name} output payload: {self.payload_text(result)}', activity.id)
                return result
            except Exception as exc:
                if attempt + 1 < attempts:
                    self.log(ctx.setdefault('logs', []), 'WARN', f'{activity.name} failed; retry {attempt + 1} of {retry_count} in {retry_delay:g} seconds: {exc}', activity.id)
                    if retry_delay: await asyncio.sleep(retry_delay)
                    continue
                fault = {'type': exc.__class__.__name__, 'description': str(exc), 'activityId': activity.id}
                if policy.get('includeInput', True): fault['input'] = ctx.get('last')
                if policy.get('outputVariable'): ctx['vars'][policy['outputVariable']] = fault
                if policy.get('action') == 'continue': return fault
                if policy.get('action') == 'ignore': return ctx.get('last')
                raise

    @staticmethod
    def as_bool(value):
        return value if isinstance(value, bool) else str(value).strip().lower() in ('true','1','yes','on')

    @staticmethod
    def payload_text(value):
        try: return json.dumps(value, ensure_ascii=False, default=str)
        except (TypeError, ValueError): return str(value)

    @staticmethod
    def is_outbound(activity: Activity) -> bool:
        operation = activity.config.get('operation', '')
        if activity.type in ('http','jdbc','ftp','sftp','ems','kafka','pubsub'): return True
        if activity.type == 'rest': return operation == 'invoke'
        if activity.type == 'soap': return operation == 'request_reply'
        if activity.type == 'sap': return operation not in ('idoc_listener','rfc_bapi_listener','idoc_converter','idoc_parser','idoc_renderer')
        return False

    async def execute(self, activity: Activity, ctx: dict):
        # Resolve environment, input, variable, and previous-output expressions in every activity field.
        cfg = self.resolve(activity.config, ctx)
        for key, expression in activity.config.get('inputMappings', {}).items():
            cfg[key] = self.resolve(expression, ctx)
        if activity.type in ('ftp','sftp','http','http_listener','http_response','rest','soap','sap') and cfg.get('resourceId'):
            shared = ctx['resources'].get(cfg['resourceId'])
            if not shared: raise RuntimeError(f'{activity.name} requires a valid shared connection')
            cfg = {**self.resolve(shared.config, ctx), **cfg}
            if activity.type in ('http','rest','soap') and cfg.get('baseUrl') and cfg.get('url','').startswith('/'):
                cfg['url'] = cfg['baseUrl'].rstrip('/') + cfg['url']
        if activity.type in ('start', 'end', 'timer'): return ctx['last']
        if activity.type in ('http_listener',) or (activity.type == 'rest' and cfg.get('operation') == 'receiver') or (activity.type == 'soap' and cfg.get('operation') == 'service'):
            return ctx['last']
        if activity.type == 'http_response':
            body = self.resolve(cfg.get('body', '${last}'), ctx)
            return {'__httpResponse': True, 'statusCode': int(cfg.get('statusCode', 200)), 'headers': cfg.get('headers', {}), 'body': body}
        if activity.type == 'log': return ctx['last']
        if activity.type == 'transform':
            source = cfg.get('source', ctx['last'])
            return execute_mapping(source, cfg.get('mappings', []))
        if activity.type == 'sap':
            resource = ctx['resources'].get(cfg.get('resourceId'))
            if not resource or resource.type != 'sap': raise RuntimeError('SAP activity requires an SAP ECC shared connection')
            sap_cfg = {**self.resolve(resource.config, ctx), **cfg}
            payload = cfg.get('payload', ctx['last'])
            return await asyncio.to_thread(sap_adapter.execute, cfg.get('operation','invoke_rfc_bapi'), sap_cfg, payload)
        if activity.type == 'http':
            method, url = cfg.get('method','GET'), self.resolve(cfg.get('url',''), ctx)
            async with httpx.AsyncClient(timeout=float(cfg.get('timeout', 30))) as client:
                response = await client.request(method, url, headers=self.resolve(cfg.get('headers', {}), ctx), json=self.resolve(cfg.get('body'), ctx) or None)
                response.raise_for_status()
                try: return response.json()
                except ValueError: return {'statusCode': response.status_code, 'body': response.text}
        if activity.type == 'rest' and cfg.get('operation') == 'invoke':
            async with httpx.AsyncClient(timeout=float(cfg.get('timeout', 30))) as client:
                response = await client.request(cfg.get('method', 'GET'), cfg.get('url', ''), headers=cfg.get('headers', {}), params=cfg.get('query', {}), json=cfg.get('body') if cfg.get('bodyType', 'json') == 'json' else None, content=cfg.get('body') if cfg.get('bodyType') != 'json' else None)
                response.raise_for_status()
                try: payload = response.json()
                except ValueError: payload = response.text
                return {'statusCode': response.status_code, 'headers': dict(response.headers), 'body': payload}
        if activity.type == 'soap' and cfg.get('operation') == 'request_reply':
            envelope = cfg.get('envelope') or ctx['last']
            if not isinstance(envelope, (str, bytes)): envelope = self.render_xml(envelope, cfg.get('rootElement', 'Request'))
            headers = {'Content-Type': cfg.get('contentType', 'text/xml; charset=utf-8'), **cfg.get('headers', {})}
            if cfg.get('soapAction'): headers['SOAPAction'] = cfg['soapAction']
            async with httpx.AsyncClient(timeout=float(cfg.get('timeout', 30))) as client:
                response = await client.post(cfg.get('url', ''), content=envelope, headers=headers)
                response.raise_for_status(); return {'statusCode': response.status_code, 'headers': dict(response.headers), 'body': response.text}
        if activity.type == 'file':
            path = Path(self.resolve(cfg.get('path',''), ctx)).expanduser()
            operation = cfg.get('operation','read')
            if operation == 'write':
                content = self.resolve(cfg.get('content', '${last}'), ctx)
                path.parent.mkdir(parents=True, exist_ok=True); path.write_text(content if isinstance(content, str) else json.dumps(content, indent=2)); return {'path': str(path), 'written': True}
            if operation == 'list': return {'files': [str(item) for item in path.glob(cfg.get('pattern', '*'))]}
            if operation == 'delete': path.unlink(); return {'path': str(path), 'deleted': True}
            if operation in ('rename', 'copy'):
                destination = Path(self.resolve(cfg.get('destination',''), ctx)).expanduser(); destination.parent.mkdir(parents=True, exist_ok=True)
                if operation == 'copy': shutil.copy2(path, destination)
                else: path.rename(destination)
                return {'source': str(path), 'destination': str(destination), 'operation': operation}
            if operation == 'poll':
                matches = list(path.glob(cfg.get('pattern', '*')))
                return {'files': [str(item) for item in matches], 'count': len(matches)}
            return {'path': str(path), 'content': path.read_text()}
        if activity.type == 'jdbc': return await asyncio.to_thread(self.jdbc, cfg, ctx)
        if activity.type == 'ftp': return await asyncio.to_thread(self.ftp, cfg, ctx)
        if activity.type == 'sftp': return await asyncio.to_thread(self.sftp, cfg, ctx)
        if activity.type == 'xml':
            if cfg.get('operation') == 'parse': return self.parse_xml(cfg.get('source', ctx['last']))
            return {'content': self.render_xml(cfg.get('source', ctx['last']), cfg.get('rootElement', 'root'), cfg.get('encoding', 'unicode'))}
        if activity.type == 'json':
            source = cfg.get('source', ctx['last'])
            if cfg.get('operation') == 'parse': return json.loads(source) if isinstance(source, (str, bytes)) else source
            return {'content': json.dumps(source, indent=int(cfg.get('indent', 2)), ensure_ascii=bool(cfg.get('asciiOnly', False)))}
        if activity.type == 'flat': return self.flat_data(cfg, ctx)
        if activity.type == 'call_task':
            project = ctx.get('project')
            if not project: raise RuntimeError('Call Sub Task requires project execution context')
            task_id = cfg.get('taskId') or cfg.get('dynamicTaskId')
            task = next((item for item in project.tasks if item.id == task_id), None)
            if not task or task.kind != 'subtask': raise RuntimeError(f'Sub Task {task_id!r} was not found')
            mapped = {key: self.resolve(value, ctx) for key, value in cfg.get('inputMappings', {}).items()} or (ctx['last'] if isinstance(ctx['last'], dict) else {'value': ctx['last']})
            invocation = self.run(task, mapped, ctx['resources'], ctx['properties'], project=project)
            if cfg.get('spawn'):
                asyncio.create_task(invocation)
                return {'spawned': True, 'taskId': task.id}
            result = await invocation
            if result.status == 'failed': raise RuntimeError(result.logs[-1]['message'] if result.logs else f'Sub Task {task.name} failed')
            return result.output
        if activity.type in ('ems', 'kafka', 'pubsub'):
            return await self.messaging(activity.type, cfg, ctx)
        if activity.type == 'java': return await self.java_worker(cfg, ctx['last'])
        raise RuntimeError(f'Unsupported activity type {activity.type}')

    async def messaging(self, technology: str, cfg: dict, ctx: dict):
        resource = ctx['resources'].get(cfg.get('resourceId'))
        if not resource or resource.type != technology:
            raise RuntimeError(f'{technology.upper()} activity requires a shared {technology.upper()} connection')
        rcfg = self.resolve(resource.config, ctx)
        operation = cfg.get('operation', 'publish')
        destination = cfg.get('queue') or cfg.get('topic') or cfg.get('subscription') or 'default'
        broker_key = f'{technology}:{resource.id}:{destination}'
        payload = self.resolve(cfg.get('message', '${last}'), ctx)
        envelope = {'id': str(uuid.uuid4()), 'data': payload, 'attributes': cfg.get('attributes', {}), 'destination': destination, 'technology': technology}
        receive_ops = {'receive', 'subscribe', 'get', 'queue_receiver', 'topic_subscriber'}
        if rcfg.get('mode', 'memory') == 'memory':
            queue = self.messages.setdefault(broker_key, [])
            if operation in receive_ops:
                maximum = int(cfg.get('maxMessages', 1))
                received, queue[:] = queue[:maximum], queue[maximum:]
                return {'messages': received, 'count': len(received), 'destination': destination}
            queue.append(envelope)
            return {'messageId': envelope['id'], 'destination': destination, 'published': True}
        if technology == 'kafka':
            try: from confluent_kafka import Consumer, Producer
            except ImportError: raise RuntimeError('External Kafka mode requires confluent-kafka')
            common = {'bootstrap.servers': rcfg['bootstrapServers'], **rcfg.get('clientProperties', {})}
            if operation in receive_ops:
                consumer = Consumer({**common, 'group.id': cfg.get('groupId', 'integration-fabric'), 'auto.offset.reset': cfg.get('offsetReset', 'earliest')}); consumer.subscribe([destination])
                messages = []
                for _ in range(int(cfg.get('maxMessages', 1))):
                    message = consumer.poll(float(cfg.get('timeout', 1)))
                    if message and not message.error(): messages.append({'data': message.value().decode(), 'partition': message.partition(), 'offset': message.offset()})
                consumer.close(); return {'messages': messages, 'count': len(messages)}
            producer = Producer(common); producer.produce(destination, json.dumps(payload).encode(), key=str(cfg.get('key', '')).encode() or None); producer.flush(); return envelope
        if technology == 'pubsub':
            try: from google.cloud import pubsub_v1
            except ImportError: raise RuntimeError('External Google Pub/Sub mode requires google-cloud-pubsub')
            project_id = rcfg['projectId']
            if operation in receive_ops:
                subscriber = pubsub_v1.SubscriberClient(); path = subscriber.subscription_path(project_id, destination); response = subscriber.pull(request={'subscription': path, 'max_messages': int(cfg.get('maxMessages', 1))}, timeout=float(cfg.get('timeout', 10)))
                messages = [{'data': item.message.data.decode(), 'attributes': dict(item.message.attributes), 'messageId': item.message.message_id} for item in response.received_messages]
                if cfg.get('acknowledge', True) and response.received_messages: subscriber.acknowledge(request={'subscription': path, 'ack_ids': [item.ack_id for item in response.received_messages]})
                return {'messages': messages, 'count': len(messages)}
            publisher = pubsub_v1.PublisherClient(); path = publisher.topic_path(project_id, destination); message_id = publisher.publish(path, json.dumps(payload).encode(), **{str(k):str(v) for k,v in cfg.get('attributes', {}).items()}).result(); return {**envelope, 'messageId': message_id}
        raise RuntimeError('External TIBCO EMS mode requires a configured EMS/JMS bridge; use memory mode for local design-time testing')

    def resolve(self, value, ctx):
        if isinstance(value, dict): return {key: self.resolve(item, ctx) for key, item in value.items()}
        if isinstance(value, list): return [self.resolve(item, ctx) for item in value]
        if value == '${last}': return ctx['last']
        if value == '${input}': return ctx['input']
        if value == '${properties}': return ctx['properties']
        if value == '${vars}': return ctx['vars']
        if isinstance(value, str) and value.startswith('${last.') and value.endswith('}'):
            current = ctx['last']
            for part in value[7:-1].split('.'): current = current.get(part, '') if isinstance(current, dict) else ''
            return current
        if isinstance(value, str) and value.startswith('${input.'):
            return ctx['input'].get(value[8:-1], '')
        if isinstance(value, str) and value.startswith('${vars.'):
            return ctx['vars'].get(value[7:-1], '')
        if isinstance(value, str) and value.startswith('${properties.') and value.endswith('}'):
            return ctx['properties'].get(value[13:-1], '')
        if isinstance(value, str) and '${properties.' in value:
            return re.sub(r'\$\{properties\.([^}]+)\}', lambda match: str(ctx['properties'].get(match.group(1), '')), value)
        return value

    def condition(self, expression, ctx):
        expression = str(expression or '').strip()
        def split_logical(value, keyword):
            depth = 0; quote = None; start = 0; parts = []; token = f' {keyword} '; index = 0
            while index < len(value):
                char = value[index]
                if quote:
                    if char == quote and (index == 0 or value[index-1] != '\\'): quote = None
                elif char in ('"', "'"): quote = char
                elif char == '(': depth += 1
                elif char == ')': depth = max(0, depth - 1)
                elif depth == 0 and value[index:index+len(token)].lower() == token:
                    parts.append(value[start:index].strip()); start = index + len(token); index = start - 1
                index += 1
            if parts: parts.append(value[start:].strip())
            return parts
        for keyword, evaluator in (('or', any), ('and', all)):
            parts = split_logical(expression, keyword)
            if parts: return evaluator(self.condition(part, ctx) for part in parts)
        if expression.lower().startswith('not(') and expression.endswith(')'): return not self.condition(expression[4:-1], ctx)
        function = re.fullmatch(r'(exists|empty|contains|startsWith|endsWith|matches)\((.*)\)', expression, re.I)
        if function:
            raw = function.group(2); args = []; depth = 0; quote = None; start = 0
            for index, char in enumerate(raw):
                if quote:
                    if char == quote and (index == 0 or raw[index-1] != '\\'): quote = None
                elif char in ('"', "'"): quote = char
                elif char == '(': depth += 1
                elif char == ')': depth = max(0, depth - 1)
                elif char == ',' and depth == 0: args.append(raw[start:index].strip()); start = index + 1
            args.append(raw[start:].strip())
            def value(arg):
                if len(arg) >= 2 and arg[0] == arg[-1] and arg[0] in ('"', "'"): return arg[1:-1]
                if re.fullmatch(r'-?\d+(\.\d+)?', arg): return float(arg) if '.' in arg else int(arg)
                return self.resolve(arg, ctx)
            values = [value(arg) for arg in args]
            name = function.group(1).lower()
            if name == 'exists': return bool(values and values[0] is not None and values[0] != '')
            if name == 'empty': return not values or values[0] is None or values[0] == '' or values[0] == [] or values[0] == {}
            if len(values) < 2: return False
            left, right = str(values[0]), str(values[1])
            if name == 'contains': return right in left
            if name == 'startswith': return left.startswith(right)
            if name == 'endswith': return left.endswith(right)
            if name == 'matches': return re.search(right, left) is not None
        for operator in ('==', '!=', '>=', '<=', '>', '<'):
            if operator in expression:
                left, right = (part.strip() for part in expression.split(operator, 1))
                def comparison_value(raw):
                    if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in ('"', "'"):
                        return raw[1:-1]
                    if re.fullmatch(r'-?\d+(\.\d+)?', raw):
                        return float(raw) if '.' in raw else int(raw)
                    return self.resolve(raw, ctx)
                left, right = comparison_value(left), comparison_value(right)
                try:
                    if operator == '==': return left == right or str(left) == str(right)
                    if operator == '!=': return left != right and str(left) != str(right)
                    if operator == '>=': return left >= right
                    if operator == '<=': return left <= right
                    if operator == '>': return left > right
                    if operator == '<': return left < right
                except TypeError: return False
        if expression.lower() in ('true', 'false'): return expression.lower() == 'true'
        return bool(self.resolve(expression, ctx))

    def jdbc(self, cfg, ctx):
        resource = ctx['resources'].get(cfg.get('resourceId'))
        if not resource: raise RuntimeError('JDBC activity requires a valid shared JDBC resource')
        rcfg, operation = self.resolve(resource.config, ctx), cfg.get('operation', 'query')
        if rcfg.get('driver', 'sqlite') != 'sqlite':
            raise RuntimeError(f"Driver {rcfg.get('driver')} requires its optional Python database adapter")
        conn = sqlite3.connect(self.resolve(rcfg.get('url', 'integration.db'), ctx)); conn.row_factory = sqlite3.Row
        try:
            parameters = {name: self.resolve(expression, ctx) for name, expression in cfg.get('parameters', {}).items()}
            sql = self.resolve(cfg.get('sql', ''), ctx)
            if operation == 'truncate':
                if sql.strip().lower().startswith('truncate '): sql = 'DELETE FROM ' + sql.strip().split()[-1]
            if operation == 'call': raise RuntimeError('Stored procedures are not supported by SQLite; select a server JDBC driver')
            cursor = conn.execute(sql, parameters)
            if operation in ('query', 'dynamic') and cursor.description:
                return {'rows': [dict(row) for row in cursor.fetchall()], 'rowCount': cursor.rowcount}
            conn.commit(); return {'rowCount': cursor.rowcount, 'lastInsertId': cursor.lastrowid}
        finally: conn.close()

    def ftp(self, cfg, ctx):
        client_class = ftplib.FTP_TLS if cfg.get('tls') else ftplib.FTP
        client = client_class(); client.connect(cfg['host'], int(cfg.get('port', 21)), timeout=float(cfg.get('timeout', 30))); client.login(cfg.get('username', 'anonymous'), cfg.get('password', ''))
        if cfg.get('tls'): client.prot_p()
        try:
            if cfg.get('workingDirectory'): client.cwd(cfg['workingDirectory'])
            operation, remote = cfg.get('operation'), cfg.get('remotePath', '')
            if operation == 'get':
                buffer = io.BytesIO(); client.retrbinary(f'RETR {remote}', buffer.write); return {'remotePath': remote, 'contentBase64': __import__('base64').b64encode(buffer.getvalue()).decode(), 'size': buffer.tell()}
            if operation == 'put':
                content = cfg.get('content', ctx['last']); raw = content if isinstance(content, bytes) else (content.encode(cfg.get('encoding', 'utf-8')) if isinstance(content, str) else json.dumps(content).encode()); client.storbinary(f'STOR {remote}', io.BytesIO(raw)); return {'remotePath': remote, 'written': True, 'size': len(raw)}
            if operation == 'delete': client.delete(remote); return {'remotePath': remote, 'deleted': True}
            if operation == 'dir': return {'directory': client.pwd(), 'entries': client.nlst(remote) if remote else client.nlst()}
            if operation == 'change_dir': client.cwd(remote); return {'directory': client.pwd()}
            raise RuntimeError(f'Unsupported FTP operation {operation}')
        finally:
            try: client.quit()
            except Exception: client.close()

    def sftp(self, cfg, ctx):
        try: import paramiko
        except ImportError: raise RuntimeError('SFTP activities require the optional paramiko package')
        ssh = paramiko.SSHClient(); ssh.load_system_host_keys()
        if cfg.get('knownHostsFile'): ssh.load_host_keys(cfg['knownHostsFile'])
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy() if cfg.get('allowUnknownHostKey') else paramiko.RejectPolicy())
        ssh.connect(cfg['host'], port=int(cfg.get('port', 22)), username=cfg.get('username'), password=cfg.get('password') or None, key_filename=cfg.get('privateKeyFile') or None, timeout=float(cfg.get('timeout', 30)), allow_agent=bool(cfg.get('useSshAgent', False)), look_for_keys=bool(cfg.get('useSshAgent', False)))
        client = ssh.open_sftp()
        try:
            if cfg.get('workingDirectory'): client.chdir(cfg['workingDirectory'])
            operation, remote = cfg.get('operation'), cfg.get('remotePath', '')
            if operation == 'get':
                buffer = io.BytesIO(); client.getfo(remote, buffer); return {'remotePath': remote, 'contentBase64': __import__('base64').b64encode(buffer.getvalue()).decode(), 'size': buffer.tell()}
            if operation == 'put':
                content = cfg.get('content', ctx['last']); raw = content if isinstance(content, bytes) else (content.encode(cfg.get('encoding', 'utf-8')) if isinstance(content, str) else json.dumps(content).encode()); client.putfo(io.BytesIO(raw), remote); return {'remotePath': remote, 'written': True, 'size': len(raw)}
            if operation == 'delete': client.remove(remote); return {'remotePath': remote, 'deleted': True}
            if operation == 'dir': return {'directory': client.getcwd() or '.', 'entries': [{'name': item.filename, 'size': item.st_size, 'modified': item.st_mtime} for item in client.listdir_attr(remote or '.')]}
            if operation == 'change_dir': client.chdir(remote); return {'directory': client.getcwd()}
            raise RuntimeError(f'Unsupported SFTP operation {operation}')
        finally: client.close(); ssh.close()

    def parse_xml(self, source):
        from xml.etree import ElementTree
        if isinstance(source, dict): source = source.get('content') or source.get('body') or ''
        root = ElementTree.fromstring(source)
        def convert(element):
            children = list(element); result = {'@' + key: value for key, value in element.attrib.items()}
            if not children: return element.text or result
            for child in children:
                value = convert(child)
                if child.tag in result: result[child.tag] = result[child.tag] if isinstance(result[child.tag], list) else [result[child.tag]]; result[child.tag].append(value)
                else: result[child.tag] = value
            if element.text and element.text.strip(): result['#text'] = element.text.strip()
            return result
        return {'root': root.tag, 'value': convert(root)}

    def render_xml(self, source, root_name='root', encoding='unicode'):
        from xml.etree import ElementTree
        if isinstance(source, dict) and 'root' in source and 'value' in source: root_name, source = source['root'], source['value']
        def build(name, value):
            element = ElementTree.Element(name)
            if isinstance(value, dict):
                for key, item in value.items():
                    if key.startswith('@'): element.set(key[1:], str(item))
                    elif key == '#text': element.text = str(item)
                    elif isinstance(item, list):
                        for entry in item: element.append(build(key, entry))
                    else: element.append(build(key, item))
            elif value is not None: element.text = str(value)
            return element
        return ElementTree.tostring(build(root_name, source), encoding=encoding).decode() if encoding != 'unicode' else ElementTree.tostring(build(root_name, source), encoding='unicode')

    def flat_data(self, cfg, ctx):
        source, delimiter = cfg.get('source', ctx['last']), cfg.get('delimiter', ',')
        fields = [item.strip() for item in cfg.get('fields', '').split(',') if item.strip()]
        if cfg.get('format', 'delimited') == 'fixed':
            widths = [int(item.strip()) for item in cfg.get('widths', '').split(',') if item.strip()]
            if not fields or len(fields) != len(widths): raise RuntimeError('Fixed-width data requires matching field names and widths')
            if cfg.get('operation') == 'parse':
                records = []
                for line in str(source).splitlines():
                    offset, record = 0, {}
                    for name, width in zip(fields, widths): record[name], offset = line[offset:offset + width].rstrip(), offset + width
                    records.append(record)
                return {'records': records}
            records = source.get('records', source) if isinstance(source, dict) else source
            if not isinstance(records, list): records = [records]
            content = cfg.get('lineEnding', '\n').join(''.join(str(record.get(name, ''))[:width].ljust(width) for name, width in zip(fields, widths)) for record in records)
            return {'content': content, 'recordCount': len(records)}
        if cfg.get('operation') == 'parse':
            reader = csv.DictReader(io.StringIO(source), delimiter=delimiter) if cfg.get('header', True) else csv.DictReader(io.StringIO(source), fieldnames=fields, delimiter=delimiter)
            return {'records': list(reader)}
        records = source.get('records', source) if isinstance(source, dict) else source
        if not isinstance(records, list): records = [records]
        names = fields or list(records[0].keys() if records else []); output = io.StringIO(); writer = csv.DictWriter(output, fieldnames=names, delimiter=delimiter, lineterminator=cfg.get('lineEnding', '\n'))
        if cfg.get('header', True): writer.writeheader()
        writer.writerows(records); return {'content': output.getvalue(), 'recordCount': len(records)}

    async def java_worker(self, cfg, payload):
        command = cfg.get('command') or os.getenv('JAVA_WORKER_COMMAND')
        if not command: raise RuntimeError('Java activity requires a configured command or JAVA_WORKER_COMMAND')
        proc = await asyncio.create_subprocess_shell(command, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        out, err = await proc.communicate(json.dumps({'className': cfg.get('className'), 'payload': payload}).encode())
        if proc.returncode: raise RuntimeError(err.decode() or 'Java worker failed')
        return json.loads(out.decode())
