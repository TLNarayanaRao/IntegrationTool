"""Repeat live round trips through MINA's Debug manager, without a GUI claim."""
import argparse,asyncio,importlib.util,json,sys
from pathlib import Path
from types import SimpleNamespace

spec=importlib.util.spec_from_file_location('live_soak',Path(__file__).with_name('live-messaging-soak.py'))
soak=importlib.util.module_from_spec(spec);spec.loader.exec_module(soak)
from app.debugger import DebugManager
from app.java_bridge import terminate_execution_processes


class DebugRuntime(soak.WorkflowRuntime):
    def __init__(self):
        super().__init__()
        self.manager=DebugManager(self)

    async def run(self,process,initial,resources=None,project=None):
        session=self.manager.start(project,process.id,initial,resources or {},{},[])['sessionId']
        try:
            state=await self.manager.action(session,'resume')
            return SimpleNamespace(status=state['status'],output=state['output'],logs=state['logs'])
        finally:
            # Match Studio's Stop lifecycle; DebugManager.stop itself only
            # unwinds frames/groups and does not own native execution workers.
            await asyncio.to_thread(terminate_execution_processes,session)
            await self.manager.stop(session)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config',required=True);parser.add_argument('--output',required=True)
    parser.add_argument('--private-diagnostics')
    args=parser.parse_args();soak.WorkflowRuntime=DebugRuntime
    passed=soak.run(args.config,args.output,args.private_diagnostics)
    report=json.loads(Path(args.output).read_text());report['mode']='debug'
    report['scopeNote']='Automated DebugManager sessions, not an interactive Studio UI soak'
    Path(args.output).write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    sys.exit(0 if passed else 1)
