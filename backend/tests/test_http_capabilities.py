import asyncio, base64, json, ssl, tempfile, threading, time, unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch, MagicMock
import httpx, jwt
from app import http_transport as transport
from app.http_server import ListenerApp, listener_config, route_pattern
from app.models import Project
from app.raw_python import raw_python_files, engine_python_files, raw_python_requirements

class Handler(BaseHTTPRequestHandler):
    protocol_version='HTTP/1.1'
    def log_message(self,*args):pass
    def do_GET(self):self.respond()
    def do_POST(self):self.respond()
    def respond(self):
        length=int(self.headers.get('content-length',0));body=self.rfile.read(length)
        if self.path=='/slow':time.sleep(.12)
        if self.path=='/redirect':
            self.send_response(302);self.send_header('Location','/reply');self.send_header('Content-Length','0');self.end_headers();return
        value={'path':self.path,'authorization':self.headers.get('Authorization'),'body':body.decode(),'cookie':self.headers.get('Cookie')}
        raw=json.dumps(value).encode();self.send_response(404 if self.path=='/missing' else 200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(raw)));self.end_headers()
        try:self.wfile.write(raw)
        except OSError:pass

class HTTPClientTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server=ThreadingHTTPServer(('127.0.0.1',0),Handler);cls.worker=threading.Thread(target=cls.server.serve_forever,daemon=True);cls.worker.start();cls.base=f'http://127.0.0.1:{cls.server.server_port}'
    @classmethod
    def tearDownClass(cls):transport.close_clients();cls.server.shutdown();cls.server.server_close();cls.worker.join()
    def test_shared_defaults_parameters_headers_and_false_body(self):
        cfg={'connectorMode':'client','baseUrl':self.base,'basePath':'api','headers':'{"X-Shared":"yes"}','query':'{"a":"one"}'}
        result=transport.request({'url':'/items/{id}','pathParameters':{'id':'x/y'},'query':{'b':[1,2]},'method':'POST','body':False},cfg)
        self.assertEqual(result['statusCode'],200);self.assertEqual(result['body']['body'],'false');self.assertEqual(result['body']['path'],'/api/items/x%2Fy?a=one&b=1&b=2')
    def test_basic_and_runtime_shared_settings(self):
        cfg={'baseUrl':self.base,'authentication':'Basic','username':'user','password':'pass','socketTimeoutMs':300,'connectionTimeoutMs':400}
        result=transport.request({'url':'/reply'},cfg)
        self.assertEqual(result['body']['authorization'],'Basic '+base64.b64encode(b'user:pass').decode())
        client=transport.client_for(cfg);self.assertIs(client,transport.client_for(cfg))
        self.assertIsNot(client,transport.client_for({**cfg,'_httpScope':'another-application'}))
    def test_read_timeout_and_response_limit(self):
        with self.assertRaisesRegex(transport.HTTPFault,'timed out'):transport.request({'url':self.base+'/slow','socketTimeoutMs':10})
        with self.assertRaisesRegex(transport.HTTPFault,'body limit'):transport.request({'url':self.base+'/reply','maxResponseBodyBytes':5})
    def test_redirect_and_status_validation(self):
        output=transport.request({'url':self.base+'/redirect','followRedirects':True});self.assertEqual(output['body']['path'],'/reply')
        with self.assertRaises(transport.HTTPFault):transport.request({'url':self.base+'/missing'})
        self.assertEqual(transport.request({'url':self.base+'/missing','successStatusCodes':'200-299,404'})['statusCode'],404)
    def test_confidentiality_and_client_role_are_enforced(self):
        for cfg in ({'defaultConfidentiality':True},{'confidentiality':True},{'connectorMode':'server'}):
            with self.assertRaises(transport.HTTPFault):transport.request({'url':self.base+'/reply'},cfg)
        with self.assertRaises(transport.HTTPFault):transport.request({'url':self.base+'/items/{id}'})
    def test_oauth_token_exchange_cache_and_fail_closed(self):
        cfg={'oauthTokenUrl':'https://issuer.example/token','oauthClientId':'client','oauthClientSecret':'secret','oauthScope':'read'}
        client=MagicMock();client.post.return_value=httpx.Response(200,json={'access_token':'test-token','expires_in':3600},request=httpx.Request('POST',cfg['oauthTokenUrl']))
        transport._TOKENS.clear();self.assertEqual(transport._oauth(cfg,client),'test-token');self.assertEqual(transport._oauth(cfg,client),'test-token');self.assertEqual(client.post.call_count,1)
        transport._TOKENS.clear();client.post.return_value=httpx.Response(400,text='secret provider detail',request=httpx.Request('POST',cfg['oauthTokenUrl']))
        with self.assertRaisesRegex(transport.HTTPFault,'OAuth token exchange failed'):transport._oauth(cfg,client)
    def test_legacy_timeout_settings_and_limits(self):
        self.assertEqual(transport._seconds({'timeoutSeconds':2},'socketTimeoutMs','timeoutSeconds',60),2)
        self.assertIsNone(transport._seconds({'socketTimeoutMs':0},'socketTimeoutMs','timeoutSeconds',60))
        with self.assertRaises(transport.HTTPFault):transport.client_for({'maximumTotalConnections':1,'maximumConnectionsPerHost':2})

class HTTPAuthenticationTests(unittest.TestCase):
    def test_certificate_folder_failures_are_configuration_errors(self):
        with tempfile.TemporaryDirectory() as folder:
            for value in (str(Path(folder)/'missing'),folder):
                with self.assertRaises(transport.HTTPFault):transport.tls_context({'trustedCertificateFolder':value})
            path=Path(folder)/'invalid.pem';path.write_text('not a certificate')
            with self.assertRaisesRegex(transport.HTTPFault,'invalid.pem'):transport.tls_context({'trustedCertificateFolder':folder})
            path.write_text('-----BEGIN PRIVATE KEY-----\nnot-a-certificate\n-----END PRIVATE KEY-----')
            with self.assertRaises(transport.HTTPFault):transport.tls_context({'trustedCertificateFolder':folder})

    def test_non_preemptive_basic_waits_for_challenge(self):
        seen=[]
        def respond(request):
            seen.append(request.headers.get('authorization'))
            return httpx.Response(401,headers={'WWW-Authenticate':'Basic realm="test"'}) if len(seen)==1 else httpx.Response(200)
        with httpx.Client(transport=httpx.MockTransport(respond)) as client:
            self.assertEqual(client.get('https://example.test',auth=transport.NonPreemptiveBasic('u','p')).status_code,200)
        self.assertEqual(seen,[None,'Basic dTpw'])

    def test_oauth_introspection_requires_active_token_and_scopes(self):
        cfg={'authentication':'OAuth2','oauthIntrospectionUrl':'https://issuer.test/token','oauthClientId':'client','oauthClientSecret':'secret','oauthRequiredScopes':'read write'}
        with httpx.Client(transport=httpx.MockTransport(lambda request:httpx.Response(200,json={'active':True,'scope':'read write','exp':time.time()+60}))) as client,patch.object(transport,'client_for',return_value=client):
            self.assertTrue(transport.authorize(cfg,'GET','/',{'authorization':'Bearer token'})['active'])
        with httpx.Client(transport=httpx.MockTransport(lambda request:httpx.Response(200,json={'active':True,'scope':'read'}))) as client,patch.object(transport,'client_for',return_value=client):
            with self.assertRaises(transport.HTTPFault):transport.authorize(cfg,'GET','/',{'authorization':'Bearer token'})

    def test_ldap_search_escapes_username_and_uses_verified_starttls(self):
        import ldap3
        entry=MagicMock();entry.entry_dn='uid=user,dc=example';entry.memberOf.values=['cn=users,dc=example']
        service=MagicMock();service.entries=[entry];user=MagicMock()
        cfg={'authentication':'LDAP','ldapUrl':'ldap://directory.test','ldapStartTls':True,'ldapBindDn':'cn=reader,dc=example','ldapBindPassword':'secret','ldapBaseDn':'dc=example','ldapRequiredGroup':'cn=users,dc=example'}
        transport.validate_authentication(cfg,server=True)
        with patch.object(ldap3,'Connection',side_effect=[service,user]),patch.object(ldap3,'Server') as server,patch.object(ldap3,'Tls') as tls:
            self.assertEqual(transport.ldap_authenticate(cfg,'user*)(uid=*)','password')['subject'],'user*)(uid=*)')
            self.assertIn('\\2a',service.search.call_args.args[1]);tls.assert_called_once();self.assertEqual(tls.call_args.kwargs['validate'],ssl.CERT_REQUIRED)
            service.start_tls.assert_called_once();user.start_tls.assert_called_once();service.unbind.assert_called_once();user.unbind.assert_called_once()

    def test_inbound_basic_and_bearer_no_empty_credentials(self):
        for mode in ('Basic','Bearer'):
            with self.assertRaises(transport.HTTPFault):transport.authorize({'authentication':mode},'GET','/',{})
        cfg={'authentication':'Basic','username':'u','password':'p'}
        self.assertEqual(transport.authorize(cfg,'GET','/',{'authorization':'Basic dTpw'})['subject'],'u')
        with self.assertRaises(transport.HTTPFault):transport.authorize(cfg,'GET','/',{'authorization':'Basic dTpx'})
    def test_jwt_expiry_issuer_audience_algorithm_and_required_exp(self):
        cfg={'authentication':'JWT','jwtAlgorithm':'HS256','jwtSecret':'x'*32,'jwtIssuer':'issuer','jwtAudience':'api'}
        token=transport.jwt_token(cfg);claims=transport.authorize(cfg,'GET','/',{'Authorization':'Bearer '+token});self.assertEqual(claims['iss'],'issuer')
        for claims in ({'iss':'issuer','aud':'api'}, {'exp':time.time()-100,'iss':'issuer','aud':'api'}, {'exp':time.time()+100,'iss':'wrong','aud':'api'}, {'exp':time.time()+100,'iss':'issuer','aud':'wrong'}):
            with self.assertRaises(transport.HTTPFault):transport.authorize(cfg,'GET','/',{'Authorization':'Bearer '+jwt.encode(claims,'x'*32,algorithm='HS256')})
        with self.assertRaises(transport.HTTPFault):transport.authorize(cfg,'GET','/',{'Authorization':'Bearer '+jwt.encode({'exp':time.time()+100},'x'*64,algorithm='HS512')})
    def test_hmac_tamper_time_and_replay(self):
        cfg={'authentication':'HMAC','hmacSecret':'s'*32,'hmacKeyId':'client'};stamp=str(int(time.time()));nonce='a'*32;body=b'{"value":1}'
        headers={'X-MINA-Timestamp':stamp,'X-MINA-Nonce':nonce,'X-MINA-Key-Id':'client','Authorization':'HMAC '+transport.hmac_signature(cfg,'POST','/api?x=1',body,stamp,nonce)}
        transport._NONCES.clear()
        with self.assertRaises(transport.HTTPFault):transport.authorize(cfg,'POST','/api?x=2',headers,body)
        self.assertEqual(transport.authorize(cfg,'POST','/api?x=1',headers,body)['keyId'],'client')
        with self.assertRaises(transport.HTTPFault):transport.authorize(cfg,'POST','/api?x=1',headers,body)
    def test_ldap_never_accepts_anonymous_or_plaintext_bind(self):
        with self.assertRaises(transport.HTTPFault):transport.ldap_authenticate({'ldapUrl':'ldap://directory','ldapStartTls':False},'user','pass')
        with self.assertRaises(transport.HTTPFault):transport.ldap_authenticate({'ldapUrl':'ldaps://directory'},'user','')
    def test_certificate_policy_requires_verified_tls(self):
        with self.assertRaises(transport.HTTPFault):transport.authorize({'authentication':'Certificate'},'GET','/',{})
        self.assertTrue(transport.authorize({'authentication':'Certificate'},'GET','/',{},peer_verified=True)['certificateVerified'])
        with self.assertRaises(transport.HTTPFault):listener_config({'authentication':'Certificate'},{})
    def test_tls_and_pkcs12_stores(self):
        from cryptography import x509
        from cryptography.hazmat.primitives import hashes,serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.hazmat.primitives.serialization import pkcs12
        from datetime import datetime,timezone,timedelta
        key=rsa.generate_private_key(public_exponent=65537,key_size=2048);name=x509.Name([x509.NameAttribute(x509.oid.NameOID.COMMON_NAME,'localhost')]);now=datetime.now(timezone.utc)
        cert=x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key()).serial_number(x509.random_serial_number()).not_valid_before(now-timedelta(days=1)).not_valid_after(now+timedelta(days=1)).add_extension(x509.BasicConstraints(ca=True,path_length=None),critical=True).sign(key,hashes.SHA256())
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'identity.p12';path.write_bytes(pkcs12.serialize_key_and_certificates(b'identity',key,cert,None,serialization.BestAvailableEncryption(b'password')))
            cfg={'identityStoreType':'PKCS12','identityStoreFile':str(path),'identityStorePassword':'password','trustStoreType':'PKCS12','trustStoreFile':str(path),'trustStorePassword':'password','clientAuthentication':'required'}
            context=transport.tls_context(cfg,server=True);self.assertEqual(context.minimum_version,ssl.TLSVersion.TLSv1_2);self.assertEqual(context.verify_mode,ssl.CERT_REQUIRED)
        with self.assertRaises(transport.HTTPFault):transport.tls_context({'tlsVersion':'TLSv1.0'})

class HTTPListenerTests(unittest.IsolatedAsyncioTestCase):
    async def test_openapi_operation_controls_route_and_validates_contract(self):
        from app.rest_contract import operation_config
        spec={'openapi':'3.0.3','servers':[{'url':'https://example.test/v1'}],'paths':{'/items/{id}':{'post':{'operationId':'create','parameters':[{'in':'path','name':'id','required':True,'schema':{'type':'integer'}}],'requestBody':{'required':True,'content':{'application/json':{'schema':{'$ref':'#/components/schemas/Item'}}}},'responses':{'201':{'content':{'application/json':{'schema':{'$ref':'#/components/schemas/Item'}}}}}}}},'components':{'schemas':{'Item':{'type':'object','required':['name'],'properties':{'name':{'type':'string'}}}}}}
        cfg=listener_config({'minimumQtpThreads':1,'maximumQtpThreads':2},{'operation':'receiver','openApiDocument':spec,'operationId':'create'})
        self.assertEqual(cfg['path'],'/v1/items/{id}');self.assertEqual(cfg['method'],'POST')
        self.assertEqual(operation_config({'operation':'invoke','openApiDocument':spec,'operationId':'create'})['url'],'https://example.test/v1/items/{id}')
        async def handle(metadata,payload):return {'statusCode':201,'body':payload['body']}
        app=ListenerApp([(None,cfg)],handle,cfg)
        try:
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app),base_url='http://test') as client:
                self.assertEqual((await client.post('/v1/items/42',json={'name':'item'})).status_code,201)
                self.assertEqual((await client.post('/v1/items/42',json={})).status_code,400)
                self.assertEqual((await client.post('/v1/items/not-number',json={'name':'item'})).status_code,400)
        finally:app.executor.shutdown()
        with self.assertRaises(ValueError):operation_config({'openApiDocument':spec,'operationId':'missing'})
        broken=json.loads(json.dumps(spec));broken['paths']['/items/{id}']['post']['requestBody']['content']['application/json']['schema']={'$ref':'https://untrusted.test/schema'}
        with self.assertRaisesRegex(ValueError,'local'):operation_config({'openApiDocument':broken,'operationId':'create'})

    async def test_live_mutual_tls_listener_and_stop(self):
        import socket, ipaddress
        from app.http_server import serve
        from cryptography import x509
        from cryptography.hazmat.primitives import hashes,serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
        from datetime import datetime,timezone,timedelta
        key=rsa.generate_private_key(public_exponent=65537,key_size=2048)
        name=x509.Name([x509.NameAttribute(x509.oid.NameOID.COMMON_NAME,'localhost')]);now=datetime.now(timezone.utc)
        certificate=x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key()).serial_number(x509.random_serial_number()).not_valid_before(now-timedelta(days=1)).not_valid_after(now+timedelta(days=1)).add_extension(x509.BasicConstraints(ca=True,path_length=None),critical=True).add_extension(x509.SubjectAlternativeName([x509.DNSName('localhost'),x509.IPAddress(ipaddress.ip_address('127.0.0.1'))]),critical=False).sign(key,hashes.SHA256())
        with tempfile.TemporaryDirectory() as folder:
            cert=Path(folder)/'cert.pem';private=Path(folder)/'key.pem';cert.write_bytes(certificate.public_bytes(serialization.Encoding.PEM));private.write_bytes(key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()))
            with socket.socket() as probe:probe.bind(('127.0.0.1',0));port=probe.getsockname()[1]
            cfg={'connectorMode':'server','host':'127.0.0.1','port':port,'minimumQtpThreads':1,'maximumQtpThreads':2,'tlsEnabled':True,'authentication':'Certificate','clientAuthentication':'required','certificateFile':str(cert),'privateKeyFile':str(private),'trustStoreFile':str(cert)}
            async def handle(metadata,payload):return {'verified':payload['auth']['certificateVerified'],'value':payload['body']}
            ready=asyncio.Event();job=asyncio.create_task(serve([(None,cfg,{'path':'/test','method':'POST'})],handle,ready))
            try:
                await asyncio.wait_for(ready.wait(),10)
                context=transport.tls_context({'trustStoreFile':str(cert),'certificateFile':str(cert),'privateKeyFile':str(private)})
                async with httpx.AsyncClient(verify=context,trust_env=False) as client:
                    response=await client.post(f'https://127.0.0.1:{port}/test',json={'x':1})
                    self.assertEqual(response.status_code,200);self.assertEqual(response.json(),{'verified':True,'value':{'x':1}})
                async with httpx.AsyncClient(verify=ssl.create_default_context(cafile=str(cert)),trust_env=False) as client:
                    with self.assertRaises(httpx.HTTPError):await client.post(f'https://127.0.0.1:{port}/test',json={})
            finally:
                job.cancel()
                try:await job
                except asyncio.CancelledError:pass
            with socket.socket() as probe:probe.bind(('127.0.0.1',port))

    async def test_asgi_route_auth_json_limits_and_response(self):
        cfg=listener_config({'minimumQtpThreads':1,'maximumQtpThreads':2,'authentication':'Basic','username':'u','password':'p'},{'path':'/items/{id}','methods':'POST','contentType':'application/json','maxRequestBodyBytes':100})
        seen=[]
        async def handler(metadata,payload):seen.append(payload);return {'statusCode':201,'body':{'id':payload['pathParameters']['id'],'value':payload['body']}}
        app=ListenerApp([(None,cfg)],handler,cfg)
        try:
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app),base_url='http://test') as client:
                response=await client.post('/items/42',json={'x':1});self.assertEqual(response.status_code,401);self.assertEqual(seen,[])
                response=await client.post('/items/42',json={'x':1},auth=('u','p'));self.assertEqual(response.status_code,201);self.assertEqual(response.json(),{'id':'42','value':{'x':1}})
                response=await client.post('/items/42',content=b'x'*101,auth=('u','p'));self.assertEqual(response.status_code,413)
                response=await client.post('/items/42',content='{bad',headers={'Content-Type':'application/json'},auth=('u','p'));self.assertEqual(response.status_code,400)
                response=await client.get('/items/42');self.assertEqual(response.status_code,404)
        finally:app.executor.shutdown()
    def test_literal_route_metacharacters_and_shared_base_path(self):
        cfg=listener_config({'basePath':'api'},{'path':'/v1.0/{id}'});pattern,names=route_pattern(cfg['path']);self.assertIsNotNone(pattern.match('/api/v1.0/1'));self.assertIsNone(pattern.match('/api/v1x0/1'));self.assertEqual(names,['id'])
    def test_worker_limits_http2_rejection(self):
        with self.assertRaises(transport.HTTPFault):listener_config({'minimumQtpThreads':10,'maximumQtpThreads':5},{})
        with self.assertRaises(transport.HTTPFault):listener_config({'httpVersion':'2'},{})

class HTTPExportTests(unittest.TestCase):
    def test_property_bound_root_folder_for_http_and_soap_in_studio_and_exports(self):
        import subprocess,sys
        from app.runtime import WorkflowRuntime
        from cryptography import x509
        from cryptography.hazmat.primitives import hashes,serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
        from datetime import datetime,timezone,timedelta
        def issue(label,key,issuer,issuer_key,ca):
            now=datetime.now(timezone.utc);name=x509.Name([x509.NameAttribute(x509.oid.NameOID.COMMON_NAME,label)])
            builder=x509.CertificateBuilder().subject_name(name).issuer_name(issuer.subject if issuer else name).public_key(key.public_key()).serial_number(x509.random_serial_number()).not_valid_before(now-timedelta(days=1)).not_valid_after(now+timedelta(days=30)).add_extension(x509.BasicConstraints(ca=ca,path_length=None),critical=True).add_extension(x509.KeyUsage(digital_signature=True,content_commitment=False,key_encipherment=not ca,data_encipherment=False,key_agreement=False,key_cert_sign=ca,crl_sign=ca,encipher_only=None,decipher_only=None),critical=True).add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()),critical=False).add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(issuer_key.public_key()),critical=False)
            if not ca:builder=builder.add_extension(x509.SubjectAlternativeName([x509.DNSName('localhost')]),critical=False)
            return builder.sign(issuer_key,hashes.SHA256())
        root_key=rsa.generate_private_key(public_exponent=65537,key_size=2048);root=issue('Test Root',root_key,None,root_key,True)
        intermediate_key=rsa.generate_private_key(public_exponent=65537,key_size=2048);intermediate=issue('Intermediate',intermediate_key,root,root_key,True)
        key=rsa.generate_private_key(public_exponent=65537,key_size=2048);leaf=issue('localhost',key,intermediate,intermediate_key,False)
        with tempfile.TemporaryDirectory() as folder:
            base=Path(folder);roots=base/'roots';roots.mkdir();(roots/'root.crt').write_bytes(root.public_bytes(serialization.Encoding.PEM))
            certificate=base/'server.pem';certificate.write_bytes(leaf.public_bytes(serialization.Encoding.PEM)+intermediate.public_bytes(serialization.Encoding.PEM))
            private=base/'server.key';private.write_bytes(key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()))
            server=ThreadingHTTPServer(('127.0.0.1',0),Handler);context=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER);context.load_cert_chain(certificate,private);server.socket=context.wrap_socket(server.socket,server_side=True);worker=threading.Thread(target=server.serve_forever,daemon=True);worker.start()
            try:
                for kind in ('http','soap'):
                    config={'operation':'request','resourceId':'http','url':'/echo','method':'POST','body':{'value':False},'responseMode':'envelope'}
                    if kind=='soap':config.update(operation='request_reply',envelope='<Request>test</Request>')
                    project={'id':'folder-trust','name':'Folder Trust','properties':{'local':[{'key':'http.roots','value':str(roots),'data_type':'string'}]},'resources':[{'id':'http','name':'HTTP','type':'http','config':{'connectorMode':'client','baseUrl':f'https://localhost:{server.server_port}','trustedCertificateFolder':'${properties.http.roots}'}}],'tasks':[{'id':'main','name':'Main','kind':'starter','groups':[],'activities':[{'id':'Start','name':'Start','type':'start','config':{}},{'id':'Call','name':'Call','type':kind,'config':config},{'id':'End','name':'End','type':'end','config':{}}],'transitions':[{'id':'t1','source':'Start','target':'Call'},{'id':'t2','source':'Call','target':'End'}]}]}
                    model=Project.model_validate(project);result=asyncio.run(WorkflowRuntime().run(model.tasks[0],{}, {resource.id:resource for resource in model.resources},{'http.roots':str(roots)},project=model))
                    self.assertEqual(result.status,'completed',result.logs);self.assertEqual(result.output['statusCode'],200)
                    for compiler in (raw_python_files,engine_python_files):
                        with self.subTest(kind=kind,compiler=compiler.__name__),tempfile.TemporaryDirectory() as destination:
                            for name,body in compiler(project,project['properties']).items():
                                target=Path(destination)/name;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(body)
                            command=[sys.executable,'run.py'] if compiler is raw_python_files else [sys.executable,'-m','application.main']
                            completed=subprocess.run([*command,'--task','main','--input','{}'],cwd=destination,capture_output=True,text=True,timeout=30)
                            self.assertEqual(completed.returncode,0,completed.stderr);self.assertEqual(json.loads(completed.stdout)['statusCode'],200)
                # An optional intermediate in the folder completes a leaf-only server chain.
                (roots/'chain.pem').write_bytes(intermediate.public_bytes(serialization.Encoding.PEM));certificate.write_bytes(leaf.public_bytes(serialization.Encoding.PEM));context.load_cert_chain(certificate,private)
                self.assertEqual(transport.request({'url':f'https://localhost:{server.server_port}/echo','trustedCertificateFolder':str(roots)})['statusCode'],200)
                # DER certificates need no conversion or OpenSSL rehash operation.
                (roots/'root.crt').unlink();(roots/'root.cer').write_bytes(root.public_bytes(serialization.Encoding.DER))
                self.assertEqual(transport.request({'url':f'https://localhost:{server.server_port}/echo','trustedCertificateFolder':str(roots)})['statusCode'],200)
                self.assertIn(str(roots),raw_python_requirements({'resources':[{'config':{'trustedCertificateFolder':str(roots)}}],'tasks':[]})[1])
            finally:transport.close_clients();server.shutdown();server.server_close();worker.join()

    def test_export_keeps_oauth_endpoints_and_store_paths_but_scrubs_secrets(self):
        from app.main import deployment_package_files
        project=Project.model_validate({'id':'security-export','name':'Security Export','properties':{'local':[]},'resources':[{'id':'http','name':'HTTP','type':'http','config':{'authentication':'OAuth2','oauthTokenUrl':'https://issuer.test/token','oauthClientSecret':'do-not-export','privateKeyFile':'/secure/key.pem','privateKeyPassword':'also-secret'}}]})
        files=deployment_package_files(project,'on-prem','local',set())
        cfg=json.loads(files['application/project.json'])['resources'][0]['config']
        self.assertEqual(cfg['oauthTokenUrl'],'https://issuer.test/token');self.assertEqual(cfg['privateKeyFile'],'/secure/key.pem')
        self.assertEqual(cfg['oauthClientSecret'],'');self.assertEqual(cfg['privateKeyPassword'],'')

    def test_rest_call_executes_in_both_python_archives(self):
        import subprocess,sys
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler);worker=threading.Thread(target=server.serve_forever,daemon=True);worker.start()
        project={'id':'http-export','name':'HTTP Export','resources':[{'id':'http','name':'HTTP','type':'http','config':{'connectorMode':'client','baseUrl':f'http://127.0.0.1:{server.server_port}','basePath':'api'}}],'tasks':[{'id':'main','name':'Main','kind':'starter','groups':[],'activities':[{'id':'Start','name':'Start','type':'start','config':{}},{'id':'rest','name':'REST','type':'rest','config':{'operation':'invoke','resourceId':'http','url':'/echo','method':'POST','body':{'value':False}}},{'id':'End','name':'End','type':'end','config':{}}],'transitions':[{'id':'t1','source':'Start','target':'rest'},{'id':'t2','source':'rest','target':'End'}]}]}
        try:
            from app.runtime import WorkflowRuntime
            model=Project.model_validate(project)
            studio=asyncio.run(WorkflowRuntime().run(model.tasks[0],{}, {value.id:value for value in model.resources},{},project=model))
            self.assertEqual(studio.status,'completed');self.assertEqual(studio.output['body']['path'],'/api/echo')
            for compiler in (raw_python_files,engine_python_files):
                with self.subTest(compiler=compiler.__name__),tempfile.TemporaryDirectory() as folder:
                    for name,body in compiler(project,{'local':[]}).items():
                        target=Path(folder)/name;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(body)
                    command=[sys.executable,'run.py'] if compiler is raw_python_files else [sys.executable,'-m','application.main']
                    completed=subprocess.run([*command,'--task','main','--input','{}'],cwd=folder,capture_output=True,text=True,timeout=30)
                    self.assertEqual(completed.returncode,0,completed.stderr)
                    result=json.loads(completed.stdout);self.assertEqual(result['statusCode'],200);self.assertEqual(json.loads(result['body']['body']),{'value':False});self.assertEqual(result['body']['path'],'/api/echo')
        finally:server.shutdown();server.server_close();worker.join()

    def test_shared_transport_and_optional_security_requirements_in_both_archives(self):
        for kind,operation in [('rest','invoke'),('rest','receiver')]:
            project=Project.model_validate({'id':'http-test','name':'HTTP','resources':[{'id':'shared','type':'http','name':'HTTP','config':{'connectorMode':'client' if operation=='invoke' else 'server','authentication':'JWT','jwtSecret':'x'*32}}],'tasks':[{'id':'task','name':'Task','kind':'starter','activities':[{'id':'Start','type':'start','name':'Start','config':{}},{'id':'rest','type':kind,'name':'REST','config':{'operation':operation,'resourceId':'shared','url':'https://api.example.com','path':'/api'}}],'transitions':[]}]}).model_dump()
            direct=raw_python_files(project,project['properties']);engine=engine_python_files(project,project['properties'])
            self.assertIn('application/native/http_transport.py',list(direct));self.assertIn('application/engine/http_transport.py',list(engine))
            if operation=='receiver':self.assertIn('application/native/http_server.py',list(direct));self.assertIn('application/engine/http_server.py',list(engine))
            names={item['name'] for item in raw_python_requirements(project)[0]};self.assertIn('JWT authentication',names);self.assertIn('HTTP transport',names)

