import asyncio, copy, json, socket, subprocess, sys, tempfile, unittest
from pathlib import Path
from unittest.mock import patch
import httpx
from fastapi.testclient import TestClient
from app.api_blueprint import validate_blueprint, blueprint_plan
from app import http_transport as transport
from app.models import Project

DOCUMENT='''openapi: 3.0.3
info: {title: Test API, version: '1.0'}
paths:
  /orders/{id}:
    get:
      operationId: getOrder
      parameters:
        - {in: path, name: id, required: true, schema: {type: string}}
      responses:
        200:
          description: Order
          content:
            application/json:
              schema: {type: object, required: [id], properties: {id: {type: string}}}
              example: {id: '${input.secret}'}
  /health:
    get:
      responses:
        '200':
          description: Health
          content:
            application/json:
              example: {status: ok}
'''

def connection(port=8080):return {'type':'http','config':{'connectorMode':'server','host':'127.0.0.1','port':port,'minimumQtpThreads':1,'maximumQtpThreads':2}}

def plan_project(port=8080,mode='example',secured=False):
    validated=validate_blueprint(DOCUMENT)
    document = validated['document']
    server = connection(port)
    if secured:
        document['components'] = {'securitySchemes': {'access': {'type':'http','scheme':'bearer'}}}
        document['paths']['/reset'] = {'get': {'operationId':'reset','security':[{'access':[]}],
                                              'responses': {'205': {'description':'Reset'}}}}
        server['config'].update(authentication='Bearer', bearerToken='audit-token', httpErrorFormat='problem')
    operations = [operation['operationId'] for operation in validated['operations']]
    plan=blueprint_plan(document,operations + (['reset'] if secured else []),server,response_mode=mode)
    if secured:
        plan['tasks'][-1]['activities'][1]['config']['statusCode'] = 205
    project=Project.model_validate({'id':'blueprint-test','name':'Blueprint Test','properties':{'local':[]},'resources':[plan['resource']],'tasks':plan['tasks'],'active_task_id':plan['tasks'][0]['id']})
    return project,plan

class BlueprintValidationTests(unittest.TestCase):
    def test_secured_operation_requires_compatible_connection_before_hosting(self):
        document = validate_blueprint(DOCUMENT)['document']
        document['components'] = {'securitySchemes': {'access': {'type':'http','scheme':'bearer'}}}
        document['security'] = [{'access': []}]
        with self.assertRaisesRegex(ValueError, 'cannot enforce'):
            blueprint_plan(document, ['getOrder'], connection())
        server = connection()
        server['config']['authentication'] = '${properties.auth.mode}'
        self.assertTrue(blueprint_plan(document, ['getOrder'], server)['warnings'])
        document['paths']['/orders/{id}']['get']['security'] = []
        self.assertTrue(blueprint_plan(document, ['getOrder'], connection())['tasks'])

    def test_validate_normalizes_yaml_and_supplies_missing_operation_ids(self):
        result=validate_blueprint(DOCUMENT)
        self.assertEqual(result['name'],'Test API');self.assertEqual(len(result['operations']),2)
        self.assertTrue(all(operation['hasExample'] for operation in result['operations']))
        self.assertIn('200',result['document']['paths']['/orders/{id}']['get']['responses'])
        self.assertEqual(validate_blueprint(DOCUMENT)['operations'],result['operations'])

    def test_invalid_yaml_schemas_and_duplicate_routes_are_rejected(self):
        for document in ('openapi: [broken', 'info: {title: Not an API}',DOCUMENT.replace('type: string','type: wrong',1),DOCUMENT.replace('/health:','/orders/{name}:'),DOCUMENT.replace('required: true','required: false')):
            with self.subTest(document=document[:40]),self.assertRaises((ValueError,KeyError)):validate_blueprint(document)
        with self.assertRaises(ValueError):validate_blueprint(DOCUMENT+'\npaths: {}')
        broken=validate_blueprint(DOCUMENT)['document'];broken['components']={'schemas':{'Broken':{'type':'object','properties':{'nested':{'$ref':'#/components/schemas/Missing'}}}}}
        with self.assertRaisesRegex(ValueError,'Unresolved API reference'):validate_blueprint(broken)

    def test_yaml_12_strings_are_not_implicit_booleans(self):
        from app.http_contracts import load_document
        value=load_document('a: on\nb: off\nc: true\nd: 2026-11-08')
        self.assertEqual(value,{'a':'on','b':'off','c':True,'d':'2026-11-08'})

    def test_plan_stores_one_contract_and_preserves_connection_bindings(self):
        original=connection();original['config']['trustedCertificateFolder']='${properties.http.roots}'
        validated=validate_blueprint(DOCUMENT);selected=[operation['operationId'] for operation in validated['operations']]
        plan=blueprint_plan(DOCUMENT,selected,original)
        self.assertNotIn('openApiDocument',original['config'])
        self.assertEqual(plan['resource']['config']['trustedCertificateFolder'],'${properties.http.roots}')
        self.assertTrue(all(task['activities'][1]['config']['statusCode']==501 for task in plan['tasks']))
        self.assertTrue(all('openApiDocument' not in task['activities'][0]['config'] for task in plan['tasks']))
        self.assertNotEqual(plan['resource']['id'],blueprint_plan(DOCUMENT,selected,original)['resource']['id'])
        with self.assertRaises(ValueError):blueprint_plan(DOCUMENT,['missing'],original)
        with self.assertRaises(ValueError):blueprint_plan(DOCUMENT,selected,{'type':'http','config':{'connectorMode':'client'}})

    def test_validate_and_plan_endpoints_return_validation_errors(self):
        from app.main import app
        with TestClient(app) as client:
            self.assertEqual(client.post('/api/api-blueprint/validate',json={'document':'bad: ['}).status_code,400)
            result=client.post('/api/api-blueprint/validate',json={'document':DOCUMENT});self.assertEqual(result.status_code,200)
            response=client.post('/api/api-blueprint/plan',json={'document':DOCUMENT,'operationIds':[operation['operationId'] for operation in result.json()['operations']],'connection':connection()})
            self.assertEqual(response.status_code,200);self.assertEqual(len(response.json()['tasks']),2)

    def test_default_confidentiality_requires_verified_tls_and_fresh_pool_identity(self):
        cfg={'defaultConfidentiality':True}
        ctx=transport.tls_context(cfg);self.assertTrue(ctx.check_hostname)
        self.assertEqual(ctx.verify_mode,__import__('ssl').CERT_REQUIRED)
        with self.assertRaises(transport.HTTPFault):transport.tls_context({**cfg,'verifyTls':False})
        self.assertNotEqual(transport._fingerprint(cfg),transport._fingerprint({}))
        client=httpx.Client(transport=httpx.MockTransport(lambda request:httpx.Response(200,json={'url':str(request.url)})))
        client._mina_route_limit=1;client._mina_routes={};client._mina_lock=__import__('threading').Lock()
        try:
            with patch.object(transport,'client_for',return_value=client):
                output=transport.request({'url':'/health','host':'provider.test','defaultConfidentiality':True})
            self.assertEqual(output['body']['url'],'https://provider.test/health')
        finally:client.close()

class BlueprintHostingTests(unittest.IsolatedAsyncioTestCase):
    async def test_declared_head_operation_overrides_get_fallback(self):
        from app.http_server import ListenerApp,listener_config
        connection={'minimumQtpThreads':1,'maximumQtpThreads':2}
        routes=[(method,listener_config(connection,{'path':'/','methods':method})) for method in ('GET','HEAD')]
        async def handle(method,payload):return {'statusCode':204 if method=='HEAD' else 200,'body':''}
        app=ListenerApp(routes,handle,connection,warm_workers=False)
        try:
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app),base_url='http://test') as client:self.assertEqual((await client.head('/')).status_code,204)
        finally:app.executor.shutdown(wait=True)

    async def test_studio_run_hosts_all_blueprint_routes_and_stops(self):
        from app import main
        with socket.socket() as probe:probe.bind(('127.0.0.1',0));port=probe.getsockname()[1]
        project,plan=plan_project(port,secured=True);task=project.tasks[0];event=task.activities[0]
        with patch.object(main,'append_project_logs'):
            try:
                await main._start_http_listener(project,task,event,'local')
                async with httpx.AsyncClient(trust_env=False,headers={'Authorization':'Bearer audit-token'}) as client:
                    order=await client.get(f'http://127.0.0.1:{port}/orders/42');self.assertEqual(order.status_code,200);self.assertEqual(order.json(),{'id':'${input.secret}'})
                    health=await client.get(f'http://127.0.0.1:{port}/health');self.assertEqual(health.json(),{'status':'ok'})
                    reset=await client.get(f'http://127.0.0.1:{port}/reset')
                    self.assertEqual((reset.status_code,reset.content),(205,b''))
                    denied=await client.get(f'http://127.0.0.1:{port}/reset',headers={'Authorization':'Bearer invalid'})
                    self.assertEqual((denied.status_code,denied.headers['content-type']),(401,'application/problem+json'))
            finally:
                job=main.active_runs.pop(project.id,None)
                if job:await main._cancel_and_wait(job)
                main.runtime_states.pop(project.id,None)
        with socket.socket() as probe:probe.bind(('127.0.0.1',port))

class BlueprintExportTests(unittest.TestCase):
    def test_both_python_archives_host_all_routes_from_the_yaml(self):
        from app.raw_python import raw_python_files,engine_python_files
        for compiler in (raw_python_files,engine_python_files):
            with self.subTest(compiler=compiler.__name__),tempfile.TemporaryDirectory() as folder:
                with socket.socket() as probe:probe.bind(('127.0.0.1',0));port=probe.getsockname()[1]
                project,_=plan_project(port,secured=True)
                for name,data in compiler(project.model_dump(),{'local':[]}).items():
                    target=Path(folder)/name;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(data)
                script=f'''import asyncio, httpx, os
from application.main import run_application
os.environ['resources.{project.resources[0].id}.config.bearerToken'] = 'audit-token'
async def main():
    job=asyncio.create_task(run_application('local'))
    try:
        async with httpx.AsyncClient(trust_env=False,headers={{'Authorization':'Bearer audit-token'}}) as client:
            for attempt in range(100):
                if job.done():await job
                try:
                    response=await client.get('http://127.0.0.1:{port}/health',timeout=.2)
                    break
                except (httpx.ConnectError,httpx.ConnectTimeout):await asyncio.sleep(.05)
            else:raise AssertionError('API did not start')
            assert response.json()=={{'status':'ok'}},response.text
            order=await client.get('http://127.0.0.1:{port}/orders/42')
            assert order.json()=={{'id':'${{input.secret}}'}},order.text
            reset=await client.get('http://127.0.0.1:{port}/reset')
            assert reset.status_code==205 and not reset.content, reset.text
            denied=await client.get('http://127.0.0.1:{port}/reset',headers={{'Authorization':'Bearer invalid'}})
            assert denied.status_code==401 and denied.headers['content-type']=='application/problem+json', denied.text
            docs=await client.get('http://127.0.0.1:{port}/_mina/docs')
            assert docs.status_code==200 and 'SwaggerUIBundle' in docs.text,docs.text
            asset=await client.get('http://127.0.0.1:{port}/_mina/assets/swagger-ui-bundle.js')
            assert asset.status_code==200 and 'SwaggerUIBundle' in asset.text
            spec=await client.get('http://127.0.0.1:{port}/_mina/openapi.json')
            assert set(spec.json()['paths'])=={{'/orders/{{id}}','/health','/reset'}},spec.text
            collection=await client.get('http://127.0.0.1:{port}/_mina/postman.json')
            assert len(collection.json()['item'])==3,collection.text
    finally:
        job.cancel()
        try:await job
        except asyncio.CancelledError:pass
asyncio.run(main())
'''
                driver=Path(folder)/'check_api.py';driver.write_text(script,encoding='utf-8')
                result=subprocess.run([sys.executable,str(driver)],cwd=folder,capture_output=True,text=True,timeout=30)
                self.assertEqual(result.returncode,0,result.stdout+result.stderr)
