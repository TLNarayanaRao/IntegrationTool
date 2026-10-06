"""ASGI HTTP hosting shared by Direct and Engine exports."""
from __future__ import annotations
import asyncio, ipaddress, json, re, threading, urllib.parse
from concurrent.futures import ThreadPoolExecutor
from .http_transport import HTTPFault, authorize, boolean, number, tls_context, validate_authentication
from .rest_contract import operation_config, validate_parameters

def route_pattern(path):
    names=[];parts=[];start=0
    for match in re.finditer(r'\{([A-Za-z_][A-Za-z0-9_]*)\}',path):
        parts.append(re.escape(path[start:match.start()]));parts.append('([^/]+)');names.append(match[1]);start=match.end()
    parts.append(re.escape(path[start:]));return re.compile('^'+''.join(parts).rstrip('/')+'/?$'),names

def listener_config(connection,activity):
    cfg={**connection,**activity}
    original_operation=cfg.get('operation')
    try:cfg=operation_config({**cfg,'operation':'receiver'})
    except (ValueError,KeyError,TypeError) as error:raise HTTPFault('Invalid REST contract: '+str(error),'HTTP_CONFIGURATION',400) from None
    cfg['operation']=original_operation
    validate_authentication(cfg,server=True)
    if cfg.get('connectorMode')=='client':raise HTTPFault('Listener requires a server shared connection','HTTP_CONFIGURATION',400)
    path='/'+('/'.join((str(cfg.get('basePath') or '').strip('/'),str(cfg.get('path') or '/').strip('/')))).strip('/')
    cfg['path']=path
    minimum=int(number(cfg,'minimumQtpThreads',10,1,10000));maximum=int(number(cfg,'maximumQtpThreads',75,minimum,10000))
    number(cfg,'port',8080,1,65535);number(cfg,'maxRequestBodyBytes',64*1024**2,1);number(cfg,'maxHeaderBytes',65536,1024)
    if str(cfg.get('httpVersion') or '1.1')!='1.1':raise HTTPFault('Python HTTP listeners currently support HTTP/1.1; terminate HTTP/2 at a gateway','HTTP_CONFIGURATION',400)
    if str(cfg.get('authentication') or '').lower()=='certificate' and (not server_tls(cfg) or cfg.get('clientAuthentication')!='required'):raise HTTPFault('Certificate authentication requires HTTPS and required client certificates','HTTP_CONFIGURATION',400)
    return cfg

def server_tls(cfg):return boolean(cfg.get('tlsEnabled'),cfg.get('scheme')=='https') or boolean(cfg.get('confidentiality')) or boolean(cfg.get('defaultConfidentiality'))

class ListenerApp:
    def __init__(self,routes,handler,connection,verified_mtls=False,warm_workers=True):
        self.verified_mtls=verified_mtls
        self.routes=routes;self.handler=handler;self.connection=connection;maximum=int(number(connection,'maximumQtpThreads',75,1,10000))
        self.gate=asyncio.Semaphore(maximum);self.executor=ThreadPoolExecutor(max_workers=maximum,thread_name_prefix='mina-http')
        self.compiled=[(*route_pattern(cfg['path']),metadata,cfg) for metadata,cfg in routes]
        # Warm the minimum worker count for authentication/LDAP work.
        minimum=int(number(connection,'minimumQtpThreads',10,1,maximum)) if warm_workers else 0;ready=threading.Barrier(minimum+1)
        jobs=[self.executor.submit(ready.wait,10) for _ in range(minimum)];ready.wait(10)
        for job in jobs:job.result(10)
    async def __call__(self,scope,receive,send):
        if scope['type']=='lifespan':
            while True:
                event=await receive()
                if event['type']=='lifespan.startup':await send({'type':'lifespan.startup.complete'})
                elif event['type']=='lifespan.shutdown':self.executor.shutdown(wait=False,cancel_futures=True);await send({'type':'lifespan.shutdown.complete'});return
        if scope['type']!='http':return
        acquired=False;headers={k.decode('latin1').lower():v.decode('latin1') for k,v in scope.get('headers',[])}
        try:
            method=scope['method'];path=scope['path'];selected=None
            for pattern,names,metadata,cfg in self.compiled:
                match=pattern.match(path)
                methods=cfg.get('methods') or cfg.get('method') or 'POST';methods=methods if isinstance(methods,list) else str(methods).split(',')
                if match and method in {str(item).strip().upper() for item in methods}:selected=(metadata,cfg,dict(zip(names,match.groups())));break
            if not selected:raise HTTPFault('No matching listener','HTTP_NOT_FOUND',404)
            metadata,cfg,parameters=selected
            allowed=str(cfg.get('allowedIps') or '').replace(',',' ').split()
            if allowed:
                remote=scope.get('client',('',0))[0]
                if not any(ipaddress.ip_address(remote) in ipaddress.ip_network(item,strict=False) for item in allowed):raise HTTPFault('Access denied','HTTP_SECURITY',403)
            if sum(len(k)+len(v)+4 for k,v in scope['headers'])>number(cfg,'maxHeaderBytes',65536,1024):raise HTTPFault('HTTP headers too large','HTTP_BAD_REQUEST',431)
            await asyncio.wait_for(self.gate.acquire(),timeout=number(cfg,'queueTimeoutMs',30000,1)/1000);acquired=True
            chunks=[];size=0
            while True:
                event=await asyncio.wait_for(receive(),timeout=number(cfg,'readTimeoutMs',30000,1)/1000)
                if event['type']=='http.disconnect':return
                chunk=event.get('body',b'');size+=len(chunk)
                if size>number(cfg,'maxRequestBodyBytes',64*1024**2,1):raise HTTPFault('Request body too large','HTTP_BAD_REQUEST',413)
                chunks.append(chunk)
                if not event.get('more_body'):break
            raw=b''.join(chunks);target=(scope.get('raw_path') or path.encode()).decode('ascii')+('?' + scope['query_string'].decode('ascii') if scope.get('query_string') else '')
            claims=await asyncio.get_running_loop().run_in_executor(self.executor,lambda:authorize(cfg,method,target,headers,raw,self.verified_mtls))
            expected=str(cfg.get('contentType') or '').split(';')[0]
            if raw and expected and headers.get('content-type','').split(';')[0]!=expected:raise HTTPFault('Unsupported content type','REST_UNSUPPORTED_MEDIA',415)
            try:text=raw.decode(str(cfg.get('encoding') or 'utf-8'))
            except (UnicodeError,LookupError):raise HTTPFault('Invalid body encoding','HTTP_BAD_REQUEST',400)
            if 'json' in headers.get('content-type','') and raw:
                try:body=json.loads(text)
                except ValueError:raise HTTPFault('Invalid JSON body','HTTP_BAD_REQUEST',400)
            elif 'application/x-www-form-urlencoded' in headers.get('content-type',''):body=dict(urllib.parse.parse_qsl(text,keep_blank_values=True))
            else:body=text
            query=dict(urllib.parse.parse_qsl(scope.get('query_string',b'').decode(),keep_blank_values=True))
            errors=validate_parameters(cfg,parameters,query,headers,body if raw else None)
            if errors:raise HTTPFault('; '.join(errors),'REST_VALIDATION',400)
            if boolean(cfg.get('validateRequest'),bool(cfg.get('openApiDocument'))) and cfg.get('requestSchema'):
                from .mapper import validate_output
                if validate_output(body,cfg['requestSchema']):raise HTTPFault('Request schema validation failed','REST_VALIDATION',400)
            payload={'body':body,'headers':headers,'method':method,'path':path,'pathParameters':parameters,'query':query,'remote':scope.get('client'),'auth':claims}
            if cfg.get('operation')=='service':payload['envelope']=text
            output=await asyncio.wait_for(self.handler(metadata,payload),timeout=number(cfg,'activityTimeoutSeconds',180,1))
            response=output if isinstance(output,dict) and ('__httpResponse' in output or 'statusCode' in output or 'sent' in output) else {'body':output}
            status=int(response.get('statusCode',200));value=response.get('body',response)
            if not 200<=status<=599:raise HTTPFault('Invalid response status','HTTP_RESPONSE',500)
            schema=(cfg.get('_restResponseSchemas') or {}).get(str(status),cfg.get('responseSchema'))
            if boolean(cfg.get('validateResponse'),bool(cfg.get('openApiDocument'))) and schema:
                from .mapper import validate_output
                if validate_output(value,schema):raise HTTPFault('Response schema validation failed','REST_VALIDATION',500)
            response_headers={str(k):str(v) for k,v in (response.get('headers') or {}).items()}
            body=json.dumps(value,ensure_ascii=False).encode() if isinstance(value,(dict,list)) else ('' if value is None else str(value)).encode()
            response_headers.setdefault('Content-Type',str(cfg.get('responseType') or ('application/json' if isinstance(value,(dict,list)) else 'text/plain; charset=utf-8')))
            if method=='HEAD' or status in (204,304):body=b''
            if len(body)>number(cfg,'maxResponseBodyBytes',64*1024**2,1):raise HTTPFault('Response body too large','HTTP_BAD_RESPONSE',500)
            if not boolean(cfg.get('usePersistentConnections'),True):response_headers['Connection']='close'
            if any('\r' in k+v or '\n' in k+v for k,v in response_headers.items()):raise HTTPFault('Invalid response headers','HTTP_RESPONSE',500)
        except HTTPFault as error:
            status=error.status;body=json.dumps({'error':str(error)}).encode();response_headers={'Content-Type':'application/json'}
            if status==401:response_headers['WWW-Authenticate']='Basic realm="MINA"' if str(self.connection.get('authentication') or '').lower() in ('basic','ldap') else 'Bearer'
        except asyncio.TimeoutError:status=504;body=b'{"error":"HTTP execution or read timeout"}';response_headers={'Content-Type':'application/json'}
        except Exception:status=500;body=b'{"error":"HTTP request failed"}';response_headers={'Content-Type':'application/json'}
        finally:
            if acquired:self.gate.release()
        response_headers['Content-Length']=str(len(body))
        await send({'type':'http.response.start','status':status,'headers':[(k.encode('latin1'),v.encode('latin1')) for k,v in response_headers.items()]})
        await send({'type':'http.response.body','body':body})

async def serve(routes,handler,ready=None):
    import uvicorn
    grouped={}
    for metadata,connection,activity in routes:
        cfg=listener_config(connection,activity);key=(str(cfg.get('host') or '0.0.0.0'),int(number(cfg,'port',8080,1,65535)))
        grouped.setdefault(key,[]).append((metadata,cfg))
    servers=[];sockets=[];jobs=[]
    try:
        for (host,port),members in grouped.items():
            connection=members[0][1]
            transport_keys=('tlsEnabled','scheme','confidentiality','certificateFile','privateKeyFile','privateKeyPassword','identityStoreFile','identityStoreType','identityStorePassword','trustedCertificateFolder','trustStoreFile','trustStoreType','trustStorePassword','certificateAuthorityFile','tlsVersion','maximumTlsVersion','cipherSuites','clientAuthentication','maximumQtpThreads','minimumQtpThreads','acceptQueueSize','idleConnectionTimeoutMs','maxHeaderBytes')
            if any(any(cfg.get(key)!=connection.get(key) for key in transport_keys) for _,cfg in members):raise HTTPFault('Listeners on the same port must share the same transport configuration','HTTP_CONFIGURATION',400)
            route_methods=set()
            for _,cfg in members:
                methods=cfg.get('methods') or cfg.get('method') or 'POST';methods=methods if isinstance(methods,list) else str(methods).split(',')
                for method in methods:
                    identity=(re.sub(r'\{[^}]+\}','{}',cfg['path']).rstrip('/'),str(method).strip().upper())
                    if identity in route_methods:raise HTTPFault('Duplicate listener route and HTTP method','HTTP_CONFIGURATION',400)
                    route_methods.add(identity)
            app=ListenerApp(members,handler,connection,verified_mtls=server_tls(connection) and connection.get('clientAuthentication')=='required')
            options=uvicorn.Config(app,host=host,port=port,proxy_headers=False,server_header=False,backlog=int(number(connection,'acceptQueueSize',128,1,65535)),limit_concurrency=int(number(connection,'maximumQtpThreads',75,1,10000))+int(number(connection,'maxQueueSize',100,0,100000)),timeout_keep_alive=int(number(connection,'idleConnectionTimeoutMs',40000)/1000),h11_max_incomplete_event_size=int(number(connection,'maxHeaderBytes',65536,1024)),log_level='info')
            options.load()
            if server_tls(connection):options.ssl=tls_context(connection,server=True)
            import socket
            address=socket.getaddrinfo(host,port,type=socket.SOCK_STREAM,flags=socket.AI_PASSIVE)[0]
            sock=socket.socket(address[0],address[1],address[2]);sock.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1)
            try:sock.bind(address[4]);sock.listen(options.backlog);sock.setblocking(False)
            except Exception:sock.close();app.executor.shutdown(wait=False,cancel_futures=True);raise
            from contextlib import nullcontext
            class EmbeddedServer(uvicorn.Server):
                def capture_signals(self):return nullcontext()
            sockets.append(sock);server=EmbeddedServer(options);servers.append(server)
            jobs.append(asyncio.create_task(server.serve(sockets=[sock])))
        if ready is not None:
            while not all(server.started for server in servers):
                for job in jobs:
                    if job.done():await job
                await asyncio.sleep(.02)
            ready.set()
        await asyncio.gather(*jobs)
    finally:
        for server in servers:server.should_exit=True
        for job in jobs:
            if not job.done():job.cancel()
        await asyncio.gather(*jobs,return_exceptions=True)
        for server in servers:
            if server.started:
                try:await asyncio.wait_for(server.shutdown(),timeout=10)
                except Exception:pass
            server.config.app.executor.shutdown(wait=False,cancel_futures=True)
        for sock in sockets:sock.close()
