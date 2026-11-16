"""Sender configuration regressions; no live-cloud throughput claims."""
import asyncio
import unittest
import types
from unittest.mock import MagicMock, patch
from app import google_pubsub
from app.models import SharedResource
from app.runtime import WorkflowRuntime
from app.raw_python import raw_python_files


class FakePublisher:
    def __init__(self, **kwargs):
        self.kwargs = kwargs; self.transport = MagicMock()
        self.publish = MagicMock(); self.publish.return_value.result.return_value = 'confirmed'
    def topic_path(self, project, topic): return f'projects/{project}/topics/{topic}'
    def stop(self): pass


class SenderSettingsTests(unittest.TestCase):
    def test_native_pubsub_zero_delay_uses_one_ms_floor_not_ten_ms_default(self):
        with patch.object(google_pubsub, 'client_configuration', return_value=({}, 'qa')):
            for setting, expected in [(0,.001),(None,.01),('',.01),(20,.02)]:
                with self.subTest(setting=setting):
                    client = google_pubsub.create_client(FakePublisher, {'batchDelayThresholdMilliseconds': setting})
                    self.assertEqual(client.kwargs['batch_settings'].max_latency, expected)

    def test_runtime_activity_zero_overrides_shared_connection_delay(self):
        async def exercise():
            runtime = WorkflowRuntime(); client = FakePublisher()
            resource = SharedResource(id='p', name='QA', type='pubsub', config={
                'projectId':'qa', 'batchDelayThresholdMilliseconds':30})
            ctx={'resources':{'p':resource},'input':{},'last':{},'properties':{},'vars':{},'context':{}}
            try:
                with patch('app.runtime.create_pubsub_client', return_value=client) as create:
                    result=await runtime.messaging('pubsub', {'resourceId':'p','topic':'qa',
                        'waitForDelivery':True,'batchDelayThresholdMilliseconds':0},ctx)
                    self.assertTrue(result['deliveryConfirmed'])
                    self.assertEqual(create.call_args.args[1]['batchDelayThresholdMilliseconds'],0)
            finally: runtime.close_publishers()
        asyncio.run(exercise())

    def test_direct_adapter_preserves_zero_override_in_sdk_settings(self):
        files=raw_python_files({'id':'qa','name':'QA','resources':[], 'tasks':[{'id':'main','name':'Main',
            'kind':'subtask','activities':[{'id':'p','name':'Publish','type':'pubsub','config':{'operation':'publish'}}],
            'transitions':[],'groups':[]}]},{'local':[]})
        generated=types.ModuleType('generated_sender')
        exec(compile(files['application/connectors.py'],'generated-connectors.py','exec'),generated.__dict__)
        clients=[]
        def factory(**kwargs):
            client=FakePublisher(**kwargs);clients.append(client);return client
        async def exercise():
            await generated.close_pubsub()
            try:
                await generated.pubsub('publish', {'projectId':'qa','batchDelayThresholdMilliseconds':30},
                    {'topic':'qa','batchDelayThresholdMilliseconds':0,'waitForDelivery':True},{})
                self.assertEqual(clients[0].kwargs['batch_settings'].max_latency,.001)
            finally: await generated.close_pubsub()
        with patch('google.cloud.pubsub_v1.PublisherClient', side_effect=factory): asyncio.run(exercise())


if __name__=='__main__':unittest.main()
