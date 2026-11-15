"""Measure complete MINA task flows, including orchestration and payload audit.

Dedicated broker resources are mandatory. No component-level timings are used
as substitutes for the end-to-end wall clock. Archive generation, import, IPC,
normal Run logs, Debug bookkeeping and final resource cleanup are included.
"""
import argparse
import asyncio
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import uuid
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))
from app.models import Project
from app.runtime import WorkflowRuntime
from app.debugger import DebugManager
from app.java_bridge import terminate_execution_processes
from app.raw_python import raw_python_files, engine_python_files

spec = importlib.util.spec_from_file_location('live_soak', ROOT / 'scripts/live-messaging-soak.py')
host = importlib.util.module_from_spec(spec); spec.loader.exec_module(host)


def record(run, index, size):
    expected = {'run': run, 'seq': index, 'text': '', 'name': 'MINA CUSTOMER',
                'country': 'US', 'total': 6, 'sku': 'item-1', 'qty': 2}
    expected['text'] = 'x' * max(0, size - len(json.dumps(expected, separators=(',', ':')).encode()))
    source = {**expected, 'name': '  mina customer  ', 'amounts': [1, 2, 3]}
    source.pop('total')
    return source, expected


def project_for(family, connection):
    rules = [{'target': key, 'source': '${vars.currentElement.' + key + '}'}
             for key in ('run', 'seq', 'text', 'name', 'country', 'sku', 'qty')]
    rules[3]['functions'] = ['trim', 'upperCase']
    rules.append({'target': 'total', 'source': '${vars.currentElement.amounts}', 'functions': ['sum']})
    activities = [{'id': 'start', 'name': 'Start', 'type': 'start'},
                  {'id': 'map', 'name': 'Transform', 'type': 'mapper', 'config': {'mappings': rules}}]
    members = ['map']
    if family != 'mapper':
        operation = {'kafka': 'publish', 'jms': 'send_message', 'ems': 'send', 'pubsub': 'publish'}[family]
        activities.append({'id': 'send', 'name': 'Publish', 'type': family, 'config': {
            'operation': operation, 'resourceId': 'connection', 'destination': '${input.destination}',
            'topic': '${input.destination}', 'message': '${last}', 'waitForDelivery': True,
            'assignCustomPartition': True, 'partitionId': 0}})
        members.append('send')
    activities.append({'id': 'end', 'name': 'End', 'type': 'end', 'config':
                       {'inputMappings': {'result': '${vars.results}'}} if family == 'mapper' else {}})
    group = {'id': 'records', 'name': 'Records', 'type': 'for_each', 'member_activity_ids': members,
             'config': {'source': '${input.records}', 'maxIterations': 10000,
                        'accumulateOutput': family == 'mapper', 'accumulatorVariable': 'results'}}
    def task(identifier, nodes, groups=None):
        return {'id': identifier, 'name': identifier, 'kind': 'subtask', 'activities': nodes, 'groups': groups or [],
                'transitions': [{'id': str(i), 'source': a['id'], 'target': b['id']}
                                for i, (a, b) in enumerate(zip(nodes, nodes[1:]))]}
    tasks = [task('publish', activities, [group])]
    resources = []
    if family != 'mapper':
        resources = [{'id': 'connection', 'name': 'Dedicated-QA', 'type': family, 'config': connection}]
        operation = {'kafka': 'get', 'jms': 'get_queue_message', 'ems': 'queue_receiver', 'pubsub': 'pull'}[family]
        cfg = {'operation': operation, 'resourceId': 'connection', 'destination': '${input.destination}',
               'topic': '${input.destination}', 'subscription': '${input.destination}',
               'maxMessages': '${input.maximum}', 'receiveTimeout': 1000 if family in ('jms', 'ems') else 2,
               'timeout': 2, 'assignCustomPartition': True, 'partitionIds': '0', 'seekPosition': 'custom',
               'customOffset': '${input.offset}', 'enableAutoCommit': False, 'groupId': '${input.group}'}
        tasks.append(task('receive', [{'id': 'start', 'name': 'Start', 'type': 'start'},
                    {'id': 'get', 'name': 'Receive', 'type': family, 'config': cfg},
                    {'id': 'end', 'name': 'End', 'type': 'end'}]))
    return Project.model_validate({'id': 'flow-throughput', 'name': 'Flow-throughput',
                                   'resources': resources, 'tasks': tasks})


CHILD = '''import asyncio,json,os,sys,traceback
sys.path.insert(0, 'generated.pyifpkg')
from application import main as app
print(json.dumps({'ready':os.getpid()}),flush=True)
async def execute():
    try:
        while True:
            line=sys.stdin.readline()
            if not line:break
            request=json.loads(line)
            try:
                output=await app.run_task(request['task'],request['input'])
                print(json.dumps({'ok':True,'output':output}),flush=True)
            except Exception as error:
                traceback.print_exc(file=sys.stderr)
                print(json.dumps({'ok':False,'exceptionType':type(error).__name__}),flush=True)
    finally:
        connectors=getattr(app,'connectors',None)
        if connectors:
            for name in ('close_kafka','close_pubsub'):
                close=getattr(connectors,name,None)
                if close:await close()
            for name in ('close_jms','close_sap'):
                close=getattr(connectors,name,None)
                if close:close()
        runtime=getattr(app,'RUNTIME',None)
        if runtime:runtime.close_publishers()
asyncio.run(execute())
'''


class Executor:
    def __init__(self, mode, project, log_path, runtime=None, manager=None):
        self.mode, self.project, self.log_path = mode, project, log_path
        self.runtime = runtime or WorkflowRuntime(); self.manager = manager or DebugManager(self.runtime)
        self.folder = None; self.child = None; self.log_count = 0

    async def start(self):
        if not self.mode.startswith('python-'): return
        self.folder = tempfile.TemporaryDirectory(prefix='mina-flow-throughput-')
        self.log = open(self.log_path, 'w', encoding='utf-8')
        build = raw_python_files if self.mode == 'python-direct' else engine_python_files
        with zipfile.ZipFile(Path(self.folder.name) / 'generated.pyifpkg', 'w', zipfile.ZIP_DEFLATED) as archive:
            for name, body in build(self.project.model_dump(), {'local': []}).items(): archive.writestr(name, body)
        self.child = subprocess.Popen([sys.executable, '-u', '-c', CHILD], cwd=self.folder.name,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=self.log, text=True, encoding='utf-8',
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        ready = json.loads(await asyncio.to_thread(self.child.stdout.readline))
        if not ready.get('ready'): raise RuntimeError('Generated application did not become ready')

    async def execute(self, task_id, initial):
        if self.child:
            def call():
                self.child.stdin.write(json.dumps({'task': task_id, 'input': initial}) + '\n'); self.child.stdin.flush()
                line = self.child.stdout.readline()
                if not line: raise RuntimeError('Generated application stopped unexpectedly')
                result = json.loads(line)
                if not result.get('ok'): raise RuntimeError('Generated task failed: ' + result.get('exceptionType', 'unknown'))
                return result['output']
            return await asyncio.to_thread(call)
        resources = {r.id: r for r in self.project.resources}
        if self.mode == 'run':
            task = next(t for t in self.project.tasks if t.id == task_id)
            result = await self.runtime.run(task, initial, resources, project=self.project)
            self.log_count += len(result.logs)
            if result.status != 'completed': raise RuntimeError('Run task failed: ' + str(result.logs[-1:]))
            return result.output
        session = self.manager.start(self.project, task_id, initial, resources, {}, [])['sessionId']
        try:
            result = await self.manager.action(session, 'resume')
            self.log_count += len(result['logs'])
            if result['status'] != 'completed': raise RuntimeError('Debug task failed: ' + str(result['logs'][-1:]))
            return result['output']
        finally:
            await asyncio.to_thread(terminate_execution_processes, session)
            await self.manager.stop(session)

    async def close(self):
        try:
            if self.child:
                try: self.child.stdin.close()
                except (BrokenPipeError, OSError): pass
                try: code = await asyncio.to_thread(self.child.wait, 30)
                except subprocess.TimeoutExpired:
                    # Only descendants of this harness-owned archive worker,
                    # never the external broker or another MINA execution.
                    try:
                        for child in host.psutil.Process(self.child.pid).children(recursive=True):
                            try: child.terminate()
                            except host.psutil.Error: pass
                    except host.psutil.Error: pass
                    self.child.kill(); await asyncio.to_thread(self.child.wait); raise RuntimeError('Archive shutdown timed out')
                self.child.stdout.close(); self.log.close()
                if code: raise RuntimeError('Archive exited unsuccessfully')
            self.runtime.close_publishers()
        finally:
            if hasattr(self, 'log') and not self.log.closed: self.log.close()
            if self.folder: self.folder.cleanup()


async def measure(args, profile):
    if args.family != 'mapper' and profile.get('dedicatedTestResources') is not True:
        raise ValueError('Explicit dedicated test resources are required')
    destinations = profile.get('destinations', [''] * args.workers)
    if len(destinations) != args.workers: raise ValueError('One dedicated destination per worker is required')
    if args.family != 'mapper' and len(set(destinations)) != len(destinations):
        raise ValueError('Worker destinations must be distinct')
    subscriptions = profile.get('subscriptions', destinations)
    if len(subscriptions) != args.workers: raise ValueError('One Pub/Sub subscription per worker is required')
    offsets = profile.get('startOffsets', [0] * args.workers)
    if len(offsets) != args.workers or any(type(n) is not int or n < 0 for n in offsets):
        raise ValueError('Supply one nonnegative Kafka starting offset per worker')
    project = project_for(args.family, profile.get('connection', {})); run = uuid.uuid4().hex
    seen = bytearray(args.records); completed = 0
    # Studio schedules concurrent jobs through one application runtime/debugger.
    # Do not accidentally benchmark independent per-job caches in these modes.
    runtime = WorkflowRuntime(); manager = DebugManager(runtime)
    executors = [Executor(args.mode, project, str(Path(args.diagnostics) / f'worker-{i}.log'), runtime, manager) for i in range(args.workers)]
    Path(args.diagnostics).mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    async def worker(i):
        nonlocal completed
        executor = executors[i]; await executor.start(); offset = offsets[i]
        for start in range(i * args.batch_size, args.records, args.workers * args.batch_size):
            indices = range(start, min(start + args.batch_size, args.records))
            values = [record(run, n, args.payload_bytes)[0] for n in indices]
            output = await executor.execute('publish', {'records': values, 'destination': destinations[i]})
            if args.family == 'mapper': received = output.get('result', output) if isinstance(output, dict) else output
            else:
                received = []
                while len(received) < len(values):
                    result = await executor.execute('receive', {'destination': subscriptions[i],
                        'maximum': len(values) - len(received), 'offset': offset + len(received), 'group': run + str(i)})
                    messages = result.get('messages', [])
                    # Direct Kafka exposes raw string values; the engine
                    # exposes message envelopes. Validate the same payload in
                    # both without changing either public output contract.
                    for message in messages:
                        value = message.get('data', message.get('body')) if isinstance(message, dict) else message
                        received.append(json.loads(value) if isinstance(value, str) else value)
                    if time.perf_counter() - started > args.deadline: raise TimeoutError('Full-flow deadline exceeded')
                offset += len(received)
            if len(received) != len(values): raise AssertionError('Unexpected record count')
            expected_indices = set(indices)
            for value in received:
                index = value.get('seq')
                if type(index) is not int or index not in expected_indices: raise AssertionError('Wrong sequence or branch')
                if seen[index]: raise AssertionError('Duplicate sequence')
                if value != record(run, index, args.payload_bytes)[1]: raise AssertionError('Mapping or transport corrupted the payload')
                seen[index] = 1
            completed += len(received)
            print(json.dumps({'verified': completed, 'seconds': round(time.perf_counter() - started, 3)}), flush=True)
    error = None
    tasks = [asyncio.create_task(worker(i)) for i in range(args.workers)]
    try: await asyncio.wait_for(asyncio.gather(*tasks), args.deadline)
    except BaseException as exc:
        error = exc
        for task in tasks: task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
    finally:
        cleanup = await asyncio.gather(*(executor.close() for executor in executors), return_exceptions=True)
        error = error or next((x for x in cleanup if isinstance(x, BaseException)), None)
    elapsed = time.perf_counter() - started
    return {'passed': error is None and completed == args.records and elapsed <= args.deadline,
            'records': completed, 'uniquePayloadsVerified': sum(seen), 'elapsedSeconds': elapsed,
            'recordsPerSecond': completed / elapsed, 'exceptionType': type(error).__name__ if error else None,
            'normalRunDebugLogEntries': sum(e.log_count for e in executors),
            'scope': 'Complete task orchestration, Mapper, validation and cleanup; archive generation/startup/IPC where applicable'
                     + ('; confirmed send and readback through receive tasks' if args.family != 'mapper' else ''),
            'errorDetailPrivate': str(error) if error else None}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--family', choices=['kafka', 'jms', 'ems', 'pubsub', 'mapper'], required=True)
    p.add_argument('--mode', choices=['run', 'debug', 'python-direct', 'python-engine'], required=True)
    p.add_argument('--records', type=int, default=100000); p.add_argument('--deadline', type=float, default=600)
    p.add_argument('--workers', type=int, default=4); p.add_argument('--batch-size', type=int, default=1000)
    p.add_argument('--payload-bytes', type=int, default=1024)
    p.add_argument('--config'); p.add_argument('--output', required=True); p.add_argument('--diagnostics', required=True)
    args = p.parse_args()
    if not 1 <= args.workers <= 8 or not 1 <= args.batch_size <= 10000 or args.records < 1 or args.deadline <= 0 or args.payload_bytes < 256: p.error('Invalid workload limits')
    if args.family != 'mapper' and not args.config: p.error('Protected dedicated broker profile required')
    release = host.keep_host_awake()
    try:
        report = asyncio.run(measure(args, json.loads(Path(args.config).read_text(encoding='utf-8-sig')) if args.config else {}))
        detail = report.pop('errorDetailPrivate')
        if detail: (Path(args.diagnostics) / 'failure.txt').write_text(detail, encoding='utf-8')
        report.update(family=args.family, mode=args.mode, targetRecords=args.records, deadlineSeconds=args.deadline,
                      workers=args.workers, batchSize=args.batch_size, approximatePayloadBytes=args.payload_bytes,
                      sharedStudioRuntime=args.mode in ('run','debug'), archiveProcesses=args.workers if args.mode.startswith('python-') else 0)
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output).write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
        print(json.dumps(report, indent=2), flush=True)
        return 0 if report['passed'] else 1
    finally: release()


if __name__ == '__main__': sys.exit(main())
