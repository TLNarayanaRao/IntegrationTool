"""Maintainer tool: rebuild importable projects and collections from MINA contracts."""
import copy,json,sys,zipfile
from pathlib import Path
ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT.parents[1]/'backend'))
from app.api_blueprint import blueprint_plan
from app.api_docs import generate_openapi,postman_collection
from app.http_server import listener_config
from app.models import Project
from app.project_import import project_payload

def prop(key,value,kind='string'):return {'key':key,'value':value,'data_type':kind}
def ref(key):return '${properties.'+key+'}'
COMMON=[prop('demo.directory',(ROOT/'local').as_posix()),prop('demo.username','mina-demo'),prop('demo.password','mina-demo-password','password'),prop('demo.clientId','mina-demo-client'),prop('demo.clientSecret','mina-demo-client-secret','password'),prop('demo.hmacSecret','mina-demo-hmac-secret-change-before-real-use','password'),prop('demo.jwtSecret','mina-demo-jwt-secret-at-least-32-characters','password')]
TLS={'scheme':'https','tlsEnabled':True,'certificateFile':ref('demo.directory')+'/server-chain.pem','privateKeyFile':ref('demo.directory')+'/server-key.pem','trustedCertificateFolder':ref('demo.directory')+'/trusted-roots','verifyTls':True}
AUTH={
 'Basic':{'authentication':'Basic','username':ref('demo.username'),'password':ref('demo.password')},
 'OAuth2':{'authentication':'OAuth2','oauthClientId':ref('demo.clientId'),'oauthClientSecret':ref('demo.clientSecret'),'oauthTokenUrl':'https://localhost:9444/token','oauthIntrospectionUrl':'https://localhost:9444/introspect','oauthGrantType':'client_credentials','oauthScope':'orders.read','oauthRequiredScopes':'orders.read'},
 'JWT':{'authentication':'JWT','jwtSecret':ref('demo.jwtSecret'),'jwtAlgorithm':'HS256','jwtIssuer':'mina-demo','jwtAudience':'mina-sample-api','jwtClaims':{'sub':'sample-client'},'jwtLifetimeSeconds':300},
 'HMAC':{'authentication':'HMAC','hmacSecret':ref('demo.hmacSecret'),'hmacKeyId':'default','hmacAlgorithm':'SHA256'},
 'Certificate':{'authentication':'Certificate','clientAuthentication':'required','clientCertificateFile':ref('demo.directory')+'/client-chain.pem','clientKeyFile':ref('demo.directory')+'/client-key.pem'},
}
def contract(multiple=False):
    document={'openapi':'3.0.3','info':{'title':'MINA sample API','version':'1.0.0'},'paths':{'/hello':{'get':{'operationId':'hello','summary':'Read a sample greeting','responses':{'200':{'description':'Greeting','content':{'application/json':{'schema':{'type':'object','required':['message'],'properties':{'message':{'type':'string'}}},'example':{'message':'Hello from MINA'}}}}}}}}}
    if multiple:
        document['paths']['/orders/{id}']={'get':{'operationId':'getOrder','summary':'Read order using path and optional query values','parameters':[{'name':'id','in':'path','required':True,'schema':{'type':'string'},'example':'42'},{'name':'detail','in':'query','schema':{'type':'boolean'},'example':True}], 'responses':{'200':{'description':'Order example','content':{'application/json':{'example':{'id':'42','status':'accepted'}}}}}}}
        schema={'type':'object','required':['name'],'additionalProperties':False,'properties':{'name':{'type':'string','minLength':1},'quantity':{'type':'integer','minimum':1}}}
        document['paths']['/echo']={'post':{'operationId':'echo','summary':'Validate and echo a JSON body','requestBody':{'required':True,'content':{'application/json':{'schema':schema,'example':{'name':'Sample item','quantity':2}}}},'responses':{'200':{'description':'Validated body','content':{'application/json':{'schema':schema,'example':{'name':'Sample item','quantity':2}}}}}}}
    return document

def activity(id,type,config):return {'id':id,'name':id,'type':type,'position':{'x':150+300*({'Start':0,'Call':1,'End':2}.get(id,0)),'y':160},'config':config}
def task(id,nodes):return {'id':id,'name':id,'kind':'starter','activities':nodes,'transitions':[{'id':f'edge-{i}','source':left['id'],'target':right['id'],'type':'success'} for i,(left,right) in enumerate(zip(nodes,nodes[1:]))]}
def project(slug,title,resources,tasks):return {'id':'mina-example-'+slug,'name':title,'description':'Local learning sample. Demo credentials only; see the accompanying README.','resources':resources,'tasks':tasks,'active_task_id':tasks[0]['id'],'active_environment':'local','properties':{'local':copy.deepcopy(COMMON)}}
def resolve(value):
    if isinstance(value,dict):return {key:resolve(item) for key,item in value.items()}
    if isinstance(value,list):return [resolve(item) for item in value]
    if isinstance(value,str):
        for item in COMMON:value=value.replace(ref(item['key']),str(item['value']))
    return value

def build():
    for name in ('projects','postman','specs'):(ROOT/name).mkdir(exist_ok=True)
    scenarios=[]
    def save(slug,title,resources,tasks,role,port,paired=None,notes=''):
        payload=project(slug,title,resources,tasks);Project.model_validate(payload)
        data=json.dumps(payload,indent=2).encode();target=ROOT/'projects'/(slug+'.mpackage')
        with zipfile.ZipFile(target,'w',zipfile.ZIP_DEFLATED) as archive:
            archive.writestr('manifest.json',json.dumps({'format':'mina-project','version':2,'projectId':payload['id'],'name':title}))
            archive.writestr('project.json',data)
        assert json.loads(project_payload(target.read_bytes()))['id']==payload['id']
        scenarios.append({'file':'projects/'+target.name,'projectId':payload['id'],'title':title,'role':role,'port':port,'pairedProject':paired,'notes':notes})
        return payload
    hosts=[('01-host-one-http','Host one REST API',9001,False,None,False),('02-host-multiple-http','Host multiple REST operations',9002,False,None,True),('03-host-generic-http','Host a plain HTTP listener',9003,False,None,False),('04-host-https','Host HTTPS with root-only client trust',9443,True,None,False),('05-host-basic','Host HTTPS with Basic authentication',9445,True,'Basic',False),('06-host-oauth2','Host HTTPS with OAuth2 token introspection',9446,True,'OAuth2',False),('07-host-jwt','Host HTTPS with JWT validation',9447,True,'JWT',False),('08-host-hmac','Host HTTPS with HMAC signatures',9448,True,'HMAC',False),('09-host-mtls','Host HTTPS with mutual TLS',9449,True,'Certificate',False)]
    for slug,title,port,tls,auth,multiple in hosts:
        cfg={'connectorMode':'server','host':'127.0.0.1','port':port,'minimumQtpThreads':1,'maximumQtpThreads':8,'authentication':'None','apiDocsEnabled':True,'apiDocsAccess':'authenticated'}
        if tls:cfg.update(copy.deepcopy(TLS))
        if auth:cfg.update(copy.deepcopy(AUTH[auth]))
        document=contract(multiple)
        selected=['hello','getOrder','echo'] if multiple else ['hello']
        plan=blueprint_plan(document,selected,{'type':'http','config':cfg},title,response_mode='example')
        old=plan['blueprintId'];stable='api-'+slug
        plan=json.loads(json.dumps(plan).replace(old,stable))
        if multiple:plan['tasks'][2]['activities'][1]['config']['inputMappings']['body']='${input.body}'
        if slug.startswith('03'):
            plan['resource']['config'].pop('openApiDocument');plan['resource']['config'].pop('apiBlueprintId')
            node=plan['tasks'][0]['activities'][0];node['type']='http_listener';node['name']='HTTP-Listener';node['config']={'operation':'listen','resourceId':plan['resource']['id'],'path':'/hello','methods':'GET'}
        payload=save(slug,title,[plan['resource']],plan['tasks'],'host',port,notes='Start the OAuth fixture first.' if auth=='OAuth2' else '')
        (ROOT/'specs'/(slug+'.openapi.json')).write_text(json.dumps(document,indent=2),encoding='utf-8')
        routes=[((t['id'],t['activities'][0]['id']),listener_config(resolve(plan['resource']['config']),resolve(t['activities'][0]['config']))) for t in plan['tasks']]
        base=f'{"https" if tls else "http"}://localhost:{port}'
        collection=postman_collection(generate_openapi(routes,base,title),base)
        (ROOT/'postman'/(slug+'.postman_collection.json')).write_text(json.dumps(collection,indent=2),encoding='utf-8')
    clients=[('10-call-http',9001,False,None,'01-host-one-http','http'),('11-invoke-rest',9002,False,None,'02-host-multiple-http','rest'),('12-call-https',9443,True,None,'04-host-https','http'),('13-default-confidentiality',9443,True,None,'04-host-https','rest'),('14-call-basic',9445,True,'Basic','05-host-basic','rest'),('15-call-oauth2',9446,True,'OAuth2','06-host-oauth2','rest'),('16-call-jwt',9447,True,'JWT','07-host-jwt','rest'),('17-call-hmac',9448,True,'HMAC','08-host-hmac','rest'),('18-call-mtls',9449,True,'Certificate','09-host-mtls','rest'),('19-post-json',9002,False,None,'02-host-multiple-http','http'),('20-path-query-headers',9002,False,None,'02-host-multiple-http','rest')]
    for slug,port,tls,auth,paired,kind in clients:
        cfg={'connectorMode':'client','baseUrl':f'{"https" if tls else "http"}://localhost:{port}','authentication':'None','verifyTls':True,'connectionTimeoutMs':5000,'socketTimeoutMs':10000,'activityTimeoutSeconds':30}
        if tls:cfg.update(trustedCertificateFolder=ref('demo.directory')+'/trusted-roots',tlsEnabled=True)
        if slug.startswith('13'):cfg.update(defaultConfidentiality=True,tlsEnabled=False)
        if auth:
            cfg.update(copy.deepcopy(AUTH[auth]));cfg.pop('clientAuthentication',None)
        resource={'id':'client','name':'HTTP client connection','type':'http','config':cfg}
        uri='/orders/{id}' if slug.startswith(('11','20')) else '/echo' if slug.startswith('19') else '/hello'
        mappings={'RestInputRequest.Config.requestURI':json.dumps(uri),'RestInputRequest.Config.Method':json.dumps('POST' if slug.startswith('19') else 'GET'),'RestInputRequest.Headers.accept':json.dumps('application/json')}
        if '{id}' in uri:mappings['RestInputRequest.Config.URIParameters']=json.dumps({'id':'42'})
        if slug.startswith('20'):
            mappings['RestInputRequest.Config.QueryParameters']=json.dumps({'detail':True})
            mappings['RestInputRequest.Headers.DynamicHeaders']=json.dumps([{'name':'X-Correlation-ID','value':'mina-sample-001'},{'name':'X-Channel','value':'studio'}])
        if slug.startswith('19'):
            mappings['RestInputRequest.Config.RequestBody']=json.dumps({'name':'Sample item','quantity':2})
            mappings['RestInputRequest.Headers.content-type']=json.dumps('application/json')
        node=activity('Call',kind,{'resourceId':'client','operation':'invoke' if kind=='rest' else 'request','requestModel':'tree','responseMode':'structured','inputMappings':mappings})
        title=slug.split('-',1)[1].replace('-',' ').title()
        save(slug,title,[resource],[task('Main',[activity('Start','start',{}),node,activity('End','end',{})])],'caller',port,paired)
    (ROOT/'catalog.json').write_text(json.dumps({'scenarios':scenarios},indent=2),encoding='utf-8')
    print(f'Built {len(scenarios)} importable projects, {len(hosts)} collections and OpenAPI documents.')

if __name__=='__main__':build()
