"""Loopback-only OAuth client-credentials/introspection fixture; not an identity provider."""
import base64,hmac,json,secrets,ssl,threading,time,urllib.parse
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
ROOT=Path(__file__).resolve().parent
CLIENT_ID='mina-demo-client';CLIENT_SECRET='mina-demo-client-secret'

def server(port=9444):
    tokens={};lock=threading.Lock()
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass # Never print credentials, form bodies or tokens.
        def reply(self,status,value):
            data=json.dumps(value).encode();self.send_response(status)
            self.send_header('Content-Type','application/json');self.send_header('Cache-Control','no-store');self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
        def do_POST(self):
            expected='Basic '+base64.b64encode((CLIENT_ID+':'+CLIENT_SECRET).encode()).decode()
            if not hmac.compare_digest(self.headers.get('Authorization',''),expected):return self.reply(401,{'error':'invalid_client'})
            try:size=int(self.headers.get('Content-Length','0'))
            except ValueError:return self.reply(400,{'error':'invalid_request'})
            if not 0<size<=65536:return self.reply(400,{'error':'invalid_request'})
            values=urllib.parse.parse_qs(self.rfile.read(size).decode(),keep_blank_values=True)
            if self.path=='/token':
                if values.get('grant_type')!=['client_credentials']:return self.reply(400,{'error':'unsupported_grant_type'})
                scope=values.get('scope',['orders.read'])[0]
                if any(item not in ('orders.read','profile') for item in scope.split()):return self.reply(400,{'error':'invalid_scope'})
                token=secrets.token_urlsafe(32);expiry=int(time.time())+300
                with lock:
                    for key in list(tokens):
                        if tokens[key]['exp']<=time.time():tokens.pop(key)
                    if len(tokens)>=1000:return self.reply(429,{'error':'fixture_capacity'})
                    tokens[token]={'active':True,'exp':expiry,'scope':scope,'client_id':CLIENT_ID,'sub':CLIENT_ID}
                return self.reply(200,{'access_token':token,'token_type':'Bearer','expires_in':300,'scope':scope})
            if self.path=='/introspect':
                with lock:claims=dict(tokens.get(values.get('token',[''])[0],{}))
                return self.reply(200,claims if claims.get('exp',0)>time.time() else {'active':False})
            self.reply(404,{'error':'not_found'})
    httpd=ThreadingHTTPServer(('127.0.0.1',port),Handler)
    context=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER);context.minimum_version=ssl.TLSVersion.TLSv1_2
    context.load_cert_chain(ROOT/'local/server-chain.pem',ROOT/'local/server-key.pem')
    httpd.socket=context.wrap_socket(httpd.socket,server_side=True)
    return httpd

if __name__=='__main__':
    with server() as httpd:
        print('MINA local OAuth fixture: https://localhost:9444/token and /introspect. Ctrl+C to stop.')
        try:httpd.serve_forever()
        except KeyboardInterrupt:pass
