from __future__ import annotations
import asyncio, json, os, subprocess, uuid
from datetime import datetime, timezone
from pathlib import Path
import httpx
from .models import Activity, ProcessDefinition, RunResult

class RuntimeErrorWithLogs(Exception): pass

class WorkflowRuntime:
    async def run(self, process: ProcessDefinition, initial: dict) -> RunResult:
        run_id, logs, context = str(uuid.uuid4()), [], {'input': initial, 'vars': {}, 'last': initial}
        activity_by_id = {a.id: a for a in process.activities}
        incoming = {t.target for t in process.transitions}
        starts = [a for a in process.activities if a.type == 'start'] or [a for a in process.activities if a.id not in incoming]
        if len(starts) != 1:
            return RunResult(run_id=run_id, status='failed', output={}, logs=[{'level':'ERROR','message':'Process must have exactly one Start activity'}])
        current = starts[0]
        try:
            for _ in range(len(process.activities) + 1):
                self.log(logs, 'INFO', f'Executing {current.name}', current.id)
                context['last'] = await self.execute(current, context)
                next_steps = [t.target for t in process.transitions if t.source == current.id]
                if current.type == 'end': break
                if len(next_steps) != 1: raise RuntimeErrorWithLogs(f'{current.name} must have one outgoing transition')
                current = activity_by_id[next_steps[0]]
            return RunResult(run_id=run_id, status='completed', output=context['last'] if isinstance(context['last'], dict) else {'result': context['last']}, logs=logs)
        except Exception as exc:
            self.log(logs, 'ERROR', str(exc), current.id)
            return RunResult(run_id=run_id, status='failed', output={}, logs=logs)

    def log(self, logs, level, message, activity_id=None):
        logs.append({'time': datetime.now(timezone.utc).isoformat(), 'level': level, 'message': message, 'activityId': activity_id})

    async def execute(self, activity: Activity, ctx: dict):
        cfg = activity.config
        if activity.type in ('start', 'end'): return ctx['last']
        if activity.type == 'log': return ctx['last']
        if activity.type == 'transform':
            # Simple deterministic field mapping. Full expressions are intentionally evaluated by a future safe expression engine.
            result = dict(ctx['last']) if isinstance(ctx['last'], dict) else {'value': ctx['last']}
            for target, source in cfg.get('mappings', {}).items(): result[target] = self.resolve(source, ctx)
            return result
        if activity.type == 'http':
            method, url = cfg.get('method','GET'), self.resolve(cfg.get('url',''), ctx)
            async with httpx.AsyncClient(timeout=float(cfg.get('timeout', 30))) as client:
                response = await client.request(method, url, headers=cfg.get('headers', {}), json=cfg.get('body') or None)
                response.raise_for_status()
                try: return response.json()
                except ValueError: return {'statusCode': response.status_code, 'body': response.text}
        if activity.type == 'file':
            path = Path(self.resolve(cfg.get('path',''), ctx)).expanduser()
            if cfg.get('operation','read') == 'write':
                path.parent.mkdir(parents=True, exist_ok=True); path.write_text(json.dumps(ctx['last'], indent=2)); return {'path': str(path), 'written': True}
            return {'path': str(path), 'content': path.read_text()}
        if activity.type == 'kafka':
            try:
                from confluent_kafka import Producer
            except ImportError: raise RuntimeError('Kafka requires optional package confluent-kafka')
            producer = Producer({'bootstrap.servers': cfg['bootstrapServers']}); producer.produce(cfg['topic'], json.dumps(ctx['last']).encode()); producer.flush(); return ctx['last']
        if activity.type == 'java': return await self.java_worker(cfg, ctx['last'])
        raise RuntimeError(f'Unsupported activity type {activity.type}')

    def resolve(self, value, ctx):
        if isinstance(value, str) and value.startswith('${input.'):
            return ctx['input'].get(value[8:-1], '')
        if isinstance(value, str) and value.startswith('${vars.'):
            return ctx['vars'].get(value[7:-1], '')
        return value

    async def java_worker(self, cfg, payload):
        command = cfg.get('command') or os.getenv('JAVA_WORKER_COMMAND')
        if not command: raise RuntimeError('Java activity requires a configured command or JAVA_WORKER_COMMAND')
        proc = await asyncio.create_subprocess_shell(command, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        out, err = await proc.communicate(json.dumps({'className': cfg.get('className'), 'payload': payload}).encode())
        if proc.returncode: raise RuntimeError(err.decode() or 'Java worker failed')
        return json.loads(out.decode())
