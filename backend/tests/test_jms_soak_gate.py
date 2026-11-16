import asyncio
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from contextlib import redirect_stdout
import io
import threading
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import MagicMock
from app import java_bridge
from app.runtime import WorkflowRuntime
from app.models import SharedResource


class JmsSoakGateTests(unittest.TestCase):
    def test_receiver_cache_does_not_consume_sender_capacity(self):
        worker=MagicMock();worker.process.poll.return_value=None;worker.request.return_value={}
        java_bridge.close_jms_senders(force=True)
        with patch.object(java_bridge,'_start_jms_sender',return_value=worker),patch.object(java_bridge,'invoke',side_effect=AssertionError('Unexpected one-shot fallback')):
            try:
                for i in range(4):java_bridge.execute_jms({'_executionScope':'budget'},'receive',str(i),options={'maxMessages':2})
                for i in range(8):java_bridge.execute_jms({'_executionScope':'sender-'+str(i)},'send','queue','data')
                self.assertEqual(len(java_bridge._jms_senders),12)
            finally:java_bridge.close_jms_senders(force=True)

    def test_waiting_receive_does_not_block_another_destination(self):
        entered=threading.Event();release=threading.Event()
        def factory(*_):
            worker=MagicMock();worker.process.poll.return_value=None
            def request(operation,values,timeout):
                if values['destination']=='slow':entered.set();release.wait(5)
                return {'received':False}
            worker.request.side_effect=request;return worker
        config={'_executionScope':'queue-isolation'}
        with patch.object(java_bridge,'_start_jms_sender',side_effect=factory),ThreadPoolExecutor(max_workers=2) as pool:
            try:
                slow=pool.submit(java_bridge.execute_jms,config,'receive','slow',None,{'maxMessages':2})
                self.assertTrue(entered.wait(2))
                fast=pool.submit(java_bridge.execute_jms,config,'receive','fast',None,{'maxMessages':2})
                self.assertFalse(fast.result(timeout=1)['received']);self.assertFalse(slow.done())
            finally:
                release.set();java_bridge.close_jms_senders('queue-isolation',force=True)

    def test_late_cycle_cannot_satisfy_strict_record_target(self):
        spec=importlib.util.spec_from_file_location('activity_throughput',Path(__file__).parents[2]/'scripts/activity-throughput.py')
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        clock=[0]
        async def late(*_):
            clock[0]=601
            return {'passed':True,'records':100000,'uniqueRecordsVerified':100000,'publishSeconds':400,'receiveSeconds':201}
        args=SimpleNamespace(soak_seconds=600,cycle_interval=0,records=100000,minimum_soak_records=100000)
        with patch.object(module.time,'perf_counter',side_effect=lambda:clock[0]),patch.object(module,'broker_test',late),redirect_stdout(io.StringIO()):
            result=asyncio.run(module.broker_soak(args,{}))
        self.assertFalse(result['passed']);self.assertEqual(result['verifiedWithinWindow'],0)
        self.assertEqual(result['records'],100000)

    def test_receive_only_application_closes_its_cached_worker_scope(self):
        runtime=WorkflowRuntime()
        resource=SharedResource(id='r',type='jms',name='QA',config={'serverUrl':'qa','username':'qa','password':'qa'})
        ctx={'resources':{'r':resource},'context':{'jmsSenderScope':runtime.jms_application_scope('qa')},
             'input':{},'last':{},'vars':{},'properties':{}}
        with patch('app.runtime.execute_jms',return_value={'received':False}),patch('app.runtime.close_jms_senders') as close:
            asyncio.run(runtime.messaging('jms',{'resourceId':'r','operation':'get_queue_message','maxMessages':2},ctx))
            self.assertIsNone(runtime._jms_executor)
            runtime.close_application_senders('qa')
            close.assert_called_once_with(runtime.jms_application_scope('qa'),force=True)
            runtime.close_publishers()
            self.assertEqual(close.call_count,2)


if __name__=='__main__':unittest.main()
