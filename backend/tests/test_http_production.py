"""Protocol, policy, streaming and export regressions for HTTP/REST."""
import asyncio, base64, json, tempfile, time, unittest
from pathlib import Path
from unittest.mock import patch
import httpx
from app import http_transport as transport, http_policy as policy
from app.http_server import ListenerApp, listener_config, serve
from app.http_contracts import schema_errors, response_schema
from app.rest_contract import operation_config, validate_parameters

class ListenerProductionTests(unittest.IsolatedAsyncioTestCase):
    async def exercise(self,handler,action,config=None,routes=None):
        cfg=listener_config({'minimumQtpThreads':1,'maximumQtpThreads':2,**(config or {})},{'path':'/echo','methods':'GET,POST'})
        app=ListenerApp(routes or [(None,cfg)],handler,cfg,warm_workers=False)
        try:
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app),base_url='http://test') as client:await action(client,app)
        finally:app.executor.shutdown(wait=True)

    async def test_binary_query_and_repeated_headers(self):
        seen=[]
        async def handle(_,payload):seen.append(payload);return {'statusCode':200,'body':payload['body'],'headers':{'Set-Cookie':['a=1','b=2']}}
        async def action(client,app):
            response=await client.post('/echo?tag=a&tag=b',content=b'\x00\xff',headers=[('Content-Type','application/octet-stream'),('X-Test','a'),('X-Test','b')])
            self.assertEqual(response.content,b'\x00\xff');self.assertEqual(response.headers.get_list('set-cookie'),['a=1','b=2'])
            self.assertEqual(seen[0]['query']['tag'],['a','b']);self.assertEqual(seen[0]['headers']['x-test'],['a','b'])
            self.assertEqual(base64.b64decode(seen[0]['binaryContent']),b'\x00\xff')
        await self.exercise(handle,action)

    async def test_method_head_options_and_boolean_response(self):
        async def handle(_,payload):return {'statusCode':200,'body':False}
        async def action(client,app):
            bad=await client.delete('/echo');self.assertEqual(bad.status_code,405);self.assertIn('GET',bad.headers['allow'])
            head=await client.head('/echo');self.assertEqual(head.content,b'');self.assertEqual(head.headers['content-length'],'5')
            options=await client.options('/echo');self.assertEqual(options.status_code,204)
            self.assertEqual((await client.get('/echo')).json(),False)
            self.assertEqual((await client.get('/missing')).status_code,404)
        await self.exercise(handle,action)

    async def test_credentialed_cors_preflight_and_failures(self):
        async def handle(_,payload):return {'statusCode':200,'body':'ok'}
        async def action(client,app):
            preflight=await client.options('/echo',headers={'Origin':'https://ui.test','Access-Control-Request-Method':'POST','Access-Control-Request-Headers':'Authorization, Content-Type'})
            self.assertEqual(preflight.status_code,204);self.assertEqual(preflight.headers['access-control-allow-origin'],'https://ui.test')
            self.assertEqual((await client.get('/echo',headers={'Origin':'https://other.test'})).status_code,403)
            denied=await client.get('/echo',headers={'Origin':'https://ui.test'})
            self.assertEqual(denied.status_code,401);self.assertEqual(denied.headers['access-control-allow-credentials'],'true')
        await self.exercise(handle,action,{'corsAllowedOrigins':'https://ui.test','corsAllowCredentials':True,'authentication':'Basic','username':'u','password':'p'})

    async def test_repeated_authorization_rejected_and_rate_limited(self):
        policy._RATES.clear()
        async def handle(_,payload):return {'statusCode':200,'body':'ok'}
        async def action(client,app):
            self.assertEqual((await client.get('/echo',headers=[('Authorization','a'),('Authorization','b')])).status_code,400)
            self.assertEqual((await client.get('/echo')).status_code,200)
            limited=await client.get('/echo');self.assertEqual(limited.status_code,429);self.assertIn('retry-after',limited.headers)
        await self.exercise(handle,action,{'rateLimitRequests':1,'rateLimitWindowSeconds':60})

    async def test_uploaded_file_lifecycle_and_streamed_response(self):
        with tempfile.TemporaryDirectory() as folder:
            response_path=Path(folder)/'response.bin';response_path.write_bytes(b'x'*200000);seen=[]
            async def handle(_,payload):
                seen.append(payload['fileName']);self.assertEqual(Path(payload['fileName']).read_bytes(),b'\xff'*100000)
                return {'fileName':str(response_path),'headers':{'content-type':'application/octet-stream'}}
            async def action(client,app):
                response=await client.post('/echo',content=b'\xff'*100000,headers={'Content-Type':'application/octet-stream'})
                self.assertEqual(response.content,response_path.read_bytes());self.assertFalse(Path(seen[0]).exists())
                self.assertEqual(app.gate._value,2)
            await self.exercise(handle,action,{'requestBodyMode':'file','uploadDirectory':folder})

    async def test_disconnect_cleans_upload_and_releases_gate(self):
        with tempfile.TemporaryDirectory() as folder:
            cfg=listener_config({'minimumQtpThreads':1,'maximumQtpThreads':1,'requestBodyMode':'file','uploadDirectory':folder},{'path':'/','methods':'POST'})
            app=ListenerApp([(None,cfg)],None,cfg,warm_workers=False)
            async def receive():return {'type':'http.disconnect'}
            async def send(event):raise AssertionError('Disconnected request must not send a response')
            try:await app({'type':'http','method':'POST','path':'/','headers':[]},receive,send)
            finally:app.executor.shutdown(wait=True)
            self.assertEqual(list(Path(folder).iterdir()),[]);self.assertEqual(app.gate._value,1)

    async def test_declared_error_response_validation(self):
        async def handle(_,payload):return {'statusCode':400,'body':{'wrong':True}}
        async def action(client,app):self.assertEqual((await client.get('/echo')).status_code,500)
        await self.exercise(handle,action,{'validateResponse':True,'_restResponseSchemas':{'4XX':{'type':'object','required':['error']}}})

    async def test_bounded_queue_and_cancelled_request_release_capacity(self):
        entered=asyncio.Event();finish=asyncio.Event()
        async def handle(_,payload):entered.set();await finish.wait();return {'statusCode':200,'body':'ok'}
        async def action(client,app):
            pending=asyncio.create_task(client.get('/echo'))
            try:
                await asyncio.wait_for(entered.wait(),2)
                overloaded=await client.get('/echo');self.assertEqual(overloaded.status_code,503)
                pending.cancel()
                with self.assertRaises(asyncio.CancelledError):await pending
                self.assertEqual(app.queued,0);self.assertEqual(app.gate._value,1)
            finally:
                finish.set()
                if not pending.done():pending.cancel()
        await self.exercise(handle,action,{'maximumQtpThreads':1,'maxQueueSize':0})

    async def test_concurrent_requests_obey_execution_limit(self):
        active=0;peak=0
        async def handle(_,payload):
            nonlocal active,peak
            active+=1;peak=max(peak,active)
            try:await asyncio.sleep(.001);return {'statusCode':200,'body':'ok'}
            finally:active-=1
        async def action(client,app):
            results=await asyncio.gather(*(client.get('/echo') for _ in range(100)))
            self.assertTrue(all(result.status_code==200 for result in results));self.assertLessEqual(peak,4)
            self.assertEqual(app.queued,0);self.assertEqual(app.gate._value,4)
        await self.exercise(handle,action,{'maximumQtpThreads':4,'maxQueueSize':100})

class ContractProductionTests(unittest.TestCase):
    def test_yaml_external_documents_and_error_schemas(self):
        yaml='''openapi: 3.0.3
servers: [{url: https://api.test}]
paths:
  /items:
    get:
      operationId: items
      responses:
        '400':
          content:
            application/json:
              schema: {$ref: 'https://schemas.test/error.yaml#/Error'}
'''
        cfg=operation_config({'openApiDocument':yaml,'operationId':'items','openApiReferenceDocuments':{'https://schemas.test/error.yaml':{'Error':{'type':'object','required':['error']}}}})
        self.assertTrue(schema_errors({},response_schema(cfg,400)))
        self.assertFalse(schema_errors({'error':'bad'},response_schema(cfg,400)))
        with self.assertRaises(ValueError):operation_config({'openApiDocument':yaml,'operationId':'items'})

    def test_yaml_aliases_and_implicit_schema_network_rejected(self):
        from app.http_contracts import load_document
        with self.assertRaises(ValueError):load_document('a: &a [1]\nb: *a')
        with self.assertRaises(ValueError):schema_errors({}, {'$ref':'https://untrusted.test/schema'})

    def test_parameter_arrays_objects_cookies_and_constraints(self):
        parameters=[{'in':'query','name':'tag','schema':{'type':'array','minItems':2,'items':{'type':'integer','minimum':1}}},{'in':'query','name':'filter','style':'deepObject','schema':{'type':'object','required':['name'],'properties':{'name':{'type':'string','minLength':3}}}},{'in':'cookie','name':'session','required':True,'schema':{'type':'string'}}]
        cfg={'_restParameters':parameters}
        self.assertFalse(validate_parameters(cfg,{}, {'tag':['1','2'],'filter[name]':'Ada'},{'cookie':'session=abc'},None))
        self.assertTrue(validate_parameters(cfg,{}, {'tag':['0'],'filter[name]':'A'},{},None))
        self.assertTrue(validate_parameters({'_restParameters':[{'in':'query','name':'count','schema':{'type':'integer'}}]}, {},{'count':'1.2'},{},None))

    def test_serialization_nullable_false_schema_and_property_constraints(self):
        from app.rest_contract import wire_parameters
        cfg={'_restParameters':[{'in':'query','name':'filter','style':'deepObject','schema':{'type':'object'}},{'in':'path','name':'id','style':'matrix','explode':True,'schema':{'type':'array'}}]}
        self.assertEqual(wire_parameters(cfg,'query',{'filter':{'active':True}}),{'filter[active]':'true'})
        self.assertEqual(wire_parameters(cfg,'path',{'id':['a','b']})['id'],';id=a;id=b')
        from app.rest_contract import parameter_value
        self.assertEqual(parameter_value(cfg['_restParameters'][1],{'id':';id=a;id=b'}),['a','b'])
        self.assertTrue(schema_errors('anything',False));self.assertFalse(schema_errors(b'\xff',{'type':'string','format':'binary'}))
        self.assertTrue(schema_errors({'a':'x'},{'type':'object','patternProperties':{'^a$':{'type':'integer'}},'additionalProperties':False}))

    def test_both_archives_include_policies_http2_and_secret_bindings(self):
        from app.models import Project
        from app.raw_python import raw_python_files,engine_python_files,raw_python_requirements
        from app.main import deployment_package_files
        value={'id':'http-policy-export','name':'HTTP policies','properties':{'local':[]},'resources':[{'id':'http','name':'HTTP','type':'http','config':{'connectorMode':'server','httpVersion':'2','scheme':'https','policyStore':'redis','policyRedisUrl':'rediss://user:private-password@redis.test:6379/0'}}],'tasks':[{'id':'main','name':'Main','kind':'starter','groups':[],'activities':[{'id':'Receive','name':'Receive','type':'rest','config':{'operation':'receiver','resourceId':'http','path':'/'}},{'id':'Reply','name':'Reply','type':'http_response','config':{'operation':'response','body':'ok'}}],'transitions':[{'id':'next','source':'Receive','target':'Reply'}]}]}
        project=Project.model_validate(value)
        for compiler,prefix in [(raw_python_files,'application/native/'),(engine_python_files,'application/engine/')]:
            files=compiler(value,{'local':[]})
            for name in ('http_policy.py','http_contracts.py','http_streams.py','http_listener.py','http2_server.py'):self.assertIn(prefix+name,files)
        names={item['name'] for item in raw_python_requirements(value)[0]}
        self.assertTrue({'HTTP/2 server','Distributed HTTP policies','HTTP contracts'}.issubset(names))
        exported=deployment_package_files(project,'on-prem','local',set())
        text=exported['application/project.json'].decode();self.assertNotIn('private-password',text)
        self.assertIn('resources.http.config.policyRedisUrl',exported['deployment/secrets.required.json'].decode())

class TransportProductionTests(unittest.TestCase):
    def tearDown(self):transport.close_clients();policy._CIRCUITS.clear();policy._JWKS.clear()
    def client(self,handler):
        client=httpx.Client(transport=httpx.MockTransport(handler));client._mina_route_limit=2;client._mina_routes={};client._mina_lock=__import__('threading').Lock();return client

    def test_file_upload_and_download_atomic_failure_cleanup(self):
        with tempfile.TemporaryDirectory() as folder:
            source=Path(folder)/'in';source.write_bytes(b'\xff'*200000);target=Path(folder)/'out';seen=[]
            def handler(request):seen.append(request.read());return httpx.Response(200,content=b'\x00\xff',headers={'Content-Type':'application/octet-stream'})
            with self.client(handler) as client,patch.object(transport,'client_for',return_value=client):
                output=transport.request({'url':'https://api.test/upload','method':'POST','body':str(source),'bodyType':'file','responseFile':str(target)})
                self.assertEqual(seen,[source.read_bytes()]);self.assertEqual(target.read_bytes(),b'\x00\xff');self.assertEqual(output['body']['size'],2)
                with self.assertRaises(transport.HTTPFault):transport.request({'url':'https://api.test','responseFile':str(target)})
                target.unlink()
                with self.assertRaises(transport.HTTPFault):transport.request({'url':'https://api.test','responseFile':str(target),'maxResponseBodyBytes':1})
                self.assertFalse(target.exists());self.assertFalse(list(Path(folder).glob('.mina-download-*')))

    def test_streaming_multipart_hmac_matches_actual_wire_body(self):
        seen=[]
        def handler(request):
            raw=request.read();seen.append(raw)
            expected=transport.hmac_signature({'hmacSecret':'secret'},request.method,request.url.raw_path.decode(),raw,request.headers['x-mina-timestamp'],request.headers['x-mina-nonce'])
            self.assertEqual(request.headers['authorization'],'HMAC '+expected);return httpx.Response(200,json={'ok':True})
        envelope={'mimePart':[{'mimeEnvelopeElement':{'mimePart':[{'textContent':'nested'}]}}]}
        with self.client(handler) as client,patch.object(transport,'client_for',return_value=client):
            transport.request({'url':'https://api.test','streamRequest':True,'authentication':'HMAC','hmacSecret':'secret','RestInputRequest':{'mimeEnvelopeElement':envelope}})
        self.assertIn(b'bmVzdGVk',seen[0])

    def test_status_retry_requires_idempotency_and_respects_budget(self):
        calls=[]
        def handler(request):calls.append(request.method);return httpx.Response(503,headers={'Retry-After':'0'}) if len(calls)==1 else httpx.Response(200,json={})
        with self.client(handler) as client,patch.object(transport,'client_for',return_value=client),patch.object(transport.time,'sleep'):
            self.assertEqual(transport.request({'url':'https://api.test','retryCount':1,'retryStatusCodes':'503'})['statusCode'],200)
            calls.clear()
            with self.assertRaises(transport.HTTPFault):transport.request({'url':'https://api.test','method':'POST','retryCount':1,'retryStatusCodes':'503'})
            self.assertEqual(len(calls),1)
            calls.clear()
            self.assertEqual(transport.request({'url':'https://api.test','method':'POST','headers':{'Idempotency-Key':'business-id'},'retryCount':1,'retryStatusCodes':'503'})['statusCode'],200)

    def test_circuit_opens_and_half_open_probe_recovers(self):
        cfg={'circuitFailureThreshold':2,'circuitResetSeconds':30}
        key=policy.circuit_enter(cfg,'host');policy.circuit_result(cfg,key,True)
        policy.circuit_result(cfg,policy.circuit_enter(cfg,'host'),True)
        with self.assertRaises(transport.HTTPFault):policy.circuit_enter(cfg,'host')
        policy._CIRCUITS[key]['until']=time.monotonic()-1
        self.assertEqual(policy.circuit_enter(cfg,'host'),key)
        with self.assertRaises(transport.HTTPFault):policy.circuit_enter(cfg,'host')
        policy.circuit_result(cfg,key,False);self.assertEqual(policy.circuit_enter(cfg,'host'),key)

    def test_jwks_verification_rotation_and_algorithm_rejection(self):
        import jwt
        from cryptography.hazmat.primitives.asymmetric import rsa
        private=[rsa.generate_private_key(public_exponent=65537,key_size=2048) for _ in range(2)]
        definitions=[{**json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(key.public_key())),'kid':str(i),'alg':'RS256'} for i,key in enumerate(private)]
        supplied=[definitions[0]];calls=[]
        def handler(request):calls.append(1);return httpx.Response(200,json={'keys':supplied})
        cfg={'authentication':'JWT','jwtJwksUrl':'https://issuer.test/keys','jwtAlgorithm':'RS256','jwtIssuer':'issuer','jwtAudience':'api'}
        def token(i):return jwt.encode({'exp':time.time()+60,'iss':'issuer','aud':'api'},private[i],algorithm='RS256',headers={'kid':str(i)})
        with self.client(handler) as client,patch.object(transport,'client_for',return_value=client):
            self.assertEqual(transport.authorize(cfg,'GET','/',{'authorization':'Bearer '+token(0)})['aud'],'api')
            transport.authorize(cfg,'GET','/',{'authorization':'Bearer '+token(0)});self.assertEqual(len(calls),1)
            supplied[:]=[definitions[1]]
            for cached in policy._JWKS.values():cached['fetched']-=11
            transport.authorize(cfg,'GET','/',{'authorization':'Bearer '+token(1)});self.assertEqual(len(calls),2)
            with self.assertRaises(transport.HTTPFault):transport.validate_authentication({**cfg,'jwtAlgorithm':'HS256'},server=True)

    def test_distributed_nonce_claims_are_atomic_and_fail_closed(self):
        class Store:
            def __init__(self):self.values=set()
            def set(self,key,value,nx=False,ex=0):
                if key in self.values:return False
                self.values.add(key);return True
        cfg={'hmacSecret':'secret','policyStore':'redis'}
        with patch.object(policy,'redis_client',return_value=Store()):
            self.assertTrue(policy.claim_nonce(cfg,'a'*32,60));self.assertFalse(policy.claim_nonce(cfg,'a'*32,60))
        with patch.object(policy,'redis_client',side_effect=OSError('offline')):
            with self.assertRaises(transport.HTTPFault) as raised:policy.claim_nonce(cfg,'b'*32,60)
            self.assertEqual(raised.exception.status,503)

class HTTP2ProductionTests(unittest.IsolatedAsyncioTestCase):
    async def test_live_http2_tls_and_stop(self):
        import ssl, socket
        from tests.test_http_capabilities import HTTPListenerTests
        from cryptography import x509
        from cryptography.hazmat.primitives import hashes,serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
        from datetime import datetime,timezone,timedelta
        key=rsa.generate_private_key(public_exponent=65537,key_size=2048);name=x509.Name([x509.NameAttribute(x509.oid.NameOID.COMMON_NAME,'localhost')]);now=datetime.now(timezone.utc)
        cert=x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key()).serial_number(x509.random_serial_number()).not_valid_before(now-timedelta(days=1)).not_valid_after(now+timedelta(days=1)).add_extension(x509.SubjectAlternativeName([x509.DNSName('localhost')]),critical=False).sign(key,hashes.SHA256())
        with tempfile.TemporaryDirectory() as folder:
            certfile=Path(folder)/'cert.pem';keyfile=Path(folder)/'key.pem';certfile.write_bytes(cert.public_bytes(serialization.Encoding.PEM));keyfile.write_bytes(key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()))
            with socket.socket() as probe:probe.bind(('127.0.0.1',0));port=probe.getsockname()[1]
            cfg={'connectorMode':'server','httpVersion':'2','scheme':'https','host':'127.0.0.1','port':port,'certificateFile':str(certfile),'privateKeyFile':str(keyfile),'minimumQtpThreads':1,'maximumQtpThreads':2}
            ready=asyncio.Event()
            async def handle(_,payload):return {'statusCode':200,'body':{'protocol':'ok'}}
            job=asyncio.create_task(serve([(None,cfg,{'path':'/','methods':'GET'})],handle,ready))
            try:
                await asyncio.wait_for(ready.wait(),10)
                context=ssl.create_default_context(cafile=str(certfile))
                async with httpx.AsyncClient(http2=True,verify=context,trust_env=False) as client:
                    response=await client.get(f'https://localhost:{port}/');self.assertEqual(response.http_version,'HTTP/2');self.assertEqual(response.json(),{'protocol':'ok'})
            finally:
                job.cancel()
                with self.assertRaises(asyncio.CancelledError):await job
            with socket.socket() as probe:probe.bind(('127.0.0.1',port))
