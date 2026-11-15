"""Verify explicit live test destinations in Run, Debug and both Python exports.

Supply four fresh destinations per family, in Run/Debug/Direct/Engine order.
No connection data or provider error text is copied to the public JSON report.
The config and optional private diagnostics directory must be kept out of Git.
"""
import argparse
import asyncio
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))
spec=importlib.util.spec_from_file_location('live_soak',Path(__file__).with_name('live-messaging-soak.py'))
soak=importlib.util.module_from_spec(spec)
spec.loader.exec_module(soak)
from app.debugger import DebugManager
from app.raw_python import raw_python_files,engine_python_files


def verify(config, output, private_diagnostics=None):
    specification=json.loads(Path(config).read_text(encoding='utf-8-sig'))
    results=[]
    for family in specification['families']:
        if len(family['destinations'])!=4:raise ValueError('Supply four fresh dedicated destinations per family')
        for index,mode in enumerate(('run','debug','python-direct','python-engine')):
            token=uuid.uuid4().hex
            project=soak.project_for(family['type'],family['connection'],family['destinations'][index],'mina-verify-'+uuid.uuid4().hex)
            runtime=soak.WorkflowRuntime()
            async def execute():
                resources={r.id:r for r in project.resources}
                if mode=='run':
                    result=await runtime.run(project.tasks[0],{'token':token,'offset':0},resources=resources,project=project)
                    if result.status!='completed':raise RuntimeError(json.dumps(result.logs))
                    return result.output
                manager=DebugManager(runtime)
                session=manager.start(project,'main',{'token':token,'offset':0},resources,{},[])['sessionId']
                try:
                    state=await manager.action(session,'resume')
                    if state['status']!='completed':raise RuntimeError(json.dumps(state['logs']))
                    return state['output']
                finally:await manager.stop(session)
            try:
                if index<2:result=asyncio.run(execute())
                else:
                    build=raw_python_files if mode=='python-direct' else engine_python_files
                    files=build(project.model_dump(),{'local':[]})
                    with tempfile.TemporaryDirectory(prefix='mina-live-export-') as folder:
                        for name,body in files.items():
                            target=Path(folder)/name
                            target.parent.mkdir(parents=True,exist_ok=True)
                            target.write_bytes(body)
                        process=subprocess.run([sys.executable,'-m','application.main','--task','main',
                            '--input',json.dumps({'token':token,'offset':0})],cwd=folder,capture_output=True,text=True,timeout=90)
                        if process.returncode:raise RuntimeError(process.stderr)
                        if 'Unclosed' in process.stderr:raise RuntimeError('Unclosed SDK resource: '+process.stderr)
                        result=json.loads(process.stdout.strip().splitlines()[-1])
                soak.verify_output(result,token)
                results.append({'family':family['type'],'mode':mode,'passed':True})
            except Exception as error:
                record={'family':family['type'],'mode':mode,'passed':False,'exceptionType':type(error).__name__}
                if private_diagnostics:
                    folder=Path(private_diagnostics);folder.mkdir(parents=True,exist_ok=True)
                    (folder/f'{family["type"]}-{mode}.txt').write_text(str(error),encoding='utf-8')
                results.append(record)
            finally:runtime.close_publishers()
    report={'passed':bool(results) and all(r['passed'] for r in results),'results':results,
        'scope':specification.get('scope','Explicit live test connections'),'notVerified':['Cloud Pub/Sub','Vendor EMS unless explicitly configured','Live SAP']}
    Path(output).parent.mkdir(parents=True,exist_ok=True)
    Path(output).write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report,indent=2),flush=True)
    return report['passed']


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config',required=True)
    parser.add_argument('--output',required=True)
    parser.add_argument('--private-diagnostics')
    args=parser.parse_args()
    sys.exit(0 if verify(args.config,args.output,args.private_diagnostics) else 1)
