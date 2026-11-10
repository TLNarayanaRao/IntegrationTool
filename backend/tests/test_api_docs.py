import asyncio,base64,gzip,json,socket,unittest,subprocess
from unittest.mock import patch
import httpx
from app.api_docs import HostedAPIDocs,generate_openapi,postman_collection,public_base
from app.http_server import ListenerApp,listener_config
from tests.test_api_blueprint import plan_project

def routes_for(project):
    connection=project.resources[0].config
    return [((task.id,task.activities[0].id),listener_config(connection,task.activities[0].config)) for task in project.tasks]

class DocumentTests(unittest.TestCase):
    def test_xsd_request_and_response_show_structure_and_wire_examples(self):
        from app.data_formats import DataFormats
        request = '''<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema" xmlns:o="urn:orders"
                       targetNamespace="urn:orders" elementFormDefault="qualified">
          <xs:simpleType name="Region"><xs:restriction base="xs:string">
            <xs:enumeration value="EU"/><xs:enumeration value="US"/>
          </xs:restriction></xs:simpleType>
          <xs:complexType name="OrderType"><xs:sequence>
            <xs:element name="Item" type="xs:int" minOccurs="2" maxOccurs="unbounded"/>
            <xs:choice><xs:element name="Region" type="o:Region"/><xs:element name="Domestic" type="xs:boolean"/></xs:choice>
          </xs:sequence><xs:attribute name="id" type="xs:string" use="required"/></xs:complexType>
          <xs:element name="Order" type="o:OrderType"/>
        </xs:schema>'''
        reply = '''<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema">
          <xs:element name="Receipt"><xs:complexType><xs:sequence>
            <xs:element name="Accepted" type="xs:boolean"/>
          </xs:sequence></xs:complexType></xs:element>
        </xs:schema>'''
        for operation in ('listen', 'receiver'):
            with self.subTest(operation=operation):
                cfg = listener_config({}, {'operation':operation, 'path':'/orders', 'methods':'POST',
                                          'requestSchema':request, 'responseSchema':reply})
                spec = generate_openapi([(None, cfg)])
                post = spec['paths']['/orders']['post']
                incoming = post['requestBody']['content']['application/xml']
                outgoing = post['responses']['200']['content']['application/xml']
                models = spec['components']['schemas']
                order = models[incoming['schema']['$ref'].rsplit('/', 1)[-1]]
                receipt = models[outgoing['schema']['$ref'].rsplit('/', 1)[-1]]
                self.assertEqual(order['xml'], {'name':'Order', 'namespace':'urn:orders'})
                self.assertEqual(order['properties']['Item']['minItems'], 2)
                self.assertEqual(order['properties']['Item']['items']['type'], 'integer')
                self.assertTrue(order['properties']['@id']['xml']['attribute'])
                self.assertEqual(order['properties']['Region']['enum'], ['EU', 'US'])
                self.assertEqual(receipt['xml']['name'], 'Receipt')
                self.assertEqual(receipt['properties']['Accepted']['type'], 'boolean')
                DataFormats.validate_xml_document(incoming['example'], request)
                DataFormats.validate_xml_document(outgoing['example'], reply)
                collection = postman_collection(spec, 'http://localhost:8080')
                self.assertEqual(collection['item'][0]['request']['body']['raw'], incoming['example'])
                self.assertNotIn('content', post['responses']['400'])

    def test_browser_and_postman_hmac_signing_matches_server(self):
        from app.api_docs_ui import SIGNER,postman_hmac_script
        from app.http_transport import hmac_signature
        script=SIGNER+"\nconsole.log(JSON.stringify(await minaSign({method:'POST',url:'https://example.com/orders/42?x=a%20b',body:'{\\\"id\\\":42}'},'test-secret','default','SHA256')));"
        result=subprocess.run(['node','--input-type=module','-e',script],capture_output=True,text=True,timeout=10)
        self.assertEqual(result.returncode,0,result.stderr);headers=json.loads(result.stdout)
        expected=hmac_signature({'hmacSecret':'test-secret'},'POST','/orders/42?x=a%20b',b'{"id":42}',headers['X-MINA-Timestamp'],headers['X-MINA-Nonce'])
        self.assertEqual(headers['Authorization'],'HMAC '+expected)
        self.assertIn('pm.variables.get',postman_hmac_script('SHA256'))

    def test_only_selected_routes_and_no_saved_credentials(self):
        project,_=plan_project();routes=routes_for(project)
        routes[0][1].update(authentication='Basic',username='SAVED_USERNAME',password='SAVED_PASSWORD')
        spec=generate_openapi(routes[:1]);collection=postman_collection(spec,'http://localhost:8080')
        self.assertEqual(list(spec['paths']),['/orders/{id}'])
        self.assertEqual(spec['paths']['/orders/{id}']['get']['responses']['200']['description'],'Order')
        self.assertNotIn('SAVED_',json.dumps([spec,collection]))
        self.assertEqual(collection['item'][0]['request']['url']['variable'][0]['key'],'id')
        self.assertEqual(collection['variable'][1]['value'],'')
        def check(value):
            if isinstance(value,dict):
                if '$ref' in value:
                    current=spec
                    for part in value['$ref'][2:].split('/'):current=current[part.replace('~1','/').replace('~0','~')]
                for item in value.values():check(item)
            elif isinstance(value,list):
                for item in value:check(item)
        check(spec)

    def test_generic_listener_and_wildcard_links(self):
        cfg=listener_config({'host':'0.0.0.0','port':8082},{'methods':'GET,POST','path':'/api/{id}'})
        spec=generate_openapi([(None,cfg)])
        self.assertEqual(set(spec['paths']['/api/{id}']),{'get','post'})
        self.assertEqual(public_base(cfg),'http://localhost:8082')
        self.assertEqual(public_base({'host':'::1','port':8082}),'http://[::1]:8082')
        with self.assertRaises(ValueError):public_base({'apiPublicBaseUrl':'https://name:secret@example.com'})
        with self.assertRaises(ValueError):HostedAPIDocs([(None,{**cfg,'path':'/_mina/docs'})],cfg)
        self.assertFalse(HostedAPIDocs([(None,{**cfg,'apiDocsEnabled':False})],cfg).enabled)

class HostedDocumentTests(unittest.IsolatedAsyncioTestCase):
    async def test_offline_swagger_assets_authenticated_spec_and_collection(self):
        project,_=plan_project();routes=routes_for(project);cfg={**routes[0][1],'authentication':'Basic','username':'alice','password':'secret'}
        calls=[]
        async def handle(metadata,payload):calls.append(payload);return {'ok':True}
        app=ListenerApp(routes,handle,cfg,warm_workers=False)
        try:
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
                response=await client.get('/_mina/docs');self.assertEqual(response.status_code,200)
                self.assertIn('SwaggerUIBundle',response.text);self.assertNotIn('cdn.',response.text)
                self.assertIn('nonce-',response.headers['content-security-policy'])
                asset=await client.get('/_mina/assets/swagger-ui-bundle.js');self.assertEqual(asset.status_code,200);self.assertIn('SwaggerUIBundle',asset.text)
                self.assertEqual((await client.get('/_mina/openapi.json')).status_code,401)
                spec=await client.get('/_mina/openapi.json',auth=('alice','secret'));self.assertEqual(spec.status_code,200)
                self.assertEqual(set(spec.json()['paths']),{'/orders/{id}','/health'})
                collection=await client.get('/_mina/postman.json',auth=('alice','secret'));self.assertEqual(collection.status_code,200)
                self.assertIn('attachment',collection.headers['content-disposition'])
                self.assertEqual(len(collection.json()['item']),2);self.assertNotIn('secret',json.dumps(collection.json()).replace('${input.secret}',''))
                self.assertEqual((await client.post('/_mina/docs')).status_code,405)
                self.assertEqual((await client.head('/_mina/docs')).content,b'')
                self.assertEqual(calls,[])
                app.docs.connection={**cfg,'allowedIps':'192.0.2.0/24'}
                self.assertEqual((await client.get('/_mina/openapi.json',auth=('alice','secret'))).status_code,403)
        finally:app.executor.shutdown(wait=True)

    async def test_live_debug_request_pauses_then_returns_response_and_rearms(self):
        from app import main
        from app.http_policy import trace_context
        from app.models import DebugRequest
        from starlette.requests import Request
        with socket.socket() as probe:probe.bind(('127.0.0.1',0));port=probe.getsockname()[1]
        project,_=plan_project(port);task=project.tasks[0];response=task.activities[1]
        project.resources[0].config['propagateTraceContext'] = True
        trace_id = '0af7651916cd43dd8448eb211c80319c'
        request=Request({'type':'http','scheme':'http','server':('127.0.0.1',8787),'path':'/','headers':[],'root_path':''})
        session=None
        with patch.object(main,'get_project',return_value=project),patch.object(main,'append_project_logs'):
            try:
                view=await main.start_debug(project.id,request,DebugRequest(task_id=task.id,breakpoints=[response.id]))
                session=view['sessionId'];state=main.debugger.sessions[session]
                self.assertEqual(view['status'],'listening');self.assertIn('docsUrl',state['endpoints'][0])
                async with httpx.AsyncClient(trust_env=False,timeout=10) as client:
                    self.assertEqual((await client.get(f'http://127.0.0.1:{port}/_mina/docs')).status_code,200)
                    pending=asyncio.create_task(client.get(f'http://127.0.0.1:{port}/orders/42',
                        headers={'traceparent':f'00-{trace_id}-b7ad6b7169203331-01'}))
                    for _ in range(100):
                        if state['status']=='paused':break
                        await asyncio.sleep(.01)
                    self.assertEqual(state['status'],'paused');self.assertFalse(pending.done())
                    busy=await client.get(f'http://127.0.0.1:{port}/health');self.assertEqual(busy.status_code,503)
                    original_step = main.debugger._step
                    async def check_trace(*args, **kwargs):
                        self.assertEqual(trace_context.get()[0], trace_id)
                        return await original_step(*args, **kwargs)
                    self.assertIsNone(trace_context.get())
                    with patch.object(main.debugger, '_step', side_effect=check_trace):
                        await main.debugger.action(session,'continue')
                    self.assertIsNone(trace_context.get())
                    result=await pending;self.assertEqual(result.status_code,200);self.assertEqual(result.json(),{'id':'${input.secret}'})
                    self.assertEqual(state['status'],'listening')
                    state['breakpoints'].clear()
                    self.assertEqual((await client.get(f'http://127.0.0.1:{port}/health')).json(),{'status':'ok'})
                download=main.download_http_collection(project.id,task_id=task.id)
                self.assertEqual(len(json.loads(download.body)['item']),2)
            finally:
                if session:
                    await main._stop_debug_session(session);main.debugger.sessions.pop(session,None)
                main.runtime_states.pop(project.id,None)
        with socket.socket() as probe:probe.bind(('127.0.0.1',port))
