"""Test measurement bookkeeping without pretending to contact SAP."""
from contextlib import redirect_stdout
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
import asyncio
from unittest.mock import MagicMock, patch


class SoakHarnessTests(unittest.TestCase):
    def load_script(self,name):
        path=Path(__file__).parents[2]/'scripts'/name
        spec=importlib.util.spec_from_file_location(name.replace('-','_'),path)
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        return module

    def test_archive_probe_uses_self_reported_interpreter_not_launcher(self):
        from app.models import Project
        module=self.load_script('live-messaging-archive-soak.py')
        project=Project.model_validate({'id':'probe','name':'Probe','tasks':[{'id':'main','name':'Main',
            'kind':'subtask','activities':[{'id':'start','name':'Start','type':'start'}],'transitions':[]}]})
        child=MagicMock();child.pid=111;child.wait.return_value=0
        child.stdout.readline.side_effect=['LIVE_PID=222\n','LIVE_RESULT={"ok":true,"output":{"value":42}}\n']
        probe=MagicMock();probe.pid=222
        runtime=module.ArchiveRuntime()
        try:
            with patch.object(module.subprocess,'Popen',return_value=child),patch.object(module.soak.psutil,'Process',return_value=probe) as create_probe:
                result=asyncio.run(runtime.run(project.tasks[0],{},project=project))
            self.assertEqual(result.output,{'value':42})
            create_probe.assert_called_once_with(222)
            self.assertIs(runtime.probe,probe)
        finally:runtime.close_publishers()

    def test_interrupted_or_incomplete_sampling_cannot_pass_duration(self):
        module=self.load_script('live-messaging-soak.py')
        def samples(*seconds):return [{'seconds':value} for value in seconds]
        self.assertTrue(module.sampling_continuity(samples(0,10,20,30),30)[0])
        for points,duration in ((samples(0,10),1800),(samples(500,510),510),(samples(0,10,500,510),510),([],1800)):
            self.assertFalse(module.sampling_continuity(points,duration)[0])

    @unittest.skipUnless(__import__('os').name=='nt','Windows execution-state request')
    def test_awake_request_restores_previous_thread_state(self):
        module=self.load_script('live-messaging-soak.py')
        kernel=MagicMock()
        kernel.SetThreadExecutionState.side_effect=[0x80000000,0x80000001]
        with patch('ctypes.WinDLL',return_value=kernel):
            release=module.keep_host_awake();release()
        self.assertEqual([call.args[0] for call in kernel.SetThreadExecutionState.call_args_list],[0x80000001,0x80000000])

    def test_sap_measurements_are_bounded_and_keep_total_failure_count(self):
        path=Path(__file__).parents[2]/'scripts/sap-production-soak.py'
        spec=importlib.util.spec_from_file_location('sap_soak_measurement_test',path)
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        for failed in (False,True):
            adapter=MagicMock();adapter.client_pools={}
            if failed:adapter.execute.side_effect=RuntimeError('Injected harness-only error')
            with tempfile.TemporaryDirectory() as directory:
                config,output=Path(directory)/'config.json',Path(directory)/'result.json'
                config.write_text(json.dumps({'durationSeconds':1,'concurrency':1}))
                with patch.object(module,'SapAdapter',return_value=adapter), patch('sys.argv',
                        ['sap-production-soak.py','--config',str(config),'--output',str(output)]), redirect_stdout(io.StringIO()):
                    result=module.main()
                report=json.loads(output.read_text())
            adapter.close_all.assert_called_once()
            self.assertEqual(result,1 if failed else 0)
            self.assertEqual(report['passed'],not failed)
            self.assertLessEqual(len(report['errors']),1000)
            self.assertGreaterEqual(report['failedCalls'],len(report['errors']))
            self.assertEqual(report['quantileSampleLimit'],10000)
