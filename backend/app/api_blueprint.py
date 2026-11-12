"""MINA API Blueprint: validate YAML/JSON contracts and scaffold editable APIs."""
from __future__ import annotations
import copy, hashlib, json, re, uuid
from unicodedata import normalize
from pydantic import TypeAdapter
from .models import PackagePath
from .http_contracts import bundle_document, schema_errors, response_schema
from .rest_contract import compatible_security, operation_config

METHODS={'get','post','put','patch','delete','head','options','trace'}

def _bundle_blueprint(document, reference_documents, document_path):
    references={} if reference_documents is None else reference_documents
    if not isinstance(references,dict) or len(references)>15:raise ValueError('Supply at most 15 reference documents')
    if not isinstance(document_path,str) or len(document_path)>1024:raise ValueError('Invalid API entry document path')
    total=0
    for name,value in references.items():
        if not isinstance(name,str) or not name or len(name)>1024:raise ValueError('Invalid reference document path')
        size=len((value if isinstance(value,str) else json.dumps(value)).encode('utf-8'))
        if size>8*1024**2:raise ValueError('An API reference document exceeds 8 MiB')
        total+=size
    if total>32*1024**2:raise ValueError('API reference documents exceed 32 MiB')
    if isinstance(document,str) and re.match(r'^\ufeff?#%RAML\b',document):
        from .raml_contract import convert_raml
        converted=convert_raml(document,references,document_path or 'api.raml')
        return bundle_document(converted,{'openApiReferenceDocuments':references,'openApiBaseUrl':document_path or 'api.raml'})
    # No origin allowlist: import uses supplied documents only, never network or filesystem reads.
    return bundle_document(document,{'openApiReferenceDocuments':references,'openApiBaseUrl':document_path})


def _examples(operation, cfg, dereference):
    chosen=None
    for code,raw_response in operation['responses'].items():
        response=dereference(raw_response)
        status=int(code) if str(code).isdigit() else int(str(code)[0])*100 if re.fullmatch('[1-5]XX',str(code)) else 599
        headers={}
        for name,raw_header in (response.get('headers') or {}).items():
            if not re.fullmatch(r"[!#$%&'*+.^_`|~0-9A-Za-z-]+",name):raise ValueError('Invalid response header name')
            header=dereference(raw_header)
            if not isinstance(header,dict):raise ValueError('Response header definitions must be objects')
            schema=dereference(header.get('schema') or {})
            if 'example' in header:headers[name]=header['example']
            elif isinstance(schema,dict) and 'default' in schema:headers[name]=schema['default']
        for values in headers.values():
            for value in values if isinstance(values,list) else [values]:
                if any((ord(char)<32 and char!='\t') or ord(char)==127 or ord(char)>255 for char in str(value)):raise ValueError('Invalid response header example or default')
        candidates=[]
        for media,raw_definition in (response.get('content') or {}).items():
            media_start=len(candidates)
            definition=dereference(raw_definition)
            if 'example' in definition:candidates.append((media,definition['example']))
            samples=definition.get('examples',{})
            if not isinstance(samples,dict):raise ValueError('Named response examples must be an object')
            for raw_sample in samples.values():
                sample=dereference(raw_sample)
                if not isinstance(sample,dict):raise ValueError('Named response examples must be objects')
                if 'value' in sample:candidates.append((media,sample['value']))
            schema=dereference(definition.get('schema') or {})
            if len(candidates)==media_start and isinstance(schema,dict):
                if 'example' in schema:candidates.append((media,schema['example']))
                elif isinstance(schema.get('examples'),list):candidates.extend((media,value) for value in schema['examples'])
        swagger_examples=response.get('examples',{})
        if not isinstance(swagger_examples,dict):raise ValueError('Response examples must be an object')
        candidates.extend(swagger_examples.items())
        if not candidates and isinstance(response.get('schema'),dict):
            schema=dereference(response['schema'])
            if isinstance(schema,dict) and 'example' in schema:
                candidates.append(((operation.get('produces') or [cfg.get('responseType','application/json')])[0],schema['example']))
        for media,body in candidates:
            if schema_errors(body,response_schema(cfg,status,media)):
                raise ValueError(f'{operation["operationId"]}: {code} {media} response example does not match its schema')
            if chosen is None and 200<=status<300:chosen={'statusCode':status,'body':body,'contentType':media,'headers':headers}
        if chosen is None and status in (204,205):chosen={'statusCode':status,'body':None,'contentType':'application/json','headers':headers}
    return chosen


def validate_blueprint(document, *, reference_documents=None, document_path=''):
    spec=_bundle_blueprint(document,reference_documents,document_path)
    if len(json.dumps(spec,allow_nan=False).encode())>8*1024**2:raise ValueError('The API contract exceeds 8 MiB')
    if not (str(spec.get('openapi','')).startswith('3.') or spec.get('swagger')=='2.0'):
        raise ValueError('MINA API Blueprint requires an OpenAPI 3 or Swagger 2 YAML/JSON document')
    paths=spec.setdefault('paths', {})
    if not isinstance(paths,dict):raise ValueError('The API contract paths must be an object')
    webhooks = spec.get('webhooks') or {}
    if not isinstance(webhooks, dict):
        raise ValueError('OpenAPI webhooks must be an object')
    for name, definition in webhooks.items():
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,127}', name) or not isinstance(definition, dict):
            raise ValueError('Invalid OpenAPI webhook name or path item')
        path = '/_webhooks/' + name
        if path in paths and (not isinstance(paths[path], dict) or paths[path].get('x-mina-webhook') != name):
            raise ValueError(f'Webhook route conflicts with an API path: {path}')
        paths.setdefault(path, {**copy.deepcopy(definition), 'x-mina-webhook': name})
    if not paths:raise ValueError('The API contract requires at least one path or webhook')
    if len(paths)>256:raise ValueError('The API contract exceeds 256 paths')
    def check_references(node):
        if isinstance(node,list):
            for item in node:check_references(item)
        elif isinstance(node,dict):
            reference=node.get('$ref')
            if reference is not None:
                if not isinstance(reference,str) or not reference.startswith('#/'):raise ValueError('API Blueprint references must use local JSON Pointers')
                current=spec
                try:
                    for part in reference[2:].split('/'):
                        key=part.replace('~1','/').replace('~0','~')
                        current=current[int(key)] if isinstance(current,list) else current[key]
                except (KeyError,IndexError,TypeError,ValueError):raise ValueError('Unresolved API reference: '+reference) from None
            for item in node.values():check_references(item)
    check_references(spec)
    def dereference(value):
        seen=set()
        while isinstance(value,dict) and '$ref' in value:
            reference=value['$ref']
            if not isinstance(reference,str) or not reference.startswith('#/') or reference in seen:raise ValueError('Invalid or cyclic API reference')
            seen.add(reference);resolved=spec
            for part in reference[2:].split('/'):resolved=resolved[part.replace('~1','/').replace('~0','~')]
            value=copy.deepcopy(resolved)
        return value
    operations=[];identifiers=set();routes=set();callback_count=0
    for path,item in list(paths.items()):
        if not isinstance(path,str) or not path.startswith('/') or '?' in path or '#' in path or any(ord(c)<32 for c in path):raise ValueError('API paths must start with / and cannot include a query or fragment')
        webhook = item.get('x-mina-webhook') if isinstance(item, dict) else None
        item=dereference(item);paths[path]=item
        if webhook and isinstance(item, dict):
            item['x-mina-webhook'] = webhook
        if not isinstance(item,dict):raise ValueError(f'Invalid API path definition: {path}')
        for method,operation in item.items():
            if method not in METHODS:continue
            if not isinstance(operation,dict):raise ValueError(f'Invalid {method.upper()} operation on {path}')
            if len(operations)>=512:raise ValueError('The API contract exceeds 512 operations')
            identity=(method,re.sub(r'\{[^}]+\}','{}',path).rstrip('/'))
            if identity in routes:raise ValueError(f'Duplicate route: {method.upper()} {path}')
            routes.add(identity)
            operation_id=operation.get('operationId') or f'{method}_{hashlib.sha256(path.encode()).hexdigest()[:12]}'
            if not isinstance(operation_id,str) or not operation_id.strip() or len(operation_id)>256:raise ValueError('Operation IDs must be nonempty strings of at most 256 characters')
            if operation_id in identifiers:raise ValueError(f'Duplicate operation ID: {operation_id}')
            identifiers.add(operation_id);operation['operationId']=operation_id
            if not isinstance(operation.get('responses'),dict) or not operation['responses']:raise ValueError(f'{operation_id}: declare at least one response')
            for code,response in operation['responses'].items():
                if not re.fullmatch(r'(?:[1-5][0-9]{2}|[1-5]XX|default)',str(code)):raise ValueError(f'{operation_id}: invalid response status {code}')
                if not isinstance(dereference(response),dict):raise ValueError(f'{operation_id}: response definitions must be objects')
            request=dereference(operation.get('requestBody',{}))
            if not isinstance(request,dict):raise ValueError(f'{operation_id}: requestBody must be an object')
            for declaration in [request,*(dereference(response) for response in operation['responses'].values())]:
                if not isinstance(declaration.get('headers',{}),dict):raise ValueError(f'{operation_id}: headers must be an object')
                content=declaration.get('content',{})
                if not isinstance(content,dict):raise ValueError(f'{operation_id}: content must be an object')
                for media,definition in content.items():
                    if not isinstance(media,str) or '/' not in media or not isinstance(dereference(definition),dict):raise ValueError(f'{operation_id}: invalid media type definition')
            placeholders=re.findall(r'\{([^}]+)\}',path)
            if len(placeholders)!=len(set(placeholders)) or '{' in re.sub(r'\{[^{}]+\}','',path) or '}' in re.sub(r'\{[^{}]+\}','',path):raise ValueError(f'{operation_id}: invalid or repeated path placeholder')
            if any(re.search(r'[\s/{}]',name) for name in placeholders):raise ValueError(f'{operation_id}: invalid path parameter name')
            for owner in (item,operation):
                parameters=owner.get('parameters',[])
                if not isinstance(parameters,list):raise ValueError(f'{operation_id}: parameters must be an array')
                seen_parameters=set()
                for raw_parameter in parameters:
                    parameter=dereference(raw_parameter)
                    if not isinstance(parameter,dict):raise ValueError(f'{operation_id}: invalid parameter definition')
                    location=parameter.get('in');name=parameter.get('name')
                    allowed={'path','query','header','cookie'} if spec.get('swagger')!='2.0' else {'path','query','header','body','formData'}
                    if location not in allowed or not isinstance(name,str) or not name:raise ValueError(f'{operation_id}: invalid parameter name or location')
                    key=(location,name.lower() if location=='header' else name)
                    if key in seen_parameters:raise ValueError(f'{operation_id}: duplicate {location} parameter {name}')
                    seen_parameters.add(key)
                    if location=='path' and name not in placeholders:raise ValueError(f'{operation_id}: path parameter {name} is not in the route')
            try:cfg=operation_config({'openApiDocument':spec,'operationId':operation_id,'operation':'receiver'},document=spec)
            except (AttributeError,KeyError,TypeError) as error:raise ValueError(f'{operation_id}: invalid API contract structure: {error}') from None
            declared={(p.get('in'),p.get('name')) for p in cfg['_restParameters']}
            for name in re.findall(r'\{([^}]+)\}',path):
                if ('path',name) not in declared:raise ValueError(f'{operation_id}: declare path parameter {name}')
            for parameter in cfg['_restParameters']:
                if not isinstance(parameter.get('name'),str) or not parameter['name']:raise ValueError(f'{operation_id}: parameter names must be nonempty strings')
                if parameter['in']=='path' and parameter.get('required') is not True:raise ValueError(f'{operation_id}: path parameters must be required')
            import jsonschema
            for schema in [cfg.get('requestSchema'),*cfg.get('_restRequestSchemas',{}).values(),*cfg.get('_restResponseSchemas',{}).values(),
                           *(schema for content in cfg.get('_restResponseContentSchemas',{}).values() for schema in content.values()),
                           *(p['schema'] for p in cfg['_restParameters'])]:
                if schema is not None:
                    try:jsonschema.validators.validator_for(schema).check_schema(schema)
                    except jsonschema.SchemaError as error:raise ValueError(f'{operation_id}: invalid schema: {error.message}') from None
            example=_examples(operation,cfg,dereference)
            callback_count+=len(callback_tasks(spec,operation,operation_id))
            if len(operations)+1+callback_count>1024:raise ValueError('The API contract exceeds 1024 generated operation and callback tasks')
            result = {'operationId':operation_id,'method':method.upper(),'path':path,'summary':str(operation.get('summary') or '')[:256],'hasExample':example is not None,'example':example}
            if webhook:
                result['webhook'] = webhook
            operations.append(result)
    if not operations:raise ValueError('The API contract has no supported HTTP operations')
    info=spec.get('info') or {}
    if not isinstance(info,dict):raise ValueError('API info must be an object')
    return {'name':str(info.get('title') or 'MINA API')[:128],'document':spec,'operations':operations}

def callback_tasks(document, declaration, owner_id):
    callbacks = declaration.get('callbacks') or {}
    if not isinstance(callbacks, dict):
        raise ValueError('OpenAPI callbacks must be an object')

    def resolve(value):
        seen = set()
        while isinstance(value, dict) and '$ref' in value:
            reference = value['$ref']
            if reference in seen:
                raise ValueError('Cyclic callback reference')
            seen.add(reference)
            value = document
            for token in reference[2:].split('/'):
                value = value[token.replace('~1', '/').replace('~0', '~')]
        if not isinstance(value, dict):
            raise ValueError('Invalid callback path item')
        return value

    tasks = []
    for name, definitions in callbacks.items():
        if name.startswith('x-'):continue
        for expression, item in resolve(definitions).items():
            if expression.startswith('x-'):
                continue
            item = resolve(item)
            for method in sorted(METHODS & item.keys()):
                operation = copy.deepcopy(item[method])
                if not isinstance(operation, dict) or not isinstance(operation.get('responses'), dict):
                    raise ValueError(f'Callback {name} must declare an operation and its responses')
                operation_id = operation.setdefault('operationId', 'sendCallback')
                contract = {key: copy.deepcopy(document[key]) for key in ('openapi','info','components','x-mina-refs','definitions') if key in document}
                contract['paths'] = {'/callback': {**{key:copy.deepcopy(item[key]) for key in ('parameters','servers') if key in item},method: operation}}
                activity = {'operation':'invoke','operationId':operation_id,'openApiDocument':contract,
                            'apiBlueprintCallbackKey':hashlib.sha256(json.dumps([declaration.get('operationId'),name,expression,method],ensure_ascii=False).encode()).hexdigest(),
                            'callbackDelivery':True,
                            'callbackAllowedOrigins':'${properties.connections.http.callbackAllowedOrigins}',
                            'inputMappings':{'RestInputRequest.Config.callbackUrl':'${input.callbackUrl}',
                                             'RestInputRequest.Config.RequestBody':'${input.body}'}}
                tasks.append({'id':f'{owner_id}-callback-{len(tasks)+1}', 'name':f'Callback-{name}-{method.upper()}',
                              'kind':'subtask','description':f'Call with callbackUrl and body. OpenAPI URL expression: {expression}',
                              'activities':[
                                  {'id':'Start','name':'Start','type':'start','position':{'x':100,'y':160},'config':{}},
                                  {'id':'Send','name':'Send-Callback','type':'rest','position':{'x':340,'y':160},'config':activity},
                                  {'id':'End','name':'End','type':'end','position':{'x':580,'y':160},'config':{}}],
                              'transitions':[{'id':'start-send','source':'Start','target':'Send','type':'success'},
                                             {'id':'send-end','source':'Send','target':'End','type':'success'}]})
    return tasks


def blueprint_plan(document,selected,connection,name='',response_mode='stub',package_path='Default', *, reference_documents=None, document_path=''):
    package_path=TypeAdapter(PackagePath).validate_python(package_path)
    validated=validate_blueprint(document,reference_documents=reference_documents,document_path=document_path)
    if response_mode not in ('stub','example'):raise ValueError('Response mode must be stub or example')
    known={operation['operationId']:operation for operation in validated['operations']}
    if not isinstance(selected,list) or not selected or len(set(selected))!=len(selected) or any(key not in known for key in selected):raise ValueError('Select unique operation IDs from the validated document')
    if not isinstance(connection,dict) or connection.get('type')!='http':raise ValueError('Select an HTTP server shared connection')
    config=copy.deepcopy(connection.get('config') or {})
    if config.get('connectorMode')=='client':raise ValueError('An HTTP client connection cannot host an API')
    blueprint_id='api-'+uuid.uuid4().hex[:12];title=str(name or validated['name']).strip()[:128]
    # Store the contract once in an API-specific server connection, not once per task.
    config.update(connectorMode='server',openApiDocument=validated['document'],apiBlueprintId=blueprint_id)
    resource={'id':blueprint_id+'-http','type':'http','name':title+' · API server','config':config}
    tasks=[];warnings=[];callbacks=[]
    for index,key in enumerate(selected):
        operation=known[key];example=operation['example'] if response_mode=='example' else None
        document = validated['document']
        declaration = document['paths'][operation['path']][operation['method'].lower()]
        protocols=declaration.get('x-mina-allowed-protocols')
        if protocols:
            scheme='https' if config.get('tlsEnabled') in (True,'true','True') or config.get('scheme')=='https' else 'http'
            if scheme not in protocols:
                if any(isinstance(config.get(field),str) and '${' in config[field] for field in ('scheme','tlsEnabled')):warnings.append(f'{key}: verify the resolved connection uses a contract-approved protocol')
                else:raise ValueError(f'{key}: the server connection protocol is not permitted by the RAML contract')
        if declaration.get('security', document.get('security')):
            if any('${' in str(config.get(field, '')) for field in ('authentication', 'clientAuthentication', 'openApiApiKeySecrets')):
                warnings.append(f'{key}: OpenAPI security will be checked after connection properties are resolved')
            else:
                try:
                    compatible_security(operation_config({**config, 'operationId':key, 'operation':'receiver'},document=validated['document']))
                except ValueError as error:
                    raise ValueError(f'{key}: {error}') from None
        if response_mode=='example' and example is None:warnings.append(f'{key}: no declared example; responds with 501 until implemented')
        status=example['statusCode'] if example else 501
        body=example['body'] if example else {'error':'API operation not implemented','operationId':key}
        response={'operation':'response','statusCode':status,'contentType':example['contentType'] if example else 'application/json','inputMappings':{'body':json.dumps(body,ensure_ascii=False)}}
        if response['contentType'].split(';',1)[0].lower().endswith(('/json','+json')):response['jsonValue']=True
        if example and example.get('headers'):response['inputMappings']['headers']=json.dumps(example['headers'],ensure_ascii=False)
        task_id=f'{blueprint_id}-{index+1}'
        tasks.append({'id':task_id,'name':f'{operation["method"]} {operation["path"]}','kind':'starter','description':f'MINA API Blueprint: {title}. '+('Declared example response for testing; replace with business logic.' if example else 'Replace the 501 response with business logic.'),'groups':[],
            'activities':[{'id':'Receive','name':'REST-API-Receiver','type':'rest','position':{'x':150,'y':160},'config':{'operation':'receiver','resourceId':resource['id'],'operationId':key,'apiBlueprintId':blueprint_id,'validateRequest':True,'validateResponse':example is not None}},
                          {'id':'Reply','name':'HTTP-Response','type':'http_response','position':{'x':450,'y':160},'config':response},
                          {'id':'End','name':'End','type':'end','position':{'x':750,'y':160},'config':{}}],
            'transitions':[{'id':'receive-reply','source':'Receive','target':'Reply','type':'success'},{'id':'reply-end','source':'Reply','target':'End','type':'success'}]})
        callbacks.extend(callback_tasks(document, declaration, task_id))
    if callbacks:
        warnings.append('Callback subtasks require an explicit call, a mapped callback URL, and an HTTPS origin allowlist.')
    resource['package_path']=package_path
    for helper in callbacks:
        for activity in helper['activities']:
            if activity.get('config',{}).get('callbackDelivery'):activity['config']['apiBlueprintId']=blueprint_id
    names=set()
    for index,item in enumerate([resource,*tasks,*callbacks]):
        label='-'.join(str(item['name']).split())[:200]
        key=normalize('NFKC',label).casefold()
        if key in names:label=label[:180]+'-'+hashlib.sha256(f'{label}:{index}'.encode()).hexdigest()[:10]
        item['name']=label;names.add(normalize('NFKC',label).casefold())
        item['package_path']=package_path
    return {'name':title,'blueprintId':blueprint_id,'resource':resource,'tasks':tasks+callbacks,'warnings':warnings,'responseMode':response_mode,'packagePath':package_path}
