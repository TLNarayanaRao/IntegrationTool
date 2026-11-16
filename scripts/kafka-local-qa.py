"""Qualify complete MINA flows against an isolated actual Apache Kafka broker.

Supply an extracted Apache Kafka 3.9 distribution and Java 17. The distribution
is not bundled with MINA. All listeners are loopback-only; every invocation owns
fresh storage and topics. No existing broker is contacted or stopped.
"""
import argparse
import asyncio
import base64
import json
from pathlib import Path
import socket
import subprocess
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--kafka-home', required=True)
    parser.add_argument('--java', default='java')
    parser.add_argument('--port', type=int, default=29092)
    parser.add_argument('--controller-port', type=int, default=29093)
    parser.add_argument('--records', type=int, default=100000)
    parser.add_argument('--workers', type=int, default=4)
    parser.add_argument('--output-dir', required=True)
    args = parser.parse_args()
    home = Path(args.kafka_home).resolve()
    if not (home / 'libs').is_dir() or not list((home / 'libs').glob('kafka_2.13-3.9*.jar')):
        parser.error('An extracted Apache Kafka 3.9 distribution is required')
    if args.records < 1 or not 1 <= args.workers <= 8:
        parser.error('Invalid workload limits')
    if args.port == args.controller_port or any(not 1 <= p <= 65535 for p in (args.port, args.controller_port)):
        parser.error('Two distinct valid listener ports are required')
    for port in (args.port, args.controller_port):
        with socket.socket() as probe:
            if probe.connect_ex(('127.0.0.1', port)) == 0:
                raise RuntimeError('Port already in use; refusing to reuse another server')
    out = Path(args.output_dir).resolve()
    if any((out / name).exists() for name in ('summary.json', 'run.json', 'debug.json', 'python-direct.json', 'python-engine.json')):
        parser.error('Use a fresh output directory to preserve previous qualification evidence')
    out.mkdir(parents=True, exist_ok=True)
    instance = out / ('broker-' + uuid.uuid4().hex)
    instance.mkdir()
    config = instance / 'server.properties'
    config.write_text('\n'.join([
        'process.roles=broker,controller', 'node.id=1',
        f'controller.quorum.voters=1@127.0.0.1:{args.controller_port}',
        f'listeners=PLAINTEXT://127.0.0.1:{args.port},CONTROLLER://127.0.0.1:{args.controller_port}',
        f'advertised.listeners=PLAINTEXT://127.0.0.1:{args.port}',
        'controller.listener.names=CONTROLLER',
        'listener.security.protocol.map=CONTROLLER:PLAINTEXT,PLAINTEXT:PLAINTEXT',
        'inter.broker.listener.name=PLAINTEXT', 'num.partitions=1',
        'offsets.topic.replication.factor=1', 'transaction.state.log.replication.factor=1',
        'transaction.state.log.min.isr=1', 'group.initial.rebalance.delay.ms=0',
        'auto.create.topics.enable=false', 'log.retention.hours=24',
        'log.retention.bytes=1073741824', 'log.segment.bytes=134217728',
        f'log.dirs={(instance / "data").as_posix()}', ''
    ]), encoding='utf-8')
    java = [args.java, '-Xms256m', '-Xmx1024m',
            f'-Dlog4j.configuration={(home / "config/log4j.properties").as_uri()}',
            f'-Dkafka.logs.dir={instance.as_posix()}', '-cp', str(home / 'libs/*')]
    flags = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
    results = []
    broker = None
    summary = {'passed': False, 'environment': 'Actual local Apache Kafka, single-node KRaft',
               'recordsPerMode': args.records, 'deadlineSeconds': 600, 'results': results,
               'brokerStopped': False, 'kafkaDistribution': home.name,
               'workers': args.workers, 'partitionsPerTopic': 1,
               'security': 'Loopback PLAINTEXT test fixture; TLS/SASL not qualified'}
    try:
        with (instance / 'format.log').open('w', encoding='utf-8') as log:
            subprocess.run(java + ['kafka.tools.StorageTool', 'format', '-t',
                base64.urlsafe_b64encode(uuid.uuid4().bytes).decode().rstrip('='), '-c', str(config)],
                check=True, stdout=log, stderr=subprocess.STDOUT, timeout=60, creationflags=flags)
        with (instance / 'server.log').open('w', encoding='utf-8') as log:
            broker = subprocess.Popen(java + ['kafka.Kafka', str(config)], stdout=log,
                                      stderr=subprocess.STDOUT, creationflags=flags)
        address = f'127.0.0.1:{args.port}'
        async def provision():
            from aiokafka.admin import AIOKafkaAdminClient, NewTopic
            deadline = time.monotonic() + 60
            while True:
                if broker.poll() is not None:
                    raise RuntimeError('Temporary broker exited; inspect its local server log')
                admin = AIOKafkaAdminClient(bootstrap_servers=address, request_timeout_ms=3000)
                try:
                    await admin.start()
                    names = ['mina-qa-' + uuid.uuid4().hex for _ in range(args.workers * 4)]
                    await admin.create_topics([NewTopic(n, 1, 1) for n in names])
                    return names
                except Exception:
                    if time.monotonic() >= deadline:
                        raise
                    await asyncio.sleep(.5)
                finally:
                    await admin.close()
        topics = asyncio.run(provision())
        for index, mode in enumerate(('run', 'debug', 'python-direct', 'python-engine')):
            profile = instance / (mode + '-profile.json')
            profile.write_text(json.dumps({'dedicatedTestResources': True,
                'connection': {'bootstrapServers': address, 'securityProtocol': 'PLAINTEXT'},
                'destinations': topics[index * args.workers:(index + 1) * args.workers]}), encoding='utf-8')
            report = out / (mode + '.json')
            print(f'Starting {mode}: {args.records} records', flush=True)
            with (out / (mode + '.log')).open('w', encoding='utf-8') as log:
                result = subprocess.run([sys.executable, str(ROOT / 'scripts/flow-throughput.py'),
                    '--family', 'kafka', '--mode', mode, '--config', str(profile),
                    '--records', str(args.records), '--workers', str(args.workers),
                    '--output', str(report), '--diagnostics', str(out / (mode + '-diagnostics'))],
                    cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, timeout=720, creationflags=flags)
            row = json.loads(report.read_text()) if report.exists() else {}
            passed = result.returncode == 0 and row.get('passed') is True
            results.append({'mode': mode, 'passed': passed, 'report': report.name,
                            'elapsedSeconds': row.get('elapsedSeconds')})
            print(json.dumps(results[-1]), flush=True)
        summary['passed'] = all(row['passed'] for row in results) and len(results) == 4
    finally:
        if broker is not None:
            if broker.poll() is None:
                broker.terminate()
                try:
                    broker.wait(timeout=30)
                except subprocess.TimeoutExpired:
                    broker.kill()
                    broker.wait(timeout=10)
            summary['brokerStopped'] = broker.poll() is not None
        (out / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n', encoding='utf-8')
    return 0 if summary['passed'] else 1


if __name__ == '__main__':
    sys.exit(main())
