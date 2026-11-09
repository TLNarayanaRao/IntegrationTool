"""Protocol handling for dedicated listeners; shared by Studio and archives."""
from __future__ import annotations
import asyncio, base64, hashlib, ipaddress, json, tempfile, urllib.parse
from pathlib import Path
from xml.etree import ElementTree
from .http_contracts import (response_schema, schema_errors, request_schema, media_schema, response_content,
                             parse_json, hosted_response_content, media_family, negotiate_media)
from .http_messages import multi_values
from .http_policy import cors_headers, rate_limit
from .rest_contract import validate_parameters,typed_form_body

class HashedBody:
    def __init__(self,digest):self.sha256=digest


def mapped_xml_response(value, schema):
    """Render a mapped body whose top-level key names a global XSD element."""
    if not isinstance(value, dict) or len(value) != 1 or not isinstance(schema, str) or not schema.lstrip().startswith('<'):
        return None
    from .data_formats import DataFormats
    schema_namespace = '{http://www.w3.org/2001/XMLSchema}'
    try:
        document = ElementTree.fromstring(DataFormats.safe_xml(schema))
        if document.tag != schema_namespace + 'schema':
            return None
        name, payload = next(iter(value.items()))
        if not any(element.get('name') == name for element in document.findall(schema_namespace + 'element')):
            return None
        namespace = document.get('targetNamespace')
        if namespace and document.get('elementFormDefault') == 'qualified':
            if isinstance(payload, dict):
                content = dict(payload)
            elif payload is None:
                content = {}
            else:
                content = {'#text': str(payload).lower() if isinstance(payload, bool) else payload}
            content['@xmlns'] = namespace
            return DataFormats().render_xml(content, name)
        root = f'{{{namespace}}}{name}' if namespace else name
        return DataFormats().render_xml(payload, root)
    except (ElementTree.ParseError, ValueError, TypeError) as error:
        raise HTTPFault('Mapped XML response could not be rendered', 'HTTP_RESPONSE', 500) from error

async def handle_request(app,scope,receive,send):
    state={}
    try:await _handle_request(app,scope,receive,send,state)
    finally:
        if state.get('acquired'):app.gate.release()
        if state.get('admitted'):app.queued-=1
        if state.get('upload'):
            state['upload'].close();Path(state['upload'].name).unlink(missing_ok=True)

async def _handle_request(app,scope,receive,send,state):
    from .http_transport import HTTPFault, authorize, boolean, number
    acquired=False;upload=None;stream_path=None;cors={};extra={};response_headers={};method=scope['method'];status=500;body=b''
    pairs=[(k.decode('latin1').lower(),v.decode('latin1')) for k,v in scope.get('headers',[])]
    headers=multi_values(pairs)
    try:
        if any(isinstance(headers.get(key),list) for key in ('authorization','host','content-type','content-length','origin')):
            raise HTTPFault('Ambiguous HTTP headers','HTTP_BAD_REQUEST',400)
        if isinstance(headers.get('cookie'),list):headers['cookie']='; '.join(headers['cookie'])
        matches=[]
        for pattern,names,metadata,cfg in app.compiled:
            match=pattern.match(scope['path'])
            if match:
                methods=cfg.get('methods') or cfg.get('method') or 'POST'
                methods={str(item).strip().upper() for item in (methods if isinstance(methods,list) else str(methods).split(','))}
                if 'GET' in methods:methods.add('HEAD')
                matches.append((metadata,cfg,dict(zip(names,match.groups())),methods))
        if not matches:raise HTTPFault('No matching listener','HTTP_NOT_FOUND',404)
        allowed_methods=set().union(*(match[3] for match in matches));allowed_methods.add('OPTIONS')
        requested=headers.get('access-control-request-method') if method=='OPTIONS' else None
        selected=next((item for item in matches if (requested or method) in item[3]),None)
        if (requested or method)=='HEAD':
            # A declared HEAD operation overrides the automatic GET fallback.
            for item in matches:
                configured=item[1].get('methods') or item[1].get('method') or 'POST'
                declared=configured if isinstance(configured,list) else str(configured).split(',')
                if 'HEAD' in {str(value).strip().upper() for value in declared}:selected=item;break
        if selected is None and method!='OPTIONS':
            extra['Allow']=', '.join(sorted(allowed_methods));raise HTTPFault('Method not allowed','HTTP_METHOD_NOT_ALLOWED',405)
        metadata,cfg,parameters,methods=selected or matches[0]
        cors=cors_headers(cfg,headers,allowed_methods,preflight=bool(requested))
        allowed=str(cfg.get('allowedIps') or '').replace(',',' ').split()
        remote=(scope.get('client') or ('',0))[0]
        if allowed:
            try:permitted=any(ipaddress.ip_address(remote) in ipaddress.ip_network(item,strict=False) for item in allowed)
            except ValueError:permitted=False
            if not permitted:raise HTTPFault('Access denied','HTTP_SECURITY',403)
        if sum(len(k)+len(v)+4 for k,v in scope.get('headers',[]))>number(cfg,'maxHeaderBytes',65536,1024):raise HTTPFault('HTTP headers too large','HTTP_BAD_REQUEST',431)
        rate_limit(cfg,remote)
        if method=='OPTIONS' and (requested or selected is None):
            response_headers={'Allow':', '.join(sorted(allowed_methods)),**cors}
            await send({'type':'http.response.start','status':204,'headers':encoded_headers(response_headers)})
            await send({'type':'http.response.body','body':b''});return
        # Reserve bounded admission capacity before yielding to the event loop.
        capacity=int(number(app.connection,'maximumQtpThreads',75,1,10000))+int(number(app.connection,'maxQueueSize',100,0,100000))
        if app.queued>=capacity:
            error=HTTPFault('HTTP execution queue is full','HTTP_CAPACITY',503);error.headers={'Retry-After':'1'};raise error
        app.queued+=1;state['admitted']=True
        await asyncio.wait_for(app.gate.acquire(),number(cfg,'queueTimeoutMs',30000,1)/1000);acquired=True;state['acquired']=True
        file_mode=str(cfg.get('requestBodyMode') or 'memory')=='file'
        if file_mode:
            if not cfg.get('uploadDirectory'):raise HTTPFault('Upload directory is required for file-backed requests','HTTP_CONFIGURATION',400)
            if cfg.get('requestSchema') is not None and boolean(cfg.get('validateRequest'),bool(cfg.get('openApiDocument'))):raise HTTPFault('Use buffered mode for schema-validated request bodies','HTTP_CONFIGURATION',400)
            upload=tempfile.NamedTemporaryFile(prefix='mina-upload-',dir=Path(cfg['uploadDirectory']).expanduser(),delete=False)
            state['upload']=upload
        chunks=[];size=0;digest=hashlib.sha256()
        while True:
            event=await asyncio.wait_for(receive(),number(cfg,'readTimeoutMs',30000,1)/1000)
            if event['type']=='http.disconnect':return
            chunk=event.get('body',b'');size+=len(chunk)
            if size>number(cfg,'maxRequestBodyBytes',64*1024**2,1):raise HTTPFault('Request body too large','HTTP_BAD_REQUEST',413)
            digest.update(chunk)
            if upload:await asyncio.to_thread(upload.write,chunk)
            else:chunks.append(chunk)
            if not event.get('more_body'):break
        raw=b''.join(chunks)
        if upload:upload.close()
        target=(scope.get('raw_path') or scope['path'].encode()).decode('ascii')+('?' + scope['query_string'].decode('ascii') if scope.get('query_string') else '')
        claims=await asyncio.wait_for(asyncio.get_running_loop().run_in_executor(app.executor,lambda:authorize(cfg,method,target,headers,HashedBody(digest.hexdigest()) if upload else raw,app.verified_mtls)),number(cfg,'activityTimeoutSeconds',180,1))
        content_type=str(headers.get('content-type','')).split(';')[0].strip().lower();expected=str(cfg.get('contentType') or '').split(';')[0].strip().lower()
        formats=cfg.get('_restRequestSchemas') or {}
        if size and (media_schema(formats,content_type)[0] is None if formats else expected and content_type!=expected):raise HTTPFault('Unsupported content type','REST_UNSUPPORTED_MEDIA',415)
        textual=not content_type or content_type.startswith('text/') or content_type.endswith(('/json','+json','/xml','+xml')) or content_type=='application/x-www-form-urlencoded'
        text=''
        if textual and not upload:
            from email.message import Message
            mime=Message();mime['content-type']=str(headers.get('content-type',''))
            try:text=raw.decode(mime.get_content_charset() or str(cfg.get('encoding') or 'utf-8'))
            except (UnicodeError,LookupError):raise HTTPFault('Invalid body encoding','HTTP_BAD_REQUEST',400)
        if upload:body_value={'fileName':upload.name,'size':size}
        elif content_type.endswith(('/json','+json')) and raw:
            try:body_value=parse_json(text)
            except ValueError:raise HTTPFault('Invalid JSON body','HTTP_BAD_REQUEST',400)
        elif content_type=='application/x-www-form-urlencoded':body_value=multi_values(urllib.parse.parse_qsl(text,keep_blank_values=True))
        else:body_value=text if textual else raw
        try:body_value=typed_form_body(cfg,body_value,content_type)
        except (ValueError,TypeError,KeyError):raise HTTPFault('Form fields violate their declared types','REST_VALIDATION',400) from None
        query=multi_values(urllib.parse.parse_qsl(scope.get('query_string',b'').decode('utf-8'),keep_blank_values=True))
        errors=validate_parameters(cfg,parameters,query,headers,body_value if size else None)
        if errors:raise HTTPFault('; '.join(errors),'REST_VALIDATION',400)
        schema=request_schema(cfg,content_type)
        validate_request = boolean(cfg.get('validateRequest'), bool(cfg.get('openApiDocument')))
        if size and validate_request and schema is not None and schema_errors(body_value,schema):raise HTTPFault('Request schema validation failed','REST_VALIDATION',400)
        payload={'body':body_value,'headers':headers,'headerPairs':[{'name':k,'value':v} for k,v in pairs],'method':method,'path':scope['path'],'pathParameters':parameters,'query':query,'remote':scope.get('client'),'auth':claims}
        if size and not upload and (isinstance(schema, str) and schema.lstrip().startswith('<')
                                    or cfg.get('requestContentTypes') and media_family(content_type) == 'xml'):
            from .data_formats import DataFormats
            try:
                root = ElementTree.fromstring(DataFormats.safe_xml(raw))
                payload['xmlBody'] = {root.tag.rsplit('}', 1)[-1]: DataFormats.xml_element_value(root, local_names=True)}
            except (ElementTree.ParseError, ValueError, RecursionError) as error:
                if validate_request or cfg.get('requestContentTypes'):
                    raise HTTPFault('Could not map the XML request body', 'HTTP_BAD_REQUEST', 400) from error
        if not textual and not upload:payload['binaryContent']=base64.b64encode(raw).decode()
        if upload:payload.update(fileName=upload.name,size=size)
        if content_type.startswith('multipart/') and not upload:
            import httpx
            from .http_messages import response_tree
            payload['mimeEnvelopeElement']=response_tree(httpx.Response(200,headers=pairs),raw).get('mimeEnvelopeElement')
        if cfg.get('operation')=='service':payload['envelope']=text
        output=await asyncio.wait_for(app.handler(metadata,payload),number(cfg,'activityTimeoutSeconds',180,1))
        response=output if isinstance(output,dict) and any(key in output for key in ('__httpResponse','statusCode','sent','fileName','binaryContent')) else {'body':output}
        status=int(response.get('statusCode',200));value=response.get('body')
        if not 200<=status<=599:raise HTTPFault('Invalid response status','HTTP_RESPONSE',500)
        explicit_media = next((str(value) for key,value in (response.get('headers') or {}).items() if str(key).lower()=='content-type'), None)
        selected_media = cfg.get('responseContentTypes') or []
        offered = hosted_response_content(cfg, status)
        negotiated = len(selected_media) > 1 and str(status).startswith('2') and status not in (204, 205)
        if negotiated:
            available = list(offered)
            if not available:
                raise HTTPFault('No configured response content type is declared for this status','HTTP_RESPONSE',500)
            if explicit_media:
                if media_schema(offered, explicit_media)[0] is None:
                    raise HTTPFault('Response content type is not configured for this endpoint','HTTP_RESPONSE',500)
                available = [explicit_media]
            response_media = negotiate_media(available, headers.get('accept'))
            if not response_media:
                error = HTTPFault('None of the available response content types match Accept','HTTP_NOT_ACCEPTABLE',406)
                error.headers = {'Vary': 'Accept'}
                raise error
        else:
            response_media = explicit_media or str(cfg.get('responseType') or ('application/octet-stream' if response.get('fileName') or isinstance(value,(bytes,bytearray,memoryview)) else 'application/json' if isinstance(value,(dict,list,bool,int,float)) else 'text/plain; charset=utf-8'))
        match, schema = media_schema(offered, response_media) if selected_media else (None, None)
        if match is None:
            schema = response_schema(cfg,status,response_media)
        rendered_xml = None
        if status not in (204,304) and method != 'HEAD' and not response.get('fileName') and 'binaryContent' not in response:
            rendered_xml = mapped_xml_response(value, schema)
            if rendered_xml is None and selected_media and media_family(response_media) == 'xml' and value is not None:
                from .data_formats import DataFormats
                if isinstance(value, dict):
                    if len(value) != 1:
                        raise HTTPFault('Map one XML root element or provide an XML document','HTTP_RESPONSE',500)
                    root, content = next(iter(value.items()))
                    rendered_xml = DataFormats().render_xml(content, root)
                else:
                    try:
                        ElementTree.fromstring(DataFormats.safe_xml(value))
                    except (ElementTree.ParseError, ValueError, TypeError) as error:
                        raise HTTPFault('Response body is not an XML document','HTTP_RESPONSE',500) from error
            if rendered_xml is not None:
                value = rendered_xml
        if status not in (204,304) and method!='HEAD' and boolean(cfg.get('validateResponse'),bool(cfg.get('openApiDocument'))) and response_content(cfg,status) and media_schema(response_content(cfg,status),response_media)[0] is None:raise HTTPFault('Undeclared response content type','REST_VALIDATION',500)
        if response.get('fileName'):
            if schema is not None and boolean(cfg.get('validateResponse'),bool(cfg.get('openApiDocument'))):raise HTTPFault('File responses cannot bypass configured schema validation','REST_VALIDATION',500)
            stream_path=Path(response['fileName']).expanduser();size=stream_path.stat().st_size
        else:
            if 'binaryContent' in response:
                try:body=base64.b64decode(response['binaryContent'],validate=True)
                except Exception:raise HTTPFault('Invalid base64 response content','HTTP_RESPONSE',500) from None
                value=body
            elif isinstance(value,(bytes,bytearray,memoryview)):body=bytes(value)
            elif isinstance(value,(dict,list,bool,int,float)):body=json.dumps(value,ensure_ascii=False,allow_nan=False).encode()
            else:body=('' if value is None else str(value)).encode()
            if status not in (204,304) and method!='HEAD' and schema is not None and boolean(cfg.get('validateResponse'),bool(cfg.get('openApiDocument'))) and schema_errors(value,schema):raise HTTPFault('Response schema validation failed','REST_VALIDATION',500)
            size=len(body)
        if size>number(cfg,'maxResponseBodyBytes',64*1024**2,1):raise HTTPFault('Response body too large','HTTP_BAD_RESPONSE',500)
        response_headers={str(k).lower():v for k,v in (response.get('headers') or {}).items() if str(k).lower() not in ('content-length','transfer-encoding','connection')}
        if negotiated:
            vary = ', '.join(map(str, response_headers['vary'])) if isinstance(response_headers.get('vary'), list) else str(response_headers.get('vary') or '')
            if not {'accept', '*'}.intersection(item.strip().lower() for item in vary.split(',')):
                response_headers['vary'] = ', '.join(filter(None, (vary, 'Accept')))
        xml_response = rendered_xml is not None or (
            isinstance(schema, str) and schema.lstrip().startswith('<')
            and isinstance(value, str) and value.lstrip().startswith('<')
        )
        response_headers.setdefault('content-type',response_media if negotiated else str(cfg.get('responseType') or ('application/xml' if xml_response else 'application/octet-stream' if stream_path or isinstance(value,(bytes,bytearray,memoryview)) else 'application/json' if isinstance(value,(dict,list,bool,int,float)) else 'text/plain; charset=utf-8')))
        if not boolean(cfg.get('usePersistentConnections'),True) and scope.get('http_version')!='2':response_headers['connection']='close'
        response_headers['content-length']=str(0 if status in (204,304) else size)
        if method=='HEAD' or status in (204,304):body=b'';stream_path=None
        encoded_headers(response_headers)  # Validate before committing any response.
    except HTTPFault as error:
        status=error.status;body=json.dumps({'error':str(error)}).encode();stream_path=None;response_headers={'content-type':'application/json',**extra,**getattr(error,'headers',{})}
        if status==401:response_headers['WWW-Authenticate']='Basic realm="MINA"' if str((locals().get('cfg') or app.connection).get('authentication') or '').lower() in ('basic','ldap') else 'Bearer'
    except asyncio.TimeoutError:status=504;body=b'{"error":"HTTP execution or read timeout"}';stream_path=None;response_headers={'content-type':'application/json'}
    except Exception:
        import logging
        logging.getLogger('mina.http').exception('HTTP listener request failed')
        status=500;body=b'{"error":"HTTP request failed"}';stream_path=None;response_headers={'content-type':'application/json'}
    if 'Vary' in cors and any(key.lower() == 'vary' for key in response_headers):
        key = next(key for key in response_headers if key.lower() == 'vary')
        response_headers[key] = str(response_headers[key]) + ', ' + cors.pop('Vary')
    response_headers.update(cors)
    if 'content-length' not in response_headers:response_headers['content-length']=str(len(body))
    if status in (204,304):response_headers.pop('content-length',None)
    await send({'type':'http.response.start','status':status,'headers':encoded_headers(response_headers)})
    if stream_path:
        with stream_path.open('rb') as source:
            remaining=int(response_headers['content-length'])
            while remaining:
                chunk=await asyncio.to_thread(source.read,min(65536,remaining))
                if not chunk:raise RuntimeError('HTTP response file changed while streaming')
                remaining-=len(chunk)
                await asyncio.wait_for(send({'type':'http.response.body','body':chunk,'more_body':True}),number(cfg,'writeTimeoutMs',60000,1)/1000)
    await send({'type':'http.response.body','body':b'' if stream_path or method=='HEAD' else body})


def encoded_headers(headers):
    import re
    result=[]
    for key,value in headers.items():
        if not re.fullmatch(r"[!#$%&'*+.^_`|~0-9A-Za-z-]+",key):raise ValueError('Invalid HTTP header name')
        for item in value if isinstance(value,list) else [value]:
            text=str(item)
            if any(ord(char)<32 and char!='\t' or ord(char)==127 for char in text):raise ValueError('Invalid HTTP header value')
            result.append((key.lower().encode('ascii'),text.encode('latin1')))
    return result
