import asyncio
import socket
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from ipaddress import ip_address
from pathlib import Path

import httpx

from app import http_transport as transport
from app.api_blueprint import blueprint_plan
from app.http_server import ListenerApp, listener_config, serve
from tests.test_http_activity_e2e import upstream


class HTTPPoliciesTests(unittest.TestCase):
    def test_public_cache_is_partitioned_and_invalidated_after_write(self):
        calls = []
        def respond(request):
            calls.append(request.method)
            return httpx.Response(200, headers={'Cache-Control':'public, max-age=60'},
                                  json={'calls':len(calls)})
        config = {'url':'http://cache-test.local/orders', 'sharedHttpCache':True, '_httpScope':'cache-test'}
        with upstream(respond):
            first = transport.request(config)
            hit = transport.request(config)
            self.assertEqual(hit['body'], first['body'])
            self.assertIn('age', hit['headers'])
            transport.request({**config, 'headers':{'Cache-Control':'no-cache'}})
            transport.request({**config, 'method':'PUT', 'body':{'state':'ready'}})
            self.assertEqual(transport.request(config)['body'], {'calls':4})
        self.assertEqual(calls, ['GET','GET','PUT','GET'])

    def test_write_preconditions_use_strong_match_and_weak_none_match(self):
        config = {'operation':'write_precondition','currentETag':'"v2"','requireWritePrecondition':True}
        cases = [
            ({}, 428),
            ({'If-Match':'"v2"'}, 200),
            ({'If-Match':'W/"v2"'}, 412),
            ({'If-None-Match':'W/"v2"'}, 412),
            ({'If-Match':'"v2"', 'If-Unmodified-Since':'Mon, 01 Jan 1990 00:00:00 GMT'}, 200),
        ]
        for headers, status in cases:
            self.assertEqual(transport.request({**config,'headers':headers}), {'allowed':status == 200,'statusCode':status})

    def test_sse_parses_multiline_events_and_sends_resume_header(self):
        def respond(request):
            self.assertEqual(request.headers['accept'], 'text/event-stream')
            self.assertEqual(request.headers['last-event-id'], '4')
            return httpx.Response(200, headers={'Content-Type':'text/event-stream'},
                content=b'\xef\xbb\xbf: heartbeat\r\nid: 5\r\nevent: update\r\ndata: one\r\ndata: two\r\nretry: 1000\r\n\r\n')
        with upstream(respond):
            result = transport.request({'operation':'sse_read','url':'http://events.test','lastEventId':'4'})
        self.assertEqual(result['events'], [{'event':'update','id':'5','data':'one\ntwo','retryMs':1000}])


class HTTPExtendedLiveTests(unittest.IsolatedAsyncioTestCase):
    async def test_websocket_exchange_returns_text_and_binary(self):
        from websockets.asyncio.server import serve as serve_websocket
        async def echo(connection):
            self.assertEqual(await connection.recv(), 'hello')
            await connection.send('reply')
            await connection.send(b'\x00\xff')
        async with serve_websocket(echo, '127.0.0.1', 0) as server:
            port = server.sockets[0].getsockname()[1]
            result = await asyncio.to_thread(transport.request, {'operation':'websocket_exchange',
                'url':f'ws://127.0.0.1:{port}/', 'maxEvents':2, 'body':'hello', 'activityTimeoutSeconds':5})
        self.assertEqual(result['events'], [{'type':'text','data':'reply'},{'type':'binary','data':'AP8='}])

    async def test_webhook_and_callback_with_origin_policy_and_combined_keys(self):
        spec = {'openapi':'3.1.0','components':{'securitySchemes':{
            'client':{'type':'apiKey','in':'header','name':'X-Client-Key'},
            'secondary':{'type':'apiKey','in':'query','name':'secondary'},
            'bearer':{'type':'http','scheme':'bearer'}}},
            'webhooks':{'orders':{'post':{'operationId':'orders','security':[{'client':[],'secondary':[],'bearer':[]}],
                'callbacks':{'complete':{'{$request.body#/callbackUrl}':{'post':{'responses':{'204':{'description':'OK'}}}}}},
                'responses':{'200':{'description':'OK'}}}}}}
        connection = {'type':'http','config':{'authentication':'Bearer','bearerToken':'token',
                      'openApiApiKeySecrets':{'client':'key-one','secondary':'key-two'}}}
        plan = blueprint_plan(spec, ['orders'], connection)
        receiver, callback = plan['tasks']
        self.assertEqual(callback['kind'], 'subtask')
        cfg = listener_config(plan['resource']['config'], receiver['activities'][0]['config'])
        async def handler(_, payload):return {'statusCode':200,'body':{'accepted':True}}
        app = ListenerApp([(None,cfg)],handler,cfg,warm_workers=False)
        try:
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
                headers = {'Authorization':'Bearer token','X-Client-Key':'key-one'}
                url = '/_webhooks/orders?secondary=key-two'
                self.assertEqual((await client.post(url,headers=headers)).status_code, 200)
                self.assertEqual((await client.post('/_webhooks/orders',headers=headers)).status_code, 403)
                self.assertEqual((await client.post(url,headers={'X-Client-Key':'key-one'})).status_code, 401)
        finally:
            app.executor.shutdown(wait=True)
        config = callback['activities'][1]['config']
        with self.assertRaisesRegex(transport.HTTPFault, 'allowed HTTPS origin'):
            transport.request({**config, 'callbackUrl':'https://other.test/hook','callbackAllowedOrigins':'https://subscriber.test'})
        with upstream(lambda req: httpx.Response(204, headers={'X-Callback-Target':str(req.url)})):
            result = transport.request({**config,'callbackUrl':'https://subscriber.test/hooks/one?kind=order',
                                        'callbackAllowedOrigins':'https://subscriber.test','body':{'id':1}})
        self.assertEqual(result['headers']['x-callback-target'], 'https://subscriber.test/hooks/one?kind=order')

    async def test_http3_runs_over_udp_with_verified_certificate(self):
        from cryptography import x509
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import rsa

        key = rsa.generate_private_key(public_exponent=65537,key_size=2048)
        name = x509.Name([x509.NameAttribute(x509.oid.NameOID.COMMON_NAME,'localhost')])
        now = datetime.now(timezone.utc)
        certificate = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(now-timedelta(days=1))
            .not_valid_after(now+timedelta(days=1))
            .add_extension(x509.BasicConstraints(ca=True,path_length=0),critical=True)
            .add_extension(x509.SubjectAlternativeName([x509.IPAddress(ip_address('127.0.0.1'))]),critical=False)
            .sign(key,hashes.SHA256()))
        with tempfile.TemporaryDirectory() as directory:
            cert, private = Path(directory)/'cert.pem', Path(directory)/'key.pem'
            cert.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
            private.write_bytes(key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()))
            with socket.socket() as probe:
                probe.bind(('127.0.0.1',0));port=probe.getsockname()[1]
            server = {'httpVersion':'3','scheme':'https','host':'127.0.0.1','port':port,
                      'certificateFile':str(cert),'privateKeyFile':str(private),'minimumQtpThreads':1}
            async def echo(_, payload):return {'statusCode':200,'body':payload['body']}
            ready = asyncio.Event()
            task = asyncio.create_task(serve([(None,server,{'path':'/echo','methods':'POST'})], echo, ready))
            try:
                await asyncio.wait_for(ready.wait(), 10)
                result = await asyncio.to_thread(transport.request, {'httpVersion':'3',
                    'url':f'https://127.0.0.1:{port}/echo','method':'POST','certificateAuthorityFile':str(cert),
                    'body':{'protocol':3},'activityTimeoutSeconds':5})
                self.assertEqual((result['httpVersion'],result['body']),('HTTP/3',{'protocol':3}))
            finally:
                task.cancel()
                with self.assertRaises(asyncio.CancelledError):await task
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
                if hasattr(socket, 'SO_EXCLUSIVEADDRUSE'):
                    probe.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
                probe.bind(('127.0.0.1', port))
