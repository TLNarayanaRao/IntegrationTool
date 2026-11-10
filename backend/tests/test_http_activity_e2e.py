import asyncio,copy,json,socket,threading,unittest,tempfile,subprocess,sys
from pathlib import Path
from contextlib import contextmanager
from unittest.mock import patch
import httpx
from fastapi.testclient import TestClient
from app import http_transport as transport
from app.http_server import ListenerApp,listener_config,serve,server_tls
from app.http_contracts import media_schema
from app.api_docs import generate_openapi
from app.models import Project
from app.runtime import WorkflowRuntime

SCHEMA={'type':'object','required':['name'],'properties':{'name':{'type':'string'}}}
FORMATS={'application/json':{'schema':SCHEMA},'text/plain':{'schema':{'type':'string','minLength':2}}}
SPEC={'openapi':'3.0.3','paths':{'/echo':{'post':{'operationId':'echo','requestBody':{'content':FORMATS},'responses':{'200':{'description':'Echo','content':FORMATS}}}}}}

@contextmanager
def upstream(respond):
    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        client._mina_lock=threading.Lock();client._mina_routes={};client._mina_route_limit=8
        with patch.object(transport,'client_for',return_value=client):yield

class OutboundContractTests(unittest.TestCase):
    def test_xml_and_form_serialization_are_inferred_from_content_type(self):
        for media,body,expected in [('application/xml','<hello/>',b'<hello/>'),('application/x-www-form-urlencoded',{'a':[1,2]},b'a=1&a=2')]:
            seen=[]
            with self.subTest(media=media),upstream(lambda request:(seen.append(request.content) or httpx.Response(200,json={'ok':True}))):
                self.assertEqual(transport.request({'url':'http://test','method':'POST','contentType':media,'body':body})['body'],{'ok':True})
            self.assertEqual(seen,[expected])

    def test_nonfinite_json_numbers_and_suppressed_required_bodies_are_rejected(self):
        with self.assertRaises(transport.HTTPFault):transport.request({'url':'http://test','method':'POST','body':{'number':float('nan')}})
        spec=copy.deepcopy(SPEC);spec['paths']['/echo']['post']['requestBody']['required']=True
        with self.assertRaisesRegex(transport.HTTPFault,'body is required'):transport.request({'baseUrl':'http://test','openApiDocument':spec,'operationId':'echo','body':{'name':'test'},'sendBodyMode':'NEVER'})
        with self.assertRaisesRegex(transport.HTTPFault,'schema validation'):transport.request({'baseUrl':'http://test','openApiDocument':spec,'operationId':'echo','requestSchema':'','body':{'wrong':'field'}})
        with upstream(lambda request:httpx.Response(200,content=b'{"number":NaN}',headers={'Content-Type':'application/json'})):
            with self.assertRaisesRegex(transport.HTTPFault,'Invalid JSON response'):transport.request({'url':'http://test'})

    def test_trace_can_be_hosted_from_a_blueprint_and_invoked(self):
        from app.api_blueprint import validate_blueprint
        spec={'openapi':'3.0.3','paths':{'/trace':{'trace':{'operationId':'trace','responses':{'200':{'description':'Trace'}}}}}}
        self.assertEqual(validate_blueprint(spec)['operations'][0]['method'],'TRACE')
        with upstream(lambda request:httpx.Response(200,text=request.method)):
            self.assertEqual(transport.request({'baseUrl':'http://test','openApiDocument':spec,'operationId':'trace'})['body'],'TRACE')

    def test_oauth_introspection_rejects_nonfinite_expiry(self):
        config={'authentication':'OAuth2','oauthIntrospectionUrl':'https://issuer.test/introspect','oauthClientId':'client','oauthClientSecret':'secret'}
        with upstream(lambda request:httpx.Response(200,content=b'{"active":true,"exp":NaN}',headers={'Content-Type':'application/json'})):
            with self.assertRaises(transport.HTTPFault):transport.authorize(config,'GET','/',{'authorization':'Bearer token'})

    def test_text_content_is_sent_raw_and_validated_against_its_own_schema(self):
        seen=[]
        def reply(request):seen.append(request.content);return httpx.Response(200,text='42',headers={'Content-Type':'text/plain'})
        with upstream(reply):
            result=transport.request({'baseUrl':'http://test','operationId':'echo','openApiDocument':SPEC,'headers':{'Content-Type':'text/plain; charset=utf-8'},'body':'hello'})
        self.assertEqual(seen,[b'hello']);self.assertEqual(result['body'],'42')

    def test_head_and_no_content_skip_response_body_validation(self):
        for status,method in [(200,'HEAD'),(204,'GET'),(205,'GET'),(304,'GET')]:
            with self.subTest(status=status),upstream(lambda request:httpx.Response(status,headers={'Content-Type':'application/json'})):
                result=transport.request({'url':'http://test','method':method,'validateResponse':True,'responseSchema':SCHEMA,'raiseForStatus':False})
                self.assertEqual(result['statusCode'],status)

    def test_allow_reserved_query_preserves_url_syntax_without_injecting_parameters(self):
        spec={'openapi':'3.1.0','paths':{'/search':{'get':{'operationId':'search',
              'parameters':[{'in':'query','name':'target','allowReserved':True,'schema':{'type':'string'}}],
              'responses':{'200':{'description':'OK'}}}}}}
        with upstream(lambda request:httpx.Response(200,text=request.url.query.decode())):
            result=transport.request({'baseUrl':'http://test','openApiDocument':spec,'operationId':'search',
                                      'query':{'target':'https://example.test/a?x=a&y=b#c+d%2F','normal':'a/b'}})
        self.assertEqual(result['body'],'target=https://example.test/a?x%3Da%26y%3Db%23c%2Bd%2F&normal=a%2Fb')

    def test_oauth_private_key_assertion_is_signed_for_the_token_endpoint(self):
        import jwt
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.hazmat.primitives import serialization
        from urllib.parse import parse_qs
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        endpoint = 'https://issuer.test/token'
        def respond(request):
            if request.url.host != 'issuer.test':
                self.assertEqual(request.headers['authorization'], 'Bearer granted')
                return httpx.Response(200, json={'ok':True})
            data = parse_qs(request.content.decode())
            self.assertNotIn('client_secret', data)
            self.assertNotIn('authorization', request.headers)
            token = data['client_assertion'][0]
            claims = jwt.decode(token, key.public_key(), algorithms=['RS256'], audience=endpoint, issuer='mina-client')
            self.assertEqual(claims['sub'], 'mina-client')
            self.assertEqual(jwt.get_unverified_header(token)['kid'], 'test-key')
            return httpx.Response(200, json={'access_token':'granted'})
        with tempfile.TemporaryDirectory() as directory, upstream(respond):
            pem = Path(directory) / 'key.pem'
            pem.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                              serialization.NoEncryption()))
            result = transport.request({'url':'https://api.test','authentication':'OAuth2','oauthTokenUrl':endpoint,
                                        'oauthClientAuthentication':'private_key_jwt','oauthClientId':'mina-client',
                                        'oauthClientPrivateKeyFile':str(pem),'oauthClientAssertionKeyId':'test-key'})
        self.assertEqual(result['body'], {'ok':True})

    def test_malformed_json_and_undeclared_response_formats_are_rejected(self):
        for headers,body in [({'Content-Type':'application/json'},b'{broken'),({'Content-Type':'text/html'},b'<html/>')]:
            with self.subTest(headers=headers),upstream(lambda request:httpx.Response(200,headers=headers,content=body)):
                with self.assertRaises(transport.HTTPFault):transport.request({'baseUrl':'http://test','operationId':'echo','openApiDocument':SPEC,'body':{'name':'test'}})

    def test_most_specific_media_range_wins_and_swagger_lists_all_formats(self):
        self.assertEqual(media_schema({'*/*':1,'text/*':2,'text/plain':3},'TEXT/PLAIN; charset=utf-8'),('text/plain',3))
        cfg=listener_config({}, {'openApiDocument':SPEC,'operationId':'echo','path':'/echo'})
        operation=generate_openapi([(None,cfg)])['paths']['/echo']['post']
        self.assertEqual(set(operation['requestBody']['content']),set(FORMATS))
        self.assertEqual(set(operation['responses']['200']['content']),set(FORMATS))

class InboundContractTests(unittest.IsolatedAsyncioTestCase):
    async def test_conditional_get_and_child_trace_context(self):
        cfg = listener_config({'conditionalResponses':True,'propagateTraceContext':True},
                              {'methods':'GET','path':'/resource'})
        trace_id = '0af7651916cd43dd8448eb211c80319c'
        incoming = f'00-{trace_id}-b7ad6b7169203331-01'
        seen = []
        def provider(request):
            seen.append(request.headers['traceparent'])
            return httpx.Response(200,json={'name':'value'})
        async def handler(metadata, payload):
            value = await asyncio.to_thread(transport.request, {'url':'http://upstream.test','propagateTraceContext':True})
            return {'__httpResponse':True, 'body':value['body'], 'headers':{'ETag':'"v1"'}}
        app = ListenerApp([(None,cfg)],handler,cfg,warm_workers=False)
        try:
            with upstream(provider):
                async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
                    cached = await client.get('/resource',headers={'If-None-Match':'W/"v1"','traceparent':incoming})
                    self.assertEqual((cached.status_code,cached.content,cached.headers['etag']),(304,b'','"v1"'))
                    fresh = await client.get('/resource',headers={'If-None-Match':'"v2"','traceparent':incoming})
                    self.assertEqual(fresh.json(),{'name':'value'})
            self.assertEqual(len(set(seen)),2)
            for value in seen:
                self.assertRegex(value, f'^00-{trace_id}-[0-9a-f]{{16}}-01$')
                self.assertNotEqual(value, incoming)
        finally:
            app.executor.shutdown(wait=True)

    async def test_contract_security_205_and_problem_details(self):
        spec={'openapi':'3.1.0','components':{'securitySchemes':{'bearer':{'type':'http','scheme':'bearer'}}},
              'security':[{'bearer':[]}],'paths':{'/reset':{'get':{'operationId':'reset','responses':{'205':{'description':'Reset'}}}}}}
        activity={'openApiDocument':spec,'operationId':'reset','operation':'receiver'}
        with self.assertRaisesRegex(transport.HTTPFault, 'cannot enforce'):
            listener_config({}, activity)
        cfg = listener_config({'authentication':'Bearer','bearerToken':'test-token','httpErrorFormat':'problem'}, activity)
        async def handler(metadata, payload):
            return {'statusCode':205,'fileName':'missing-file-is-ignored','body':{'never':'sent'}}
        app = ListenerApp([(None,cfg)],handler,cfg,warm_workers=False)
        try:
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
                denied = await client.get('/reset')
                self.assertEqual(denied.status_code,401)
                self.assertEqual(denied.headers['content-type'],'application/problem+json')
                self.assertEqual(denied.json()['status'],401)
                self.assertEqual(denied.headers['www-authenticate'],'Bearer')
                reset = await client.get('/reset',headers={'Authorization':'Bearer test-token'})
                self.assertEqual((reset.status_code,reset.content,reset.headers['content-length']),(205,b'','0'))
        finally:
            app.executor.shutdown(wait=True)

    async def test_multipart_contract_round_trips_typed_fields_and_part_content_types(self):
        media = 'multipart/form-data'
        body = {'tags':['one','two'],'options':{'strict':True},'count':7,'file':'AAH/'}
        schema = {'type':'object','required':list(body),'properties':{
            'tags':{'type':'array','items':{'type':'string'}},'options':{'type':'object'},
            'count':{'type':'integer'},'file':{'type':'string','format':'binary'}}}
        spec={'openapi':'3.1.0','paths':{'/upload':{'post':{'operationId':'upload',
              'requestBody':{'required':True,'content':{media:{'schema':schema,'encoding':{
                  'options':{'contentType':'application/vnd.test+json','headers':{
                      'X-Part-Version':{'required':True,'schema':{'type':'integer','minimum':2,'default':2}}}},
                  'file':{'contentType':'text/plain'}}}}},
              'responses':{'200':{'description':'OK'}}}}}}
        def echo(request):
            return httpx.Response(200,json={'raw':request.content.decode('latin1'),'type':request.headers['content-type']})
        with upstream(echo):
            result = transport.request({'baseUrl':'http://test','operationId':'upload','openApiDocument':spec,'body':body})['body']
        cfg = listener_config({}, {'openApiDocument':spec,'operationId':'upload','operation':'receiver'})
        async def handler(metadata, payload):
            return payload['body']
        app = ListenerApp([(None,cfg)],handler,cfg,warm_workers=False)
        try:
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
                raw = result['raw'].encode('latin1')
                good = await client.post('/upload',content=raw,headers={'Content-Type':result['type']})
                self.assertEqual(good.status_code,200,good.text)
                self.assertEqual(good.json(),body)
                self.assertIn(b'X-Part-Version: 2', raw)
                invalid_header = await client.post('/upload',content=raw.replace(b'X-Part-Version: 2',b'X-Part-Version: 1'),headers={'Content-Type':result['type']})
                self.assertEqual(invalid_header.status_code,400,invalid_header.text)
                bad = await client.post('/upload',content=raw.replace(b'application/vnd.test+json',b'application/json'),headers={'Content-Type':result['type']})
                self.assertEqual(bad.status_code,400,bad.text)
        finally:
            app.executor.shutdown(wait=True)

    async def test_configured_xml_media_types_take_precedence_for_listener_and_receiver(self):
        schema = '<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema"><xs:element name="Message" type="xs:string"/></xs:schema>'
        for operation in ('listen', 'receiver'):
            with self.subTest(operation=operation):
                cfg = listener_config({}, {
                    'operation': operation, 'path': '/message', 'method': 'POST',
                    'contentType': 'text/xml', 'responseType': 'application/vnd.mina.reply+xml',
                    'requestSchema': schema, 'responseSchema': schema,
                    'validateRequest': True, 'validateResponse': True,
                })
                async def handler(metadata, payload):
                    return {'__httpResponse': True, 'body': payload['body']}
                app = ListenerApp([(None, cfg)], handler, cfg, warm_workers=False)
                try:
                    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
                        result = await client.post('/message', content='<Message>hello</Message>', headers={'content-type': 'text/xml; charset=utf-8'})
                        self.assertEqual(result.status_code, 200, result.text)
                        self.assertEqual(result.headers['content-type'], 'application/vnd.mina.reply+xml')
                        self.assertEqual((await client.post('/message', content='<Message/>', headers={'content-type':'application/xml'})).status_code, 415)
                        cfg.pop('responseType')
                        automatic = await client.post('/message', content='<Message>hello</Message>', headers={'content-type':'text/xml'})
                        self.assertEqual(automatic.headers['content-type'], 'application/xml')
                finally:
                    app.executor.shutdown(wait=True)

    def test_explicit_openapi_request_type_limits_listener_and_swagger(self):
        cfg = listener_config({}, {'operation': 'receiver', 'openApiDocument': SPEC, 'operationId': 'echo', 'contentType': 'text/plain'})
        self.assertEqual(cfg['contentType'], 'text/plain')
        self.assertEqual(set(cfg['_restRequestSchemas']), {'text/plain'})
        document = generate_openapi([(None, cfg)])
        self.assertEqual(set(document['paths']['/echo']['post']['requestBody']['content']), {'text/plain'})
        with self.assertRaisesRegex(transport.HTTPFault, 'not declared'):
            listener_config({}, {'operation': 'receiver', 'openApiDocument': SPEC, 'operationId': 'echo', 'contentType': 'application/xml'})

    async def test_xsd_request_fields_can_be_mapped_by_downstream_activity(self):
        schema = '''<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema"
          targetNamespace="urn:orders" elementFormDefault="qualified">
          <xs:element name="Order"><xs:complexType><xs:sequence>
            <xs:element name="Number" type="xs:string"/>
          </xs:sequence></xs:complexType></xs:element>
        </xs:schema>'''
        xml = '<Order xmlns="urn:orders"><Number>123</Number></Order>'
        config = {'operation': 'listen', 'path': '/order', 'methods': 'POST', 'requestSchema': schema, 'validateRequest': True}
        project = Project.model_validate({'id': 'orders', 'name': 'Orders', 'tasks': [{
            'id': 'orders', 'name': 'Orders', 'kind': 'starter',
            'activities': [
                {'id': 'Receive', 'name': 'Receive', 'type': 'http_listener', 'config': config},
                {'id': 'Reply', 'name': 'Reply', 'type': 'http_response', 'config': {'inputMappings': {
                    'body.number': '${Receive.xmlBody.Order.Number}',
                    'body.original': '${Receive.body}',
                }}},
            ],
            'transitions': [{'id': 'next', 'source': 'Receive', 'target': 'Reply'}],
        }]})
        runtime = WorkflowRuntime()
        async def handler(metadata, payload):
            result = await runtime.run(project.tasks[0], payload, {}, {}, 'Receive', project)
            self.assertEqual(result.status, 'completed', result.logs)
            return result.output
        cfg = listener_config({}, config)
        app = ListenerApp([(None, cfg)], handler, cfg, warm_workers=False)
        try:
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
                response = await client.post('/order', content=xml, headers={'content-type': 'application/xml'})
                invalid = await client.post('/order', content='<Order/>', headers={'content-type': 'application/xml'})
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.json(), {'number': '123', 'original': xml})
            self.assertEqual(invalid.status_code, 400)
        finally:
            app.executor.shutdown(wait=True)

    async def test_mapped_response_is_rendered_as_xml_and_validated(self):
        schema = '''<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema"
          targetNamespace="urn:reply" elementFormDefault="qualified">
          <xs:element name="Reply"><xs:complexType><xs:sequence>
            <xs:element name="accepted" type="xs:boolean"/>
          </xs:sequence></xs:complexType></xs:element>
        </xs:schema>'''
        cfg = listener_config({}, {'path': '/reply', 'method': 'GET', 'responseSchema': schema, 'validateResponse': True})
        async def handler(metadata, payload):
            return {'__httpResponse': True, 'body': {'Reply': {'accepted': True}}}
        app = ListenerApp([(None, cfg)], handler, cfg, warm_workers=False)
        try:
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
                result = await client.get('/reply')
            self.assertEqual(result.status_code, 200, result.text)
            self.assertEqual(result.headers['content-type'], 'application/xml')
            self.assertEqual(result.text, '<Reply xmlns="urn:reply"><accepted>true</accepted></Reply>')
        finally:
            app.executor.shutdown(wait=True)

    async def test_urlencoded_form_fields_use_schema_types(self):
        schema={'type':'object','required':['quantity'],'properties':{'quantity':{'type':'integer'},'tags':{'type':'array','items':{'type':'integer'}}}}
        spec={'openapi':'3.0.3','paths':{'/form':{'post':{'operationId':'form','requestBody':{'content':{'application/x-www-form-urlencoded':{'schema':schema}}},'responses':{'200':{'description':'Result','content':{'application/json':{'schema':schema}}}}}}}}
        cfg=listener_config({}, {'openApiDocument':spec,'operationId':'form','operation':'receiver'})
        async def handler(metadata,payload):return payload['body']
        app=ListenerApp([(None,cfg)],handler,cfg,warm_workers=False)
        try:
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
                response=await client.post('/form',data={'quantity':'2','tags':['1','3']});self.assertEqual(response.status_code,200,response.text);self.assertEqual(response.json(),{'quantity':2,'tags':[1,3]})
                self.assertEqual((await client.post('/form',data={'quantity':'wrong'})).status_code,400)
        finally:app.executor.shutdown(wait=True)

    async def test_optional_body_multiple_media_and_rejection(self):
        cfg=listener_config({}, {'openApiDocument':SPEC,'operationId':'echo','operation':'receiver','requestSchema':''})
        async def handler(metadata,payload):return {'__httpResponse':True,'body':payload['body'],'headers':{'content-type':payload['headers'].get('content-type','text/plain')}}
        app=ListenerApp([(None,cfg)],handler,cfg,warm_workers=False)
        try:
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
                result=await client.post('/echo',content='hello',headers={'Content-Type':'text/plain'});self.assertEqual(result.status_code,200);self.assertEqual(result.text,'hello')
                self.assertEqual((await client.post('/echo',json={'name':'test'})).status_code,200)
                self.assertEqual((await client.post('/echo',content='bad',headers={'Content-Type':'image/png'})).status_code,415)
                self.assertEqual((await client.post('/echo',content='x',headers={'Content-Type':'text/plain'})).status_code,400)
                self.assertEqual((await client.post('/echo',content='{"name":NaN}',headers={'Content-Type':'application/json'})).status_code,400)
                # Optional absence must not fail the request object schema. Use a valid explicit reply.
                async def empty_reply(metadata,payload):return {'__httpResponse':True,'body':{'name':'empty'}}
                app.handler=empty_reply
                self.assertEqual((await client.post('/echo')).status_code,200)
        finally:app.executor.shutdown(wait=True)

class StudioPreviewTests(unittest.TestCase):
    def test_debug_get_only_uses_live_http_and_excludes_other_ports(self):
        from app import main
        from app.api_docs import postman_collection

        with socket.socket() as first, socket.socket() as second:
            first.bind(('127.0.0.1', 0))
            second.bind(('127.0.0.1', 0))
            port, other_port = first.getsockname()[1], second.getsockname()[1]
        declarations = [
            {'in': 'path', 'name': 'id', 'type': 'integer', 'required': True},
            {'in': 'query', 'name': 'details', 'type': 'boolean', 'required': True},
            {'in': 'header', 'name': 'X-Tenant', 'type': 'string', 'required': True},
        ]
        def task(task_id, resource_id, method):
            return {'id': task_id, 'name': task_id, 'kind': 'starter', 'activities': [
                {'id': 'receive', 'type': 'rest', 'name': 'Receive', 'config': {'operation': 'receiver',
                 'resourceId': resource_id, 'methods': method, 'path': '/orders/{id}', 'apiBlueprintId': 'orders',
                 'requestParameters': declarations}},
                {'id': 'respond', 'type': 'http_response', 'name': 'Respond', 'config': {
                    'operation': 'response', 'inputMappings': {'body': '${input}'}}},
            ], 'transitions': [{'id': 'next', 'source': 'receive', 'target': 'respond'}]}
        def resource(resource_id, bind_port):
            return {'id': resource_id, 'type': 'http', 'name': resource_id, 'config': {
                'host': '127.0.0.1', 'port': bind_port, 'scheme': 'http', 'tlsEnabled': 'false',
                'apiPublicBaseUrl': 'https://gateway.example.test', 'minimumQtpThreads': 1, 'maximumQtpThreads': 2,
                'httpErrorFormat': 'problem', 'trustedProxyCidrs': '127.0.0.1/32', 'propagateTraceContext': True}}
        project = Project.model_validate({'id': 'receiver-get-debug', 'name': 'Receiver GET',
            'resources': [resource('one', port), resource('two', other_port)],
            'tasks': [task('get-orders', 'one', 'GET'), task('post-orders', 'two', 'POST')]})
        with patch.object(main, 'get_project', return_value=project), patch.object(main, 'append_project_logs'), TestClient(main.app) as client:
            started = client.post(f'/api/projects/{project.id}/debug', json={'task_id': 'get-orders'})
            self.assertEqual(started.status_code, 200, started.text)
            state = started.json()
            base = f'http://127.0.0.1:{port}'
            try:
                endpoint, = state['endpoints']
                self.assertEqual(endpoint['methods'], ['GET'])
                self.assertEqual(endpoint['url'], base + '/orders/{id}')
                self.assertEqual(endpoint['configuredUrl'], 'https://gateway.example.test/orders/{id}')
                self.assertFalse(endpoint['tlsEnabled'])
                with httpx.Client(trust_env=False, timeout=5) as live:
                    rejected = live.post(base + '/orders/42')
                    self.assertEqual((rejected.status_code,rejected.headers['content-type']),(405,'application/problem+json'))
                    with self.assertRaises(httpx.ConnectError):
                        live.post(f'http://127.0.0.1:{other_port}/orders/42')
                    self.assertEqual(live.get(base + '/orders/42?details=true').status_code, 400)
                    self.assertEqual(live.get(base + '/orders/nope?details=true', headers={'X-Tenant': 'west'}).status_code, 400)
                    trace_id = '0af7651916cd43dd8448eb211c80319c'
                    response = live.get(base + '/orders/42?details=true', headers={'X-Tenant': 'west',
                        'X-Forwarded-For': '198.51.100.2', 'traceparent': f'00-{trace_id}-b7ad6b7169203331-01'})
                    self.assertEqual(response.status_code, 200, response.text)
                    self.assertEqual(response.json()['pathParameters'], {'id': 42})
                    self.assertEqual(response.json()['query'], {'details': True})
                    self.assertEqual(response.json()['headers']['x-tenant'], 'west')
                    self.assertEqual(response.json()['clientIp'], '198.51.100.2')
                    self.assertEqual(response.json()['traceId'], trace_id)
                    spec = live.get(base + '/_mina/openapi.json').json()
                    methods = spec['paths']['/orders/{id}']
                    self.assertEqual(set(methods), {'get'})
                    def parameter_type(parameter):
                        schema = parameter['schema']
                        if '$ref' in schema:
                            schema = spec['components']['schemas'][schema['$ref'].rsplit('/', 1)[-1]]
                        return schema['type']
                    self.assertEqual({p['in']: parameter_type(p) for p in methods['get']['parameters']},
                                     {'path': 'integer', 'query': 'boolean', 'header': 'string'})
                    self.assertIn('X-Tenant', json.dumps(postman_collection(spec, base)))
                    self.assertEqual(client.post(f'/api/listeners/{project.id}/orders/42').status_code, 405)
            finally:
                client.post(f"/api/debug/{state['sessionId']}/action", json={'action': 'stop'})
        main.runtime_states.pop(project.id, None)

    def test_hmac_preview_uses_the_actual_encoded_request_target(self):
        import time
        from tests.test_api_blueprint import plan_project
        from app import main
        project,_=plan_project();project.resources[0].config.update(authentication='HMAC',hmacSecret='test-secret',hmacKeyId='default')
        path='/api/listeners/'+project.id+'/orders/a%20b';stamp=str(int(time.time()));nonce='abcdefghijklmnop'
        signature=transport.hmac_signature({'hmacSecret':'test-secret'},'GET',path,b'',stamp,nonce)
        headers={'Authorization':'HMAC '+signature,'X-MINA-Timestamp':stamp,'X-MINA-Nonce':nonce,'X-MINA-Key-Id':'default'}
        with patch.object(main,'get_project',return_value=project),patch.object(main,'append_project_logs'),TestClient(main.app) as client:
            self.assertEqual(client.get(path,headers=headers).status_code,200)
        main.runtime_states.pop(project.id,None)

    def test_contract_routes_methods_and_head_are_resolved_in_preview(self):
        from tests.test_api_blueprint import plan_project
        from app import main
        project,_=plan_project()
        with patch.object(main,'get_project',return_value=project),patch.object(main,'append_project_logs'),TestClient(main.app) as client:
            prefix='/api/listeners/'+project.id
            self.assertEqual(client.get(prefix+'/health').json(),{'status':'ok'})
            self.assertEqual(client.head(prefix+'/health').status_code,200)
            self.assertEqual(client.post(prefix+'/health').status_code,405)
            self.assertEqual(client.options(prefix+'/health').status_code,204)
            self.assertEqual(client.get(prefix+'/orders/42').status_code,200)
        main.runtime_states.pop(project.id,None)

    def test_https_shared_connection_cannot_be_bypassed_with_plain_http_preview(self):
        from tests.test_api_blueprint import plan_project
        from app import main
        for settings in ({'tlsEnabled':True},{'scheme':'https','tlsEnabled':False}):
            project,_=plan_project();project.resources[0].config.update(settings)
            self.assertTrue(server_tls(project.resources[0].config))
            with patch.object(main,'get_project',return_value=project),TestClient(main.app) as client:
                self.assertEqual(client.get('/api/listeners/'+project.id+'/health').status_code,400)

class ActivityBridgeTests(unittest.IsolatedAsyncioTestCase):
    async def test_hosted_endpoints_accept_and_negotiate_checked_content_types(self):
        runtime = WorkflowRuntime()
        with socket.socket() as probe:
            probe.bind(('127.0.0.1', 0))
            port = probe.getsockname()[1]
        xml_type = 'application/vnd.mina.order+xml'
        media_types = ['application/json', 'application/xml', xml_type]
        routes = []
        tasks = []
        for kind in ('http_listener', 'rest'):
            config = {'operation': 'receiver' if kind == 'rest' else 'listen', 'path': '/'+kind, 'methods': 'POST',
                      'requestContentTypes': media_types, 'responseContentTypes': media_types,
                      'requestSchema': SCHEMA, 'validateRequest': True}
            tasks.append({'id': kind, 'name': kind, 'kind': 'starter', 'activities': [
                {'id': 'Receive', 'name': 'Receive', 'type': kind, 'config': config},
                {'id': 'Reply', 'name': 'Reply', 'type': 'http_response', 'config': {
                    'inputMappings': {'body': '{"order":{"name":"Mina"}}'},
                }},
            ], 'transitions': [{'id': 'a', 'source': 'Receive', 'target': 'Reply'}]})
            routes.append(((kind, 'Receive'), {'host': '127.0.0.1', 'port': port, 'minimumQtpThreads': 1}, config))
        project = Project.model_validate({'id': 'multi-media', 'name': 'Multiple formats', 'tasks': tasks})

        async def handler(metadata, payload):
            task = next(task for task in project.tasks if task.id == metadata[0])
            if payload['headers']['content-type'].startswith('application/xml'):
                self.assertEqual(payload['xmlBody']['order']['name'], 'Mina')
            result = await runtime.run(task, payload, {}, {}, metadata[1], project)
            self.assertEqual(result.status, 'completed', result.logs)
            return result.output

        ready = asyncio.Event()
        job = asyncio.create_task(serve(routes, handler, ready))
        try:
            await asyncio.wait_for(ready.wait(), 10)
            async with httpx.AsyncClient(base_url=f'http://127.0.0.1:{port}', trust_env=False) as client:
                spec = (await client.get('/_mina/openapi.json')).json()
                collection = (await client.get('/_mina/postman.json')).json()
                for kind in ('http_listener', 'rest'):
                    with self.subTest(kind=kind):
                        path = '/'+kind
                        xml_body = '<order><name>Mina</name></order>'
                        xml = await client.post(path, json={'name': 'Mina'}, headers={
                            'Accept': 'application/json;q=0.2, application/xml;q=0.8'})
                        self.assertEqual(xml.status_code, 200, xml.text)
                        self.assertEqual(xml.headers['content-type'], 'application/xml')
                        self.assertIn('Accept', xml.headers['vary'])
                        self.assertEqual(xml.text, xml_body)
                        response = await client.post(path, content=xml_body, headers={
                            'Content-Type': 'application/xml; charset=utf-8', 'Accept': 'application/json'})
                        self.assertEqual(response.headers['content-type'], 'application/json')
                        self.assertEqual(response.json(), {'order': {'name': 'Mina'}})
                        custom = await client.post(path, content=xml_body, headers={'Content-Type': xml_type, 'Accept': xml_type})
                        self.assertEqual(custom.headers['content-type'], xml_type)
                        self.assertEqual(custom.text, xml_body)
                        default = await client.post(path, json={'name': 'Mina'})
                        self.assertEqual(default.headers['content-type'], 'application/json')
                        self.assertEqual((await client.post(path, content='unsupported', headers={'Content-Type': 'text/plain'})).status_code, 415)
                        self.assertEqual((await client.post(path, json={'name': 'Mina'}, headers={'Accept': 'application/*;q=0'})).status_code, 406)
                        self.assertEqual((await client.post(path, json={})).status_code, 400)
                        operation = spec['paths'][path]['post']
                        self.assertEqual(list(operation['requestBody']['content']), media_types)
                        self.assertEqual(list(operation['responses']['200']['content']), media_types)
                        exported = [{header['key']: header['value'] for header in item['request']['header']}
                                    for item in collection['item'] if item['request']['url']['raw'] == '{{baseUrl}}'+path]
                        self.assertEqual([headers['Content-Type'] for headers in exported], media_types)
                        self.assertTrue(all(headers['Accept'] == ', '.join(media_types) for headers in exported))
                        xml_export = next(item['request'] for item in collection['item']
                                          if item['name'] == f'POST {path} ({xml_type})')
                        replay = await client.post(path, content=xml_export['body']['raw'],
                                                   headers={'Content-Type': xml_type, 'Accept': xml_type})
                        self.assertEqual(replay.status_code, 200, replay.text)
        finally:
            job.cancel()
            await asyncio.gather(job, return_exceptions=True)

    async def test_http_and_rest_inbound_outbound_activity_matrix_on_real_listeners(self):
        runtime=WorkflowRuntime()
        def free_port():
            with socket.socket() as probe:probe.bind(('127.0.0.1',0));return probe.getsockname()[1]
        provider_port=free_port();bridge_port=free_port()
        connection={'host':'127.0.0.1','minimumQtpThreads':1,'maximumQtpThreads':8}
        async def provider(metadata,payload):
            headers = payload['headers']
            return {'__httpResponse': True, 'body': {
                'echo': payload['body'], 'trace': headers.get('x-trace'),
                'contentType': headers.get('content-type'), 'accept': headers.get('accept'),
            }}
        tasks=[];routes=[];expected_types={}
        for inbound in ('http_listener','rest'):
            for outbound in ('http','rest'):
                name=inbound+'-'+outbound;path='/'+name
                request_type, response_type = (
                    ('application/vnd.mina.request+json', 'application/vnd.mina.reply+json')
                    if inbound == 'rest' else ('application/json', 'text/plain')
                )
                expected_types[name] = (request_type, response_type)
                outbound_type = request_type if inbound == 'rest' else 'text/xml'
                config={'operation':'receiver' if inbound=='rest' else 'listen','path':path,'methods':'POST','requestSchema':SCHEMA,'validateRequest':True,
                        'contentType': request_type, 'responseType': response_type}
                mappings = {
                    'RestInputRequest.Config.Method': '"POST"',
                    'RestInputRequest.Config.requestURI': '"/provider"',
                    'RestInputRequest.Config.RequestBody': '${input.body}' if inbound == 'rest' else json.dumps('<Order/>'),
                    'RestInputRequest.Headers.content-type': json.dumps(outbound_type),
                    'RestInputRequest.Headers.accept': json.dumps(response_type),
                    'RestInputRequest.Headers.DynamicHeaders': '[{"name":"X-Trace","value":"matrix"}]',
                }
                nodes = [
                    {'id':'Receive','name':'Receive','type':inbound,'config':config},
                    {'id':'Call','name':'Call','type':outbound,'config': {
                        'operation':'invoke' if outbound=='rest' else 'request', 'requestModel':'tree',
                        'baseUrl':f'http://127.0.0.1:{provider_port}', 'inputMappings':mappings,
                    }},
                    {'id':'Reply','name':'Reply','type':'http_response','config': {
                        'contentType': response_type if outbound == 'http' else 'application/octet-stream',
                        'inputMappings': {'body':'${last.body}', **(
                            {'contentType':json.dumps(response_type)} if outbound == 'rest' else {}
                        )},
                    }},
                ]
                tasks.append({'id':name,'name':name,'kind':'starter','activities':nodes,'transitions':[{'id':'a','source':'Receive','target':'Call'},{'id':'b','source':'Call','target':'Reply'}]})
                routes.append(((name,'Receive'),{**connection,'port':bridge_port},config))
        project=Project.model_validate({'id':'activity-matrix','name':'Matrix','tasks':tasks})
        async def bridge(metadata,payload):
            task=next(task for task in project.tasks if task.id==metadata[0]);result=await runtime.run(task,payload,{}, {},metadata[1],project)
            self.assertEqual(result.status,'completed',result.logs);return result.output
        jobs=[]
        try:
            for members,handler in [([(None,{**connection,'port':provider_port},{'path':'/provider','methods':'POST'})],provider),(routes,bridge)]:
                ready=asyncio.Event();job=asyncio.create_task(serve(members,handler,ready));jobs.append(job)
                await asyncio.wait_for(ready.wait(),10)
            async with httpx.AsyncClient(trust_env=False) as client:
                base = f'http://127.0.0.1:{bridge_port}'
                spec = (await client.get(base+'/_mina/openapi.json')).json()
                collection = (await client.get(base+'/_mina/postman.json')).json()
                exported = {item['name']: item['request'] for item in collection['item']}
                for task in project.tasks:
                    with self.subTest(task=task.id):
                        request_type, response_type = expected_types[task.id]
                        path = '/' + task.id
                        result = await client.post(base+path, json={'name':task.id}, headers={'Content-Type':request_type})
                        self.assertEqual(result.status_code, 200, result.text)
                        self.assertEqual(result.headers['content-type'], response_type)
                        self.assertEqual(result.json(), {
                            'echo': {'name':task.id} if task.id.startswith('rest-') else '<Order/>', 'trace':'matrix',
                            'contentType':request_type if task.id.startswith('rest-') else 'text/xml', 'accept':response_type,
                        })
                        operation = spec['paths'][path]['post']
                        self.assertEqual(set(operation['requestBody']['content']), {request_type})
                        self.assertEqual(set(operation['responses']['200']['content']), {response_type})
                        headers = {header['key'].lower():header['value'] for header in exported['POST '+path]['header']}
                        self.assertEqual(headers['content-type'], request_type)
                        self.assertEqual(headers['accept'], response_type)
        finally:
            transport.close_clients()
            for job in jobs:job.cancel()
            await asyncio.gather(*jobs,return_exceptions=True)

class ExportContractTests(unittest.TestCase):
    def test_multiple_content_types_and_documentation_work_in_both_python_archives(self):
        from app.api_blueprint import blueprint_plan
        from app.raw_python import raw_python_files,engine_python_files
        for compiler in (raw_python_files,engine_python_files):
            with self.subTest(compiler=compiler.__name__),tempfile.TemporaryDirectory() as folder:
                with socket.socket() as probe:probe.bind(('127.0.0.1',0));port=probe.getsockname()[1]
                plan=blueprint_plan(SPEC,['echo'],{'type':'http','config':{'host':'127.0.0.1','port':port,'minimumQtpThreads':1,'maximumQtpThreads':4}})
                types = ['text/plain', 'application/json']
                plan['tasks'][0]['activities'][0]['config'].update(requestContentTypes=types, responseContentTypes=types)
                plan['tasks'][0]['activities'][1]['config']={'statusCode':200,'inputMappings':{'body':'${input.body}'}}
                project=Project.model_validate({'id':'export-contracts','name':'Export contracts','resources':[plan['resource']],'tasks':plan['tasks']})
                for name,data in compiler(project.model_dump(),{'local':[]}).items():
                    target=Path(folder)/name;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(data)
                driver=Path(folder)/'check.py'
                driver.write_text(f'''import asyncio,httpx
from application.main import run_application
async def check():
 job=asyncio.create_task(run_application('local'))
 try:
  async with httpx.AsyncClient(trust_env=False) as client:
   for _ in range(100):
    if job.done():await job
    try:
     response=await client.post('http://127.0.0.1:{port}/echo',content='hello',headers={{'Content-Type':'text/plain'}},timeout=.2)
     break
    except (httpx.ConnectError,httpx.ConnectTimeout):await asyncio.sleep(.05)
   else:raise AssertionError('Listener did not start')
   assert response.status_code==200 and response.text=='hello',response.text
   assert response.headers['content-type']=='text/plain'
   response=await client.post('http://127.0.0.1:{port}/echo',json={{'name':'hello'}},headers={{'Accept':'application/json'}})
   assert response.status_code==200 and response.json()=={{'name':'hello'}},response.text
   assert response.headers['content-type']=='application/json'
   spec=(await client.get('http://127.0.0.1:{port}/_mina/openapi.json')).json()
   assert set(spec['paths']['/echo']['post']['requestBody']['content'])=={{'text/plain','application/json'}}
   assert set(spec['paths']['/echo']['post']['responses']['200']['content'])=={{'text/plain','application/json'}}
 finally:
  job.cancel()
  try:await job
  except asyncio.CancelledError:pass
asyncio.run(check())
''',encoding='utf-8')
                result=subprocess.run([sys.executable,str(driver)],cwd=folder,capture_output=True,text=True,timeout=30)
                self.assertEqual(result.returncode,0,result.stdout+result.stderr)
