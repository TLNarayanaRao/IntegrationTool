"""Structured request inputs and MIME envelopes for HTTP and REST activities."""
from __future__ import annotations
import base64, json, re, urllib.parse, uuid
from email import policy, encoders
from email.message import Message
from email.parser import BytesParser
from pathlib import Path

STANDARD_HEADERS={'accept','content-type','accept-charset','accept-encoding','cookie','pragma'}


def response_message(config, default_body=None):
    """Normalize legacy and optional structured HTTP Send Response mappings."""
    headers={}
    def header(name,value):
        if not isinstance(name,str) or not re.fullmatch(r"[!#$%&'*+.^_`|~0-9A-Za-z-]+",name):
            raise ValueError('Invalid response header name')
        values=value if isinstance(value,list) else [value]
        if name.lower()=='content-type':
            if len(values)!=1:raise ValueError('Content-Type is a non-repeating response header')
            value=values[0]
        for item in values:
            if not isinstance(item,(str,int,float,bool)):raise ValueError('Response header values must be scalars')
            text=str(item)
            if any(ord(char)<32 and char!='\t' or ord(char)==127 for char in text):raise ValueError('Invalid response header value')
            try:text.encode('latin1')
            except UnicodeEncodeError:raise ValueError('Response header values must use HTTP Latin-1 encoding') from None
        headers[name.lower()]=[str(item) for item in values] if isinstance(value,list) else str(value)
    for name,value in object_value(config.get('headers'),'Response headers').items():header(name,value)
    if config.get('contentType'):header('content-type',config['contentType'])
    standard=object_value(config.get('HTTPHeaders'),'HTTPHeaders')
    if standard.get('Content-Type'):header('content-type',standard['Content-Type'])
    cookies=repeating(standard.get('Cookies'))
    if cookies not in (None,'',[]):header('set-cookie',cookies)
    status=config.get('statusCode',200)
    line=standard.get('StatusLine')
    status_line={}
    if isinstance(line,dict):
        if line.get('statusCode') not in (None,''):status=line['statusCode']
        version=line.get('httpVersion')
        if version not in (None,''):
            if not isinstance(version,str) or not re.fullmatch(r'(?:HTTP/)?(?:1\.[01]|2(?:\.0)?|3(?:\.0)?)',version):
                raise ValueError('StatusLine.httpVersion must be HTTP/1.0, HTTP/1.1, HTTP/2 or HTTP/3 (HTTP/ prefix optional)')
            status_line['httpVersion']=version if version.startswith('HTTP/') else 'HTTP/'+version
        phrase=line.get('reasonPhrase')
        if phrase is not None:
            if not isinstance(phrase,str) or not re.fullmatch(r'[\x20-\x7e\x80-\xff]*',phrase):
                raise ValueError('StatusLine.reasonPhrase must be a Latin-1 string without control characters')
            status_line['reasonPhrase']=phrase
    elif line not in (None,''):
        if not isinstance(line,str) or not re.fullmatch(r'(?:HTTP/(?:1\.[01]|2(?:\.0)?|3(?:\.0)?) )?[1-5][0-9]{2}(?: [\x20-\x7e\x80-\xff]*)?',line):
            raise ValueError('StatusLine must be an object or a legacy status such as HTTP/1.1 201 Created')
        status=line.split()[1 if line.startswith('HTTP/') else 0]
        parts=line.split(' ',2 if line.startswith('HTTP/') else 1)
        if line.startswith('HTTP/'):status_line['httpVersion']=parts.pop(0)
        if len(parts)>1:status_line['reasonPhrase']=parts[1]
    if isinstance(status,bool) or not re.fullmatch(r'[1-5][0-9]{2}',str(status)):
        raise ValueError('HTTP response status must be an integer from 100 to 599')
    dynamic=object_value(config.get('DynamicHTTPHeaders'),'DynamicHTTPHeaders')
    entries=repeating(dynamic.get('Headers')) or []
    if isinstance(entries,dict):entries=[entries]
    if not isinstance(entries,list):raise ValueError('DynamicHTTPHeaders.Headers must be repeating headerName/headerValue entries')
    seen=set()
    for entry in entries:
        if not isinstance(entry,dict):raise ValueError('Each response header must contain headerName and headerValue')
        name=entry.get('headerName');value=entry.get('headerValue')
        if name in (None,'') and value in (None,''):continue
        key=name.lower() if isinstance(name,str) else ''
        if key=='content-type' and key in seen:raise ValueError('Content-Type is a non-repeating response header')
        previous=headers.get(key)
        header(name,value)
        if key in seen or key=='set-cookie' and previous is not None:
            headers[key]=(previous if isinstance(previous,list) else [previous])+(headers[key] if isinstance(headers[key],list) else [headers[key]])
        seen.add(key)
    return {'statusCode':int(status),'headers':headers,'body':config.get('body',default_body),
            **({'statusLine':{**status_line,'statusCode':int(status)}} if isinstance(line,dict) or status_line else {}),
            **{key:config[key] for key in ('fileName','binaryContent','jsonValue') if config.get(key) is not None}}

def multi_values(pairs):
    result={}
    for key,value in pairs:
        if key not in result:result[key]=value
        elif isinstance(result[key],list):result[key].append(value)
        else:result[key]=[result[key],value]
    return result

def repeating(value):
    if isinstance(value,dict) and value and all(str(key).isdigit() for key in value):return [value[key] for key in sorted(value,key=lambda item:int(item))]
    return value

def object_value(value, label):
    if value in (None, ''):
        return {}
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            raise ValueError(f'{label} must be a JSON object') from None
    if not isinstance(value, dict):
        raise ValueError(f'{label} must be a JSON object')
    return value

def header_values(values):
    if not isinstance(values,dict):raise ValueError('Headers must be an object')
    result={str(key).lower():value for key,value in values.items() if key.lower()!='dynamicheaders'}
    dynamic=repeating(values.get('DynamicHeaders',values.get('dynamicHeaders',[]))) or []
    if isinstance(dynamic,dict):dynamic=[dynamic]
    if not isinstance(dynamic,list):raise ValueError('DynamicHeaders must be a repeating name/value structure')
    seen={}
    for item in dynamic:
        if not isinstance(item,dict):raise ValueError('Each dynamic header requires a name/value pair')
        name=str(item.get('name',item.get('Name','')));value=item.get('value',item.get('Value'))
        if not re.fullmatch(r"[!#$%&'*+.^_`|~0-9A-Za-z-]+",name) or value is None:raise ValueError('Each dynamic header requires a valid name and value')
        entries = value if isinstance(value, list) else [value]
        if any(not isinstance(entry, (str, int, float, bool)) for entry in entries):
            raise ValueError('Dynamic header values must be scalars or a list of scalars')
        key = name.lower()
        for entry in entries:
            text = str(entry)
            if not text.isascii() or '\r' in text or '\n' in text:
                raise ValueError('Dynamic header values must be US-ASCII without newlines')
            seen[key] = seen.get(key, 0) + 1
            if key in STANDARD_HEADERS and key != 'cookie' and seen[key] > 1:
                raise ValueError(f'Header {name} is non-repeating')
            if seen[key] == 1 and key != 'cookie':
                result[key] = text
            else:
                existing = result.get(key, [])
                result[key] = (existing if isinstance(existing, list) else [existing]) + [text]
    if isinstance(result.get('cookie'),list):result['cookie']='; '.join(str(value) for value in result['cookie'])
    return result

def request_config(cfg):
    root=cfg.get('RestInputRequest')
    if root is None:return cfg
    if not isinstance(root,dict):raise ValueError('RestInputRequest must be an object')
    result=dict(cfg);config=root.get('Config') or {}
    if not isinstance(config,dict):raise ValueError('RestInputRequest.Config must be an object')
    aliases={'host':'host','Host':'host','port':'port','Port':'port','scheme':'scheme','requestURI':'url','RequestURI':'url','Method':'method','method':'method','RequestBody':'body','PostData':'body','bodyFormat':'bodyType','URIParameters':'pathParameters','timeout':'socketTimeoutMs','Timeout':'socketTimeoutMs','activityTimeoutSeconds':'activityTimeoutSeconds','followRedirects':'followRedirects','sendBodyMode':'sendBodyMode','requestEntityProcessing':'requestEntityProcessing','successStatusCodes':'successStatusCodes','raiseForStatus':'raiseForStatus','FilePath':'body'}
    aliases.update({key:key for key in ('openApiDocument','openApiBaseUrl','openApiReferenceDocuments','openApiAllowedRefOrigins','operationId','validateRequest','requestSchema','validateResponse','responseSchema')})
    aliases.update({key:key for key in ('maxEvents','lastEventId','currentETag','currentLastModified','representationExists','requireWritePrecondition','multipartPartHeaders','callbackUrl')})
    for key,target in aliases.items():
        if key in config:result[target]=config[key]
    for key in ('streamRequest','responseFile','overwriteResponseFile','responseBodyMode'):
        if key in config:result[key]=config[key]
    if 'FilePath' in config:result['bodyType']='file'
    if 'PostData' in config and 'bodyFormat' not in config:result['bodyType']='text'
    if 'timeout' in config or 'Timeout' in config:result.pop('timeout',None)
    if 'QueryParameters' in config:
        result['query'] = {**object_value(result.get('query'), 'Default query'),
                           **object_value(config['QueryParameters'], 'Query parameters')}
    if 'QueryString' in config:
        result['query']={**object_value(result.get('query'), 'Query parameters'),**multi_values(urllib.parse.parse_qsl(str(config['QueryString'] or '').lstrip('?'),keep_blank_values=True))}
    if any(key in config for key in ('host','Host','port','Port','scheme')):
        base=urllib.parse.urlsplit(str(result.get('baseUrl') or result.get('url') or ''))
        host=str(config.get('host') or config.get('Host') or base.hostname or result.get('host') or 'localhost')
        port=config.get('port',config.get('Port',base.port or result.get('port')))
        if port is not None:
            if isinstance(port,bool) or not str(port).isdigit() or not 1<=int(port)<=65535:raise ValueError('Port must be an integer between 1 and 65535')
        scheme=str(config.get('scheme') or base.scheme or ('https' if str(result.get('tlsEnabled')).lower()=='true' else result.get('scheme') or 'http'))
        if ':' in host and not host.startswith('['):host='['+host+']'
        result['baseUrl']=f'{scheme}://{host}'+(f':{int(port)}' if port else '')+(base.path.rstrip('/') if cfg.get('baseUrl') else '')
        if 'requestURI' not in config and 'RequestURI' not in config and base.scheme:result['url']=base.path+('?' + base.query if base.query else '')
    if 'Headers' in root or 'CustomHeaders' in root:
        mapped_headers = root.get('Headers') or {}
        if 'CustomHeaders' in root:
            if not isinstance(mapped_headers, dict):
                raise ValueError('Headers must be an object')
            mapped_headers = {**mapped_headers, 'DynamicHeaders': root['CustomHeaders']}
        headers = {str(key).lower(): value for key, value in (result.get('headers') or {}).items()}
        headers.update(header_values(mapped_headers))
        result['headers'] = headers
        # Explicit mapped headers take precedence over inherited shorthand settings.
        for key in ('accept','contentType'):
            if ('content-type' if key=='contentType' else key) in headers:result.pop(key,None)
    if root.get('mimeEnvelopeElement') is not None:result['_mimeEnvelope']=root['mimeEnvelopeElement']
    result['_structuredRequest']=True
    return result

def mime_message(envelope,limit,depth=0,budget=None):
    if depth>8:raise ValueError('MIME nesting exceeds 8 levels')
    if not isinstance(envelope,dict):raise ValueError('mimeEnvelopeElement must be an object')
    budget=budget if budget is not None else [0,0]
    parts=repeating(envelope.get('mimePart')) or []
    if isinstance(parts,dict):parts=[parts]
    if not isinstance(parts,list) or not parts:raise ValueError('mimeEnvelopeElement requires at least one mimePart')
    message=Message(policy=policy.SMTP);message.set_type('multipart/mixed');message.set_boundary('mina-'+uuid.uuid4().hex)
    for part in parts:
        budget[0]+=1
        if budget[0]>256 or not isinstance(part,dict):raise ValueError('MIME envelope requires valid parts (maximum 256)')
        alternatives=[key for key in ('binaryContent','textContent','fileName','mimeEnvelopeElement') if key in part and part[key] is not None]
        if len(alternatives)!=1:raise ValueError('Each mimePart requires exactly one of binaryContent, textContent, fileName or mimeEnvelopeElement')
        choice=alternatives[0];headers=header_values(part.get('mimeHeaders') or {})
        if choice=='mimeEnvelopeElement':child=mime_message(part[choice],limit,depth+1,budget)
        else:
            value=part[choice]
            if choice=='fileName':
                with Path(str(value)).expanduser().open('rb') as source:raw=source.read(limit+1)
            elif choice=='binaryContent':raw=bytes(value) if isinstance(value,(bytes,bytearray,list)) else base64.b64decode(str(value),validate=True)
            else:raw=str(value).encode('utf-8')
            budget[1]+=len(raw)
            if budget[1]>limit:raise ValueError('MIME attachment body limit exceeded')
            child=Message(policy=policy.SMTP);child.set_type(str(headers.pop('content-type','text/plain; charset=utf-8' if choice=='textContent' else 'application/octet-stream')));child.set_payload(raw)
            transfer=str(headers.pop('content-transfer-encoding','base64')).lower()
            if transfer=='base64':encoders.encode_base64(child)
            elif transfer=='quoted-printable':encoders.encode_quopri(child)
            elif transfer in ('binary','8bit','7bit'):child['Content-Transfer-Encoding']=transfer
            else:raise ValueError('Unsupported MIME content-transfer-encoding')
        for key,value in headers.items():
            if '\r' in key+str(value) or '\n' in key+str(value):raise ValueError('Invalid MIME header')
            for text in value if isinstance(value,list) else [value]:child[key]=str(text)
        message.attach(child)
    return message

def mime_body(envelope,limit,body=None,body_type='application/json'):
    message=mime_message(envelope,limit)
    if body_type.lower().startswith('multipart/'):
        message.set_type(body_type.split(';',1)[0]);body_type='application/json'
    if body is not None:
        part=Message(policy=policy.SMTP);part.set_type(body_type);part.set_payload(bytes(body) if isinstance(body,(bytes,bytearray)) else json.dumps(body).encode() if isinstance(body,(dict,list,bool,int,float)) else str(body).encode());encoders.encode_base64(part);message.set_payload([part,*message.get_payload()])
    raw=message.as_bytes().split(b'\r\n\r\n',1)[1]
    if len(raw)>limit:raise ValueError('MIME request body limit exceeded')
    return raw,message['Content-Type']

def parse_mime_entity(content_type, raw):
    return BytesParser(policy=policy.default).parsebytes(
        ('Content-Type: ' + content_type + '\r\nMIME-Version: 1.0\r\n\r\n').encode() + raw
    )


def response_tree(response,raw,*,mime=None):
    headers=response.headers;group={key.lower():headers.get_list(key) if len(headers.get_list(key))>1 else value for key,value in headers.items()}
    for name in ('Allow','Content-Type','Content-Length','Content-Encoding','Date','Location','Set-Cookie','Pragma'):
        if name.lower() in group:group[name]=headers.get_list(name) if name in ('Allow','Set-Cookie') else group[name.lower()]
    group['DynamicHeaders']=[{'name':key,'value':value} for key,value in headers.multi_items()]
    result={'statusLine':{'httpVersion':response.http_version,'statusCode':response.status_code,'reasonPhrase':response.reason_phrase},'Headers':group,'body':None,'asciiContent':raw.decode(response.encoding or 'utf-8',errors='replace'),'binaryContent':base64.b64encode(raw).decode()}
    if 'multipart/' in headers.get('content-type','').lower():
        message=mime if mime is not None else parse_mime_entity(headers['content-type'],raw);count=[0]
        def unpack(message,depth=0):
            if depth>8:raise ValueError('MIME response nesting exceeds 8 levels')
            parts=[]
            for part in message.iter_parts():
                count[0]+=1
                if count[0]>256:raise ValueError('MIME response exceeds 256 parts')
                value={'mimeHeaders':{key.lower():value for key,value in part.items()}}
                if part.is_multipart():value['mimeEnvelopeElement']=unpack(part,depth+1)
                else:
                    payload=part.get_payload(decode=True) or b''
                    if part.get_content_maintype()=='text':value['textContent']=payload.decode(part.get_content_charset() or 'utf-8',errors='replace')
                    else:value['binaryContent']=base64.b64encode(payload).decode()
                parts.append(value)
            return {'mimePart':parts}
        result['mimeEnvelopeElement']=unpack(message)
    return result
