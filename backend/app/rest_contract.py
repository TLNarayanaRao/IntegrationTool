"""Local OpenAPI 3 / Swagger 2 operation contracts. Never fetch remote refs."""
from __future__ import annotations
import copy, json, urllib.parse
from .http_contracts import bundle_document, schema_errors

def operation_config(config):
    supplied=config.get('openApiDocument')
    if not supplied:return dict(config)
    supplied=bundle_document(supplied,config)
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
            if method.lower() in ('get','post','put','patch','delete','head','options','trace') and isinstance(operation,dict) and operation.get('operationId')==selected:matches.append((path,method.upper(),operation,definition))
    if len(matches)!=1:raise ValueError('OpenAPI operation ID must identify exactly one operation')
    path,method,operation,path_item=matches[0];cfg=dict(config)
    cfg['_restOperation']=copy.deepcopy(operation)
    cfg['_restOperation']['requestBody']=copy.deepcopy(dereference(operation.get('requestBody') or {}))
    cfg['_restOperation']['responses']={str(code):copy.deepcopy(dereference(value)) for code,value in (operation.get('responses') or {}).items()}
    cfg.update(method=method,methods=method,path=path)
    def wrapped(schema):
        result=copy.deepcopy(dereference(schema))
        if not isinstance(result,dict):return result
        def compatibility(node):
            if isinstance(node,list):return [compatibility(item) for item in node]
            if not isinstance(node,dict):return node
            node={key:compatibility(item) for key,item in node.items()}
            if node.get('nullable') and isinstance(node.get('type'),str):node['type']=[node['type'],'null']
            for exclusive,bound in [('exclusiveMinimum','minimum'),('exclusiveMaximum','maximum')]:
                if isinstance(node.get(exclusive),bool):
                    enabled=node.pop(exclusive)
                    if enabled and bound in node:node[exclusive]=node.pop(bound)
            return node
        result=compatibility(result)
        return {**result, 'components':compatibility(copy.deepcopy(supplied.get('components') or {})),'definitions':compatibility(copy.deepcopy(supplied.get('definitions') or {})),'x-mina-refs':compatibility(copy.deepcopy(supplied.get('x-mina-refs') or {}))}
    def media(content,preferred=''):
        if not content:return '',None
        name=preferred if preferred in content else next((key for key in content if 'json' in key),next(iter(content)))
        return name,wrapped(dereference(content[name]).get('schema',{}))
    request=dereference(operation.get('requestBody') or {})
    headers=cfg.get('headers') or {}
    preferred=cfg.get('contentType') or (next((value for key,value in headers.items() if key.lower()=='content-type'),'') if isinstance(headers,dict) else '')
    preferred=str(preferred).split(';',1)[0].strip().lower()
    content_type,schema=media(request.get('content') or {},preferred)
    cfg['_restRequestSchemas']={name:wrapped(dereference(definition).get('schema',{})) for name,definition in (request.get('content') or {}).items()}
    cfg['_explicitRequestSchema']=config.get('_explicitRequestSchema',config.get('requestSchema') not in (None,''))
    # An operation parameter overrides the path-level parameter of the same name/location.
    parameters=list({(p.get('in'),p.get('name')):p for p in (dereference(value) for value in [*(path_item.get('parameters') or []),*(operation.get('parameters') or [])])}.values())
    parameters=[{**p,'schema':wrapped(p.get('schema') or {key:value for key,value in p.items() if key in ('type','items','enum','minimum','maximum','pattern','minLength','maxLength')})} for p in parameters]
    if supplied.get('swagger')=='2.0':
        parameters=[{**p,'collectionFormat':p.get('collectionFormat','csv'),'explode':p.get('collectionFormat')=='multi'} if (p.get('schema') or {}).get('type')=='array' else p for p in parameters]
    body=next((value for value in parameters if value.get('in')=='body'),None)
    if body:content_type=(operation.get('consumes') or supplied.get('consumes') or ['application/json'])[0];schema=wrapped(body.get('schema') or {})
    if content_type:cfg['contentType']=content_type
    if schema is not None and cfg.get('requestSchema') in (None,''):cfg['requestSchema']=schema
    cfg['_requiredBody']=bool(request.get('required') or body and body.get('required'))
    cfg['_restParameters']=[value for value in parameters if value.get('in') in ('path','query','header','cookie','formData')]
    responses={};response_content={}
    for code,response in (operation.get('responses') or {}).items():
        response=dereference(response)
        response_content[str(code).upper() if str(code)!='default' else 'default']={name:wrapped(dereference(definition).get('schema',{})) for name,definition in (response.get('content') or {}).items()}
        response_type,response_schema=media(response.get('content') or {})
        if response.get('schema'):response_schema=wrapped(response['schema']);response_type=(operation.get('produces') or supplied.get('produces') or ['application/json'])[0]
        if response_schema is not None:responses[str(code).upper() if str(code)!='default' else 'default']=response_schema
        if response_type and str(code).startswith('2'):cfg.setdefault('responseType',response_type);cfg.setdefault('accept',response_type)
    cfg['_restResponseSchemas']=responses
    cfg['_restResponseContentSchemas']=response_content
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

def _primitive(value, schema):
    kind=schema.get('type')
    if value is None:return None
    if kind=='integer':
        if isinstance(value,bool) or not __import__('re').fullmatch(r'-?\d+',str(value)):raise ValueError()
        return int(value)
    if kind=='number':
        import math
        converted=float(value)
        if isinstance(value,bool) or not math.isfinite(converted):raise ValueError()
        return converted
    if kind=='boolean':
        if str(value).lower() not in ('true','false'):raise ValueError()
        return str(value).lower()=='true'
    return value

def typed_form_body(cfg,body,content_type):
    """Decode primitive form fields using their contract types before validation."""
    if str(content_type).split(';',1)[0].lower()!='application/x-www-form-urlencoded' or not isinstance(body,dict):return body
    from .http_contracts import request_schema
    root=request_schema(cfg,content_type)
    if not isinstance(root,dict):return body
    def resolve(schema):
        seen=set()
        while isinstance(schema,dict) and str(schema.get('$ref','')).startswith('#/'):
            reference=schema['$ref']
            if reference in seen:break
            seen.add(reference);schema=root
            for part in reference[2:].split('/'):schema=schema[part.replace('~1','/').replace('~0','~')]
        return schema if isinstance(schema,dict) else {}
    result=dict(body)
    for name,schema in resolve(root).get('properties',{}).items():
        if name not in result:continue
        schema=resolve(schema);value=result[name]
        if schema.get('type')=='array':result[name]=[_primitive(item,resolve(schema.get('items',{}))) for item in (value if isinstance(value,list) else [value])]
        elif schema.get('type') in ('integer','number','boolean','string'):
            if isinstance(value,list):raise ValueError('Scalar form field is repeated')
            result[name]=_primitive(value,schema)
    return result

def parameter_value(parameter, values):
    name=parameter.get('name');schema=parameter.get('schema') or parameter;kind=schema.get('type');location=parameter.get('in')
    name=str(name).lower() if location=='header' else name
    value=values.get(name)
    style=parameter.get('style') or ('form' if location in ('query','cookie') else 'simple')
    explode=parameter.get('explode',style=='form')
    if style=='deepObject' and kind=='object':
        value={key[len(name)+1:-1]:item for key,item in values.items() if key.startswith(name+'[') and key.endswith(']')} or None
    elif kind=='object' and explode and style=='form':
        value={key:values[key] for key in schema.get('properties',{}) if key in values} or value
    if value is None:return None
    if kind=='array':
        delimiter={'spaceDelimited':' ','pipeDelimited':'|','label':'.' if explode else ','}.get(style,{'ssv':' ','pipes':'|','tsv':'\t'}.get(parameter.get('collectionFormat'),','))
        if not isinstance(value,list):
            if style=='matrix':
                value=[item.split('=',1)[-1] for item in str(value).lstrip(';').split(';')] if explode else str(value).split('=',1)[-1].split(',')
            elif style=='form' and explode and parameter.get('collectionFormat','multi')=='multi':value=[value]
            else:value=str(value).lstrip('.').split(delimiter)
        return [_primitive(item,schema.get('items') or {}) for item in value]
    if kind=='object':
        if not isinstance(value,dict):
            if style=='matrix':items=str(value).lstrip(';').split(';')
            else:items=str(value).lstrip('.').split('.' if style=='label' and explode else ',')
            if explode:value=dict(item.split('=',1) for item in items)
            else:value=dict(zip(items[::2],items[1::2],strict=True))
        return {key:_primitive(item,(schema.get('properties') or {}).get(key,{})) for key,item in value.items()}
    if isinstance(value,list):raise ValueError('Scalar parameter is repeated')
    if style=='label':value=str(value).lstrip('.')
    if style=='matrix':value=str(value).split('=',1)[-1]
    return _primitive(value,schema)

def validate_parameters(cfg,parameters,query,headers,body):
    """Validate presence and primitive wire types before invoking a workflow/API."""
    from http.cookies import SimpleCookie
    errors=[];headers={str(key).lower():value for key,value in headers.items()}
    cookies=SimpleCookie();cookies.load('; '.join(headers.get('cookie',[])) if isinstance(headers.get('cookie'),list) else str(headers.get('cookie') or ''))
    cookie_values={key:item.value for key,item in cookies.items()}
    for parameter in cfg.get('_restParameters') or []:
        name=parameter.get('name');location=parameter.get('in');values=parameters if location=='path' else query if location=='query' else cookie_values if location=='cookie' else (body if isinstance(body,dict) else {}) if location=='formData' else headers
        try:value=parameter_value(parameter,values)
        except (ValueError,TypeError):errors.append(f'{location} parameter {name} has an invalid value');continue
        if value is None:
            if parameter.get('required') or location=='path':errors.append(f'{location} parameter {name} is required')
            continue
        if schema_errors(value,parameter.get('schema') or parameter):errors.append(f'{location} parameter {name} violates its schema')
    if cfg.get('_requiredBody') and body is None:errors.append('Request body is required')
    return errors

def serialize_parameter(parameter,value):
    """OpenAPI form/simple/label/matrix and Swagger collection serialization."""
    location=parameter.get('in');name=parameter.get('name');style=parameter.get('style') or ('form' if location in ('query','cookie') else 'simple')
    explode=parameter.get('explode',style=='form');kind=(parameter.get('schema') or parameter).get('type')
    primitive=lambda item:'true' if item is True else 'false' if item is False else str(item)
    if isinstance(value,dict):
        if style=='deepObject':return {f'{name}[{key}]':primitive(item) for key,item in value.items()}
        if style=='form' and explode:return {key:primitive(item) for key,item in value.items()}
        separator=';' if style=='matrix' and explode else '.' if style=='label' and explode else ','
        result=separator.join(f'{key}={primitive(item)}' if explode else f'{key},{primitive(item)}' for key,item in value.items())
    elif isinstance(value,list):
        if style=='form' and explode and parameter.get('collectionFormat','multi')=='multi':return value
        separator={'spaceDelimited':' ','pipeDelimited':'|','label':'.' if explode else ','}.get(style,{'ssv':' ','pipes':'|','tsv':'\t'}.get(parameter.get('collectionFormat'),','))
        result=separator.join(map(primitive,value))
        if style=='matrix' and explode:result=';'.join(f'{name}={primitive(item)}' for item in value)
    else:result=primitive(value)
    if style=='label':return '.'+result
    if style=='matrix':return ';'+('' if explode and isinstance(value,dict) or explode and isinstance(value,list) else str(name)+'=')+result
    return result

def wire_parameters(cfg,location,values):
    result=dict(values)
    for parameter in cfg.get('_restParameters') or []:
        if parameter.get('in')!=location:continue
        name=str(parameter.get('name'));name=name.lower() if location=='header' else name
        if name not in values:continue
        encoded=serialize_parameter(parameter,values[name])
        if isinstance(encoded,dict):result.pop(name,None);result.update(encoded)
        else:result[name]=encoded
    return result
