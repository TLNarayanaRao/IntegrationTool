import os
import socket
import sys
from hmac import compare_digest
from app.library_overrides import activate, diagnostic
activate()
if __name__ == '__main__' and sys.argv[1:] == ['--mina-library-info']:
    diagnostic()
    raise SystemExit(0)

if __name__ == '__main__' and sys.argv[1:] == ['--mina-xslt-worker']:
    from app.mapper_xml import xslt_worker
    raise SystemExit(xslt_worker())

import uvicorn
from app.main import app
from starlette.responses import JSONResponse


class DesktopAccess:
    """Authorize desktop API requests on the host-wide loopback network."""

    header = b'x-mina-desktop-token'

    def __init__(self, app, token):
        self.app = app
        self.token = token.encode('ascii')

    async def __call__(self, scope, receive, send):
        if scope['type'] in ('http', 'websocket'):
            route = scope['path']
            if route == '/api' or route.startswith('/api/'):
                values = [value for key, value in scope['headers'] if key == self.header]
                if len(values) != 1 or not compare_digest(values[0], self.token):
                    if scope['type'] == 'websocket':
                        await send({'type': 'websocket.close', 'code': 1008})
                    else:
                        await JSONResponse({'detail': 'This runtime requires its Studio desktop session.'},
                                           status_code=403, headers={'Cache-Control': 'no-store'})(scope, receive, send)
                    return
                # Preview listeners expose application request headers to
                # mappings. Keep the desktop capability out of that payload.
                scope = {**scope, 'headers': [(key, value) for key, value in scope['headers'] if key != self.header]}
        await self.app(scope, receive, send)

if __name__ == '__main__':
    port = int(os.environ.get('MINA_PORT', '8787'))
    token = os.environ.pop('MINA_DESKTOP_TOKEN', '')
    if port == 0 and len(token) < 32:
        raise SystemExit('Dynamic desktop startup requires a per-launch token.')
    sidecar = DesktopAccess(app, token) if token else app
    config = uvicorn.Config(sidecar, host='127.0.0.1', port=port, proxy_headers=not token,
                            log_level=os.environ.get('MINA_LOG_LEVEL', 'warning'), access_log=not token,
                            timeout_keep_alive=30 if token else 5)
    if port:
        uvicorn.Server(config).run()
    else:
        # Keep ownership from selection through Uvicorn startup. Closing and
        # reopening a selected port races other logons on the same host.
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
            if hasattr(socket, 'SO_EXCLUSIVEADDRUSE'):
                listener.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            listener.bind(('127.0.0.1', 0))
            print(f'MINA_DESKTOP_PORT={listener.getsockname()[1]}', flush=True)
            uvicorn.Server(config).run(sockets=[listener])
