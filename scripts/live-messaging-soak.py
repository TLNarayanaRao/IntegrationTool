"""Live broker round-trip qualification using explicitly supplied test connections.

Never use production destinations. The config is private and is not copied to
the report. Each family requires a dedicated existing topic/queue per worker.
Broker provisioning and cloud/SAP qualification are separate operations.
"""
import argparse
import asyncio
from collections import Counter, deque
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import sys
import threading
import time
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
import psutil
from app.models import Project
from app.runtime import WorkflowRuntime


def keep_host_awake():
    """Hold a thread-scoped Windows system request; do not change power plans."""
    if os.name != 'nt': return lambda: None
    import ctypes
    api=ctypes.WinDLL('kernel32',use_last_error=True).SetThreadExecutionState
    api.argtypes=[ctypes.c_uint];api.restype=ctypes.c_uint
    previous=api(0x80000001)  # ES_CONTINUOUS | ES_SYSTEM_REQUIRED; display may sleep.
    if not previous: raise ctypes.WinError(ctypes.get_last_error())
    return lambda: api(previous)


def sampling_continuity(samples,duration):
    max_gap=max((b['seconds']-a['seconds'] for a,b in zip(samples,samples[1:])),default=0)
    complete=bool(samples) and samples[0]['seconds']<=15 and samples[-1]['seconds']>=duration-15 and max_gap<=60
    return complete,max_gap


def project_for(family, connection, destination, group):
    if family not in ('kafka', 'jms', 'ems', 'amqp'):
        raise ValueError('This harness qualifies Kafka/JMS/EMS/AMQP, not Pub/Sub or SAP')
    send, receive = ({'kafka': ('publish', 'get'), 'jms': ('send_message', 'get_queue_message'),
        'ems': ('send', 'queue_receiver'), 'amqp': ('send', 'get')})[family]
    common = {'resourceId': 'connection', 'topic': destination, 'destination': destination, 'queueName': destination}
    send_cfg = {**common, 'operation': send, 'message': '${input.token}', 'body': '${input.token}', 'waitForDelivery': True}
    receive_cfg = {**common, 'operation': receive, 'groupId': group, 'maxMessages': 1,
        'receiveTimeout': 5000, 'receiveTimeoutSeconds': 5, 'timeout': 5, 'timeoutMs': 5000}
    if family == 'kafka':
        # The verifier seeks partition 0 explicitly. Pin its producer too,
        # rather than depending on the broker's auto-created partition count.
        send_cfg.update(assignCustomPartition=True, partitionId=0)
        receive_cfg.update(assignCustomPartition=True, partitionIds='0', seekPosition='custom', customOffset='${input.offset}')
    return Project.model_validate({'id': group, 'name': 'Live-messaging-qualification', 'resources': [
        {'id': 'connection', 'name': 'Explicit-test-connection', 'type': family, 'config': connection}], 'tasks': [{
        'id': 'main', 'name': 'Round-trip', 'kind': 'subtask', 'activities': [
            {'id': 'start', 'name': 'Start', 'type': 'start'},
            {'id': 'send', 'name': 'Send', 'type': family, 'config': send_cfg},
            {'id': 'receive', 'name': 'Receive', 'type': family, 'config': receive_cfg},
            {'id': 'end', 'name': 'End', 'type': 'end'}],
        'transitions': [{'id': str(i), 'source': a, 'target': b} for i, (a,b) in enumerate(
            [('start','send'), ('send','receive'), ('receive','end')])]}]})


def verify_output(output, token):
    def values(value):
        if isinstance(value, dict):
            for child in value.values(): yield from values(child)
        elif isinstance(value, list):
            for child in value: yield from values(child)
        else: yield value
    if token not in values(output): raise AssertionError('Round-trip payload missing or differs from sent token')


def run(config_path, output_path, private_diagnostics=None):
    specification = json.loads(Path(config_path).read_text(encoding='utf-8-sig'))
    duration = float(specification.get('durationSeconds', 1800))
    warmup = float(specification.get('warmupSeconds', 60))
    interval = float(specification.get('minimumCycleSeconds', .5))
    if duration <= 0 or warmup < 0: raise ValueError('Invalid duration')
    if interval < 0: raise ValueError('Invalid minimum cycle interval')
    cases = []
    for family in specification['families']:
        for index, destination in enumerate(family['destinations']):
            cases.append((family['type'], project_for(family['type'], family['connection'], destination,
                'mina-live-' + uuid.uuid4().hex)))
    if not cases or len(cases) > 32: raise ValueError('Supply 1..32 dedicated worker destinations')
    runtimes = [WorkflowRuntime() for _ in cases]
    counts, errors, timings = Counter(), [], {}
    lock, stop = threading.Lock(), threading.Event()
    started = time.monotonic()
    process = psutil.Process()
    samples = []

    def worker(index):
        family, project = cases[index]
        async def execute():
            offset = 0
            while not stop.is_set():
                token = uuid.uuid4().hex
                began = time.monotonic()
                result = await runtimes[index].run(project.tasks[0], {'token': token, 'offset': offset},
                    resources={r.id:r for r in project.resources}, project=project)
                if result.status != 'completed':
                    if private_diagnostics:
                        folder=Path(private_diagnostics);folder.mkdir(parents=True,exist_ok=True)
                        (folder/f'worker-{index}.json').write_text(json.dumps(result.logs,indent=2),encoding='utf-8')
                    raise RuntimeError('Activity failed; consult the private runtime log for diagnostic detail')
                verify_output(result.output, token)
                offset += 1
                with lock:
                    counts[family] += 1
                    timings.setdefault(family, deque(maxlen=10000)).append((time.monotonic()-began)*1000)
                await asyncio.sleep(max(0,interval-(time.monotonic()-began)))
        try: asyncio.run(execute())
        except Exception as error:
            # Avoid copying credentials, payloads or provider exception strings.
            with lock: errors.append({'family': family, 'exceptionType': type(error).__name__, 'worker': index})
            stop.set()

    release_awake=keep_host_awake()
    try:
        with ThreadPoolExecutor(max_workers=len(cases), thread_name_prefix='mina-live-soak') as pool:
            jobs = [pool.submit(worker, index) for index in range(len(cases))]
            while not stop.is_set() and time.monotonic()-started < warmup+duration:
                elapsed = time.monotonic()-started
                if elapsed >= warmup:
                    info = process.memory_info()
                    children = process.children(recursive=True)
                    child_rss = 0
                    for child in children:
                        try: child_rss += child.memory_info().rss
                        except psutil.Error: pass
                    samples.append({'seconds': round(elapsed-warmup,2), 'rssMiB': info.rss/1048576,
                        'handles': process.num_handles() if hasattr(process,'num_handles') else process.num_fds(),
                        'threads': process.num_threads(), 'childProcesses':len(children), 'childRssMiB':child_rss/1048576})
                    if len(samples)%6 == 0:
                        with lock: print(json.dumps({'measuredSeconds':samples[-1]['seconds'],'roundTrips':dict(counts)}),flush=True)
                stop.wait(min(10,max(.01,warmup+duration-elapsed)))
            stop.set()
            for job in jobs: job.result()
    finally:
        try:
            for runtime in runtimes: runtime.close_publishers()
        finally: release_awake()
    actual = time.monotonic()-started-warmup
    first, last = (samples[0], samples[-1]) if samples else ({'rssMiB':0,'handles':0,'threads':0},)*2
    tail=samples[len(samples)//2:]
    xs=[s['seconds']/60 for s in tail]; ys=[s['rssMiB'] for s in tail]
    mx=sum(xs)/len(xs) if xs else 0; my=sum(ys)/len(ys) if ys else 0
    denominator=sum((x-mx)**2 for x in xs)
    slope=sum((x-mx)*(y-my) for x,y in zip(xs,ys))/denominator if denominator else 0
    growth={key:last[key]-first[key] for key in ('rssMiB','handles','threads')}
    continuous,max_gap=sampling_continuity(samples,duration)
    gates={'duration':actual>=duration-1,'continuousSampling':continuous,'noErrors':not errors,'allFamilies':all(counts[f] for f,_ in cases),
        'rssGrowth':growth['rssMiB']<=128,'lateRssSlope':slope<=.5,'handleGrowth':growth['handles']<=24,'threadGrowth':growth['threads']<=8}
    report={'passed':all(gates.values()),'gates':gates,'measuredSeconds':round(actual,2),'warmupSeconds':warmup,
        'workers':len(cases),'minimumCycleSecondsPerWorker':interval,'maxSampleGapSeconds':max_gap,'roundTripsIncludingWarmup':dict(counts),'errors':errors,'growth':growth,
        'lateRssMiBPerMinute':slope,'latencySampleMaxPerFamily':10000,'samples':samples,
        'scope':specification.get('scope','Operator-supplied test connections'),
        'sourceSha256':{name:hashlib.sha256((Path(__file__).resolve().parents[1]/name).read_bytes()).hexdigest()
            for name in ('backend/app/runtime.py','backend/app/amqp.py','backend/app/java_bridge.py')}}
    Path(output_path).parent.mkdir(parents=True,exist_ok=True)
    Path(output_path).write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k!='samples'},indent=2),flush=True)
    return report['passed']


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config',required=True)
    parser.add_argument('--output',required=True)
    parser.add_argument('--private-diagnostics')
    args=parser.parse_args()
    sys.exit(0 if run(args.config,args.output,args.private_diagnostics) else 1)
