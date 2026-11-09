"""TLS HTTP/2 host using Hypercorn's programmatic ASGI API."""
from __future__ import annotations
import asyncio

async def serve_http2(routes,handler,ready):
    from hypercorn.asyncio import serve
    from hypercorn.config import Config
    from .http_server import ListenerApp
    from .http_transport import tls_context, number, HTTPFault
    connection=routes[0][1]
    transport_keys=('host','port','httpVersion','scheme','tlsEnabled','defaultConfidentiality','confidentiality','certificateFile','privateKeyFile','privateKeyPassword','identityStoreFile','identityStoreType','identityStorePassword','trustStoreFile','trustStoreType','trustStorePassword','certificateAuthorityFile','trustedCertificateFolder','clientAuthentication','tlsVersion','maximumTlsVersion','cipherSuites','crlFile','maximumQtpThreads','minimumQtpThreads','maxQueueSize','maxHeaderBytes','acceptQueueSize','idleConnectionTimeoutMs','readTimeoutMs')
    if any(any(cfg.get(key)!=connection.get(key) for key in transport_keys) for _,cfg in routes):raise HTTPFault('HTTP/2 listeners sharing a port require the same transport configuration','HTTP_CONFIGURATION',400)
    identities=set()
    import re
    for _,cfg in routes:
        methods=cfg.get('methods') or cfg.get('method') or 'POST'
        for method in methods if isinstance(methods,list) else str(methods).split(','):
            identity=(re.sub(r'\{[^}]+\}','{}',cfg['path']).rstrip('/'),method.strip().upper())
            if identity in identities:raise HTTPFault('Duplicate listener route and HTTP method','HTTP_CONFIGURATION',400)
            identities.add(identity)
    context=tls_context(connection,server=True);context.set_alpn_protocols(['h2','http/1.1'])
    class HTTP2Config(Config):
        @property
        def ssl_enabled(self):return True
        def create_ssl_context(self):
            return context
        def create_sockets(self):
            sockets=super().create_sockets()
            for sock in sockets.secure_sockets:sock.listen(self.backlog)
            ready.set();return sockets
    config=HTTP2Config();host=str(connection.get('host') or '0.0.0.0');host='['+host+']' if ':' in host else host
    config.bind=[f"{host}:{int(connection.get('port') or 8080)}"]
    config.backlog=int(number(connection,'acceptQueueSize',128,1,65535))
    config.keep_alive_timeout=number(connection,'idleConnectionTimeoutMs',40000)/1000
    config.read_timeout=number(connection,'readTimeoutMs',30000,1)/1000
    config.h2_max_concurrent_streams=int(number(connection,'maximumQtpThreads',75,1,10000))+int(number(connection,'maxQueueSize',100,0,100000))
    config.h2_max_header_list_size=int(number(connection,'maxHeaderBytes',65536,1024))
    config.graceful_timeout=10;config.accesslog=None;config.errorlog=None
    app=ListenerApp(routes,handler,connection,verified_mtls=connection.get('clientAuthentication')=='required')
    stop=asyncio.Event()
    try:await serve(app,config,shutdown_trigger=stop.wait,mode='asgi')
    finally:app.executor.shutdown(wait=False,cancel_futures=True)
