"""Local OpenAPI 3 / Swagger 2 operation contracts. Never fetch remote refs."""
from __future__ import annotations
import copy, json, urllib.parse

def operation_config(config):
    supplied=config.get('openApiDocument')
    if not supplied:return dict(config)
    if isinstance(supplied,str):
        if len(supplied)>8*1024**2:raise ValueError('OpenAPI document exceeds 8 MiB')
        supplied=json.loads(supplied)
    if not isinstance(supplied,dict) or not (str(supplied.get('openapi','')).startswith('3.') or supplied.get('swagger')=='2.0'):raise ValueError('Provide an OpenAPI 3 or Swagger 2 JSON document')
    selected=str(config.get('operationId') or '')
    if not selected:raise ValueError('OpenAPI operation ID is required')
    def dereference(value):
        seen=set()
        while isinstance(value,dict) and '$ref' in value:
            ref=value['$ref']
            if not isinstance(ref,str) or not ref.startswith('#/') or ref in seen:raise ValueError('Only acyclic local OpenAPI references are supported')
            seen.add(ref);value=supplied
            for part in ref[2:].split('/'):
                value=value[part.replace('~1','/').replace('~0','~')]
        return value
    matches=[]
    for path,definition in (supplied.get('paths') or {}).items():
        definition=dereference(definition)
        for method,operation in definition.items():
            if method.lower() in ('get','post','put','patch','delete','head','options') and isinstance(operation,dict) and operation.get('operationId')==selected:matches.append((path,method.upper(),operation,definition))
    if len(matches)!=1:raise ValueError('OpenAPI operation ID must identify exactly one operation')
    path,method,operation,path_item=matches[0];cfg=dict(config)
    cfg.update(method=method,methods=method,path=path)
    def wrapped(schema):
        return {**copy.deepcopy(dereference(schema)), 'components':copy.deepcopy(supplied.get('components') or {}),'definitions':copy.deepcopy(supplied.get('definitions') or {})}
    def media(content,preferred=''):
        if not content:return '',None
        name=preferred if preferred in content else next((key for key in content if 'json' in key),next(iter(content)))
        return name,wrapped(dereference(content[name]).get('schema') or {})
    request=dereference(operation.get('requestBody') or {})
    content_type,schema=media(request.get('content') or {},cfg.get('contentType'))
    parameters=[dereference(value) for value in [*(path_item.get('parameters') or []),*(operation.get('parameters') or [])]]
    body=next((value for value in parameters if value.get('in')=='body'),None)
    if body:content_type=(operation.get('consumes') or supplied.get('consumes') or ['application/json'])[0];schema=wrapped(body.get('schema') or {})
    if content_type:cfg['contentType']=content_type
    if schema and not cfg.get('requestSchema'):cfg['requestSchema']=schema
    cfg['_requiredBody']=bool(request.get('required') or body and body.get('required'))
    cfg['_restParameters']=[value for value in parameters if value.get('in') in ('path','query','header')]
    responses={}
    for code,response in (operation.get('responses') or {}).items():
        if not str(code).startswith('2'):continue
        response=dereference(response)
        response_type,response_schema=media(response.get('content') or {})
        if response.get('schema'):response_schema=wrapped(response['schema']);response_type=(operation.get('produces') or supplied.get('produces') or ['application/json'])[0]
        if response_schema:responses[str(code)]=response_schema
        if response_type:cfg.setdefault('responseType',response_type);cfg.setdefault('accept',response_type)
    cfg['_restResponseSchemas']=responses
    if not cfg.get('responseSchema') and responses:cfg['responseSchema']=next(iter(responses.values()))
    codes=[str(code) for code in (operation.get('responses') or {}) if str(code).startswith('2')]
    cfg['successStatusCodes']=','.join(codes) if codes and all(key.isdigit() for key in codes) else cfg.get('successStatusCodes','200-299')
    servers=operation.get('servers') or path_item.get('servers') or supplied.get('servers') or []
    if servers:
        server=servers[0];url=str(server.get('url') or '')
        for key,value in (server.get('variables') or {}).items():url=url.replace('{'+key+'}',str(value.get('default') or ''))
    else:url=((supplied.get('schemes') or ['https'])[0]+'://'+str(supplied.get('host') or '')+str(supplied.get('basePath') or '')) if supplied.get('host') else ''
    if cfg.get('operation')!='receiver':
        base=str(cfg.get('baseUrl') or url)
        if not base:raise ValueError('OpenAPI invocation requires a server URL or HTTP connection base URL')
        cfg['url']=base.rstrip('/')+path;cfg['basePath']=''
    elif url and not cfg.get('basePath'):cfg['basePath']=urllib.parse.urlsplit(url).path
    return cfg

def validate_parameters(cfg,parameters,query,headers,body):
    """Validate presence and primitive wire types before invoking a workflow/API."""
    errors=[];headers={str(key).lower():value for key,value in headers.items()}
    for parameter in cfg.get('_restParameters') or []:
        name=parameter.get('name');location=parameter.get('in');values=parameters if location=='path' else query if location=='query' else headers
        value=values.get(str(name).lower() if location=='header' else name)
        if value is None:
            if parameter.get('required') or location=='path':errors.append(f'{location} parameter {name} is required')
            continue
        schema=parameter.get('schema') or parameter;kind=schema.get('type')
        try:
            if kind=='integer':int(str(value))
            elif kind=='number':
                import math
                if not math.isfinite(float(value)):raise ValueError()
            elif kind=='boolean' and str(value).lower() not in ('true','false'):raise ValueError()
            if schema.get('enum') and str(value) not in {str(item) for item in schema['enum']}:raise ValueError()
        except (ValueError,TypeError):errors.append(f'{location} parameter {name} has an invalid value')
    if cfg.get('_requiredBody') and body is None:errors.append('Request body is required')
    return errors
