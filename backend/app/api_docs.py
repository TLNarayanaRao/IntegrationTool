"""Sanitized OpenAPI and Postman documents for the routes actually hosted."""
from __future__ import annotations
import copy, hashlib, json, re, urllib.parse, uuid
from functools import lru_cache
from .http_contracts import hosted_response_content, load_document, media_family, media_schema, schema_for_media
from .xsd_openapi import describe_xsd

DOC_PREFIX='/_mina'
DOCS_PATH=DOC_PREFIX+'/docs'
SPEC_PATH=DOC_PREFIX+'/openapi.json'
POSTMAN_PATH=DOC_PREFIX+'/postman.json'

@lru_cache(maxsize=8)
def asset_bytes(name,compressed):
    import base64,gzip
    from .swagger_assets import ASSETS
    body=base64.b64decode(ASSETS[name]['data'])
    return body if compressed else gzip.decompress(body)

def methods_for(cfg):
    value = cfg.get('methods')
    if value is None:
        value = cfg.get('method') or 'POST'
    return list(dict.fromkeys(str(item).strip().upper() for item in
                             (value if isinstance(value, list) else str(value).split(',')) if str(item).strip()))

def public_base(cfg):
    explicit=str(cfg.get('apiPublicBaseUrl') or '').rstrip('/')
    if explicit:
        parsed=urllib.parse.urlsplit(explicit)
        if parsed.scheme not in ('http','https') or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:raise ValueError('Public API base URL must be an HTTP/HTTPS URL without credentials, query or fragment')
        return explicit
    from .http_server import server_tls
    scheme='https' if server_tls(cfg) else str(cfg.get('scheme') or 'http')
    host=str(cfg.get('host') or 'localhost')
    if host in ('0.0.0.0','::','[::]'):host='localhost'
    if ':' in host and not host.startswith('['):host='['+host+']'
    port=int(cfg.get('port') or 8080)
    return f'{scheme}://{host}'+('' if port==(443 if scheme=='https' else 80) else f':{port}')

def document_urls(cfg):
    base=public_base(cfg)
    return {'docsUrl':base+DOCS_PATH,'openApiUrl':base+SPEC_PATH,'postmanUrl':base+POSTMAN_PATH}

def sample(schema,root=None,depth=0):
    if not isinstance(schema,dict) or depth>7:return None
    root=root or schema
    if '$ref' in schema and str(schema['$ref']).startswith('#/'):
        try:
            resolved=root
            for part in schema['$ref'][2:].split('/'):resolved=resolved[part.replace('~1','/').replace('~0','~')]
            return sample(resolved,root,depth+1)
        except (KeyError,TypeError):return None
    for key in ('example','default','const'):
        if key in schema:return copy.deepcopy(schema[key])
    if schema.get('enum'):return schema['enum'][0]
    if schema.get('oneOf') or schema.get('anyOf'):return sample((schema.get('oneOf') or schema['anyOf'])[0],root,depth+1)
    kind=schema.get('type')
    if isinstance(kind,list):kind=next((item for item in kind if item!='null'),'null')
    if kind=='object' or 'properties' in schema:return {key:sample(value,root,depth+1) for key,value in list(schema.get('properties',{}).items())[:40]}
    if kind=='array':return [sample(schema.get('items',{}),root,depth+1)]
    if kind=='boolean':return True
    if kind in ('integer','number'):return max(schema.get('minimum',1),1)
    if kind=='null':return None
    return {'date':'2026-01-01','date-time':'2026-01-01T00:00:00Z','uuid':'00000000-0000-4000-8000-000000000001','email':'user@example.com'}.get(schema.get('format'),'example')

def _security(cfg):
    scheme=str(cfg.get('authentication') or 'none').lower()
    if scheme=='none':return {},[]
    if scheme in ('basic','ldap'):return {'MINA_Basic':{'type':'http','scheme':'basic','description':'Supply your API credentials; no saved credentials are included.'}},[{'MINA_Basic':[]}]
    if scheme in ('bearer','jwt','oauth2'):return {'MINA_Bearer':{'type':'http','scheme':'bearer','description':'Supply an access token for this API.','bearerFormat':'JWT' if scheme=='jwt' else 'token'}},[{'MINA_Bearer':[]}]
    if scheme=='certificate':return {'MINA_Certificate':{'type':'mutualTLS','description':'Configure a client certificate in your browser or API client.'}},[{'MINA_Certificate':[]}]
    if scheme=='hmac':
        names=['Authorization','X-MINA-Key-Id','X-MINA-Timestamp','X-MINA-Nonce']
        definitions={'MINA_'+name.replace('-','_'):{'type':'apiKey','in':'header','name':name,'description':'MINA HMAC signature headers; the documentation access panel can sign raw requests.'} for name in names}
        return definitions,[{key:[] for key in definitions}]
    return {},[]

def generate_openapi(routes,base_url='/',title='MINA hosted APIs'):
    """Routes contain resolved listener configs only; never serialize connection configs."""
    spec={'openapi':'3.1.0','info':{'title':title,'version':'1.0.0'},'servers':[{'url':base_url}],'paths':{},'components':{'schemas':{},'securitySchemes':{}}}
    schemas=spec['components']['schemas'];operation_ids=set()
    xml_contracts = {}

    def xsd_description(schema):
        if not isinstance(schema, str) or not schema.lstrip().startswith('<'):
            return None
        if schema not in xml_contracts:
            xml_contracts[schema] = describe_xsd(schema)
        return xml_contracts[schema]

    def inferred_media(schema):
        return 'application/xml' if isinstance(schema, str) and schema.lstrip().startswith('<') else 'application/json'

    def embed(schema):
        if isinstance(schema,str):
            try:schema=json.loads(schema)
            except ValueError:
                projected = xsd_description(schema)
                if projected is None:
                    return {'type':'string','description':'XML document validated by the configured XSD.'}
                schema = projected[0]
        if not isinstance(schema,(dict,bool)):return {}
        signature=hashlib.sha256(json.dumps(schema,sort_keys=True).encode()).hexdigest()[:16];name='Schema_'+signature
        if name in schemas:return {'$ref':'#/components/schemas/'+name}
        if isinstance(schema,bool):schemas[name]=schema;return {'$ref':'#/components/schemas/'+name}
        definitions={key:schema[key] for key in ('components','definitions','x-mina-refs','$defs') if key in schema}
        core={key:copy.deepcopy(value) for key,value in schema.items() if key not in definitions}
        foundation='Definitions_'+hashlib.sha256(json.dumps(definitions,sort_keys=True).encode()).hexdigest()[:16]
        root_prefix='#/components/schemas/'+name;definition_prefix='#/components/schemas/'+foundation
        def rewrite(value):
            if isinstance(value,list):return [rewrite(item) for item in value]
            if not isinstance(value,dict):return value
            result={key:rewrite(item) for key,item in value.items()}
            reference=result.get('$ref')
            if reference=='#':result['$ref']=root_prefix
            elif isinstance(reference,str) and reference.startswith('#/'):
                head=reference[2:].split('/')[0]
                result['$ref']=(definition_prefix if head in definitions else root_prefix)+reference[1:]
            return result
        if definitions and foundation not in schemas:schemas[foundation]=rewrite(definitions)
        schemas[name]=rewrite(core)
        return {'$ref':root_prefix}
    for metadata,cfg in routes:
        operation=cfg.get('_restOperation') or {}
        security,requirement=_security(cfg)
        if cfg.get('clientAuthentication') == 'required':
            security['MINA_Certificate'] = {'type':'mutualTLS','description':'Configure a trusted client certificate in your browser or API client.'}
            requirement = [{**alternative, 'MINA_Certificate': []} for alternative in requirement or [{}]]
        spec['components']['securitySchemes'].update(security)
        for method in methods_for(cfg):
            if method not in ('GET','POST','PUT','PATCH','DELETE','HEAD','OPTIONS','TRACE'):continue
            path=cfg['path'];identity=str(cfg.get('operationId') or method.lower()+'_'+hashlib.sha256(path.encode()).hexdigest()[:10])
            if identity in operation_ids:identity+='_'+hashlib.sha256((path+method+str(metadata)).encode()).hexdigest()[:8]
            operation_ids.add(identity)
            entry={'operationId':identity,'summary':str(operation.get('summary') or method+' '+path),'responses':{},'security':requirement}
            if any(scopes for _, scopes in cfg.get('_restSecurityAlternatives', ())):
                entry['x-mina-required-scope-alternatives'] = [scopes for _, scopes in cfg['_restSecurityAlternatives']]
            for key in ('description','tags','deprecated'):
                if key in operation:entry[key]=copy.deepcopy(operation[key])
            parameters=[]
            for parameter in cfg.get('_restParameters') or []:
                if parameter.get('in')=='formData':continue
                fields={key:copy.deepcopy(parameter[key]) for key in ('name','in','required','description','style','explode','example','examples','allowReserved') if key in parameter}
                fields['schema']=embed(parameter.get('schema') or {});parameters.append(fields)
            declared={(p['in'],p['name']) for p in parameters}
            for name in re.findall(r'\{([^}]+)\}',path):
                if ('path',name) not in declared:parameters.append({'in':'path','name':name,'required':True,'schema':{'type':'string'}})
            if parameters:entry['parameters']=parameters
            request_schema=cfg.get('requestSchema')
            request_body=operation.get('requestBody') or {};media=str(cfg.get('contentType') or inferred_media(request_schema))
            selected_request_types = cfg.get('requestContentTypes') or []
            selected_response_types = cfg.get('responseContentTypes') or []
            if request_schema is not None or request_body or selected_request_types or method in ('POST','PUT','PATCH'):
                content={}
                formats = cfg.get('_restRequestSchemas') or {}
                if selected_request_types:
                    formats = {name: (media_schema(formats, name)[1] if formats else
                                      schema_for_media(request_schema, name, len(selected_request_types) > 1))
                               for name in selected_request_types}
                for name,schema in (formats or {media:request_schema}).items():
                    if cfg.get('_explicitRequestSchema') and not selected_request_types:schema=request_schema
                    definition={'schema':embed(schema) if schema is not None else {}}
                    original=(request_body.get('content') or {}).get(name,{}) if isinstance(request_body,dict) else {}
                    for key in ('example','examples'):
                        if key in original:definition[key]=copy.deepcopy(original[key])
                    if name == 'multipart/form-data' and cfg.get('_restMultipartEncoding'):
                        definition['encoding'] = copy.deepcopy(cfg['_restMultipartEncoding'])
                    if 'example' not in definition and 'examples' not in definition and schema is not None:
                        projected = xsd_description(schema)
                        example = projected[1] if projected else sample(schema)
                        if example is not None:
                            definition['example'] = example
                    content[name]=definition
                entry['requestBody']={'required':bool(cfg.get('_requiredBody')),'content':content}
            response_schemas=cfg.get('_restResponseSchemas') or {}
            declared_responses=operation.get('responses') or {}
            for code in dict.fromkeys([*declared_responses,*response_schemas] or ['200','400','500']):
                original=declared_responses.get(code) or {}
                fallback_schema = cfg.get('responseSchema') if str(code).startswith('2') else None
                schema = response_schemas.get(str(code), fallback_schema)
                response={'description':str(original.get('description') or ('Successful response' if str(code).startswith('2') else 'API response'))}
                content={}
                formats=hosted_response_content(cfg, code)
                if not formats and not (selected_response_types and str(code).startswith('2')):
                    formats = {str(cfg.get('responseType') or inferred_media(schema)):schema}
                if str(code) in ('204','205','304') or method == 'HEAD':
                    formats = {}
                for name,body_schema in formats.items():
                    original_content=(original.get('content') or {}).get(name) or {}
                    definition={key:copy.deepcopy(original_content[key]) for key in ('example','examples') if key in original_content}
                    if body_schema is not None:definition['schema']=embed(body_schema)
                    if 'example' not in definition and 'examples' not in definition:
                        projected = xsd_description(body_schema)
                        if projected and projected[1] is not None:
                            definition['example'] = projected[1]
                    has_configured_body = (
                        str(code).startswith('2') and str(code) not in ('204', '205')
                        and method != 'HEAD' and (name in selected_response_types or name == cfg.get('responseType'))
                    )
                    if definition or has_configured_body:
                        content[name]=definition
                if content:response['content']=content
                entry['responses'][str(code)]=response
            entry['x-mina-authentication']=str(cfg.get('authentication') or 'None')
            entry['x-mina-hmac-algorithm']=str(cfg.get('hmacAlgorithm') or 'SHA256')
            if selected_request_types or selected_response_types:
                entry['x-mina-selected-media-types'] = True
            spec['paths'].setdefault(path,{})[method.lower()]=entry
    return spec

def _resolve_schema(schema,spec):
    seen=set()
    while isinstance(schema,dict) and '$ref' in schema:
        reference=schema['$ref']
        if reference in seen or not reference.startswith('#/'):break
        seen.add(reference);schema=spec
        for part in reference[2:].split('/'):schema=schema[part.replace('~1','/').replace('~0','~')]
    return schema

def _postman_body(request, media, body, spec):
    schema=body.get('schema') or {}
    value=body.get('example')
    if value is None:
        examples=body.get('examples') or {};value=next((v['value'] for v in examples.values() if isinstance(v,dict) and 'value' in v),None)
    family = media_family(media)
    if value is None:
        value = '<root/>' if family == 'xml' and not schema else sample(_resolve_schema(schema,spec),spec)
    if media != 'multipart/form-data': # Postman supplies the multipart boundary.
        request['header'].append({'key':'Content-Type','value':media})
    if media in ('application/x-www-form-urlencoded','multipart/form-data'):
        mode='urlencoded' if media=='application/x-www-form-urlencoded' else 'formdata'
        fields=[];resolved=_resolve_schema(schema,spec)
        for key,item in (value if isinstance(value,dict) else {}).items():
            prop=_resolve_schema((resolved.get('properties') or {}).get(key,{}),spec)
            binary=mode=='formdata' and prop.get('format')=='binary'
            fields.append({'key':key,**({'type':'file','src':[]} if binary else {'value':str(item),'type':'text'})})
        request['body']={'mode':mode,mode:fields}
    elif media=='application/octet-stream':request['body']={'mode':'file','file':{}}
    else:request['body']={'mode':'raw','raw':json.dumps(value,indent=2,ensure_ascii=False) if family == 'json' else str(value or ''),'options':{'raw':{'language':family or 'text'}}}

def postman_collection(spec,base_url):
    variables={'baseUrl':base_url};items=[]
    for path,definition in spec['paths'].items():
        for method,operation in definition.items():
            headers=[];query=[];path_variables=[];url_path=re.sub(r'\{([^}]+)\}',r':\1',path)
            for parameter in operation.get('parameters',[]):
                schema=_resolve_schema(parameter.get('schema',{}),spec);value=parameter.get('example',sample(schema,spec))
                text=json.dumps(value,separators=(',',':')) if isinstance(value,(dict,list)) else str(value if value is not None else '')
                item={'key':parameter['name'],'value':text,'description':str(parameter.get('description') or '')}
                if parameter['in']=='path':path_variables.append(item)
                elif parameter['in']=='query':query.append({**item,'disabled':not parameter.get('required',False)})
                elif parameter['in']=='header':headers.append({**item,'disabled':not parameter.get('required',False)})
                elif parameter['in']=='cookie':headers.append({'key':'Cookie','value':parameter['name']+'='+text})
            url={'raw':'{{baseUrl}}'+url_path,'host':['{{baseUrl}}'],'path':url_path.lstrip('/').split('/')}
            if path_variables:url['variable']=path_variables
            if query:
                url['query']=query
                active=[(item['key'],item['value']) for item in query if not item['disabled']]
                if active:url['raw']+='?'+urllib.parse.urlencode(active)
            request={'method':method.upper(),'header':headers,'url':url,'description':operation.get('description',operation.get('summary',''))}
            content=(operation.get('requestBody') or {}).get('content') or {}
            multi = operation.get('x-mina-selected-media-types')
            if not any(header['key'].lower() == 'accept' for header in headers):
                response_types = dict.fromkeys(media for code, response in operation.get('responses', {}).items()
                                               if code.startswith('2') for media in response.get('content', {}))
                if response_types:
                    headers.append({'key':'Accept', 'value':', '.join(response_types) if multi else next(iter(response_types))})
            scheme=operation.get('x-mina-authentication','None').lower();events=[]
            if scheme in ('basic','ldap'):
                variables.update(username='',password='');request['auth']={'type':'basic','basic':[{'key':'username','value':'{{username}}','type':'string'},{'key':'password','value':'{{password}}','type':'string'}]}
            elif scheme in ('bearer','jwt','oauth2'):
                variables['accessToken']='';request['auth']={'type':'bearer','bearer':[{'key':'token','value':'{{accessToken}}','type':'string'}]}
            elif scheme=='hmac':
                from .api_docs_ui import postman_hmac_script
                variables.update(hmacSecret='',hmacKeyId='default')
                events=[{'listen':'prerequest','script':{'type':'text/javascript','exec':postman_hmac_script(operation.get('x-mina-hmac-algorithm','SHA256')).splitlines()}}]
            variants = (list(content.items()) if multi else list(content.items())[:1]) or [(None, None)]
            for media, body in variants:
                variant = {**request, 'header': list(headers)}
                if media:
                    _postman_body(variant, media, body, spec)
                entry={'name':method.upper()+' '+path+(f' ({media})' if len(variants)>1 else ''),'request':variant,'response':[]}
                if events:entry['event']=events
                items.append(entry)
    return {'info':{'_postman_id':str(uuid.uuid4()),'name':spec['info']['title'],'schema':'https://schema.getpostman.com/json/collection/v2.1.0/collection.json','description':'Generated by MINA from hosted routes. Set credential variables locally; no saved credentials are included. Configure client certificates in Postman for mutual TLS.'},'item':items,'variable':[{'key':key,'value':value,'type':'string'} for key,value in variables.items()]}

class HostedAPIDocs:
    def __init__(self,routes,connection):
        from .http_transport import boolean
        self.routes=[(metadata,cfg) for metadata,cfg in routes if cfg.get('operation')!='service' and boolean(cfg.get('apiDocsEnabled'),True)]
        self.connection=connection
        self.enabled=bool(self.routes)
        self.pending=0
        if self.enabled:
            public_base(connection)
            if any(cfg['path'].rstrip('/')==DOC_PREFIX or cfg['path'].startswith(DOC_PREFIX+'/') for _,cfg in routes):raise ValueError('The /_mina path is reserved for API documentation. Change the route or disable API documentation.')
        self.spec=generate_openapi(self.routes,connection.get('apiPublicBaseUrl') or '/') if self.enabled else None

    async def handle(self,scope,send):
        path=scope['path']
        if not self.enabled or path not in (DOCS_PATH,DOCS_PATH+'/',SPEC_PATH,POSTMAN_PATH) and not path.startswith(DOC_PREFIX+'/assets/'):return False
        from .http_transport import authorize,HTTPFault,boolean
        import asyncio
        headers=[(b'cache-control',b'no-store'),(b'x-content-type-options',b'nosniff')]
        status=200;content_type='application/json';body=b''
        try:
            pairs=scope.get('headers',[])
            from .http_transport import number
            if sum(len(k)+len(v)+4 for k,v in pairs)>number(self.connection,'maxHeaderBytes',65536,1024):raise HTTPFault('HTTP headers too large','HTTP_BAD_REQUEST',431)
            allowed=str(self.connection.get('allowedIps') or '').replace(',',' ').split()
            if allowed:
                import ipaddress
                try:permitted=any(ipaddress.ip_address((scope.get('client') or ('',0))[0]) in ipaddress.ip_network(network,strict=False) for network in allowed)
                except ValueError:permitted=False
                if not permitted:raise HTTPFault('Access denied','HTTP_SECURITY',403)
            if any(sum(key.lower()==name for key,_ in pairs)>1 for name in (b'host',b'authorization')):raise HTTPFault('Duplicate request header','HTTP_BAD_REQUEST',400)
            if scope['method'] not in ('GET','HEAD'):raise HTTPFault('Documentation supports GET and HEAD','HTTP_METHOD_NOT_ALLOWED',405)
            if path.startswith(DOC_PREFIX+'/assets/'):
                from .swagger_assets import ASSETS
                name=path.rsplit('/',1)[-1]
                if name not in ASSETS:raise HTTPFault('Asset not found','HTTP_NOT_FOUND',404)
                compressed=any(k.lower()==b'accept-encoding' and 'gzip' in v.decode('latin1').lower() for k,v in pairs)
                body=asset_bytes(name,compressed)
                if compressed:headers.append((b'content-encoding',b'gzip'))
                headers.extend([(b'vary',b'Accept-Encoding'),(b'etag',('"'+ASSETS[name]['sha256']+'"').encode())])
                content_type='application/javascript' if name.endswith('.js') else 'text/css' if name.endswith('.css') else 'text/plain'
            elif path.rstrip('/')==DOCS_PATH:
                from .api_docs_ui import swagger_html
                prefix=urllib.parse.urlsplit(str(self.connection.get('apiPublicBaseUrl') or '')).path.rstrip('/')
                body,nonce=swagger_html(str(self.connection.get('authentication') or 'None'),str(self.connection.get('hmacAlgorithm') or 'SHA256'),prefix+DOC_PREFIX+'/assets')
                content_type='text/html; charset=utf-8'
                headers.append((b'content-security-policy',f"default-src 'self'; script-src 'self' 'nonce-{nonce}'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self' http: https:; object-src 'none'; base-uri 'none'; frame-ancestors 'none'".encode()))
            else:
                request_headers={k.decode().lower():v.decode('latin1') for k,v in scope.get('headers',[])}
                if str(self.connection.get('apiDocsAccess') or 'authenticated')!='public':
                    target=(scope.get('raw_path') or path.encode()).decode('ascii')+('?' + scope.get('query_string',b'').decode('ascii') if scope.get('query_string') else '')
                    if self.pending>=8:raise HTTPFault('Documentation authentication is busy','HTTP_BUSY',503)
                    self.pending+=1
                    try:await asyncio.to_thread(authorize,self.connection,scope['method'],target,request_headers,b'',scope.get('_mina_verified_mtls',False))
                    finally:self.pending-=1
                if path==SPEC_PATH:body=json.dumps(self.spec,ensure_ascii=False).encode()
                else:
                    host=request_headers.get('host','localhost')
                    origin=self.connection.get('apiPublicBaseUrl') or scope.get('scheme','http')+'://'+host
                    body=json.dumps(postman_collection(self.spec,origin),ensure_ascii=False,indent=2).encode()
                    headers.append((b'content-disposition',b'attachment; filename="MINA-API.postman_collection.json"'))
        except HTTPFault as error:
            status=error.status;body=json.dumps({'error':str(error)}).encode()
            if status==401:headers.append((b'www-authenticate',b'Basic realm="MINA API"' if str(self.connection.get('authentication') or '').lower() in ('basic','ldap') else b'Bearer'))
            if status==405:headers.append((b'allow',b'GET, HEAD'))
        headers.extend([(b'content-type',content_type.encode()),(b'content-length',str(len(body)).encode())])
        await send({'type':'http.response.start','status':status,'headers':headers})
        await send({'type':'http.response.body','body':b'' if scope['method']=='HEAD' else body})
        return True
