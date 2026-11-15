import asyncio
import gc
import io
import subprocess
import sys
import tempfile
import threading
import time
import tracemalloc
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from app.file_operations import _read_bytes,file_activity,run_io
from app.transfer import transfer
from app.raw_python import raw_python_files,engine_python_files
from app.sftp import open_connection


class FileTransferMemoryTests(unittest.TestCase):
    def test_finished_debug_sessions_and_log_history_are_bounded(self):
        from app.debugger import DebugManager
        from app.runtime import WorkflowRuntime
        from app.models import Project,ProcessDefinition,Activity,Transition
        project=Project(id='retention',name='Retention',process=ProcessDefinition(activities=[Activity(id='s',name='Start',type='start'),Activity(id='e',name='End',type='end')],transitions=[Transition(id='edge',source='s',target='e')]))
        async def test():
            manager=DebugManager(WorkflowRuntime());manager.history_limit=2;manager.log_limit=5
            active=manager.start(project,project.tasks[0].id,{}, {}, {}, [])['sessionId'];completed=[]
            for _ in range(5):
                session=manager.start(project,project.tasks[0].id,{'file':'x'*1000000}, {}, {}, [])['sessionId']
                await manager.stop(session);completed.append(session)
            self.assertEqual(len(manager.sessions),3);self.assertIn(active,manager.sessions)
            self.assertNotIn(completed[0],manager.sessions);self.assertIn(completed[-1],manager.sessions)
            state=manager.sessions[active]
            for index in range(50):manager.runtime.log(state['logs'],'INFO',str(index))
            self.assertEqual(len(state['logs']),5)
            view=manager.view(state);self.assertGreater(view['logEntriesDropped'],0)
        asyncio.run(test())
    def test_sftp_subsystem_handshake_cannot_wait_forever(self):
        from unittest.mock import MagicMock
        closed=threading.Event();client=MagicMock()
        client.close.side_effect=closed.set
        def stalled():
            if not closed.wait(1):raise AssertionError('Subsystem timeout was not enforced')
            raise OSError('transport closed')
        client.open_sftp.side_effect=stalled
        with patch('paramiko.SSHClient',return_value=client),self.assertRaisesRegex(TimeoutError,'subsystem'):
            open_connection({'host':'test-only','timeout':.02})
        self.assertTrue(closed.is_set())
    def test_failed_reads_close_buffers_even_when_tracebacks_are_retained(self):
        original=io.BytesIO;buffers=[];errors=[]
        def buffer(*args):
            result=original(*args);buffers.append(result);return result
        source=original(b'x'*200000)
        with patch('app.file_operations.io.BytesIO',side_effect=buffer):
            try:_read_bytes(source,100000)
            except ValueError as error:errors.append(error)
        self.assertTrue(buffers);self.assertTrue(all(item.closed for item in buffers));self.assertTrue(errors[0].__traceback__)

    def test_failed_transfers_release_memory_buffers_and_connections(self):
        original=io.BytesIO;buffers=[];errors=[]
        def buffer(*args):
            result=original(*args);buffers.append(result);return result
        class FTP:
            closed=False
            def connect(self,*args,**kwargs):pass
            def login(self,*args):pass
            def set_pasv(self,*args):pass
            def retrbinary(self,command,receive):receive(b'x'*100000);raise OSError('transfer failed')
            def quit(self):pass
            def close(self):self.closed=True
        client=FTP()
        with patch('app.transfer.ftplib.FTP',return_value=client),patch('app.transfer.io.BytesIO',side_effect=buffer):
            try:transfer('ftp','get',{'remotePath':'file'})
            except OSError as error:errors.append(error)
        self.assertTrue(all(item.closed for item in buffers));self.assertTrue(client.closed);self.assertTrue(errors[0].__traceback__)

    def test_streamed_download_memory_is_bounded_and_no_temp_files_accumulate(self):
        chunk=b'x'*65536
        class FTP:
            def connect(self,*args,**kwargs):pass
            def login(self,*args):pass
            def set_pasv(self,*args):pass
            def retrbinary(self,command,receive):
                for _ in range(512):receive(chunk)
            def quit(self):pass
            def close(self):pass
        with tempfile.TemporaryDirectory() as folder,patch('app.transfer.ftplib.FTP',side_effect=lambda **kwargs:FTP()):
            path=Path(folder)/'download'
            tracemalloc.start()
            try:
                result=transfer('ftp','get',{'remotePath':'file','localPath':str(path),'maxDownloadBytes':33554432})
                _,peak=tracemalloc.get_traced_memory()
            finally:tracemalloc.stop()
            self.assertEqual(result['size'],33554432);self.assertEqual(path.stat().st_size,33554432)
            self.assertLess(peak,2*1024*1024);self.assertFalse(list(Path(folder).glob('.mina-*')))

    def test_repeated_file_reads_do_not_retain_payload_allocations(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'read';path.write_bytes(b'x'*1000000)
            tracemalloc.start()
            try:
                for _ in range(5):file_activity('read',{'path':str(path),'maxReadBytes':1000000},None)
                gc.collect();before=tracemalloc.get_traced_memory()[0]
                for _ in range(60):file_activity('read',{'path':str(path),'maxReadBytes':1000000},None)
                gc.collect();after=tracemalloc.get_traced_memory()[0]
            finally:tracemalloc.stop()
            self.assertLess(after-before,500000)

    def test_directory_limits_and_disappearing_files(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)
            for name in ('first','second','third'):(path/name).write_text('x')
            with self.assertRaisesRegex(ValueError,'maximum entries'):file_activity('list',{'path':str(path),'maxEntries':2},None)
            from app.file_operations import _file_info
            def info(item,configured):
                if item.name=='first':raise FileNotFoundError(str(item))
                return _file_info(item,configured)
            with patch('app.file_operations._file_info',side_effect=info):result=file_activity('list',{'path':str(path)},None)
            self.assertEqual(result['count'],2)
        class FTP:
            closed=False
            def connect(self,*args,**kwargs):pass
            def login(self,*args):pass
            def set_pasv(self,*args):pass
            def retrlines(self,command,entry):
                for value in ('one','two','three'):entry(value)
            def quit(self):pass
            def close(self):self.closed=True
        client=FTP()
        with patch('app.transfer.ftplib.FTP',return_value=client),self.assertRaisesRegex(ValueError,'maximum entries'):transfer('ftp','dir',{'maxEntries':2})
        self.assertTrue(client.closed)

    def test_runtime_cancelled_copy_does_not_publish(self):
        from app.runtime import WorkflowRuntime
        from app.models import Activity
        from app.file_operations import check_cancel
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);source=root/'source';source.write_text('new');target=root/'target';target.write_text('old');ready=threading.Event()
            def copying(source,stage,cancel):
                Path(stage).write_text('partial');ready.set()
                deadline=time.monotonic()+3
                while time.monotonic()<deadline:check_cancel(cancel);time.sleep(.005)
                raise AssertionError('Copy cancellation was not observed')
            async def test():
                with patch('app.file_operations._copy_file',side_effect=copying):
                    activity=Activity(id='Copy',name='Copy',type='file',config={'operation':'copy','path':str(source),'destination':str(target),'overwrite':True})
                    task=asyncio.create_task(WorkflowRuntime().execute(activity,{'input':{},'last':{},'resources':{},'properties':{},'vars':{}}))
                    self.assertTrue(await asyncio.to_thread(ready.wait,2));task.cancel()
                    with self.assertRaises(asyncio.CancelledError):await task
                    deadline=time.monotonic()+2
                    while list(root.glob('.mina-*')) and time.monotonic()<deadline:await asyncio.sleep(.005)
                self.assertEqual(target.read_text(),'old');self.assertFalse(list(root.glob('.mina-*')))
            asyncio.run(test())

    def test_cancelled_io_preserves_destination_and_closes_resources_in_both_archives(self):
        from tests.test_python_mapper_parity import PythonMapperParityTests
        project=PythonMapperParityTests().project()
        project['tasks'][0]['activities'].insert(1,{'id':'Get','name':'Get','type':'ftp','config':{'operation':'get'}})
        for compiler in (None,raw_python_files,engine_python_files):
            with self.subTest(format=compiler.__name__ if compiler else 'studio'),tempfile.TemporaryDirectory() as folder:
                if compiler:
                    for name,data in compiler(project,{'local':[]}).items():
                        path=Path(folder)/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(data)
                package='app' if compiler is None else 'application.native' if compiler is raw_python_files else 'application.engine'
                code=f'''
import asyncio,threading,time,sys
from pathlib import Path
from unittest.mock import patch
from {package}.file_operations import run_io
from {package}.transfer import transfer
folder=Path(sys.argv[1]);destination=folder/'destination';destination.write_text('original')
config={{'host':'test-only','operation':'get','remotePath':'file','localPath':str(destination),'overwrite':True}}
if {compiler is raw_python_files!r}:
 from application.core import Context,execute
 from types import SimpleNamespace
 context=Context({{}},{{}},{{'connection':SimpleNamespace(type='ftp',config={{'host':'test-only'}})}})
 async def work():return await execute('ftp',{{**config,'resourceId':'connection'}},context,'Get','Get')
else:
 from {package}.runtime import WorkflowRuntime
 from {package}.models import Activity
 async def work():return await WorkflowRuntime().execute(Activity(id='Get',name='Get',type='ftp',config=config),{{'input':{{}},'last':{{}},'resources':{{}},'properties':{{}},'vars':{{}}}})
ready=threading.Event();closed=threading.Event()
class FTP:
 def connect(self,*args,**kwargs):pass
 def login(self,*args):pass
 def set_pasv(self,*args):pass
 def retrbinary(self,command,receive):
  deadline=time.monotonic()+3
  while time.monotonic()<deadline:
   receive(b'data');ready.set();time.sleep(.005)
  raise AssertionError('Transfer cancellation was not observed')
 def quit(self):pass
 def close(self):closed.set()
async def test():
 with patch('{package}.transfer.ftplib.FTP',return_value=FTP()):
  task=asyncio.create_task(work())
  assert await asyncio.to_thread(ready.wait,2)
  task.cancel()
  try:await task
  except asyncio.CancelledError:pass
  assert await asyncio.to_thread(closed.wait,2)
  assert destination.read_text()=='original'
  assert not list(folder.glob('.mina-*'))
asyncio.run(test());print('cancelled safely')
'''
                env=__import__('os').environ.copy()
                if compiler is None:env['PYTHONPATH']=str(Path(__file__).resolve().parents[1])
                result=subprocess.run([sys.executable,'-c',code,folder],cwd=folder,env=env,capture_output=True,text=True,timeout=15)
                self.assertEqual(result.returncode,0,result.stderr);self.assertIn('cancelled safely',result.stdout)
