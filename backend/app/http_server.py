"""ASGI HTTP hosting shared by Direct and Engine exports."""
from __future__ import annotations
import asyncio, ipaddress, json, re, threading, urllib.parse
from concurrent.futures import ThreadPoolExecutor
from .http_transport import HTTPFault, authorize, boolean, number, tls_context, validate_authentication
from .rest_contract import compatible_security, listener_parameters, operation_config
from .http_contracts import listener_media_types, media_name, media_schema, schema_for_media

def route_pattern(path):
    names=[];parts=[];start=0
    for match in re.finditer(r'\{([^\s/{}]+)\}',path):
        parts.append(re.escape(path[start:match.start()]));parts.append('([^/]+)');names.append(match[1]);start=match.end()
    parts.append(re.escape(path[start:]));return re.compile('^'+''.join(parts).rstrip('/')+'/?$'),names

def listener_config(connection,activity):
    cfg={**connection,**activity}
    original_operation=cfg.get('operation')
    configured_type = str(cfg.get('contentType') or '').strip()
    try:
        request_types = listener_media_types(cfg, 'requestContentTypes')
        response_types = listener_media_types(cfg, 'responseContentTypes')
        cfg=operation_config({**cfg,'operation':'receiver'})
    except (ValueError,KeyError,TypeError) as error:raise HTTPFault('Invalid REST contract: '+str(error),'HTTP_CONFIGURATION',400) from None
    cfg['operation']=original_operation
    cfg['_inboundHttp'] = True
    if request_types:
        cfg['requestContentTypes'] = request_types
        cfg['contentType'] = request_types[0]
        declared = cfg.get('_restRequestSchemas') or {}
        selected = {}
        for media in request_types:
            match, schema = media_schema(declared, media)
            if declared and match is None:
                raise HTTPFault(f'Request media type {media} is not declared by the OpenAPI operation', 'HTTP_CONFIGURATION', 400)
            if cfg.get('_explicitRequestSchema') or not declared:
                schema = schema_for_media(cfg.get('requestSchema'), media, len(request_types) > 1)
            selected[media_name(media)] = schema
        cfg['_restRequestSchemas'] = selected
    elif configured_type:
        cfg['contentType'] = configured_type
        formats = cfg.get('_restRequestSchemas')
        if formats:
            matched, schema = media_schema(formats, configured_type)
            if matched is None:
                raise HTTPFault('Configured request content type is not declared by the OpenAPI operation', 'HTTP_CONFIGURATION', 400)
            cfg['_restRequestSchemas'] = {media_name(configured_type): schema}
    if response_types:
        declared = [formats for code, formats in (cfg.get('_restResponseContentSchemas') or {}).items()
                    if code.startswith('2') and formats]
        for media in response_types:
            if declared and not any(media_schema(formats, media)[0] is not None for formats in declared):
                raise HTTPFault(f'Response media type {media} is not declared by the OpenAPI operation', 'HTTP_CONFIGURATION', 400)
        cfg['responseContentTypes'] = response_types
        cfg['responseType'] = response_types[0]
    validate_authentication(cfg,server=True)
    from .http_policy import validate_listener_policy
    validate_listener_policy(cfg)
    if cfg.get('connectorMode')=='client':raise HTTPFault('Listener requires a server shared connection','HTTP_CONFIGURATION',400)
    path='/'+('/'.join((str(cfg.get('basePath') or '').strip('/'),str(cfg.get('path') or '/').strip('/')))).strip('/')
    cfg['path']=path
    from .api_docs import methods_for
    methods = methods_for(cfg)
    if not methods or any(method not in {'GET','POST','PUT','PATCH','DELETE','HEAD','OPTIONS','TRACE'} for method in methods):
        raise HTTPFault('Select at least one supported HTTP method','HTTP_CONFIGURATION',400)
    cfg['methods'] = methods
    try:
        cfg['_restParameters'] = listener_parameters(cfg, route_pattern(path)[1])
        cfg['_restSecurityAlternatives'] = compatible_security(cfg)
    except (ValueError, KeyError, TypeError) as error:
        raise HTTPFault(str(error), 'HTTP_CONFIGURATION', 400) from None
    minimum=int(number(cfg,'minimumQtpThreads',10,1,10000));maximum=int(number(cfg,'maximumQtpThreads',75,minimum,10000))
    number(cfg,'port',8080,1,65535);number(cfg,'maxRequestBodyBytes',64*1024**2,1);number(cfg,'maxHeaderBytes',65536,1024)
    version = str(cfg.get('httpVersion') or '1.1')
    if version not in ('1.1','2','3'):
        raise HTTPFault('HTTP listener version must be 1.1, 2 or 3','HTTP_CONFIGURATION',400)
    if version in ('2', '3') and not server_tls(cfg):
        raise HTTPFault(f'Inbound HTTP/{version} requires HTTPS','HTTP_CONFIGURATION',400)
    if version == '3':
        if not cfg.get('certificateFile') or not cfg.get('privateKeyFile') or cfg.get('privateKeyPassword') or cfg.get('identityStoreFile'):
            raise HTTPFault('HTTP/3 requires a PEM certificate and an unencrypted PEM private key','HTTP_CONFIGURATION',400)
        if cfg.get('clientAuthentication') not in (None, '', 'none') or cfg.get('maximumTlsVersion') == 'TLSv1.2':
            raise HTTPFault('HTTP/3 requires TLS 1.3 and cannot use client certificates','HTTP_CONFIGURATION',400)
        if cfg.get('crlFile') or cfg.get('cipherSuites'):
            raise HTTPFault('HTTP/3 does not support custom CRLs or cipher suites','HTTP_CONFIGURATION',400)
    if str(cfg.get('authentication') or '').lower()=='certificate' and (not server_tls(cfg) or cfg.get('clientAuthentication')!='required'):raise HTTPFault('Certificate authentication requires HTTPS and required client certificates','HTTP_CONFIGURATION',400)
    if cfg.get('clientAuthentication') == 'required' and not server_tls(cfg):
        raise HTTPFault('Required client certificates need HTTPS','HTTP_CONFIGURATION',400)
    return cfg

def server_tls(cfg):return str(cfg.get('scheme') or '').lower()=='https' or boolean(cfg.get('tlsEnabled')) or boolean(cfg.get('confidentiality')) or boolean(cfg.get('defaultConfidentiality'))

class ListenerApp:
    def __init__(self,routes,handler,connection,verified_mtls=False,warm_workers=True):
        self.verified_mtls=verified_mtls
        from .api_docs import HostedAPIDocs
        self.docs=HostedAPIDocs(routes,connection)
        self.routes=routes;self.handler=handler;self.connection=connection;maximum=int(number(connection,'maximumQtpThreads',75,1,10000))
        self.gate=asyncio.Semaphore(maximum);self.queued=0;self.executor=ThreadPoolExecutor(max_workers=maximum,thread_name_prefix='mina-http')
        self.compiled=[(*route_pattern(cfg['path']),metadata,cfg) for metadata,cfg in sorted(routes,key=lambda item:('{' in item[1]['path'],-len(item[1]['path'])))]
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
        if await self.docs.handle({**scope,'_mina_verified_mtls':self.verified_mtls},send):return
        from .http_listener import handle_request
        await handle_request(self,scope,receive,send)

async def _serve_http1(routes,handler,ready=None):
    import uvicorn
    grouped={}
    for metadata,connection,activity in routes:
        cfg=listener_config(connection,activity);key=(str(cfg.get('host') or '0.0.0.0'),int(number(cfg,'port',8080,1,65535)))
        grouped.setdefault(key,[]).append((metadata,cfg))
    servers=[];sockets=[];jobs=[]
    try:
        for (host,port),members in grouped.items():
            connection=members[0][1]
            transport_keys=('tlsEnabled','scheme','confidentiality','defaultConfidentiality','certificateFile','privateKeyFile','privateKeyPassword','identityStoreFile','identityStoreType','identityStorePassword','trustedCertificateFolder','trustStoreFile','trustStoreType','trustStorePassword','certificateAuthorityFile','crlFile','tlsVersion','maximumTlsVersion','cipherSuites','clientAuthentication','maximumQtpThreads','minimumQtpThreads','maxQueueSize','acceptQueueSize','idleConnectionTimeoutMs','maxHeaderBytes')
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
            if any(location == 'query' for _, cfg in members
                   for _, _, keys in cfg.get('_restSecurityAlternatives', []) for _, location, _ in keys):
                options.access_log = False
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

async def serve(routes,handler,ready=None):
    """Select Uvicorn HTTP/1.1 or Hypercorn HTTP/2 and HTTP/3 per bind address."""
    groups={}
    for metadata,connection,activity in routes:
        cfg=listener_config(connection,activity)
        groups.setdefault((str(cfg.get('host') or '0.0.0.0'),int(cfg.get('port') or 8080)),[]).append((metadata,connection,activity,cfg))
    jobs=[];signals=[]
    try:
        for members in groups.values():
            versions={str(cfg.get('httpVersion') or '1.1') for _,_,_,cfg in members}
            if len(versions)!=1:raise HTTPFault('Listeners sharing a port must use the same HTTP version','HTTP_CONFIGURATION',400)
            signal=asyncio.Event();signals.append(signal)
            if versions & {'2', '3'}:
                from .http2_server import serve_http2
                job=serve_http2([(metadata,cfg) for metadata,_,_,cfg in members],handler,signal)
            else:job=_serve_http1([(metadata,connection,activity) for metadata,connection,activity,_ in members],handler,signal)
            jobs.append(asyncio.create_task(job))
        while not all(signal.is_set() for signal in signals):
            for job in jobs:
                if job.done():await job
            await asyncio.sleep(.01)
        if ready is not None:ready.set()
        await asyncio.gather(*jobs)
    finally:
        for job in jobs:
            if not job.done():job.cancel()
        await asyncio.gather(*jobs,return_exceptions=True)
