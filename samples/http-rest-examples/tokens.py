"""Print short-lived local fixture tokens for Swagger/Postman testing."""
import argparse,base64,hashlib,hmac,json,ssl,time,urllib.parse,urllib.request
from pathlib import Path
ROOT=Path(__file__).resolve().parent

def token(kind):
    if kind=='jwt':
        def encode(value):return base64.urlsafe_b64encode(value).decode().rstrip('=')
        now=int(time.time());header=encode(json.dumps({'alg':'HS256','typ':'JWT'}).encode())
        body=encode(json.dumps({'sub':'sample-client','iss':'mina-demo','aud':'mina-sample-api','iat':now,'exp':now+300}).encode())
        data=header+'.'+body
        return data+'.'+encode(hmac.new(b'mina-demo-jwt-secret-at-least-32-characters',data.encode(),hashlib.sha256).digest())
    data=urllib.parse.urlencode({'grant_type':'client_credentials','scope':'orders.read'}).encode()
    auth=base64.b64encode(b'mina-demo-client:mina-demo-client-secret').decode()
    request=urllib.request.Request('https://localhost:9444/token',data=data,headers={'Authorization':'Basic '+auth,'Content-Type':'application/x-www-form-urlencoded'})
    context=ssl.create_default_context(cafile=str(ROOT/'local/trusted-roots/root.pem'))
    with urllib.request.urlopen(request,context=context,timeout=10) as response:return json.load(response)['access_token']

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('kind',choices=['oauth2','jwt']);args=parser.parse_args();print(token(args.kind))
