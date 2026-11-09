"""Bounded OpenAPI document loading and offline schema validation."""
from __future__ import annotations
import copy, json, re, urllib.parse
from .schema_validation import schema_errors

LIMIT = 8 * 1024**2

def parse_json(value):
    def invalid_constant(name):raise ValueError('Non-finite JSON number: '+name)
    return json.loads(value,parse_constant=invalid_constant)

def load_document(value):
    if not isinstance(value, str): return copy.deepcopy(value)
    if len(value.encode()) > LIMIT: raise ValueError('OpenAPI document exceeds 8 MiB')
    try: document = json.loads(value)
    except ValueError:
        import yaml
        # Alias expansion is unnecessary for API contracts and can create cycles.
        try:
            if any(isinstance(token, yaml.tokens.AliasToken) for token in yaml.scan(value)):
                raise ValueError('YAML aliases are not permitted in API contracts')
            class ContractLoader(yaml.SafeLoader):
                yaml_implicit_resolvers={key:[entry for entry in entries if entry[0] not in ('tag:yaml.org,2002:bool','tag:yaml.org,2002:timestamp')] for key,entries in yaml.SafeLoader.yaml_implicit_resolvers.items()}
                def construct_mapping(self,node,deep=False):
                    result={}
                    for key_node,value_node in node.value:
                        key=self.construct_object(key_node,deep=deep)
                        if isinstance(key,(dict,list)):raise ValueError('YAML object keys must be scalar')
                        if key in result:raise ValueError('Duplicate YAML key: '+str(key))
                        result[key]=self.construct_object(value_node,deep=deep)
                    return result
            import re
            ContractLoader.add_implicit_resolver('tag:yaml.org,2002:bool',re.compile(r'^(?:true|false|True|False|TRUE|FALSE)$'),list('tTfF'))
            document = yaml.load(value,Loader=ContractLoader)
        except yaml.YAMLError as error:raise ValueError('Invalid YAML: '+str(error)) from None
    budget = [0]
    def check(node, depth=0):
        budget[0] += 1
        if depth > 128 or budget[0] > 100000: raise ValueError('OpenAPI document complexity limit exceeded')
        if isinstance(node, dict):
            for key, item in list(node.items()):
                if isinstance(key,int) and not isinstance(key,bool):
                    if str(key) in node:raise ValueError('Duplicate API document key')
                    del node[key];node[str(key)]=item
                elif not isinstance(key, str): raise ValueError('OpenAPI object keys must be strings')
                check(item, depth+1)
        elif isinstance(node, list):
            for item in node: check(item, depth+1)
    check(document)
    return document

def bundle_document(value, cfg):
    root = load_document(value)
    if not isinstance(root, dict): raise ValueError('API contract must be an object')
    supplied = cfg.get('openApiReferenceDocuments') or {}
    if isinstance(supplied, str): supplied = json.loads(supplied)
    if not isinstance(supplied, dict): raise ValueError('Reference documents must be a URI/document object')
    origins = str(cfg.get('openApiAllowedRefOrigins') or '').replace(',', ' ').split()
    base = str(cfg.get('openApiBaseUrl') or '')
    documents = {base: root}; bundled = {}; references = {}; total = [0]
    def get_document(uri):
        if uri in documents: return documents[uri]
        if len(documents) >= 16: raise ValueError('OpenAPI reference document limit exceeded')
        if uri in supplied: document = load_document(supplied[uri])
        else:
            parts = urllib.parse.urlsplit(uri)
            origin = f'{parts.scheme}://{parts.netloc}'
            if parts.scheme != 'https' or parts.username or parts.password or origin not in origins:
                raise ValueError('External API reference requires an explicitly allowed HTTPS origin or a supplied reference document')
            from .http_transport import client_for
            with client_for(cfg).stream('GET', uri, follow_redirects=False, timeout=10) as response:
                response.raise_for_status(); chunks=[]; size=0
                for chunk in response.iter_bytes():
                    size += len(chunk)
                    if size > LIMIT: raise ValueError('API reference exceeds 8 MiB')
                    chunks.append(chunk)
                total[0] += size
                if total[0] > 32*1024**2: raise ValueError('API reference total exceeds 32 MiB')
                document = load_document(b''.join(chunks).decode('utf-8'))
        documents[uri] = document
        return document
    def rewrite(node, uri, external=False, depth=0):
        if depth > 128: raise ValueError('API reference nesting limit exceeded')
        if isinstance(node, list): return [rewrite(x, uri, external, depth+1) for x in node]
        if not isinstance(node, dict): return node
        output = {}
        for key, item in node.items():
            if key != '$ref' or not isinstance(item, str): output[key] = rewrite(item, uri, external, depth+1); continue
            if item.startswith('#') and not external: output[key] = item; continue
            target = urllib.parse.urljoin(uri, item); document_uri, fragment = urllib.parse.urldefrag(target)
            if fragment and not fragment.startswith('/'): raise ValueError('API references require JSON Pointer fragments')
            identity = (document_uri, fragment)
            if identity not in references:
                if len(references) >= 512: raise ValueError('API reference count limit exceeded')
                name = 'ref'+str(len(references)); references[identity] = name
                document = get_document(document_uri)
                for part in fragment.lstrip('/').split('/') if fragment else []:
                    document = document[urllib.parse.unquote(part).replace('~1','/').replace('~0','~')]
                bundled[name] = rewrite(document, document_uri, True, depth+1)
            output[key] = '#/x-mina-refs/'+references[identity]
        return output
    result = rewrite(root, base)
    if bundled: result['x-mina-refs'] = bundled
    return result


def media_schema(schemas, content_type):
    """Return the most specific OpenAPI media range and its schema."""
    media=str(content_type or '').split(';',1)[0].strip().lower()
    normalized={str(key).lower():value for key,value in schemas.items()}
    for key in (media,media.split('/')[0]+'/*' if '/' in media else '', '*/*'):
        if key and key in normalized:return key,normalized[key]
    return None,None

def media_name(value):
    return str(value or '').split(';', 1)[0].strip().lower()

def media_family(value):
    media = media_name(value)
    if media.endswith(('/xml', '+xml')):
        return 'xml'
    if media.endswith(('/json', '+json')):
        return 'json'
    return ''

def schema_for_media(schema, media, mixed):
    if schema is None or not mixed:
        return schema
    family = 'xml' if isinstance(schema, str) and schema.lstrip().startswith('<') else 'json'
    return schema if media_family(media) == family else None

def listener_media_types(config, key):
    values = config.get(key, [])
    if not isinstance(values, list):
        raise ValueError(f'{key} must be a list of media types')
    result = {}
    token = r"[A-Za-z0-9!#$%&'+.^_`|~-]+"
    for value in values:
        if not isinstance(value, str) or not re.fullmatch(token+'/'+token, media_name(value)) or any(ord(char) < 32 or ord(char) > 126 for char in value):
            raise ValueError(f'{key} must contain concrete media types such as application/json')
        result.setdefault(media_name(value), value.strip())
    return list(result.values())

def negotiate_media(available, accept):
    """Select by client quality, then specificity and configured server order."""
    if not available:
        return None
    if not accept:
        return available[0]
    if isinstance(accept, list):
        accept = ','.join(accept)
    ranges = []
    for item in accept.split(','):
        name, *params = item.lower().split(';')
        quality = 1.0
        for param in params:
            key, _, value = param.partition('=')
            if key.strip() == 'q':
                try:
                    quality = float(value)
                except ValueError:
                    quality = 0
                if not 0 <= quality <= 1:
                    quality = 0
                break
        ranges.append((name.strip(), quality))
    candidates = []
    for index, media in enumerate(available):
        name = media_name(media)
        masks = ('*/*', name.split('/')[0]+'/*', name)
        matches = [(masks.index(mask), quality) for mask, quality in ranges if mask in masks]
        specificity, quality = max(matches, default=(-1, 0))
        if quality:
            candidates.append((quality, specificity, -index, media))
    return max(candidates)[-1] if candidates else None

def request_schema(cfg,content_type):
    if cfg.get('requestContentTypes') and cfg.get('_restRequestSchemas'):
        return media_schema(cfg['_restRequestSchemas'],content_type)[1]
    if cfg.get('_explicitRequestSchema') or not cfg.get('_restRequestSchemas'):return cfg.get('requestSchema')
    return media_schema(cfg['_restRequestSchemas'],content_type)[1]

def response_content(cfg,status):
    content=cfg.get('_restResponseContentSchemas') or {}
    return content.get(str(status),content.get(str(status)[0]+'XX',content.get('default',{})))

def hosted_response_content(cfg, status):
    """Keep OpenAPI per-type schemas and apply standalone schemas to matching formats."""
    declared = response_content(cfg, status)
    selected = cfg.get('responseContentTypes') or []
    if not selected or not str(status).startswith('2'):
        return declared
    if declared:
        return {media: schema for media in selected for name, schema in [media_schema(declared, media)] if name is not None}
    schema = cfg.get('responseSchema')
    return {media: schema_for_media(schema, media, len(selected) > 1) for media in selected}

def response_schema(cfg, status, content_type=None):
    formats=response_content(cfg,status)
    if content_type is not None and formats:return media_schema(formats,content_type)[1]
    schemas = cfg.get('_restResponseSchemas') or {}
    return schemas.get(str(status), schemas.get(str(status)[0]+'XX', schemas.get('default',cfg.get('responseSchema'))))
