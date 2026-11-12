"""Offline RAML 1.0 expansion into the runtime's canonical OpenAPI contract.

Input resolution is an explicit, bounded document map; never a filesystem or
HTTP resolver. Unsupported executable/validation features fail closed.
"""
from __future__ import annotations
import copy, json, posixpath, re
from collections import deque
import yaml
import inflection

METHODS={'get','post','put','patch','delete','head','options','trace'}
GROUPS=('types','traits','resourceTypes','securitySchemes','annotationTypes')
BUILTINS={'any','object','array','string','number','integer','boolean','nil','file','date-only','time-only','datetime-only','datetime'}


class Document(dict):
    def __init__(self,value,path):super().__init__(value);self.path=path


def merge(base,own):
    if isinstance(base,dict) and isinstance(own,dict):
        result=copy.deepcopy(base)
        for key,value in own.items():result[key]=merge(result[key],value) if key in result else copy.deepcopy(value)
        return result
    if isinstance(base,list) and isinstance(own,list):
        result=copy.deepcopy(own)
        result.extend(copy.deepcopy(value) for value in base if value not in result)
        return result
    return copy.deepcopy(own)


def convert_raml(text, references=None, document_path='api.raml'):
    if not isinstance(text,str) or not re.match(r'^\ufeff?#%RAML 1\.0(?:\s|$)',text):raise ValueError('Provide a RAML 1.0 API document')
    sources={key.replace('\\','/'):value for key,value in (references or {}).items()}
    entry=(document_path or 'api.raml').replace('\\','/')
    sources[entry]=text
    if len(sources)>16:raise ValueError('RAML import supports at most 16 source files')
    if sum(len((value if isinstance(value,str) else json.dumps(value)).encode()) for value in sources.values())>32*1024**2:raise ValueError('RAML source limit exceeds 32 MiB')
    loaded={};steps=[0]
    def budget(depth=0):
        steps[0]+=1
        if depth>64 or steps[0]>100000:raise ValueError('RAML expansion complexity limit exceeded')
    def location(base,target):
        if not isinstance(target,str) or '<<' in target or re.match(r'^(?:[A-Za-z][\w+.-]*:|/)',target):raise ValueError('RAML references must be supplied local relative paths')
        value=posixpath.normpath(posixpath.join(posixpath.dirname(base),target.replace('\\','/')))
        if value=='..' or value.startswith('../') or '\x00' in value:raise ValueError('RAML reference escapes the supplied API folder')
        if value not in sources:raise ValueError('RAML reference was not supplied: '+value)
        return value
    def read(path,chain=()):
        if path in chain:raise ValueError('Cyclic RAML include/library reference: '+path)
        if path in loaded:return copy.deepcopy(loaded[path])
        budget(len(chain));value=sources[path]
        if not isinstance(value,str):return Document(copy.deepcopy(value),path) if isinstance(value,dict) else copy.deepcopy(value)
        if len(value.encode())>8*1024**2:raise ValueError('RAML file exceeds 8 MiB')
        if path!=entry and not re.search(r'\.(?:raml|ya?ml|json)$',path,re.I):return value
        class Loader(yaml.SafeLoader):
            yaml_implicit_resolvers={key:[item for item in items if item[0] not in ('tag:yaml.org,2002:bool','tag:yaml.org,2002:timestamp')] for key,items in yaml.SafeLoader.yaml_implicit_resolvers.items()}
            def compose_node(self,parent,index):
                if self.check_event(yaml.AliasEvent):raise ValueError('RAML YAML aliases are not permitted')
                return super().compose_node(parent,index)
        Loader.add_implicit_resolver('tag:yaml.org,2002:bool',re.compile(r'^(?:true|false|True|False|TRUE|FALSE)$'),list('tTfF'))
        def mapping(loader,node,deep=False):
            result={}
            for key_node,value_node in node.value:
                key=loader.construct_object(key_node,deep=deep)
                if not isinstance(key,(str,int)) or isinstance(key,bool):raise ValueError('RAML object keys must be strings or status codes')
                key=str(key)
                if key in result:raise ValueError('Duplicate RAML key: '+key)
                result[key]=loader.construct_object(value_node,deep=deep)
            return result
        Loader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,mapping)
        Loader.add_constructor('!include',lambda loader,node:read(location(path,loader.construct_scalar(node)),(*chain,path)))
        try:value=yaml.load(value.lstrip('\ufeff'),Loader=Loader)
        except yaml.YAMLError as error:raise ValueError('Invalid RAML YAML: '+str(error)) from None
        if isinstance(value,dict):value=Document(value,path)
        def check(node,depth=0):
            budget(depth)
            if isinstance(node,dict):
                for item in node.values():check(item,depth+1)
            elif isinstance(node,list):
                for item in node:check(item,depth+1)
        check(value);loaded[path]=value;return copy.deepcopy(value)
    root=read(entry)
    if not isinstance(root,dict) or not isinstance(root.get('title'),str) or not root['title'].strip():raise ValueError('RAML API requires a title')
    if re.match(r'^\ufeff?#%RAML 1\.0\s+(?:Library|Trait|ResourceType|DataType|NamedExample)\b',text):raise ValueError('Select the RAML API entry file, not a fragment')
    if 'extends' in root:raise ValueError('RAML overlays/extensions must be expanded before import')
    definitions={group:{} for group in GROUPS}
    def qualify(value,names,prefix):
        if not isinstance(value,str):return value
        return re.sub(r'(?<![\w.])([A-Za-z_][\w.-]*)(?![\w.])',lambda match:prefix+match[1] if match[1] in names else match[1],value)
    def rewrite(node,names,prefix,context=''):
        if isinstance(node,str):return qualify(node,names,prefix) if context in ('type','items','is','securedBy') else node
        if isinstance(node,list):return [rewrite(value,names,prefix,context) for value in node]
        if not isinstance(node,dict):return node
        result={}
        for key,value in node.items():
            target=qualify(key,names,prefix) if context in ('is','securedBy','resourceTypeRef') else key
            # Parameter shorthand under properties/header/query maps is a type expression.
            child_context='type' if context in ('properties','headers','queryParameters','uriParameters') and isinstance(value,str) else key
            if key=='type' and isinstance(value,dict):child_context='resourceTypeRef'
            result[target]=rewrite(value,names,prefix,child_context)
        return Document(result,node.path) if isinstance(node,Document) else result
    def register(document,prefix='',chain=()):
        source=getattr(document,'path',entry)
        if source in chain:raise ValueError('Cyclic RAML library: '+source)
        uses=document.get('uses') or {}
        if not isinstance(uses,dict):raise ValueError('RAML uses must be a library map')
        local=set()
        for group in GROUPS:
            entries=document.get(group) or {}
            if not isinstance(entries,dict):raise ValueError('RAML '+group+' must be a map')
            local.update(entries)
        for alias,target in uses.items():
            if not re.fullmatch(r'[A-Za-z_][\w-]*',alias):raise ValueError('Invalid RAML library alias')
            library=read(location(source,target),(*chain,source))
            if not isinstance(library,dict):raise ValueError('RAML library must be an object')
            register(library,prefix+alias+'.',(*chain,source))
            local.update(alias+'.'+name for group in GROUPS for name in (library.get(group) or {}))
            # Nested library references remain fully qualified in exported definitions.
            local.update(name[len(prefix):] for group in GROUPS for name in definitions[group] if name.startswith(prefix+alias+'.'))
        for group in GROUPS:
            for name,value in (document.get(group) or {}).items():
                key=prefix+name
                if key in definitions[group]:raise ValueError('Duplicate RAML declaration: '+key)
                definitions[group][key]=rewrite(copy.deepcopy(value),local,prefix) if prefix else copy.deepcopy(value)
    register(root)
    # Fragments can bring their own library namespace into a trait or resource type.
    for group in GROUPS:
        for key,value in list(definitions[group].items()):
            if isinstance(value,Document) and value.get('uses'):
                prefix=key+'.'
                register(value,prefix)
                names={name[len(prefix):] for category in GROUPS for name in definitions[category] if name.startswith(prefix)}
                definitions[group][key]={name:item for name,item in rewrite(value,names,prefix).items() if name!='uses'}

    def template(node,values,depth=0):
        budget(depth)
        if isinstance(node,list):return [template(value,values,depth+1) for value in node]
        if isinstance(node,dict):return {str(template(key,values,depth+1)):template(value,values,depth+1) for key,value in node.items() if key not in ('usage','uses')}
        if not isinstance(node,str):return node
        def substitute(match):
            parts=[part.strip() for part in match[1].split('|')];name=parts.pop(0)
            if name not in values:raise ValueError('Missing RAML template parameter: '+name)
            value=copy.deepcopy(values[name])
            functions={'!singularize':inflection.singularize,'!pluralize':inflection.pluralize,'!uppercase':str.upper,'!lowercase':str.lower,
                '!lowercamelcase':lambda v:inflection.camelize(v,False),'!uppercamelcase':inflection.camelize,
                '!lowerunderscorecase':inflection.underscore,'!upperunderscorecase':lambda v:inflection.underscore(v).upper(),
                '!lowerhyphencase':lambda v:inflection.dasherize(inflection.underscore(v)),
                '!upperhyphencase':lambda v:inflection.dasherize(inflection.underscore(v)).upper()}
            for function in parts:
                if function not in functions:raise ValueError('Unknown RAML template function: '+function)
                value=functions[function](str(value))
            return value
        full=re.fullmatch(r'<<\s*(.*?)\s*>>',node)
        if full:return substitute(full)
        return re.sub(r'<<\s*(.*?)\s*>>',lambda match:str(substitute(match)),node)
    def reference(value):
        if isinstance(value,str):return value,{}
        if isinstance(value,dict) and len(value)==1:
            name,parameters=next(iter(value.items()))
            if parameters is None:parameters={}
            if isinstance(parameters,dict):return name,parameters
        raise ValueError('Invalid RAML trait/resource type reference')
    def resource_type(value,values,active,chain=()):
        name,parameters=reference(value);budget(len(chain))
        if set(parameters)&{'resourcePath','resourcePathName','methodName'}:raise ValueError('Reserved RAML template parameters cannot be supplied')
        if name in chain or name not in definitions['resourceTypes']:raise ValueError('Unknown or cyclic RAML resource type: '+name)
        raw=copy.deepcopy(definitions['resourceTypes'][name])
        if not isinstance(raw,dict) or any(key.startswith('/') for key in raw):raise ValueError('RAML resource types cannot declare nested resources')
        active.update(key for key in raw if key in METHODS)
        raw={key:({} if key.rstrip('?') in METHODS and value is None else value) for key,value in raw.items()}
        values={**parameters,**values}
        parent=resource_type(template(raw['type'],values),values,active,(*chain,name)) if raw.get('type') else {}
        raw={key.rstrip('?') if key.endswith('?') and key[:-1] in METHODS else key:value for key,value in raw.items()
             if key!='type' and (not key.endswith('?') or key[:-1] in active)}
        return merge(parent,template(raw,values))
    def traits(refs,values):
        if refs is None:return {}
        if not isinstance(refs,list):raise ValueError('RAML is must be a trait array')
        queue=deque((item,0,()) for item in refs);seen=set();levels={}
        while queue:
            ref,depth,chain=queue.popleft();budget(depth);name,parameters=reference(ref)
            if set(parameters)&{'resourcePath','resourcePathName','methodName'}:raise ValueError('Reserved RAML template parameters cannot be supplied')
            if name in chain or name not in definitions['traits']:raise ValueError('Unknown or cyclic RAML trait: '+name)
            if name in seen:continue
            seen.add(name);raw=template(definitions['traits'][name],{**parameters,**values})
            if not isinstance(raw,dict) or any(key.startswith('/') or key.rstrip('?') in METHODS for key in raw):raise ValueError('Invalid RAML trait definition')
            nested=raw.pop('is',[]) or []
            if not isinstance(nested,list):raise ValueError('RAML trait is must be an array')
            queue.extend((item,depth+1,(*chain,name)) for item in nested)
            levels.setdefault(depth,[]).append(raw)
        result={}
        for depth in sorted(levels,reverse=True):
            for raw in levels[depth]:result=merge(result,raw)
        return result

    spec={'openapi':'3.1.0','info':{'title':root['title'],'version':str(root.get('version','1.0.0'))},'paths':{},'components':{'schemas':{},'securitySchemes':{}},'x-mina-source-format':'RAML 1.0'}
    if root.get('description'):spec['info']['description']=root['description']
    def split_union(value):
        parts=[];depth=0;start=0
        for index,char in enumerate(value):
            depth+=1 if char=='(' else -1 if char==')' else 0
            if depth<0:raise ValueError('Invalid RAML type expression')
            if char=='|' and depth==0:parts.append(value[start:index].strip());start=index+1
        if depth:raise ValueError('Invalid RAML type expression')
        return parts+[value[start:].strip()]
    building=set()
    def expression(value):
        if isinstance(value,list):return {'allOf':[schema(item) for item in value]}
        if not isinstance(value,str):raise ValueError('Invalid RAML type expression')
        value=value.strip()
        if value.startswith('{'):
            try:return json.loads(value)
            except ValueError:raise ValueError('Invalid included JSON schema') from None
        union=split_union(value)
        if len(union)>1:return {'anyOf':[expression(item) for item in union]}
        if value.endswith('[]'):return {'type':'array','items':expression(value[:-2])}
        if value.startswith('(') and value.endswith(')'):return expression(value[1:-1])
        if value in definitions['types']:
            if value not in spec['components']['schemas']:
                spec['components']['schemas'][value]={};building.add(value)
                spec['components']['schemas'][value]=schema(definitions['types'][value]);building.discard(value)
            return {'$ref':'#/components/schemas/'+value.replace('~','~0').replace('/','~1')}
        if value not in BUILTINS:raise ValueError('Unknown RAML type: '+value)
        if value=='any':return {}
        if value=='nil':return {'type':'null'}
        if value=='file':return {'type':'string','format':'binary'}
        if value in ('date-only','time-only','datetime','datetime-only'):
            return {'type':'string',**({'format':{'date-only':'date','time-only':'time','datetime':'date-time'}[value]} if value!='datetime-only' else {'pattern':r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?$'})}
        return {'type':value}
    def example_value(value):
        return value['value'] if isinstance(value,dict) and 'value' in value and set(value)<={'value','strict','displayName','description'} else value
    def schema(value,depth=0):
        budget(depth)
        if value is None:value={}
        if isinstance(value,str):return expression(value)
        if not isinstance(value,dict):raise ValueError('RAML data type must be a string or object')
        if isinstance(value,Document) and (value.path.lower().endswith('.json') or '$schema' in value):
            return {'$ref':posixpath.relpath(value.path,posixpath.dirname(entry) or '.')}
        if '$schema' in value or '$ref' in value:return copy.deepcopy(value)
        if 'schema' in value and 'type' in value:raise ValueError('RAML type and schema cannot both be specified')
        kind=value.get('type',value.get('schema','object' if 'properties' in value else 'string'))
        result=expression(kind) if not isinstance(kind,dict) else schema(kind,depth+1)
        if 'properties' in value:
            if not isinstance(value['properties'],dict):raise ValueError('RAML properties must be a map')
            props={};patterns={};required=[]
            for name,definition in value['properties'].items():
                target=name[:-1] if name.endswith('?') else name
                definition={} if definition is None else definition
                if name.startswith('/') and name.endswith('/'):
                    patterns[name[1:-1]]=schema(definition,depth+1);continue
                props[target]=schema(definition,depth+1)
                if not name.endswith('?') and not (isinstance(definition,dict) and definition.get('required') is False):required.append(target)
            result={**result,'properties':props}
            if patterns:result['patternProperties']=patterns
            if required:result['required']=required
        if 'items' in value:result['items']=schema(value['items'],depth+1)
        for facet in ('enum','minimum','maximum','multipleOf','minLength','maxLength','pattern','minItems','maxItems','uniqueItems','minProperties','maxProperties','additionalProperties','default','description','format'):
            if facet in value:result[facet]=copy.deepcopy(value[facet])
        if kind=='datetime' and value.get('format')=='rfc3339':result['format']='date-time'
        if kind=='datetime' and value.get('format')=='rfc2616':raise ValueError('RAML RFC2616 datetime format requires an explicit string pattern in this runtime')
        if 'displayName' in value:result['title']=value['displayName']
        if 'example' in value:result['examples']=[example_value(value['example'])]
        if isinstance(value.get('examples'),dict):result['examples']=[example_value(item) for item in value['examples'].values()]
        if value.get('facets'):raise ValueError('RAML custom validation facets must be expanded into supported constraints before import')
        if value.get('fileTypes'):raise ValueError('RAML fileTypes constraints must be declared as request media types before import')
        ignored={'type','schema','properties','items','required','example','examples','displayName','usage','facets','xml','fileTypes'}
        for key in value:
            if key not in ignored and key not in result and not key.startswith('('):raise ValueError('Unsupported RAML type facet: '+key)
        if 'xml' in value:result['xml']=copy.deepcopy(value['xml'])
        return result
    for name in list(definitions['types']):expression(name)
    default_media=root.get('mediaType') or 'application/json'
    default_media=default_media if isinstance(default_media,list) else [default_media]
    def body(value):
        if value is None:value={}
        if not isinstance(value,dict):value={'type':value}
        media=value if value and all('/' in key for key in value) else {name:value for name in default_media}
        result={}
        for name,definition in media.items():
            definition={} if definition is None else definition
            definition=definition if isinstance(definition,dict) else {'type':definition}
            item={'schema':schema(definition)}
            if 'example' in definition:item['example']=example_value(definition['example'])
            if isinstance(definition.get('examples'),dict):item['examples']={key:{'value':example_value(value)} for key,value in definition['examples'].items()}
            result[name]=item
        return result
    def parameters(values,where):
        if values is None:return []
        if not isinstance(values,dict):raise ValueError('RAML '+where+' parameters must be a map')
        result=[]
        for key,value in values.items():
            name=key[:-1] if key.endswith('?') else key
            declaration=value if isinstance(value,dict) else {'type':value or 'string'}
            result.append({'name':name,'in':where,'required':where=='path' or bool(declaration.get('required',not key.endswith('?'))),
                           'schema':schema(declaration),**({'description':declaration['description']} if 'description' in declaration else {})})
        return result
    def secured(values):
        if not isinstance(values,list):raise ValueError('RAML securedBy must be an array')
        result=[]
        for value in values:
            if value is None:result.append({});continue
            name,settings=reference(value)
            if name not in definitions['securitySchemes']:raise ValueError('Unknown RAML security scheme: '+name)
            result.append({name:settings.get('scopes',[])})
        return result
    for name,value in definitions['securitySchemes'].items():
        if not isinstance(value,dict):raise ValueError('Invalid RAML security scheme')
        kind=value.get('type');settings=value.get('settings') or {}
        if kind=='Basic Authentication':converted={'type':'http','scheme':'basic'}
        elif kind=='OAuth 2.0':
            grants=settings.get('authorizationGrants') or ['authorization_code'];flows={}
            for grant in grants:
                target={'authorization_code':'authorizationCode','implicit':'implicit','client_credentials':'clientCredentials','password':'password'}.get(grant)
                if target is None:raise ValueError('Unsupported RAML OAuth grant: '+str(grant))
                flow={'scopes':{str(scope):str(scope) for scope in settings.get('scopes',[])}}
                if target in ('authorizationCode','implicit'):flow['authorizationUrl']=settings.get('authorizationUri','')
                if target!='implicit':flow['tokenUrl']=settings.get('accessTokenUri','')
                flows[target]=flow
            converted={'type':'oauth2','flows':flows}
        elif kind=='Pass Through':
            described=value.get('describedBy') or {};headers=described.get('headers') or {};queries=described.get('queryParameters') or {}
            if len(headers)+len(queries)!=1:raise ValueError('Pass Through security requires exactly one header or query credential')
            converted={'type':'apiKey','in':'header' if headers else 'query','name':next(iter(headers or queries))}
        else:raise ValueError('Unsupported RAML authentication mechanism: '+str(kind))
        if value.get('description'):converted['description']=value['description']
        spec['components']['securitySchemes'][name]=converted
    if 'securedBy' in root:spec['security']=secured(root['securedBy'])
    if root.get('baseUri'):
        uri=str(root['baseUri']).replace('{version}',str(root.get('version','')));variables={}
        for key,declaration in (root.get('baseUriParameters') or {}).items():
            declaration=declaration if isinstance(declaration,dict) else {}
            if key=='version':continue
            if 'default' not in declaration and not declaration.get('enum'):raise ValueError('RAML base URI parameter requires a default or enum: '+key)
            variables[key]={'default':str(declaration.get('default',(declaration.get('enum') or [''])[0]))}
        spec['servers']=[{'url':uri,**({'variables':variables} if variables else {})}]
    def resource(path,node,inherited_parameters,inherited_security,depth=0):
        budget(depth)
        node={} if node is None else node
        if not isinstance(node,dict):raise ValueError('RAML resource must be an object')
        node={key:({} if key in METHODS and value is None else value) for key,value in node.items()}
        values={'resourcePath':path,'resourcePathName':next((item for item in reversed(path.split('/')) if item and '{' not in item),'')}
        inherited=resource_type(node['type'],values,set(node)&METHODS) if node.get('type') else {}
        current=merge(inherited,node)
        uri=merge(inherited_parameters,current.get('uriParameters') or {})
        security=current.get('securedBy',inherited_security)
        for method in current:
            if method not in METHODS:continue
            declaration=current[method] or {}
            if not isinstance(declaration,dict):raise ValueError('RAML method must be an object')
            method_values={**values,'methodName':method}
            combined=merge(traits(current.get('is',[]),method_values),traits(declaration.get('is',[]),method_values))
            expanded=merge(combined,{key:value for key,value in declaration.items() if key!='is'})
            operation={'responses':{},'operationId':str(expanded.get('(operationId)') or method+'_'+__import__('hashlib').sha256(path.encode()).hexdigest()[:12])}
            if expanded.get('displayName'):operation['summary']=expanded['displayName']
            if expanded.get('description'):operation['description']=expanded['description']
            declared=parameters({key:value for key,value in uri.items() if '{'+key.rstrip('?')+'}' in path},'path')
            for name in re.findall(r'\{([^}]+)\}',path):
                if not any(item['name']==name for item in declared):declared.append({'name':name,'in':'path','required':True,'schema':{'type':'string'}})
            declared+=parameters(expanded.get('queryParameters'),'query')+parameters(expanded.get('headers'),'header')
            if expanded.get('queryString') is not None:raise ValueError('RAML queryString object must be expressed as queryParameters for this HTTP runtime')
            if declared:operation['parameters']=declared
            if 'body' in expanded:operation['requestBody']={'required':True,'content':body(expanded['body'])}
            responses=expanded.get('responses') or {'200':{'description':'Successful response'}}
            if not isinstance(responses,dict):raise ValueError('RAML responses must be a map')
            for code,response in responses.items():
                response=response or {}
                item={'description':str(response.get('description') or 'API response')}
                if 'body' in response:item['content']=body(response['body'])
                if response.get('headers'):
                    item['headers']={parameter['name']:{'schema':parameter['schema'],**({'description':parameter['description']} if 'description' in parameter else {})} for parameter in parameters(response['headers'],'header')}
                operation['responses'][str(code)]=item
            method_security=expanded.get('securedBy',security)
            if method_security is not None:operation['security']=secured(method_security)
            protocols=expanded.get('protocols',root.get('protocols'))
            if protocols is not None:
                if not isinstance(protocols,list) or not protocols or any(item not in ('HTTP','HTTPS') for item in protocols):raise ValueError('RAML protocols must contain HTTP and/or HTTPS')
                operation['x-mina-allowed-protocols']=[item.lower() for item in protocols]
            spec['paths'].setdefault(path,{})[method]=operation
        for key,value in node.items():
            if key.startswith('/'):resource(path.rstrip('/')+key,value,uri,security,depth+1)
    for key,value in root.items():
        if key.startswith('/'):resource(key,value,{},root.get('securedBy'),0)
    return spec
