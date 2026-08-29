from __future__ import annotations
import asyncio, base64, csv, ftplib, gzip, io, json, os, re, shutil, sqlite3, uuid
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
        self.acknowledgements: dict[str, dict] = {}

    def register_acknowledgement(self, technology: str, message_id: str, callback=None) -> str:
        ack_id = f'{technology}:{message_id}:{uuid.uuid4()}'
        self.acknowledgements[ack_id] = {'technology': technology, 'messageId': message_id, 'callback': callback, 'created': datetime.now(timezone.utc).isoformat()}
        return ack_id

    async def confirm_messages(self, handles) -> dict:
        handles = handles if isinstance(handles, list) else [handles]
        confirmed, technologies = [], []
        for handle in [item for item in handles if item]:
            pending = self.acknowledgements.pop(str(handle), None)
            if not pending: raise RuntimeError(f'Acknowledgement handle {handle!r} was not found or was already confirmed')
            callback = pending.get('callback')
            if callback:
                result = callback()
                if asyncio.iscoroutine(result): await result
            confirmed.append(str(handle)); technologies.append(pending['technology'])
        return {'confirmed': True, 'count': len(confirmed), 'ackIds': confirmed, 'technologies': sorted(set(technologies))}

    async def run(self, process: ProcessDefinition, initial: dict, resources=None, properties=None, entry_activity_id=None, project: Project | None=None, execution_state: dict | None=None) -> RunResult:
        run_id, logs = str(uuid.uuid4()), []
        execution_state = execution_state or {'activities': {}, 'tasks': {}}
        activity_outputs = execution_state.setdefault('activities', {})
        task_outputs = execution_state.setdefault('tasks', {})
        task_state = task_outputs.setdefault(process.id, {'name': process.name, 'activities': {}})
        context = {
            'input': initial, 'vars': {}, 'last': initial, 'resources': resources or {},
            'properties': properties or {}, 'project': project, 'runtime': self, 'logs': logs,
            'activities': activity_outputs, 'tasks': task_outputs,
            'context': {'taskId': process.id, 'activityId': '', 'environment': getattr(project, 'active_environment', '') if project else ''},
        }
        activity_by_id = {a.id: a for a in process.activities}
        incoming = {t.target for t in process.transitions}
        starts = [activity_by_id[entry_activity_id]] if entry_activity_id in activity_by_id else ([a for a in process.activities if a.type == 'start'] or [a for a in process.activities if a.id not in incoming])
        if len(starts) != 1:
            return RunResult(run_id=run_id, status='failed', output={}, logs=[{'level':'ERROR','message':'Process must have exactly one Start activity'}])
        current = starts[0]
        try:
            for _ in range(len(process.activities) + 1):
                self.log(logs, 'DEBUG', f'Executing {current.name}', current.id)
                context['context']['activityId'] = current.id
                error = None
                try:
                    context['last'] = await self.execute_with_policy(current, context)
                    self.record_activity_output(current, context['last'], context)
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
            final_output = context['last'] if isinstance(context['last'], dict) else {'result': context['last']}
            task_state['output'] = final_output
            return RunResult(run_id=run_id, status='completed', output=final_output, logs=logs, activity_outputs=activity_outputs, task_outputs=task_outputs)
        except Exception as exc:
            self.log(logs, 'ERROR', str(exc), current.id)
            task_state['error'] = {'message': str(exc), 'activityId': current.id}
            return RunResult(run_id=run_id, status='failed', output={}, logs=logs, activity_outputs=activity_outputs, task_outputs=task_outputs)

    @staticmethod
    def record_activity_output(activity: Activity, result, ctx: dict):
        """Retain every executed activity result for downstream mappings and debugging."""
        record = {'activityId': activity.id, 'name': activity.name, 'type': activity.type, 'output': result}
        record.update(ctx.pop('_activityMetadata', {}))
        ctx.setdefault('activities', {})[activity.id] = record
        task_id = ctx.get('context', {}).get('taskId')
        if task_id:
            task = ctx.setdefault('tasks', {}).setdefault(task_id, {'activities': {}})
            task.setdefault('activities', {})[activity.id] = record

    def log(self, logs, level, message, activity_id=None, **details):
        logs.append({'time': datetime.now(timezone.utc).isoformat(), 'level': level, 'message': message, 'activityId': activity_id, **details})

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
            self.assign_path(cfg, key, self.resolve(expression, ctx))
        if activity.type in ('ftp','sftp','http','http_listener','http_response','rest','soap','sap') and cfg.get('resourceId'):
            shared = ctx['resources'].get(cfg['resourceId'])
            if not shared: raise RuntimeError(f'{activity.name} requires a valid shared connection')
            cfg = {**self.resolve(shared.config, ctx), **cfg}
            if activity.type in ('http','rest','soap') and cfg.get('baseUrl') and cfg.get('url','').startswith('/'):
                cfg['url'] = cfg['baseUrl'].rstrip('/') + cfg['url']
        if activity.type == 'start':
            mapped = self.map_input_values(activity.config.get('inputMappings', {}), ctx)
            return self.unwrap_boundary(mapped, 'payload', ctx['input'])
        if activity.type == 'end':
            mapped = self.map_input_values(activity.config.get('inputMappings', {}), ctx)
            return self.unwrap_boundary(mapped, 'result', ctx['last'])
        if activity.type == 'timer': return ctx['last']
        if activity.type in ('http_listener',) or (activity.type == 'rest' and cfg.get('operation') == 'receiver') or (activity.type == 'soap' and cfg.get('operation') == 'service'):
            return ctx['last']
        if activity.type == 'http_response':
            body = self.resolve(cfg.get('body', '${last}'), ctx)
            return {'__httpResponse': True, 'statusCode': int(cfg.get('statusCode', 200)), 'headers': cfg.get('headers', {}), 'body': body}
        if activity.type == 'log':
            level = str(cfg.get('level') or 'INFO').upper()
            if level not in ('DEBUG', 'INFO', 'WARN', 'ERROR'): level = 'INFO'
            message = cfg.get('message')
            if message in (None, ''): message = f'{activity.name} payload'
            if not isinstance(message, str): message = self.payload_text(message)
            payload = cfg.get('payload', ctx['last'])
            include_payload = self.as_bool(cfg.get('includePayload', False)) or 'payload' in activity.config.get('inputMappings', {})
            event = {'level': level, 'message': message, 'activityId': activity.id, 'activityName': activity.name}
            if include_payload: event['payload'] = payload
            self.log(ctx.setdefault('logs', []), level, message, activity.id, activityName=activity.name, **({'payload': payload} if include_payload else {}))
            ctx['_activityMetadata'] = {'logEvent': event}
            return ctx['last']
        if activity.type == 'confirm':
            previous = ctx['last'] if isinstance(ctx['last'], dict) else {}
            handles = cfg.get('ackIds') or cfg.get('ackId') or previous.get('ackIds') or previous.get('ackId') or previous.get('AckID')
            if not handles:
                if self.as_bool(cfg.get('failIfMissing', True)):
                    raise RuntimeError('Confirm Message requires an acknowledgement handle from a client/manual receiver')
                return {'confirmed': False, 'count': 0, 'ackIds': [], 'technologies': []}
            return await self.confirm_messages(handles)
        if activity.type == 'transform':
            source = cfg.get('source', ctx['last'])
            rules = []
            for rule in activity.config.get('mappings', []) or []:
                normalized = {**rule}
                if 'constant' in rule:
                    normalized['constant'] = rule['constant']
                elif isinstance(rule.get('source'), str) and rule['source'].startswith('${'):
                    normalized.pop('source', None)
                    normalized['constant'] = self.resolve(rule['source'], ctx)
                rules.append(normalized)
            return execute_mapping(source, rules)
        if activity.type == 'sap':
            resource = ctx['resources'].get(cfg.get('resourceId'))
            if not resource or resource.type != 'sap': raise RuntimeError('SAP activity requires an SAP ECC shared connection')
            sap_cfg = {**self.resolve(resource.config, ctx), **cfg}
            selected_idoc = next((item for item in sap_cfg.get('idocCatalog', []) if item.get('idocType') == sap_cfg.get('idocType')), None) or sap_cfg.get('selectedIdoc')
            if selected_idoc:
                sap_cfg = {**sap_cfg, 'selectedIdoc': selected_idoc, 'idocType': sap_cfg.get('idocType') or selected_idoc.get('idocType'), 'extensionType': sap_cfg.get('extensionType') or selected_idoc.get('extensionType',''), 'release': sap_cfg.get('release') or selected_idoc.get('release',''), 'idocSchema': selected_idoc.get('schema')}
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
            def file_info(item: Path):
                stat = item.stat()
                return {'fullName':str(item.resolve()), 'fileName':item.name, 'location':str(item.parent.resolve()), 'configuredFileName':str(path), 'type':'directory' if item.is_dir() else 'file', 'readProtected':not os.access(item, os.R_OK), 'writeProtected':not os.access(item, os.W_OK), 'size':stat.st_size, 'lastModified':datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat()}
            if operation == 'write':
                if path.exists() and not self.as_bool(cfg.get('overwrite', False)) and not self.as_bool(cfg.get('append', False)): raise FileExistsError(f'{path} already exists')
                if self.as_bool(cfg.get('createDirectories', True)): path.parent.mkdir(parents=True, exist_ok=True)
                binary = str(cfg.get('writeAs', 'Text')).lower() == 'binary' or cfg.get('binaryContent') not in (None, '')
                content = cfg.get('binaryContent') if binary else cfg.get('textContent', cfg.get('content', ctx['last']))
                if binary:
                    raw = base64.b64decode(content) if isinstance(content, str) else bytes(content)
                    if str(cfg.get('compression', 'None')).lower() == 'gzip': raw = gzip.compress(raw)
                    with path.open('ab' if self.as_bool(cfg.get('append', False)) else 'wb') as stream: stream.write(raw)
                else:
                    text = content if isinstance(content, str) else json.dumps(content, indent=2)
                    if self.as_bool(cfg.get('addLineSeparator', False)): text += os.linesep
                    if str(cfg.get('compression', 'None')).lower() == 'gzip':
                        with gzip.open(path, 'at' if self.as_bool(cfg.get('append', False)) else 'wt', encoding=cfg.get('encoding') or 'utf-8') as stream: stream.write(text)
                    else:
                        with path.open('a' if self.as_bool(cfg.get('append', False)) else 'w', encoding=cfg.get('encoding') or 'utf-8') as stream: stream.write(text)
                return {'path': str(path), 'written': True, 'success': True, 'fileInfo': file_info(path)}
            if operation == 'list':
                pattern = cfg.get('pattern', '*'); matches = list(path.rglob(pattern) if self.as_bool(cfg.get('recursive', False)) else path.glob(pattern))
                list_type = str(cfg.get('listType', 'Files and Directories')).lower()
                if list_type == 'only files': matches = [item for item in matches if item.is_file()]
                if list_type == 'only directories': matches = [item for item in matches if item.is_dir()]
                sort_by = str(cfg.get('sortBy', 'Name')).lower(); key = (lambda item: item.stat().st_size) if sort_by == 'size' else ((lambda item: item.stat().st_mtime) if sort_by == 'last modified' else (lambda item: item.name.lower()))
                matches.sort(key=key, reverse=str(cfg.get('sortOrder', 'Ascending')).lower() == 'descending')
                return {'files': [file_info(item) for item in matches], 'count':len(matches)}
            if operation == 'delete':
                if not path.exists() and self.as_bool(cfg.get('ignoreMissing', False)): return {'path':str(path), 'deleted':False, 'success':True}
                if path.is_dir(): shutil.rmtree(path) if self.as_bool(cfg.get('recursive', False)) else path.rmdir()
                else: path.unlink()
                return {'path': str(path), 'deleted': True, 'success': True}
            if operation in ('rename', 'copy'):
                destination = Path(self.resolve(cfg.get('destination',''), ctx)).expanduser()
                if self.as_bool(cfg.get('createDirectories', False)): destination.parent.mkdir(parents=True, exist_ok=True)
                if destination.exists() and not self.as_bool(cfg.get('overwrite', False)): raise FileExistsError(f'{destination} already exists')
                if destination.exists() and self.as_bool(cfg.get('overwrite', False)):
                    shutil.rmtree(destination) if destination.is_dir() else destination.unlink()
                if operation == 'copy':
                    if path.is_dir(): shutil.copytree(path, destination, copy_function=shutil.copy2 if self.as_bool(cfg.get('preserveAttributes', True)) else shutil.copy)
                    else: (shutil.copy2 if self.as_bool(cfg.get('preserveAttributes', True)) else shutil.copy)(path, destination)
                else: path.rename(destination)
                return {'source': str(path), 'destination': str(destination), 'path':str(destination), 'operation': operation, 'success':True, 'fileInfo':file_info(destination)}
            if operation == 'poll':
                matches = list(path.rglob(cfg.get('pattern', '*')) if self.as_bool(cfg.get('recursive', False)) else path.glob(cfg.get('pattern', '*')))
                return {'files': [file_info(item) for item in matches], 'count': len(matches), 'eventType':cfg.get('eventType', 'Created')}
            info = file_info(path)
            if self.as_bool(cfg.get('excludeFileContent', False)): return {'path':str(path), 'fileInfo':info, **info}
            if str(cfg.get('readAs', 'Text')).lower() == 'binary': return {'path':str(path), 'binaryContent':base64.b64encode(path.read_bytes()).decode(), 'content':None, 'fileInfo':info, **info}
            content = path.read_text(encoding=cfg.get('encoding') or 'utf-8')
            return {'path': str(path), 'content': content, 'textContent':content, 'fileInfo':info, **info}
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
            task_id = cfg.get('dynamicTaskId') or cfg.get('taskId')
            task = next((item for item in project.tasks if item.id == task_id), None)
            if not task or task.kind != 'subtask': raise RuntimeError(f'Sub Task {task_id!r} was not found')
            mapped_values = self.map_input_values(activity.config.get('inputMappings', {}), ctx)
            mapped = self.unwrap_boundary(mapped_values, 'payload', ctx['last'] if isinstance(ctx['last'], dict) else {'value':ctx['last']})
            execution_state = {'activities': ctx.setdefault('activities', {}), 'tasks': ctx.setdefault('tasks', {})}
            invocation = self.run(task, mapped, ctx['resources'], ctx['properties'], project=project, execution_state=execution_state)
            if cfg.get('spawn'):
                asyncio.create_task(invocation)
                return {'spawned': True, 'taskId': task.id}
            result = await invocation
            ctx.setdefault('logs', []).extend(result.logs)
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
        payload = self.resolve(cfg.get('data', cfg.get('message', '${last}')), ctx)
        def mapping(value):
            if isinstance(value, dict): return value
            if isinstance(value, str) and value.strip():
                try: return json.loads(value)
                except ValueError: return {}
            return {}
        attributes = {str(key): str(value) for key, value in {**mapping(cfg.get('dynamicProperties')), **mapping(cfg.get('attributes')), **mapping(cfg.get('headers'))}.items()}
        envelope = {'id': str(uuid.uuid4()), 'data': payload, 'attributes': attributes, 'destination': destination, 'technology': technology, 'timestamp': datetime.now(timezone.utc).isoformat(), 'key': cfg.get('key')}
        receive_ops = {'receive', 'subscribe', 'get', 'queue_receiver', 'topic_subscriber'}
        client_ack = str(cfg.get('acknowledgeMode', '')).lower() in ('client', 'manual', 'explicit client', 'explicit client dups ok') or cfg.get('acknowledge') is False
        if rcfg.get('mode', 'memory') == 'memory':
            queue = self.messages.setdefault(broker_key, [])
            if operation in receive_ops:
                maximum = int(cfg.get('maxMessages', 1))
                received, queue[:] = queue[:maximum], queue[maximum:]
                for item in received:
                    if client_ack: item['ackId'] = self.register_acknowledgement(technology, item['id'])
                if technology == 'ems':
                    first = received[0] if received else {}
                    return {'body': first.get('data'), 'headers': {'JMSMessageID': first.get('id'), 'JMSTimestamp': first.get('timestamp'), 'JMSCorrelationID': first.get('correlationId')}, 'properties': first.get('attributes', {}), 'ackId': first.get('ackId'), 'messages': received, 'count': len(received)}
                if technology == 'pubsub':
                    first = received[0] if received else {}
                    return {'MessageID': first.get('id'), 'PublishTime': first.get('timestamp'), 'Data': first.get('data'), 'Attributes': first.get('attributes', {}), 'AckID': first.get('ackId'), 'ackId': first.get('ackId'), 'messages': received, 'count': len(received)}
                return {'messages': received, 'count': len(received), 'destination': destination, 'ackId': received[0].get('ackId') if received else None, 'ackIds': [item['ackId'] for item in received if item.get('ackId')]}
            queue.append(envelope)
            if technology == 'pubsub': return {'TopicName': destination, 'MessageID': envelope['id'], 'messageId': envelope['id'], 'published': True}
            if technology == 'ems': return {'messageId': envelope['id'], 'destination': destination, 'timestamp': envelope['timestamp'], 'published': True}
            return {'messageId': envelope['id'], 'topic': destination, 'partition': int(cfg.get('partitionId', 0) or 0), 'offset': len(queue)-1, 'timestamp': envelope['timestamp'], 'published': True}
        if technology == 'ems':
            try: import stomp
            except ImportError: raise RuntimeError('External TIBCO EMS/JMS mode requires the optional stomp.py package and an enabled EMS STOMP service')
            host, port = rcfg.get('host', 'localhost'), int(rcfg.get('port', 7222)); connection = stomp.Connection12([(host, port)], heartbeats=(int(rcfg.get('heartbeatOutgoingMs', 0) or 0), int(rcfg.get('heartbeatIncomingMs', 0) or 0)))
            connection.connect(rcfg.get('username', ''), rcfg.get('password', ''), wait=True, headers={'client-id': rcfg.get('clientId', '')} if rcfg.get('clientId') else {})
            target = destination if str(destination).startswith('/') else f"/{'topic' if 'topic' in operation else 'queue'}/{destination}"
            if operation in receive_ops:
                import queue as queue_module
                received_queue = queue_module.Queue()
                class Listener(stomp.ConnectionListener):
                    def on_message(self, frame): received_queue.put(frame)
                    def on_error(self, frame): received_queue.put(RuntimeError(frame.body))
                subscription_id = f'integration-fabric-{uuid.uuid4()}'
                connection.set_listener(subscription_id, Listener()); connection.subscribe(target, id=subscription_id, ack='client-individual' if client_ack else 'auto', headers={'selector': cfg.get('messageSelector', '')} if cfg.get('messageSelector') else {})
                frame = await asyncio.to_thread(received_queue.get, True, float(cfg.get('receiveTimeout', 30000) or 30000) / 1000)
                if isinstance(frame, Exception): connection.disconnect(); raise frame
                message_id = frame.headers.get('message-id') or str(uuid.uuid4())
                ack_id = None
                if client_ack:
                    ack_id = self.register_acknowledgement('ems', message_id, lambda: (connection.ack(message_id, subscription_id), connection.disconnect()))
                else: connection.disconnect()
                try: body = json.loads(frame.body)
                except (ValueError, TypeError): body = frame.body
                return {'body': body, 'headers': frame.headers, 'properties': {k:v for k,v in frame.headers.items() if not k.startswith('JMS')}, 'ackId': ack_id, 'messages': [{'id':message_id,'data':body,'attributes':frame.headers,'ackId':ack_id}], 'count': 1}
            headers = {**attributes, 'persistent': 'true' if str(cfg.get('deliveryMode','Persistent')).lower() == 'persistent' else 'false', 'priority': str(cfg.get('priority', 4)), 'correlation-id': str(cfg.get('correlationId',''))}
            body = payload if isinstance(payload, str) else json.dumps(payload)
            connection.send(target, body=body, headers=headers); connection.disconnect()
            return {'messageId': envelope['id'], 'destination': destination, 'timestamp': envelope['timestamp'], 'published': True}
        if technology == 'kafka':
            try: from confluent_kafka import Consumer, Producer
            except ImportError: raise RuntimeError('External Kafka mode requires confluent-kafka')
            common = {'bootstrap.servers': rcfg['bootstrapServers'], 'client.id': rcfg.get('clientId', 'integration-fabric'), **mapping(rcfg.get('clientProperties'))}
            if rcfg.get('securityProtocol'): common['security.protocol'] = rcfg['securityProtocol']
            if rcfg.get('saslMechanism'): common['sasl.mechanism'] = rcfg['saslMechanism']
            if rcfg.get('username'): common['sasl.username'] = rcfg['username']
            if rcfg.get('password'): common['sasl.password'] = rcfg['password']
            if operation in receive_ops:
                consumer_cfg = {**common, 'group.id': cfg.get('groupId') or rcfg.get('groupId', 'integration-fabric'), 'auto.offset.reset': cfg.get('autoOffsetReset', cfg.get('offsetReset', 'earliest')), 'enable.auto.commit': bool(cfg.get('enableAutoCommit', not client_ack)), 'fetch.min.bytes': int(cfg.get('fetchMinBytes', 1) or 1), 'max.poll.records': int(cfg.get('maxPollRecords', cfg.get('maxMessages', 1)) or 1), **mapping(cfg.get('additionalProperties'))}
                consumer = Consumer(consumer_cfg); topics = [item.strip() for item in str(destination).split(';') if item.strip()]; consumer.subscribe(topics)
                messages, native_messages = [], []
                for _ in range(int(cfg.get('maxMessages', 1))):
                    message = consumer.poll(float(cfg.get('timeout', 1)))
                    if message and not message.error():
                        try: data = json.loads(message.value().decode())
                        except (ValueError, UnicodeDecodeError): data = message.value().decode(errors='replace')
                        item = {'id':f'{message.topic()}:{message.partition()}:{message.offset()}','data':data,'key':message.key().decode(errors='replace') if message.key() else None,'topic':message.topic(),'partition':message.partition(),'offset':message.offset(),'timestamp':message.timestamp()[1],'headers':dict(message.headers() or [])}
                        messages.append(item); native_messages.append(message)
                if client_ack:
                    pending = {'count': len(native_messages)}
                    def kafka_confirm(native_message):
                        consumer.commit(message=native_message, asynchronous=False)
                        pending['count'] -= 1
                        if pending['count'] <= 0: consumer.close()
                    for item, native_message in zip(messages, native_messages):
                        item['ackId'] = self.register_acknowledgement('kafka', item['id'], lambda m=native_message: kafka_confirm(m))
                    if not native_messages: consumer.close()
                else: consumer.close()
                return {'messages': messages, 'count': len(messages), 'ackId': messages[0].get('ackId') if messages else None, 'ackIds':[item['ackId'] for item in messages if item.get('ackId')]}
            producer_cfg = {**common, 'acks': str(cfg.get('acks','all')), 'compression.type': cfg.get('compressionType','none'), 'retries': int(cfg.get('retries',3) or 0), 'batch.size': int(cfg.get('batchSize',16384) or 16384), 'linger.ms': int(cfg.get('lingerMs',0) or 0), 'enable.idempotence': bool(cfg.get('enableIdempotence',False)), **mapping(cfg.get('additionalProperties'))}
            if cfg.get('transactionalId'): producer_cfg['transactional.id'] = cfg['transactionalId']
            producer = Producer(producer_cfg); delivered = {}
            def delivery(error, message):
                if error: delivered['error'] = str(error)
                else: delivered.update({'partition':message.partition(),'offset':message.offset(),'timestamp':message.timestamp()[1]})
            raw = payload if isinstance(payload, bytes) else (payload.encode() if isinstance(payload, str) else json.dumps(payload).encode())
            producer.produce(destination, raw, key=str(cfg.get('key', '')).encode() or None, partition=int(cfg['partitionId']) if cfg.get('assignCustomPartition') else -1, headers=list(attributes.items()), callback=delivery); producer.flush()
            if delivered.get('error'): raise RuntimeError(delivered['error'])
            return {**envelope, **delivered, 'messageId':envelope['id'], 'topic':destination, 'published':True}
        if technology == 'pubsub':
            try: from google.cloud import pubsub_v1
            except ImportError: raise RuntimeError('External Google Pub/Sub mode requires google-cloud-pubsub')
            project_id = cfg.get('projectId') or rcfg['projectId']; client_kwargs = {}
            if rcfg.get('credentialsFile'):
                from google.oauth2 import service_account
                client_kwargs['credentials'] = service_account.Credentials.from_service_account_file(rcfg['credentialsFile'])
            endpoint = rcfg.get('emulatorHost') or rcfg.get('endpoint')
            if endpoint: client_kwargs['client_options'] = {'api_endpoint': endpoint}
            if operation in receive_ops:
                subscriber = pubsub_v1.SubscriberClient(**client_kwargs); path = subscriber.subscription_path(project_id, destination); response = subscriber.pull(request={'subscription': path, 'max_messages': int(cfg.get('maxMessages', 1))}, timeout=float(cfg.get('receiveTimeout', cfg.get('timeout', 10))))
                messages, native_ack_ids = [], []
                for item in response.received_messages:
                    record = {'id':item.message.message_id,'messageId':item.message.message_id,'data':item.message.data.decode(errors='replace'),'attributes':dict(item.message.attributes),'publishTime':item.message.publish_time.isoformat() if item.message.publish_time else None}
                    messages.append(record); native_ack_ids.append(item.ack_id)
                if client_ack:
                    pending = {'count': len(native_ack_ids)}
                    def pubsub_confirm(native_ack_id):
                        subscriber.acknowledge(request={'subscription':path,'ack_ids':[native_ack_id]})
                        pending['count'] -= 1
                        if pending['count'] <= 0: subscriber.close()
                    for record, native_ack_id in zip(messages, native_ack_ids):
                        record['ackId'] = self.register_acknowledgement('pubsub', record['id'], lambda ack=native_ack_id: pubsub_confirm(ack))
                    if not native_ack_ids: subscriber.close()
                else:
                    if response.received_messages: subscriber.acknowledge(request={'subscription':path,'ack_ids':[item.ack_id for item in response.received_messages]})
                    subscriber.close()
                first = messages[0] if messages else {}
                return {'MessageID':first.get('messageId'),'PublishTime':first.get('publishTime'),'Data':first.get('data'),'Attributes':first.get('attributes',{}),'AckID':first.get('ackId'),'ackId':first.get('ackId'),'messages':messages,'count':len(messages)}
            publisher = pubsub_v1.PublisherClient(**client_kwargs); path = publisher.topic_path(project_id, destination); raw = payload if isinstance(payload, bytes) else (payload.encode() if isinstance(payload, str) else json.dumps(payload).encode()); message_id = publisher.publish(path, raw, ordering_key=str(cfg.get('orderingKey','')), **attributes).result(timeout=float(cfg.get('publishTimeout', 60))); publisher.transport.close(); return {**envelope, 'TopicName':path, 'MessageID':message_id, 'messageId':message_id, 'published':True}
        raise RuntimeError(f'Unsupported messaging technology {technology}')

    @staticmethod
    def assign_path(target: dict, path: str, value):
        parts = [part for part in str(path).split('.') if part]
        if not parts: return
        current = target
        for part in parts[:-1]:
            child = current.get(part)
            if not isinstance(child, dict): child = {}; current[part] = child
            current = child
        current[parts[-1]] = value

    def map_input_values(self, mappings: dict, ctx: dict) -> dict:
        result = {}
        for path, expression in (mappings or {}).items(): self.assign_path(result, path, self.resolve(expression, ctx))
        return result

    @staticmethod
    def unwrap_boundary(mapped: dict, wrapper: str, fallback):
        if not mapped: return fallback
        return mapped[wrapper] if set(mapped) == {wrapper} else mapped

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
            current = ctx['input']
            for part in value[8:-1].split('.'): current = current.get(part, '') if isinstance(current, dict) else ''
            return current
        if isinstance(value, str) and value.startswith('${vars.'):
            current = ctx['vars']
            for part in value[7:-1].split('.'): current = current.get(part, '') if isinstance(current, dict) else ''
            return current
        if isinstance(value, str) and value.startswith('${properties.') and value.endswith('}'):
            return ctx['properties'].get(value[13:-1], '')
        if isinstance(value, str) and value.startswith('${') and value.endswith('}'):
            path = value[2:-1].split('.')
            if path[0] in ('activities', 'tasks', 'context'):
                current = ctx.get(path[0], {})
                for part in path[1:]:
                    if isinstance(current, dict): current = current.get(part, '')
                    elif isinstance(current, list) and part.isdigit() and int(part) < len(current): current = current[int(part)]
                    else: return ''
                return current
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
