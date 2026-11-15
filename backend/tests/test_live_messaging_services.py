"""Opt-in live protocol checks. The operator supplies dedicated QA resources."""
import asyncio
import json
import os
import time
import unittest
import uuid
from pathlib import Path

from app import amqp
from app.java_bridge import execute_jms,start_jms_listener


@unittest.skipUnless(os.environ.get('MINA_LIVE_EDGE_CONFIG'),'Requires dedicated approved live test destinations')
class LiveMessagingServices(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.spec=json.loads(Path(os.environ['MINA_LIVE_EDGE_CONFIG']).read_text(encoding='utf-8-sig'))
        if cls.spec.get('approvedTestDestinations') is not True:
            raise ValueError('Explicit dedicated-test destination configuration is required')

    def test_amqp_default_ttl_and_auto_settlement(self):
        cfg=self.spec['amqpConnection'];queue=self.spec['amqpQueues'][0];token=uuid.uuid4().hex
        amqp.send(cfg,{'queueName':queue,'body':token})
        message,settle=amqp.get(cfg,{'queueName':queue,'receiveTimeoutSeconds':3})
        self.assertIsNotNone(message);self.assertEqual(message['body'],token);self.assertIsNone(settle)
        self.assertEqual(amqp.get(cfg,{'queueName':queue,'receiveTimeoutSeconds':.1}),(None,None))

    def test_amqp_expiration_units_headers_and_client_settlement(self):
        cfg=self.spec['amqpConnection'];queue=self.spec['amqpQueues'][1];token=uuid.uuid4().hex
        amqp.send(cfg,{'queueName':queue,'body':token,'expiration':2500,'priority':7,'contentType':'text/plain',
            'correlationID':token,'userProperties':[{'name':'mina-test','value':token}]})
        message,settle=amqp.get(cfg,{'queueName':queue,'acknowledgeMode':'Client','receiveTimeoutSeconds':3})
        self.assertIsNotNone(message)
        try:
            self.assertEqual(message['body'],token)
            self.assertEqual(message['UserProperties']['mina-test'],token)
            self.assertEqual(message['MessageProperties']['priority'],7)
            self.assertEqual(str(message['MessageProperties']['contentType']),'text/plain')
            self.assertEqual(str(message['MessageProperties']['correlationID']),token)
            self.assertGreater(message['MessageProperties']['expiration'],0)
            self.assertLessEqual(message['MessageProperties']['expiration'],2500)
        finally:settle()
        self.assertEqual(amqp.get(cfg,{'queueName':queue,'receiveTimeoutSeconds':.1}),(None,None))

    def test_amqp_short_lived_message_expires(self):
        cfg=self.spec['amqpConnection'];queue=self.spec['amqpQueues'][2]
        amqp.send(cfg,{'queueName':queue,'body':uuid.uuid4().hex,'expiration':100})
        time.sleep(.3)
        self.assertEqual(amqp.get(cfg,{'queueName':queue,'receiveTimeoutSeconds':.2}),(None,None))

    def test_jms_request_reply_keeps_temporary_destination_and_correlation(self):
        cfg=self.spec['jmsConnection'];queue=self.spec['requestReplyQueue'];token=uuid.uuid4().hex
        async def execute():
            listener=start_jms_listener(cfg,queue)
            request=None
            try:
                ready=await listener.next_event(timeout=10)
                self.assertEqual(ready.get('event'),'listening')
                request=asyncio.create_task(asyncio.to_thread(execute_jms,cfg,'request',queue,token,
                    {'receiveTimeout':5000,'correlationId':token}))
                delivery=await listener.next_event(timeout=10)
                self.assertEqual(delivery.get('body'),token)
                listener.reply_jms(delivery['deliveryId'],'reply-'+token)
                response=await request
                self.assertTrue(response.get('received'))
                self.assertEqual(response['body'],'reply-'+token)
                self.assertEqual(response['headers']['JMSCorrelationID'],token)
            finally:
                listener.close()
                if request is not None:await asyncio.gather(request,return_exceptions=True)
        asyncio.run(execute())
