"""Pub/Sub correctness/concurrency guards; no hosted-cloud rate claims."""
import asyncio
from concurrent.futures import Future, ThreadPoolExecutor
from threading import Event
from unittest.mock import MagicMock, patch
import types
import unittest
from app.runtime import WorkflowRuntime
from app.models import SharedResource
from app.raw_python_support import connectors


class PubsubThroughputTests(unittest.TestCase):
    def test_publish_bypasses_a_saturated_receiver_pool_in_both_runtimes(self):
        client = MagicMock()
        confirmation = Future()
        confirmation.set_result('confirmed')
        client.publish.return_value = confirmation
        client.topic_path.return_value = 'projects/qa/topics/test'

        async def exercise():
            loop = asyncio.get_running_loop()
            loop.set_default_executor(ThreadPoolExecutor(max_workers=1))
            entered, release = Event(), Event()
            def receiver():
                entered.set()
                release.wait(5)

            blocked = loop.run_in_executor(None, receiver)
            runtime = WorkflowRuntime()
            resource = SharedResource(id='p', name='QA', type='pubsub', config={'projectId': 'qa'})
            cfg = {'resourceId': 'p', 'topic': 'test', 'waitForDelivery': True}
            try:
                while not entered.is_set():
                    await asyncio.sleep(0)
                result = await asyncio.wait_for(runtime.messaging('pubsub', cfg, {'resources': {'p': resource}, 'last': {}}), 1)
                self.assertEqual(result['providerMessageId'], 'confirmed')
                self.assertIn('confirmationMs', result['publishTiming'])
                direct = await asyncio.wait_for(connectors.pubsub('publish', resource.config, cfg, {}), 1)
                self.assertEqual(direct['providerMessageId'], 'confirmed')
                self.assertFalse(blocked.done())
            finally:
                release.set()
                await blocked
                await connectors.close_pubsub()
                runtime.close_publishers()

        with patch('app.runtime.create_pubsub_client', return_value=client), patch('google.cloud.pubsub_v1.PublisherClient', return_value=client):
            asyncio.run(exercise())

    def test_fully_qualified_topic_is_not_prefixed_twice(self):
        client=MagicMock();future=Future();future.set_result('id');client.publish.return_value=future
        async def exercise():
            runtime=WorkflowRuntime();resource=SharedResource(id='p',name='QA',type='pubsub',config={'projectId':'qa'})
            ctx={'resources':{'p':resource},'last':{},'input':{},'properties':{},'vars':{},'context':{}}
            try:
                await runtime.messaging('pubsub',{'resourceId':'p','topic':'projects/other/topics/test','waitForDelivery':True},ctx)
                client.topic_path.assert_not_called()
                self.assertEqual(client.publish.call_args.args[0],'projects/other/topics/test')
            finally:runtime.close_publishers()
        with patch('app.runtime.create_pubsub_client',return_value=client):asyncio.run(exercise())

    def test_direct_publisher_honors_endpoint_and_bounded_flow_control(self):
        client=MagicMock();future=Future();future.set_result('id');client.publish.return_value=future
        async def exercise():
            await connectors.close_pubsub()
            try:
                await connectors.pubsub('publish',{'projectId':'qa','endpoint':'regional.example.invalid'},
                    {'topic':'test','waitForDelivery':True,'flowControlMaxMessages':23,'flowControlMaxBytes':12345},{})
            finally:await connectors.close_pubsub()
        with patch('google.cloud.pubsub_v1.PublisherClient',return_value=client) as create:
            asyncio.run(exercise())
        self.assertEqual(create.call_args.kwargs['client_options']['api_endpoint'],'regional.example.invalid')
        flow=create.call_args.kwargs['publisher_options'].flow_control
        self.assertEqual(flow.message_limit,23);self.assertEqual(flow.byte_limit,12345)

    def test_confirmation_wait_does_not_occupy_shared_executor(self):
        futures=[];client=MagicMock();client.topic_path.return_value='projects/qa/topics/test'
        def publish(*args,**kwargs):
            value=Future();futures.append(value);return value
        client.publish.side_effect=publish
        async def exercise():
            asyncio.get_running_loop().set_default_executor(ThreadPoolExecutor(max_workers=1))
            runtime=WorkflowRuntime();resource=SharedResource(id='p',name='QA',type='pubsub',config={'projectId':'qa'})
            ctx={'resources':{'p':resource},'last':{},'input':{},'properties':{},'vars':{},'context':{}}
            first=asyncio.create_task(runtime.messaging('pubsub',{'resourceId':'p','topic':'test','waitForDelivery':True},ctx))
            try:
                for _ in range(100):
                    if futures:break
                    await asyncio.sleep(.005)
                result=await asyncio.wait_for(runtime.messaging('pubsub',{'resourceId':'p','topic':'test'},ctx),.5)
                self.assertFalse(result['deliveryConfirmed']);self.assertFalse(first.done())
                for i,value in enumerate(futures):value.set_result(str(i))
                self.assertTrue((await first)['deliveryConfirmed'])
            finally:
                for value in futures:
                    if not value.done():value.set_result('cleanup')
                await asyncio.gather(first,return_exceptions=True);runtime.close_publishers()
        with patch('app.runtime.create_pubsub_client',return_value=client):asyncio.run(exercise())

    def test_direct_pull_auto_acknowledges_but_manual_mode_does_not(self):
        client=MagicMock()
        client.subscription_path.return_value='projects/qa/subscriptions/test'
        client.pull.return_value.received_messages=[types.SimpleNamespace(ack_id='ack',message=types.SimpleNamespace(data=b'body'))]
        async def exercise():
            result=await connectors.pubsub('pull',{'projectId':'qa','endpoint':'regional.example.invalid'},{'subscription':'test'},None)
            self.assertEqual(result['messages'][0]['data'],'body')
            client.acknowledge.assert_called_once_with(request={'subscription':'projects/qa/subscriptions/test','ack_ids':['ack']})
            client.acknowledge.reset_mock()
            await connectors.pubsub('pull',{'projectId':'qa'},{'subscription':'test','acknowledgeMode':'Client'},None)
            client.acknowledge.assert_not_called()
        with patch('google.cloud.pubsub_v1.SubscriberClient',return_value=client) as create:
            asyncio.run(exercise())
            self.assertEqual(create.call_args_list[0].kwargs['client_options']['api_endpoint'],'regional.example.invalid')

if __name__=='__main__':unittest.main()
