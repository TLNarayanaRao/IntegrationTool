"""Own a temporary official Pub/Sub emulator and qualify MINA task flows.

Supply Google's emulator JAR; it is not redistributed with MINA. Never connects
to hosted GCP. SDKs and a Java runtime are prerequisites. No credentials needed.
"""
import argparse
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import uuid

ROOT=Path(__file__).resolve().parents[1]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--jar',required=True);parser.add_argument('--java',default='java')
    parser.add_argument('--port',type=int,default=18085);parser.add_argument('--records',type=int,default=100000)
    parser.add_argument('--workers',type=int,default=4);parser.add_argument('--soak-seconds',type=float,default=600)
    parser.add_argument('--output-dir',required=True)
    args=parser.parse_args()
    jar=Path(args.jar).resolve()
    if not jar.is_file() or not 1<=args.port<=65535 or not 1<=args.workers<=8 or args.records<1 or args.soak_seconds<0:parser.error('Invalid JAR, port or workload limits')
    with socket.socket() as probe:
        if probe.connect_ex(('127.0.0.1',args.port))==0:raise RuntimeError('Port already in use; refusing to reuse or stop another server')
    out=Path(args.output_dir).resolve();out.mkdir(parents=True,exist_ok=True)
    host=f'127.0.0.1:{args.port}';previous=os.environ.get('PUBSUB_EMULATOR_HOST')
    os.environ['PUBSUB_EMULATOR_HOST']=host
    process=None;publisher=None;subscriber=None;resources=[];results=[]
    log=(out/'emulator.log').open('w',encoding='utf-8')
    def cleanup():
        for topic,sub in resources[:]:
            try:subscriber.delete_subscription(request={'subscription':sub},retry=None,timeout=5)
            except Exception:pass
            try:publisher.delete_topic(request={'topic':topic},retry=None,timeout=5)
            except Exception:pass
            resources.remove((topic,sub))
    try:
        process=subprocess.Popen([args.java,'-Xmx1024m','-jar',str(jar),'--host=127.0.0.1',f'--port={args.port}','--projects=mina-qa'],
            stdout=log,stderr=subprocess.STDOUT,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        ready=time.monotonic()+60
        while True:
            if process.poll() is not None:raise RuntimeError('Emulator exited; inspect the local emulator log')
            with socket.socket() as probe:
                if probe.connect_ex(('127.0.0.1',args.port))==0:break
            if time.monotonic()>ready:raise TimeoutError('Emulator startup timed out')
            time.sleep(.1)
        from google.cloud import pubsub_v1
        publisher=pubsub_v1.PublisherClient();subscriber=pubsub_v1.SubscriberClient()
        def provision(count):
            topics=[];subs=[]
            for _ in range(count):
                topic=publisher.topic_path('mina-qa','mina-qa-'+uuid.uuid4().hex)
                sub=subscriber.subscription_path('mina-qa','mina-qa-'+uuid.uuid4().hex)
                publisher.create_topic(request={'name':topic});resources.append((topic,sub))
                subscriber.create_subscription(request={'name':sub,'topic':topic,'ack_deadline_seconds':60})
                topics.append(topic.rsplit('/',1)[1]);subs.append(sub.rsplit('/',1)[1])
            return topics,subs
        connection={'projectId':'mina-qa','authenticationType':'Emulator','emulatorHost':host}
        with tempfile.TemporaryDirectory(prefix='mina-pubsub-qa-') as folder:
            for mode in ('run','debug','python-direct','python-engine'):
                topics,subs=provision(args.workers);profile=Path(folder)/'profile.json'
                profile.write_text(json.dumps({'dedicatedTestResources':True,'connection':connection,'destinations':topics,'subscriptions':subs}))
                report=out/(mode+'.json')
                with (out/(mode+'.log')).open('w',encoding='utf-8') as output:
                    result=subprocess.run([sys.executable,str(ROOT/'scripts/flow-throughput.py'),'--family','pubsub','--mode',mode,
                        '--config',str(profile),'--records',str(args.records),'--workers',str(args.workers),
                        '--output',str(report),'--diagnostics',str(out/(mode+'-diagnostics'))],cwd=ROOT,stdout=output,stderr=subprocess.STDOUT,timeout=720)
                results.append({'mode':mode,'passed':result.returncode==0 and report.exists() and json.loads(report.read_text())['passed']})
                cleanup()
            if args.soak_seconds:
                topics,subs=provision(1);profile=Path(folder)/'soak.json'
                profile.write_text(json.dumps({'dedicatedTestResources':True,'connection':connection,'destination':topics[0],'subscription':subs[0]}))
                with (out/'soak.log').open('w',encoding='utf-8') as output:
                    result=subprocess.run([sys.executable,str(ROOT/'scripts/activity-throughput.py'),'--family','pubsub','--operation','publish',
                        '--config',str(profile),'--records',str(min(args.records,2000)),'--concurrency','32','--soak-seconds',str(args.soak_seconds),
                        '--cycle-interval','10','--minimum-soak-records',str(args.records),'--output',str(out/'soak.json')],cwd=ROOT,
                        stdout=output,stderr=subprocess.STDOUT,timeout=args.soak_seconds+720)
                results.append({'mode':'soak','passed':result.returncode==0})
        summary={'passed':all(row['passed'] for row in results),'environment':'Official local emulator; hosted GCP unverified','results':results}
        (out/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
        return 0 if summary['passed'] else 1
    finally:
        if publisher and subscriber and process and process.poll() is None:cleanup()
        if publisher:
            try:publisher.transport.close()
            except Exception:pass
        if subscriber:
            try:subscriber.close()
            except Exception:pass
        if process and process.poll() is None:
            process.terminate()
            try:process.wait(timeout=10)
            except subprocess.TimeoutExpired:process.kill();process.wait()
        log.close()
        if previous is None:os.environ.pop('PUBSUB_EMULATOR_HOST',None)
        else:os.environ['PUBSUB_EMULATOR_HOST']=previous


if __name__=='__main__':sys.exit(main())
