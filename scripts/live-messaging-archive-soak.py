"""Sustained real-broker checks using generated applications in child processes."""
import argparse,asyncio,importlib.util,json,subprocess,sys,tempfile,time,zipfile
from pathlib import Path
from types import SimpleNamespace

spec=importlib.util.spec_from_file_location('live_soak',Path(__file__).with_name('live-messaging-soak.py'))
soak=importlib.util.module_from_spec(spec);spec.loader.exec_module(soak)
from app.raw_python import raw_python_files,engine_python_files

CHILD='''import asyncio,json,sys,traceback,os
sys.path.insert(0,'generated.pyifpkg')
from application import main as app
print('LIVE_PID='+str(os.getpid()),flush=True)
async def run():
    try:
        while True:
            line=sys.stdin.readline()
            if not line:break
            try:
                result=await asyncio.wait_for(app.run_task('main',json.loads(line)),60)
                print('LIVE_RESULT='+json.dumps({'ok':True,'output':result}),flush=True)
            except Exception as error:
                traceback.print_exc(file=sys.stderr)
                print('LIVE_RESULT='+json.dumps({'ok':False,'exceptionType':type(error).__name__}),flush=True)
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
asyncio.run(run())
'''


class ArchiveRuntime:
    instances=[]
    mode='python-direct'
    warmup=60
    private_diagnostics=None
    def __init__(self):
        self.child=None;self.probe=None;self.folder=None;self.samples=[];self.clean=True
        self.instances.append(self)

    async def run(self,process,initial,resources=None,project=None):
        if self.child is None:
            self.folder=tempfile.TemporaryDirectory(prefix='mina-live-archive-soak-')
            root=Path(self.folder.name)
            build=raw_python_files if self.mode=='python-direct' else engine_python_files
            with zipfile.ZipFile(root/'generated.pyifpkg','w',zipfile.ZIP_DEFLATED) as archive:
                for name,body in build(project.model_dump(),{'local':[]}).items():archive.writestr(name,body)
            self.logpath=root/'private-stderr.log';self.log=self.logpath.open('w',encoding='utf-8')
            self.child=subprocess.Popen([sys.executable,'-u','-c',CHILD],cwd=root,stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,stderr=self.log,text=True,encoding='utf-8',creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            self.probe=None;self.started=time.monotonic();self.last_sample=0
        self.child.stdin.write(json.dumps(initial)+'\n');self.child.stdin.flush()
        while True:
            line=await asyncio.to_thread(self.child.stdout.readline)
            if not line:raise RuntimeError('Generated application exited unexpectedly')
            if line.startswith('LIVE_PID='):
                self.probe=soak.psutil.Process(int(line[len('LIVE_PID='):]))
                continue
            if line.startswith('LIVE_RESULT='):break
        result=json.loads(line[len('LIVE_RESULT='):])
        if not result.get('ok'):raise RuntimeError('Generated activity failed: '+str(result.get('exceptionType')))
        if self.probe is None:raise RuntimeError('Actual generated interpreter was not identified')
        elapsed=time.monotonic()-self.started
        if elapsed>=self.warmup and elapsed-self.last_sample>=10:
            self.last_sample=elapsed
            self.samples.append({'seconds':elapsed-self.warmup,'rssMiB':self.probe.memory_info().rss/1048576,
                'handles':self.probe.num_handles() if hasattr(self.probe,'num_handles') else self.probe.num_fds(),'threads':self.probe.num_threads()})
        return SimpleNamespace(status='completed',output=result['output'])

    def close_publishers(self):
        if self.child is None:
            if hasattr(self,'log'):self.log.close()
            if self.folder is not None:self.folder.cleanup()
            return
        try:
            self.child.stdin.close()
            try:self.clean=self.child.wait(timeout=30)==0
            except subprocess.TimeoutExpired:self.child.kill();self.child.wait();self.clean=False
            self.log.close()
            if self.private_diagnostics:
                folder=Path(self.private_diagnostics);folder.mkdir(parents=True,exist_ok=True)
                (folder/f'worker-{self.child.pid}.txt').write_text(self.logpath.read_text(encoding='utf-8',errors='replace'),encoding='utf-8')
            if 'Unclosed' in self.logpath.read_text(encoding='utf-8',errors='replace'):self.clean=False
            self.child.stdout.close()
        finally:self.folder.cleanup()

    def metrics(self):
        xs=self.samples[len(self.samples)//2:]
        mx=sum(s['seconds'] for s in xs)/len(xs) if xs else 0
        my=sum(s['rssMiB'] for s in xs)/len(xs) if xs else 0
        denominator=sum((s['seconds']-mx)**2 for s in xs)
        slope=60*sum((s['seconds']-mx)*(s['rssMiB']-my) for s in xs)/denominator if denominator else 0
        growth={key:self.samples[-1][key]-self.samples[0][key] for key in ('rssMiB','handles','threads')} if self.samples else {}
        passed=bool(growth) and self.clean and growth['rssMiB']<=64 and growth['handles']<=16 and growth['threads']<=4 and slope<=.5
        return {'passed':passed,'cleanShutdown':self.clean,'actualInterpreterIdentified':self.probe is not None,
            'launcherWasSeparate':self.probe is not None and self.probe.pid!=self.child.pid,
            'growth':growth,'lateRssMiBPerMinute':slope,'samples':self.samples}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config',required=True);parser.add_argument('--output',required=True)
    parser.add_argument('--mode',choices=('python-direct','python-engine'),required=True)
    parser.add_argument('--private-diagnostics')
    args=parser.parse_args();configuration=json.loads(Path(args.config).read_text(encoding='utf-8-sig'))
    ArchiveRuntime.mode=args.mode;ArchiveRuntime.warmup=float(configuration.get('warmupSeconds',60))
    ArchiveRuntime.private_diagnostics=args.private_diagnostics
    soak.WorkflowRuntime=ArchiveRuntime
    passed=soak.run(args.config,args.output)
    report=json.loads(Path(args.output).read_text());report['mode']=args.mode
    report['archiveWorkers']=[worker.metrics() for worker in ArchiveRuntime.instances]
    report['passed']=passed and all(worker['passed'] for worker in report['archiveWorkers'])
    Path(args.output).write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'mode':args.mode,'passed':report['passed'],'cleanShutdowns':[w['cleanShutdown'] for w in report['archiveWorkers']]}),flush=True)
    sys.exit(0 if report['passed'] else 1)
