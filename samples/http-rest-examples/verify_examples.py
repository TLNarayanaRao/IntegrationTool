"""Exercise every packaged sample with the repository runtime and local sockets."""
import asyncio,json,ssl,sys,threading
from pathlib import Path
ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT.parents[1]/'backend'))
from app.models import Project
from app.project_import import project_payload
from app.runtime import WorkflowRuntime
from app.http_server import serve
from app.http_transport import request as send_request,HTTPFault,close_clients
from oauth_fixture import server
from tokens import token

async def verify():
    runtime=WorkflowRuntime();catalog=json.loads((ROOT/'catalog.json').read_text())['scenarios'];report=[]
    projects={entry['file']:Project.model_validate_json(project_payload((ROOT/entry['file']).read_bytes())) for entry in catalog}
    fixture=server();thread=threading.Thread(target=fixture.serve_forever,daemon=True);thread.start()
    def props(project):return {item.key:item.value for item in project.properties['local']}
    def resolve(value,project):return runtime.resolve(value,{'properties':props(project),'input':{},'last':{},'vars':{},'context':{}})
    async def direct(cfg,path,method='GET',body=None):return await asyncio.to_thread(send_request,{**cfg,'url':path,'method':method,'body':body})
    try:
        for entry in (item for item in catalog if item['role']=='host'):
            project=projects[entry['file']];resources={r.id:r for r in project.resources};connection=resolve(project.resources[0].config,project)
            tasks={t.id:t for t in project.tasks}
            routes=[((task.id,task.activities[0].id),connection,resolve(task.activities[0].config,project)) for task in project.tasks]
            async def handler(metadata,payload):
                task_id,event_id=metadata
                result=await runtime.run(tasks[task_id],payload,resources,props(project),event_id,project)
                if result.status!='completed':raise AssertionError(result.logs)
                return result.output
            ready=asyncio.Event();job=asyncio.create_task(serve(routes,handler,ready));waiter=asyncio.create_task(ready.wait())
            try:
                done,_=await asyncio.wait([job,waiter],timeout=10,return_when=asyncio.FIRST_COMPLETED)
                if job in done:await job
                assert ready.is_set(),'Host did not start: '+entry['title']
                callers=[item for item in catalog if item.get('pairedProject')==Path(entry['file']).stem]
                docs_client=None
                for caller in callers:
                    client=projects[caller['file']]
                    result=await runtime.run(client.tasks[0],{}, {r.id:r for r in client.resources},props(client),project=client)
                    assert result.status=='completed',(caller['title'],result.logs)
                    assert result.output['statusCode']==200,(caller['title'],result.output)
                    if caller['file'].endswith('19-post-json.mpackage'):assert result.output['body']=={'name':'Sample item','quantity':2}
                    report.append({'case':caller['file'],'status':'passed','statusCode':200})
                    docs_client=resolve(client.resources[0].config,client)
                if docs_client is None:docs_client={'baseUrl':f'http://localhost:{entry["port"]}'}
                spec=await direct(docs_client,'/_mina/openapi.json');assert spec['statusCode']==200
                collection=await direct(docs_client,'/_mina/postman.json');assert collection['statusCode']==200
                expected=3 if entry['port']==9002 else 1
                assert len(collection['body']['item'])==expected
                assert len(spec['body']['paths'])==expected
                report.append({'case':entry['file'],'status':'passed','hostedOperations':expected})
                if entry['port']==9003:assert (await direct(docs_client,'/hello'))['body']=={'message':'Hello from MINA'}
                if entry['port']==9002:
                    for path,method,body,status in [('/echo','POST',{'quantity':0},400),('/hello','DELETE',None,405),('/missing','GET',None,404)]:
                        response=await direct({**docs_client,'raiseForStatus':False},path,method,body)
                        assert response['statusCode']==status,response
                        report.append({'case':f'negative {method} {path}','status':'passed','statusCode':status})
                if entry['port'] in (9445,9446,9447,9448):
                    response=await direct({**docs_client,'authentication':'None','raiseForStatus':False},'/hello')
                    assert response['statusCode']==401,response
                    if entry['port']==9445:
                        response=await direct({**docs_client,'password':'incorrect','raiseForStatus':False},'/hello');assert response['statusCode']==401
                    if entry['port']==9446:
                        response=await direct({**docs_client,'oauthScope':'profile','raiseForStatus':False},'/hello');assert response['statusCode']==401,response
                    if entry['port']==9447:
                        response=await direct({**docs_client,'jwtSecret':'incorrect-signing-key','raiseForStatus':False},'/hello');assert response['statusCode']==401,response
                    if entry['port']==9448:
                        response=await direct({**docs_client,'hmacSecret':'incorrect-signing-key','raiseForStatus':False},'/hello');assert response['statusCode']==401,response
                    report.append({'case':'negative credentials/scopes '+str(entry['port']),'status':'passed'})
                if entry['port'] in (9446,9447):
                    bearer=await asyncio.to_thread(token,'oauth2' if entry['port']==9446 else 'jwt')
                    assert (await direct({**docs_client,'authentication':'Bearer','bearerToken':bearer},'/hello'))['statusCode']==200
                    report.append({'case':'Swagger/Postman token helper '+str(entry['port']),'status':'passed'})
                if entry['port']==9449:
                    try:await direct({**docs_client,'authentication':'None','clientCertificateFile':'','clientKeyFile':''},'/hello')
                    except HTTPFault:pass
                    else:raise AssertionError('Server accepted a client without a certificate')
                    report.append({'case':'missing mutual TLS client certificate rejected','status':'passed'})
                if entry['port']==9443:
                    try:await direct({**docs_client,'trustedCertificateFolder':''},'/hello')
                    except HTTPFault:pass
                    else:raise AssertionError('Untrusted certificate accepted')
                    assert len(list((ROOT/'local/trusted-roots').glob('*.pem')))==1
                    report.append({'case':'root-only chain trust and untrusted-root rejection','status':'passed'})
                print('PASS',entry['title'],flush=True)
            finally:
                close_clients() # Release keep-alive sockets before shutting down the fixture listener.
                waiter.cancel();job.cancel()
                try:await job
                except asyncio.CancelledError:pass
                close_clients(project.id)
    finally:
        await asyncio.to_thread(fixture.shutdown);fixture.server_close();thread.join(timeout=3)
        close_clients()
    (ROOT/'verification-report.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(f'{len(report)} sample and failure checks passed. No listener is left running.')
    return report

if __name__=='__main__':asyncio.run(verify())
