from __future__ import annotations
import ast, asyncio, base64, csv, ftplib, gzip, importlib.util, io, json, os, re, shutil, sqlite3, sys, tempfile, traceback, uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path
import httpx
from .models import Activity, ProcessDefinition, Project, RunResult
from .mapper import execute as execute_mapping
from .dataweave import DataWeaveError, execute as execute_dataweave
from .sap import sap_adapter

class RuntimeErrorWithLogs(Exception): pass
class FabricFault(Exception):
    def __init__(self, message: str, *, fault_type='UserDefinedException', code='', details=None, cause=None):
        super().__init__(message); self.fault_type = fault_type; self.code = code; self.details = details or {}; self.cause = cause

class WorkflowRuntime:
    def __init__(self):
        self.messages: dict[str, list[dict]] = {}
        self.acknowledgements: dict[str, dict] = {}
        self.shared_variables: dict[str, Any] = {}

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
        started = datetime.now(timezone.utc)
        correlation_id = str(initial.get('correlationId') or initial.get('correlation_id') or run_id) if isinstance(initial, dict) else run_id
        execution_state = execution_state or {'activities': {}, 'tasks': {}}
        activity_outputs = execution_state.setdefault('activities', {})
        task_outputs = execution_state.setdefault('tasks', {})
        task_state = task_outputs.setdefault(process.id, {'name': process.name, 'activities': {}})
        context = {
            'input': initial, 'vars': {}, 'last': initial, 'resources': resources or {},
            'properties': properties or {}, 'project': project, 'runtime': self, 'logs': logs,
            'activities': activity_outputs, 'tasks': task_outputs,
            'context': {'taskId': process.id, 'activityId': '', 'environment': getattr(project, 'active_environment', '') if project else '', 'correlationId': correlation_id, 'runId': run_id},
        }
        self.log(logs, 'INFO', f'Job started: {process.name}', kind='lifecycle', correlationId=correlation_id, runId=run_id, startedAt=started.isoformat())
        def finish(status: str, output: dict) -> RunResult:
            ended = datetime.now(timezone.utc); duration = round((ended - started).total_seconds() * 1000, 3)
            self.log(logs, 'INFO' if status == 'completed' else 'ERROR', f'Job {status}: {process.name} in {duration:.3f} ms', kind='lifecycle', correlationId=correlation_id, runId=run_id, endedAt=ended.isoformat(), durationMs=duration)
            for entry in logs:
                entry.setdefault('correlationId', correlation_id); entry.setdefault('runId', run_id)
            return RunResult(run_id=run_id, correlation_id=correlation_id, started_at=started.isoformat(), ended_at=ended.isoformat(), duration_ms=duration, status=status, output=output, logs=logs, activity_outputs=activity_outputs, task_outputs=task_outputs)
        activity_by_id = {a.id: a for a in process.activities}
        incoming = {t.target for t in process.transitions}
        starts = [activity_by_id[entry_activity_id]] if entry_activity_id in activity_by_id else ([a for a in process.activities if a.type == 'start'] or [a for a in process.activities if a.id not in incoming and a.type != 'catch'])
        if len(starts) != 1:
            self.log(logs, 'ERROR', 'Process must have exactly one Start activity')
            return finish('failed', {})
        current = starts[0]
        try:
            for _ in range(len(process.activities) + 1):
                self.log(logs, 'DEBUG', f'Executing {current.name}', current.id, kind='trace')
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
                    fault = self.fault_payload(error, current.id)
                    context['last'] = fault; context['context']['error'] = fault
                    if not chosen:
                        used = set(context['context'].setdefault('handledCatchIds', []))
                        catches = [activity for activity in process.activities if activity.type == 'catch' and activity.id not in used]
                        caught = next((activity for activity in catches if self.as_bool(activity.config.get('catchAll', True)) or (activity.config.get('errorType') and activity.config.get('errorType') == fault['type']) or (activity.config.get('errorCode') and str(activity.config.get('errorCode')) == fault['code'])), None)
                        if not caught: raise error
                        context['context']['handledCatchIds'].append(caught.id)
                        self.log(logs, 'WARN', f'{caught.name} caught {fault["type"]}: {fault["message"]}', caught.id, kind='exception', fault=fault)
                        current = caught
                        continue
                else:
                    chosen = next((t for t in outgoing if t.type == 'success_condition' and self.condition(t.condition, context)), None)
                    chosen = chosen or next((t for t in outgoing if t.type == 'success'), None)
                    chosen = chosen or next((t for t in outgoing if t.type == 'success_no_match'), None)
                if not chosen: raise RuntimeErrorWithLogs(f'{current.name} has no matching outgoing transition')
                current = activity_by_id[chosen.target]
            final_output = context['last'] if isinstance(context['last'], dict) else {'result': context['last']}
            task_state['output'] = final_output
            return finish('completed', final_output)
        except Exception as exc:
            self.log(logs, 'ERROR', str(exc), current.id)
            task_state['error'] = {'message': str(exc), 'activityId': current.id}
            return finish('failed', {})

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

    @staticmethod
    def fault_payload(error: Exception, activity_id: str) -> dict:
        stack_trace = ''.join(traceback.format_exception(type(error), error, error.__traceback__))
        return {'type': getattr(error, 'fault_type', error.__class__.__name__), 'code': str(getattr(error, 'code', '') or ''), 'message': str(error), 'stackTrace': stack_trace, 'activityId': activity_id, 'details': getattr(error, 'details', {}) or {}, 'cause': getattr(error, 'cause', None)}

    def log(self, logs, level, message, activity_id=None, **details):
        logs.append({'time': datetime.now(timezone.utc).isoformat(), 'level': level, 'message': message, 'activityId': activity_id, **details})

    @staticmethod
    def _cron_field_matches(expression: str, value: int, minimum: int, maximum: int) -> bool:
        def item_matches(item: str) -> bool:
            base, _, step_text = item.partition('/')
            step = int(step_text or 1)
            if step < 1: raise ValueError('Cron step must be greater than zero')
            if base == '*': start, end = minimum, maximum
            elif '-' in base: start, end = (int(part) for part in base.split('-', 1))
            else: start = end = int(base)
            if start < minimum or end > maximum or start > end: raise ValueError(f'Cron value {item!r} is outside {minimum}-{maximum}')
            return start <= value <= end and (value - start) % step == 0
        return any(item_matches(item.strip()) for item in expression.split(',') if item.strip())

    @classmethod
    def _next_cron_time(cls, expression: str, now: datetime) -> datetime:
        parts = expression.split()
        if len(parts) != 5: raise FabricFault('Cron expression requires five fields: minute hour day month weekday', fault_type='SCHEDULER')
        candidate = now.replace(second=0, microsecond=0) + timedelta(minutes=1)
        for _ in range(527040):
            weekday = (candidate.weekday() + 1) % 7
            try:
                if (cls._cron_field_matches(parts[0], candidate.minute, 0, 59) and cls._cron_field_matches(parts[1], candidate.hour, 0, 23) and cls._cron_field_matches(parts[2], candidate.day, 1, 31) and cls._cron_field_matches(parts[3], candidate.month, 1, 12) and cls._cron_field_matches(parts[4], weekday, 0, 6)):
                    return candidate
            except ValueError as error:
                raise FabricFault(str(error), fault_type='SCHEDULER') from error
            candidate += timedelta(minutes=1)
        raise FabricFault('Cron expression did not produce an execution time within one year', fault_type='SCHEDULER')

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
            include, value = self.evaluate_mapping(expression, ctx)
            if include: self.assign_path(cfg, key, value)
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
        if activity.type == 'timer':
            now = datetime.now(timezone.utc)
            environment = str(ctx.get('context', {}).get('environment') or '').lower()
            run_once = environment == 'local' and self.as_bool(cfg.get('runOnceOnLocalStart', True))
            mode = str(cfg.get('scheduleMode') or 'dateTime')
            if run_once:
                scheduled = now
                trigger_mode = 'local-run-once'
            elif mode == 'cron':
                scheduled = self._next_cron_time(str(cfg.get('cronExpression') or ''), now)
                trigger_mode = 'cron'
            else:
                raw = str(cfg.get('scheduledDateTime') or '').strip()
                if not raw: raise FabricFault('Scheduler requires a date/time or local Run once option', fault_type='SCHEDULER')
                try:
                    scheduled = datetime.fromisoformat(raw.replace('Z', '+00:00'))
                    if scheduled.tzinfo is None: scheduled = scheduled.astimezone()
                    scheduled = scheduled.astimezone(timezone.utc)
                except ValueError as error: raise FabricFault(f'Invalid scheduler date/time: {raw}', fault_type='SCHEDULER') from error
                trigger_mode = 'dateTime'
            delay = max(0.0, (scheduled - now).total_seconds())
            self.log(ctx['logs'], 'INFO', f'Scheduler armed for {scheduled.isoformat()}', activity.id, kind='scheduler', triggerMode=trigger_mode, waitSeconds=round(delay, 3))
            if delay: await asyncio.sleep(delay)
            fired = datetime.now(timezone.utc)
            return {'scheduledTime': scheduled.isoformat(), 'actualTime': fired.isoformat(), 'sequence': 1, 'triggerMode': trigger_mode, 'payload': ctx['last']}
        if activity.type == 'basic':
            operation = str(cfg.get('operation') or 'empty')
            if operation == 'empty': return ctx['last']
            if operation == 'assign':
                name, value = str(cfg.get('variable') or '').strip(), cfg.get('value', ctx['last'])
                if not name: raise RuntimeError('Assign Variable requires a process variable name')
                ctx['vars'][name] = value; return {'name': name, 'value': value}
            if operation == 'sleep':
                duration = float(cfg.get('duration') or 0); unit = str(cfg.get('unit') or 'milliseconds').lower()
                seconds = duration * (60 if unit == 'minutes' else 1 if unit == 'seconds' else .001)
                await asyncio.sleep(max(0, seconds)); return {'sleptMilliseconds': round(seconds * 1000), 'payload': ctx['last']}
            if operation == 'get_context': return dict(ctx.get('context', {}))
            if operation == 'set_context':
                values = cfg.get('values') or {}
                if not isinstance(values, dict): raise RuntimeError('Set Process Context requires an object')
                ctx['context'].update(values); return {'context': dict(ctx['context'])}
            if operation == 'get_shared_variable':
                name = str(cfg.get('name') or '').strip(); return {'name': name, 'value': self.shared_variables.get(name, cfg.get('default'))}
            if operation == 'set_shared_variable':
                name, value = str(cfg.get('name') or '').strip(), cfg.get('value', ctx['last'])
                if not name: raise RuntimeError('Set Shared Variable requires a name')
                self.shared_variables[name] = value; return {'name': name, 'value': value}
            if operation == 'inspector':
                label = str(cfg.get('label') or activity.name); payload = cfg.get('payload', ctx['last'])
                self.log(ctx['logs'], 'DEBUG', f'Inspector: {label}', activity.id, kind='inspection', **({'payload': payload} if self.as_bool(cfg.get('includePayload', True)) else {}))
                return ctx['last']
            raise RuntimeError(f'Unsupported Basic/General operation {operation}')
        if activity.type == 'catch': return ctx.get('context', {}).get('error') or ctx['last']
        if activity.type == 'throw':
            details = cfg.get('details', {})
            if isinstance(details, str) and details.strip():
                try: details = json.loads(details)
                except ValueError: details = {'text': details}
            if cfg.get('stackTrace'):
                details = {**(details if isinstance(details, dict) else {'value': details}), 'stackTrace': cfg.get('stackTrace')}
            raise FabricFault(str(cfg.get('message') or 'Business fault'), fault_type=str(cfg.get('errorType') or cfg.get('type') or 'UserDefinedException'), code=str(cfg.get('code') or ''), details=details)
        if activity.type == 'rethrow':
            fault = ctx.get('context', {}).get('error')
            if not fault: raise FabricFault('Rethrow requires an active caught exception', fault_type='RethrowException')
            raise FabricFault(fault.get('message', 'Rethrown exception'), fault_type=fault.get('type', 'RethrowException'), code=fault.get('code', ''), details=fault.get('details', {}), cause=fault)
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
        if activity.type in ('mapper', 'transform', 'ai_transform'):
            source = {
                **(ctx['last'] if isinstance(ctx.get('last'), dict) else {}),
                'last': ctx.get('last'), 'input': ctx.get('input'),
                'properties': ctx.get('properties', {}), 'vars': ctx.get('vars', {}),
                'context': ctx.get('context', {}), 'activities': ctx.get('activities', {}),
            }
            rules = []
            for rule in activity.config.get('mappings', []) or []:
                normalized = {**rule}
                if 'constant' in rule: normalized['constant'] = self.resolve(rule['constant'], ctx)
                for key in ('source', 'select'):
                    value = normalized.get(key)
                    if isinstance(value, str) and value.startswith('${') and value.endswith('}'):
                        normalized[key] = value[2:-1]
                if isinstance(normalized.get('condition'), str):
                    normalized['condition'] = re.sub(r'\$\{([^}]+)\}', r'\1', normalized['condition'])
                rules.append(normalized)
            return execute_mapping(source, rules, cfg)
        if activity.type == 'dataweave':
            try:
                return execute_dataweave(
                    str(cfg.get('script') or '%dw 2.0\noutput application/json\n---\npayload'),
                    payload=cfg.get('payload', ctx.get('last')),
                    attributes=cfg.get('attributes', ctx.get('attributes', {})),
                    variables={**ctx.get('vars', {}), **(cfg.get('variables', {}) or {})},
                    input_mime_type=str(cfg.get('inputMimeType') or ''),
                )
            except DataWeaveError as exc:
                raise FabricFault(str(exc), fault_type='DATAWEAVE_SYNTAX', cause=exc.__class__.__name__) from exc
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
            try:
                if cfg.get('operation') == 'parse': return self.parse_xml_activity(cfg, ctx)
                return self.render_xml_activity(cfg, ctx)
            except FabricFault: raise
            except (ValueError, TypeError, UnicodeError, LookupError) as exc: raise FabricFault(str(exc), fault_type='XMLParseException' if cfg.get('operation') == 'parse' else 'XMLRenderException', cause=exc.__class__.__name__) from exc
        if activity.type == 'json':
            try: return self.json_activity(cfg, ctx)
            except FabricFault: raise
            except (ValueError, TypeError, UnicodeError) as exc: raise FabricFault(str(exc), fault_type='JSONParserException' if cfg.get('operation') == 'parse' else 'JSONRenderException', cause=exc.__class__.__name__) from exc
        if activity.type == 'flat':
            try: return self.flat_data(cfg, ctx)
            except FabricFault: raise
            except (ValueError, TypeError, csv.Error) as exc: raise FabricFault(str(exc), fault_type='ParseDataException' if cfg.get('operation') == 'parse' else 'RenderDataException', cause=exc.__class__.__name__) from exc
        if activity.type == 'call_task':
            project = ctx.get('project')
            if not project: raise RuntimeError('Call Sub Task requires project execution context')
            dynamic_value = self.resolve(cfg.get('dynamicTaskId'), ctx) if cfg.get('dynamicTaskId') not in (None, '') else None
            task_id = str(dynamic_value).strip() if dynamic_value not in (None, '') else str(cfg.get('taskId') or '').strip()
            task = next((item for item in project.tasks if item.id == task_id and item.kind == 'subtask'), None)
            if not task:
                task = next((item for item in project.tasks if item.name.casefold() == task_id.casefold() and item.kind == 'subtask'), None)
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
        if activity.type == 'python': return await self.python_worker(cfg, ctx['last'])
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
        for path, expression in (mappings or {}).items():
            include, value = self.evaluate_mapping(expression, ctx)
            if include: self.assign_path(result, path, value)
        return result

    def evaluate_mapping(self, expression, ctx) -> tuple[bool, Any]:
        """Evaluate the structured mapping statements used by every activity Input tab."""
        if not isinstance(expression, dict) or '$rule' not in expression:
            return True, self.resolve(expression, ctx)
        rule = str(expression.get('$rule', '')).lower()
        source_expression = expression.get('select') or expression.get('source')
        source = self.resolve(source_expression, ctx)
        if rule == 'if':
            return self.condition(expression.get('condition', ''), ctx), source
        if rule == 'when-otherwise':
            if self.condition(expression.get('condition', ''), ctx): return True, source
            return True, self.resolve(expression.get('otherwise'), ctx)
        if rule == 'for-each':
            values = source if isinstance(source, list) else ([] if source in (None, '') else [source])
            return True, values
        if rule == 'for-each-group':
            values = source if isinstance(source, list) else ([] if source in (None, '') else [source])
            group_path = str(expression.get('groupBy') or '').strip('.')
            groups: dict[str, list[Any]] = {}
            for item in values:
                current = item
                for part in group_path.split('.') if group_path else []:
                    current = current.get(part) if isinstance(current, dict) else None
                groups.setdefault(str(current), []).append(item)
            return True, [{'key': key, 'items': items} for key, items in groups.items()]
        return True, source

    @staticmethod
    def unwrap_boundary(mapped: dict, wrapper: str, fallback):
        if not mapped: return fallback
        return mapped[wrapper] if set(mapped) == {wrapper} else mapped

    @staticmethod
    def split_function_args(raw: str) -> list[str]:
        args, start, depth, quote = [], 0, 0, None
        for index, char in enumerate(raw):
            if quote:
                if char == quote and (index == 0 or raw[index - 1] != '\\'): quote = None
            elif char in ('"', "'"): quote = char
            elif char == '(': depth += 1
            elif char == ')': depth = max(0, depth - 1)
            elif char == ',' and depth == 0: args.append(raw[start:index].strip()); start = index + 1
        if raw.strip(): args.append(raw[start:].strip())
        return args

    def evaluate_function_expression(self, expression: str, ctx: dict, variables: dict | None = None):
        variables = variables or {}
        text = expression.strip()
        if text in variables: return variables[text]
        if len(text) >= 2 and text[0] == text[-1] and text[0] in ('"', "'"): return text[1:-1]
        if re.fullmatch(r'-?\d+(\.\d+)?', text): return float(text) if '.' in text else int(text)
        if text.lower() in ('true()', 'true'): return True
        if text.lower() in ('false()', 'false'): return False
        call = re.fullmatch(r'([\w:-]+)\((.*)\)', text, re.S)
        if not call: return self.resolve(text, ctx)
        name = call.group(1); args = [self.evaluate_function_expression(item, ctx, variables) for item in self.split_function_args(call.group(2))]
        if name.startswith('custom:'):
            function_name = name.split(':', 1)[1]
            project = ctx.get('project')
            definition = next((item for item in (getattr(project, 'custom_functions', []) if project else []) if item.name == function_name), None)
            if not definition: raise RuntimeError(f'Custom function {function_name!r} was not found in this project')
            bindings = {f'${parameter}': args[index] if index < len(args) else None for index, parameter in enumerate(definition.parameters)}
            return self.evaluate_function_expression(definition.expression, ctx, bindings)
        key = name.lower().replace('-', '')
        if key == 'concat': return ''.join('' if value is None else str(value) for value in args)
        if key in ('uppercase', 'upper'): return str(args[0] if args else '').upper()
        if key in ('lowercase', 'lower'): return str(args[0] if args else '').lower()
        if key in ('trim', 'normalizespace'): return ' '.join(str(args[0] if args else '').split())
        if key == 'stringlength': return len(str(args[0] if args else ''))
        if key == 'substring':
            start = int(args[1]) - 1
            return str(args[0])[start:start + int(args[2])] if len(args) > 2 else str(args[0])[start:]
        if key == 'replace': return re.sub(str(args[1]), str(args[2]), str(args[0]))
        if key == 'contains': return str(args[1]) in str(args[0])
        if key == 'startswith': return str(args[0]).startswith(str(args[1]))
        if key == 'endswith': return str(args[0]).endswith(str(args[1]))
        if key == 'coalesce': return next((value for value in args if value not in (None, '')), None)
        if key == 'count': return len(args[0]) if args and hasattr(args[0], '__len__') else len(args)
        if key == 'sum': return sum(args[0] if len(args) == 1 and isinstance(args[0], list) else args)
        if key in ('average', 'avg'):
            values = args[0] if len(args) == 1 and isinstance(args[0], list) else args
            return sum(values) / len(values) if values else 0
        if key == 'ifthenelse': return args[1] if args and self.as_bool(args[0]) else (args[2] if len(args) > 2 else None)
        if key == 'uuid': return str(uuid.uuid4())
        if key == 'exists': return bool(args and args[0] not in (None, '', [], {}))
        if key == 'empty': return not args or args[0] in (None, '', [], {})
        raise RuntimeError(f'Unsupported mapper function {name!r}')

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
        if isinstance(value, str) and re.fullmatch(r'[\w:-]+\(.*\)', value.strip(), re.S):
            return self.evaluate_function_expression(value, ctx)
        if isinstance(value, str) and len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
            try: return ast.literal_eval(value)
            except (SyntaxError, ValueError): return value[1:-1]
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

    @staticmethod
    def schema_content(schema_id, ctx):
        project = ctx.get('project')
        schema = next((item for item in getattr(project, 'schemas', []) if item.id == schema_id or item.name == schema_id), None) if project and schema_id else None
        return schema.content if schema else ''

    def configured_schema(self, cfg, ctx):
        return cfg.get('schemaText') or self.schema_content(cfg.get('schemaId'), ctx)

    @staticmethod
    def schema_root_name(schema):
        if not schema: return ''
        try:
            document = json.loads(schema)
            return document.get('title') or next(iter((document.get('properties') or {}).keys()), '')
        except (ValueError, TypeError):
            pass
        from xml.etree import ElementTree
        try: root = ElementTree.fromstring(schema)
        except (ElementTree.ParseError, TypeError): return ''
        return next((item.attrib.get('name') for item in list(root) if item.tag.rsplit('}', 1)[-1] == 'element' and item.attrib.get('name')), '')

    @staticmethod
    def schema_leaf_fields(schema):
        if not schema: return [], []
        try:
            document = json.loads(schema); fields = []
            def walk(node):
                properties = node.get('properties', {}) if isinstance(node, dict) else {}
                for name, child in properties.items():
                    if isinstance(child, dict) and child.get('properties'): walk(child)
                    else: fields.append((name, child.get('type', 'string') if isinstance(child, dict) else 'string'))
            walk(document)
            return [item[0] for item in fields], [item[1] for item in fields]
        except (ValueError, TypeError):
            pass
        from xml.etree import ElementTree
        try: document = ElementTree.fromstring(schema)
        except (ElementTree.ParseError, TypeError): return [], []
        fields = []
        def local(element): return element.tag.rsplit('}', 1)[-1]
        def child_elements(element):
            result = []
            for child in list(element):
                if local(child) == 'element': result.append(child)
                elif local(child) in ('complexType', 'sequence', 'all', 'choice', 'group', 'extension'): result.extend(child_elements(child))
            return result
        def walk(element):
            children = child_elements(element)
            if children:
                for child in children: walk(child)
            elif local(element) == 'element' and element.attrib.get('name'):
                fields.append((element.attrib['name'], element.attrib.get('type', 'string').split(':')[-1]))
            for child in element.iter():
                if local(child) == 'attribute' and child.attrib.get('name'): fields.append((child.attrib['name'], child.attrib.get('type', 'string').split(':')[-1]))
        roots = [item for item in list(document) if local(item) == 'element']
        for root in roots: walk(root)
        unique = list(dict.fromkeys(fields))
        return [item[0] for item in unique], [item[1] for item in unique]

    def parse_xml_activity(self, cfg, ctx):
        style = str(cfg.get('inputStyle', 'Text')).lower()
        source = cfg.get('xmlString', cfg.get('source', ctx['last']))
        if style in ('binary','dynamic') and cfg.get('xmlBinary') not in (None, ''): source = cfg.get('xmlBinary')
        if isinstance(source, dict): source = source.get('bytes') or source.get('binaryContent') or source.get('xmlString') or source.get('content') or source.get('body') or ''
        if isinstance(source, str) and style == 'binary':
            try: source = base64.b64decode(source)
            except ValueError: source = source.encode(cfg.get('forceEncoding') or cfg.get('encoding') or 'utf-8')
        if isinstance(source, bytes): source = source.decode(cfg.get('forceEncoding') or cfg.get('encoding') or 'utf-8-sig')
        parsed = self.parse_xml(source)
        if self.as_bool(cfg.get('validateOutput', False)):
            schema = self.configured_schema(cfg, ctx)
            if not schema: raise FabricFault('Validate Output requires a project or inline XSD in Output Editor', fault_type='ValidationException')
            self.validate_xml_root(parsed['root'], schema)
        return parsed

    def render_xml_activity(self, cfg, ctx):
        schema = self.configured_schema(cfg, ctx)
        root_name = self.schema_root_name(schema) or cfg.get('rootElement') or 'root'
        source = cfg.get(root_name, cfg.get('value', cfg.get('source', ctx['last'])))
        if isinstance(source, dict) and root_name in source and not ('root' in source and 'value' in source): source = source[root_name]
        if self.as_bool(cfg.get('validateInput', False)):
            if not schema: raise FabricFault('Validate Input requires a project or inline XSD in Input Editor', fault_type='ValidationException')
            actual_root = source.get('root') if isinstance(source, dict) and 'root' in source else root_name
            self.validate_xml_root(actual_root, schema)
        encoding = cfg.get('encoding') or 'UTF-8'
        content = self.render_xml(source, root_name, 'unicode', pretty=self.as_bool(cfg.get('prettyPrint', False)))
        if not self.as_bool(cfg.get('suppressXmlDeclaration', False)): content = f'<?xml version="1.0" encoding="{encoding}"?>\n{content}'
        if str(cfg.get('outputStyle', 'Text')).lower() == 'binary':
            raw = content.encode(encoding); return {'binaryContent': base64.b64encode(raw).decode(), 'bytes': base64.b64encode(raw).decode(), 'byteCount': len(raw), 'encoding': encoding, 'content': None}
        return {'content': content, 'xmlString': content, 'encoding': encoding}

    @staticmethod
    def validate_xml_root(root_name, schema):
        from xml.etree import ElementTree
        try: schema_root = ElementTree.fromstring(schema)
        except ElementTree.ParseError as exc: raise FabricFault(f'Selected XSD is invalid: {exc}', fault_type='ValidationException') from exc
        expected = next((item.attrib.get('name') for item in list(schema_root) if item.tag.rsplit('}',1)[-1] == 'element' and item.attrib.get('name')), None)
        actual = str(root_name or '').rsplit('}',1)[-1]
        if expected and actual != expected: raise FabricFault(f'XML root {actual!r} does not match XSD root {expected!r}', fault_type='ValidationException', details={'expectedRoot':expected,'actualRoot':actual})

    def parse_xml(self, source):
        from xml.etree import ElementTree
        if isinstance(source, dict): source = source.get('content') or source.get('body') or ''
        root = ElementTree.fromstring(source)
        def convert(element):
            children = list(element); result = {'@' + key: value for key, value in element.attrib.items()}
            if not children:
                text = element.text or ''
                if result:
                    if text: result['#text'] = text
                    return result
                return text
            for child in children:
                value = convert(child)
                if child.tag in result: result[child.tag] = result[child.tag] if isinstance(result[child.tag], list) else [result[child.tag]]; result[child.tag].append(value)
                else: result[child.tag] = value
            if element.text and element.text.strip(): result['#text'] = element.text.strip()
            return result
        value = convert(root)
        return {'root': root.tag, 'value': value, root.tag.rsplit('}', 1)[-1]: value}

    def render_xml(self, source, root_name='root', encoding='unicode', pretty=False):
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
        root = build(root_name, source)
        if pretty: ElementTree.indent(root, space='  ')
        return ElementTree.tostring(root, encoding=encoding).decode() if encoding != 'unicode' else ElementTree.tostring(root, encoding='unicode')

    def json_activity(self, cfg, ctx):
        operation = cfg.get('operation', 'parse'); source = cfg.get('jsonString', cfg.get('value', cfg.get('source', ctx['last'])))
        if isinstance(source, dict) and operation == 'parse': source = source.get('jsonString') or source.get('content') or source.get('body') or source
        if operation == 'parse':
            if not isinstance(source, (str, bytes, bytearray)): value = source
            else:
                policy = str(cfg.get('duplicateKeyPolicy', 'Last wins')).lower()
                def pairs(items):
                    result = {}
                    for key, value in items:
                        if key in result and policy == 'error': raise ValueError(f'Duplicate JSON key: {key}')
                        if key not in result or policy != 'first wins': result[key] = value
                    return result
                value = json.loads(source, object_pairs_hook=pairs)
            self.validate_json_if_requested(value, cfg, ctx, 'validateOutput')
            return value
        schema = self.configured_schema(cfg, ctx); root_name = self.schema_root_name(schema)
        if root_name and root_name in cfg:
            source = {root_name: cfg[root_name]} if str(cfg.get('rootStyle', 'With root')).lower() != 'anonymous' else cfg[root_name]
        self.validate_json_if_requested(source, cfg, ctx, 'validateInput')
        if self.as_bool(cfg.get('omitNulls', False)):
            def without_nulls(value):
                if isinstance(value, dict): return {key: without_nulls(item) for key, item in value.items() if item is not None}
                if isinstance(value, list): return [without_nulls(item) for item in value if item is not None]
                return value
            source = without_nulls(source)
        indent = int(cfg.get('indent', 2)) if self.as_bool(cfg.get('prettyPrint', True)) else None
        content = json.dumps(source, indent=indent, ensure_ascii=self.as_bool(cfg.get('asciiOnly', False)), separators=None if indent is not None else (',', ':'))
        return {'content': content, 'jsonString': content}

    def validate_json_if_requested(self, value, cfg, ctx, flag):
        if not self.as_bool(cfg.get(flag, False)): return
        content = self.configured_schema(cfg, ctx)
        if not content: raise FabricFault(f'{flag} requires a project or inline schema in the schema editor', fault_type='ValidationException')
        try: schema = json.loads(content)
        except ValueError: return
        if schema.get('type') == 'object' and not isinstance(value, dict): raise FabricFault('JSON value must be an object according to the selected schema', fault_type='ValidationException')
        missing = [key for key in schema.get('required', []) if not isinstance(value, dict) or key not in value]
        if missing: raise FabricFault(f'Missing required JSON fields: {", ".join(missing)}', fault_type='ValidationException', details={'missing':missing})

    def flat_data(self, cfg, ctx):
        source, delimiter = cfg.get('text', cfg.get('records', cfg.get('source', ctx['last']))), str(cfg.get('delimiter', ','))
        fields = [item.strip() for item in cfg.get('fields', '').split(',') if item.strip()]
        types = [item.strip().lower() for item in str(cfg.get('fieldTypes', '')).split(',') if item.strip()]
        if not fields:
            schema_fields, schema_types = self.schema_leaf_fields(self.configured_schema(cfg, ctx))
            if schema_fields: fields = schema_fields
            if not types and schema_types: types = [item.lower() for item in schema_types]
        line_ending = {'lf':'\n','crlf':'\r\n','cr':'\r','auto':'\n'}.get(str(cfg.get('lineSeparator', cfg.get('lineEnding', 'Auto'))).lower(), str(cfg.get('lineEnding', '\n')))
        def typed(value, index):
            value = value.strip() if self.as_bool(cfg.get('trimValues', True)) else value
            kind = types[index] if index < len(types) else 'string'
            if value == '': return None if kind not in ('string','text') else ''
            if kind in ('integer','int','long'): return int(value)
            if kind in ('decimal','number','float','double'): return float(value)
            if kind in ('boolean','bool'): return value.lower() in ('true','1','yes','y')
            return value
        if str(cfg.get('format', 'delimited')).lower() == 'fixed':
            widths = [int(item.strip()) for item in cfg.get('widths', '').split(',') if item.strip()]
            if not fields or len(fields) != len(widths): raise RuntimeError('Fixed-width data requires matching field names and widths')
            if cfg.get('operation') == 'parse':
                records = []
                for line in str(source).splitlines():
                    if not line and self.as_bool(cfg.get('skipBlankLines', True)): continue
                    if self.as_bool(cfg.get('strictColumns', False)) and len(line) != sum(widths): raise FabricFault(f'Fixed-width line length {len(line)} does not match configured width {sum(widths)}', fault_type='ParseDataException')
                    offset, record = 0, {}
                    for index, (name, width) in enumerate(zip(fields, widths)): record[name], offset = typed(line[offset:offset + width].rstrip(str(cfg.get('fillCharacter', ' ')) or ' '), index), offset + width
                    records.append(record)
                return {'records': records, 'recordCount':len(records)}
            records = source.get('records', source) if isinstance(source, dict) else source
            if not isinstance(records, list): records = [records]
            fill = str(cfg.get('fillCharacter', ' ') or ' ')[0]
            def fixed_field(record, name, width, index):
                value = '' if record.get(name) is None else str(record.get(name)); value = value[:width]
                return value.rjust(width, fill) if index < len(types) and types[index] in ('integer','int','long','decimal','number','float','double') else value.ljust(width, fill)
            content = line_ending.join(''.join(fixed_field(record, name, width, index) for index, (name, width) in enumerate(zip(fields, widths))) for record in records)
            if self.as_bool(cfg.get('includeFinalLineSeparator', False)): content += line_ending
            return {'content': content, 'recordCount': len(records)}
        if cfg.get('operation') == 'parse':
            text = str(source.get('content', source) if isinstance(source, dict) else source)
            lines = [line for line in text.splitlines() if line or not self.as_bool(cfg.get('skipBlankLines', True))]
            if len(delimiter) == 1:
                rows = list(csv.reader(lines, delimiter=delimiter))
            else:
                pattern = f'[{re.escape(delimiter)}]' if str(cfg.get('separatorRule', 'single')).lower() == 'any-character' else re.escape(delimiter)
                rows = [re.split(pattern, line) for line in lines]
            if self.as_bool(cfg.get('header', True)) and rows: names, rows = rows[0], rows[1:]
            else: names = fields
            if not names: raise FabricFault('Parse Data requires header fields or configured field names', fault_type='ParseDataException')
            records = []
            for row in rows:
                if self.as_bool(cfg.get('strictColumns', False)) and len(row) != len(names): raise FabricFault(f'Column count {len(row)} does not match schema field count {len(names)}', fault_type='ParseDataException')
                records.append({name: typed(row[index] if index < len(row) else '', index) for index, name in enumerate(names)})
            return {'records': records, 'recordCount':len(records), 'fields':names}
        records = source.get('records', source) if isinstance(source, dict) else source
        if not isinstance(records, list): records = [records]
        names = fields or list(records[0].keys() if records else [])
        if len(delimiter) == 1:
            output = io.StringIO(); writer = csv.DictWriter(output, fieldnames=names, delimiter=delimiter, lineterminator=line_ending)
            if self.as_bool(cfg.get('header', True)): writer.writeheader()
            writer.writerows(records); content = output.getvalue()
            if not self.as_bool(cfg.get('includeFinalLineSeparator', True)): content = content.removesuffix(line_ending)
        else:
            rows = ([delimiter.join(names)] if self.as_bool(cfg.get('header', True)) else []) + [delimiter.join('' if record.get(name) is None else str(record.get(name)) for name in names) for record in records]
            content = line_ending.join(rows) + (line_ending if self.as_bool(cfg.get('includeFinalLineSeparator', False)) else '')
        return {'content': content, 'recordCount': len(records), 'fields':names}

    async def java_worker(self, cfg, payload):
        command = cfg.get('command') or os.getenv('JAVA_WORKER_COMMAND')
        if command:
            proc = await asyncio.create_subprocess_shell(command, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
            out, err = await proc.communicate(json.dumps({'className': cfg.get('className'), 'method': cfg.get('method'), 'payload': payload}).encode())
            if proc.returncode: raise RuntimeError(err.decode() or 'Java worker failed')
            return json.loads(out.decode())
        class_name, method = str(cfg.get('className') or '').strip(), str(cfg.get('method') or '').strip()
        if not class_name or not method: raise RuntimeError('Java Invoke requires a class name and method')
        artifact = Path(str(cfg.get('artifactPath') or '')).expanduser()
        source = str(cfg.get('sourceCode') or '')
        parameters = cfg.get('parameters')
        if not isinstance(parameters, list): parameters = [cfg.get('payload', payload)]
        helper = '''import java.lang.reflect.*; public class FabricInvoker { public static void main(String[] a) throws Exception { Class<?> c=Class.forName(a[0]); Method found=null; for(Method m:c.getMethods()) if(m.getName().equals(a[1])&&m.getParameterCount()==a.length-2){found=m;break;} if(found==null) throw new NoSuchMethodException(a[0]+"."+a[1]); Object[] v=new Object[found.getParameterCount()]; Class<?>[] t=found.getParameterTypes(); for(int i=0;i<v.length;i++){String s=a[i+2]; v[i]=t[i]==String.class?s:t[i]==int.class||t[i]==Integer.class?Integer.valueOf(s):t[i]==long.class||t[i]==Long.class?Long.valueOf(s):t[i]==double.class||t[i]==Double.class?Double.valueOf(s):t[i]==boolean.class||t[i]==Boolean.class?Boolean.valueOf(s):s;} Object target=Modifier.isStatic(found.getModifiers())?null:c.getDeclaredConstructor().newInstance(); Object out=found.invoke(target,v); if(out!=null) System.out.print(out); }}'''
        with tempfile.TemporaryDirectory(prefix='fabric-java-') as folder:
            root = Path(folder); (root / 'FabricInvoker.java').write_text(helper, encoding='utf-8')
            classpath = str(root)
            compile_inputs = [str(root / 'FabricInvoker.java')]
            if source:
                java_file = root / f'{class_name.rsplit(".", 1)[-1]}.java'; java_file.write_text(source, encoding='utf-8'); compile_inputs.append(str(java_file))
            elif artifact.exists() and artifact.suffix.lower() == '.java': compile_inputs.append(str(artifact)); classpath += os.pathsep + str(artifact.parent)
            elif artifact.exists() and artifact.suffix.lower() == '.jar': classpath += os.pathsep + str(artifact)
            elif artifact.exists() and artifact.suffix.lower() == '.class': classpath += os.pathsep + str(artifact.parent)
            elif not artifact.exists(): raise RuntimeError('Java Invoke requires an existing JAR/class/source artifact or inline source')
            compiler = await asyncio.create_subprocess_exec('javac', '-cp', classpath, '-d', str(root), *compile_inputs, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
            _, compile_error = await compiler.communicate()
            if compiler.returncode: raise RuntimeError(f'Java compilation failed: {compile_error.decode().strip()}')
            args = [json.dumps(value, separators=(',', ':')) if isinstance(value, (dict, list)) else str(value) for value in parameters]
            process = await asyncio.create_subprocess_exec('java', '-cp', classpath, 'FabricInvoker', class_name, method, *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
            try: out, err = await asyncio.wait_for(process.communicate(), timeout=float(cfg.get('timeout') or 60))
            except asyncio.TimeoutError: process.kill(); raise RuntimeError('Java method invocation timed out')
            if process.returncode: raise RuntimeError(err.decode().strip() or 'Java method invocation failed')
            value = out.decode().strip()
            try: value = json.loads(value)
            except ValueError: pass
            return {'methodReturnValue': value, 'className': class_name, 'method': method}

    async def python_worker(self, cfg, payload):
        def invoke():
            function_name = str(cfg.get('function') or '').strip()
            if not function_name: raise RuntimeError('Python Invoke requires a function name')
            source, artifact = str(cfg.get('sourceCode') or ''), Path(str(cfg.get('artifactPath') or '')).expanduser()
            module_name = str(cfg.get('moduleName') or artifact.stem or 'fabric_inline')
            if source:
                namespace = {'__name__': module_name}; exec(compile(source, f'<{module_name}>', 'exec'), namespace); function = namespace.get(function_name)
            elif artifact.suffix.lower() == '.py' and artifact.exists():
                spec = importlib.util.spec_from_file_location(module_name, artifact)
                if not spec or not spec.loader: raise RuntimeError(f'Cannot load Python module {artifact}')
                module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module); function = getattr(module, function_name, None)
            elif artifact.exists():
                sys.path.insert(0, str(artifact));
                try: module = __import__(module_name, fromlist=[function_name]); function = getattr(module, function_name, None)
                finally: sys.path.pop(0)
            else: raise RuntimeError('Python Invoke requires an existing .py/package artifact or inline source')
            if not callable(function): raise RuntimeError(f'Python function {module_name}.{function_name} was not found')
            parameters = cfg.get('parameters')
            if isinstance(parameters, list): result = function(*parameters)
            elif isinstance(parameters, dict): result = function(**parameters)
            else: result = function(cfg.get('payload', payload))
            return {'result': result, 'module': module_name, 'function': function_name}
        return await asyncio.wait_for(asyncio.to_thread(invoke), timeout=float(cfg.get('timeout') or 60))
