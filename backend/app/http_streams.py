"""Replayable bounded file/MIME streams; no complete attachment buffering."""
from __future__ import annotations
import base64, json, uuid
from pathlib import Path
from email.message import Message
from email import policy
from .http_messages import header_values, repeating
import httpx

class ReplayStream(httpx.SyncByteStream):
    def __init__(self,factory):self.factory=factory
    def __iter__(self):yield from self.factory()

def file_chunks(path,limit):
    size=0
    with Path(path).expanduser().open('rb') as source:
        while True:
            chunk=source.read(65536)
            if not chunk:break
            size+=len(chunk)
            if size>limit:raise ValueError('HTTP file exceeds request size limit')
            yield chunk

def multipart_stream(envelope,limit,body=None,body_type='application/json'):
    boundary='mina-'+uuid.uuid4().hex
    mime_type=body_type.split(';',1)[0] if body_type.startswith('multipart/') else 'multipart/mixed'
    def produce():
        budget=[0,0]
        def bounded(chunks):
            for chunk in chunks:
                budget[1]+=len(chunk)
                if budget[1]>limit:raise ValueError('MIME request exceeds size limit')
                yield chunk
        def parts(node,boundary,depth=0,initial=None):
            if depth>8:raise ValueError('MIME nesting exceeds 8 levels')
            items=repeating(node.get('mimePart')) or []
            if isinstance(items,dict):items=[items]
            if not isinstance(items,list) or not items:raise ValueError('MIME envelope requires parts')
            if initial is not None:items=[{'textContent':initial,'mimeHeaders':{'content-type':body_type if not body_type.startswith('multipart/') else 'application/json'}},*items]
            for item in items:
                budget[0]+=1
                if budget[0]>256 or not isinstance(item,dict):raise ValueError('Invalid MIME parts or count exceeds 256')
                choices=[key for key in ('binaryContent','textContent','fileName','mimeEnvelopeElement') if item.get(key) is not None]
                if len(choices)!=1:raise ValueError('Each MIME part requires exactly one content choice')
                choice=choices[0];headers=header_values(item.get('mimeHeaders') or {})
                transfer=str(headers.pop('content-transfer-encoding','base64')).lower()
                message=Message(policy=policy.SMTP)
                if choice=='mimeEnvelopeElement':
                    import hashlib
                    nested='mina-'+hashlib.sha256((boundary+str(budget[0])).encode()).hexdigest()[:32];message['Content-Type']=f'multipart/mixed; boundary="{nested}"'
                    chunks=parts(item[choice],nested,depth+1)
                else:
                    message['Content-Type']=headers.pop('content-type','text/plain; charset=utf-8' if choice=='textContent' else 'application/octet-stream')
                    if choice=='fileName':chunks=file_chunks(item[choice],limit)
                    else:
                        value=item[choice]
                        if choice=='binaryContent':raw=bytes(value) if isinstance(value,(bytes,bytearray,list)) else base64.b64decode(str(value),validate=True)
                        elif isinstance(value,(dict,list,bool,int,float)):raw=json.dumps(value,ensure_ascii=False).encode()
                        else:raw=str(value).encode()
                        chunks=(raw[i:i+65536] for i in range(0,len(raw),65536))
                    if transfer=='base64':
                        def encode(source):
                            pending=b''
                            for chunk in source:
                                pending+=chunk;end=len(pending)//57*57
                                for offset in range(0,end,57):yield base64.b64encode(pending[offset:offset+57])+b'\r\n'
                                pending=pending[end:]
                            if pending:yield base64.b64encode(pending)+b'\r\n'
                        chunks=encode(chunks)
                    elif transfer not in ('binary','8bit','7bit'):raise ValueError('Streaming MIME supports base64, binary, 7bit or 8bit transfer encoding')
                    message['Content-Transfer-Encoding']=transfer
                for key,value in headers.items():
                    for text in value if isinstance(value,list) else [value]:message[key]=str(text)
                yield ('--'+boundary+'\r\n').encode()
                yield message.as_bytes().split(b'\r\n\r\n',1)[0]+b'\r\n\r\n'
                yield from chunks
                yield b'\r\n'
            yield ('--'+boundary+'--\r\n').encode()
        yield from bounded(parts(envelope,boundary,initial=body))
    return produce,f'{mime_type}; boundary="{boundary}"'
def read_sse(response, maximum_events, maximum_bytes, deadline):
    from itertools import chain
    import re
    import time
    from .http_transport import HTTPFault

    events, data = [], []
    event_type, event_id, retry = '', '', None
    pending = b''
    received = 0
    first = True
    for chunk in chain(response.iter_bytes(), (None,)):
        if chunk is None and not pending.endswith(b'\r'):
            break
        received += len(chunk or b'')
        if received > maximum_bytes:
            raise HTTPFault('SSE stream exceeds the response byte limit', 'HTTP_BAD_RESPONSE', 502)
        if time.monotonic() >= deadline:
            raise HTTPFault('SSE activity timed out', 'HTTP_TIMEOUT', 504)
        pending += chunk or b''
        # Defer a trailing CR until we know whether it starts CRLF.
        end = len(pending) - 1 if chunk is not None and pending.endswith(b'\r') else len(pending)
        start = 0
        for boundary in re.finditer(rb'\r\n|[\r\n]', pending[:end]):
            line = pending[start:boundary.start()].decode('utf-8-sig' if first else 'utf-8', errors='replace')
            first = False
            start = boundary.end()
            if not line:
                if data:
                    events.append({'event':event_type or 'message', 'data':'\n'.join(data), 'id':event_id, 'retryMs':retry})
                    if len(events) >= maximum_events:
                        return events
                data, event_type = [], ''
                continue
            name, _, value = line.partition(':')
            value = value.removeprefix(' ')
            if name == 'data':data.append(value)
            elif name == 'event':event_type = value
            elif name == 'id' and '\x00' not in value:event_id = value
            elif name == 'retry' and value.isascii() and value.isdecimal() and len(value) <= 10:retry = int(value)
        pending = pending[start:]
    return events


def websocket_exchange(cfg, url, headers):
    import base64
    import json
    import time
    import urllib.parse
    from websockets.exceptions import ConnectionClosedOK, WebSocketException
    from websockets.sync.client import connect
    from .http_transport import HTTPFault, jwt_token, number, secure_url, tls_context, validate_authentication

    parts = urllib.parse.urlsplit(url)
    if parts.scheme not in ('ws', 'wss'):
        raise HTTPFault('WebSocket URL must use ws or wss', 'HTTP_CONFIGURATION', 400)
    secure_url(urllib.parse.urlunsplit(parts._replace(scheme='https' if parts.scheme == 'wss' else 'http')), cfg)
    mode = str(cfg.get('authentication') or 'none').lower()
    if mode not in ('none', 'basic', 'bearer', 'jwt', 'certificate') or cfg.get('proxyUrl') or cfg.get('proxyHost'):
        raise HTTPFault('WebSocket exchange requires direct transport and a supported authentication mode', 'HTTP_CONFIGURATION', 400)
    validate_authentication(cfg)
    if mode == 'basic':
        headers['authorization'] = 'Basic ' + base64.b64encode(f"{cfg['username']}:{cfg['password']}".encode()).decode()
    elif mode in ('bearer', 'jwt'):
        headers['authorization'] = 'Bearer ' + (jwt_token(cfg) if mode == 'jwt' else str(cfg['bearerToken']))
    count = int(number(cfg, 'maxEvents', 1, 1, 1000))
    maximum = int(number(cfg, 'maxResponseBodyBytes', 64*1024**2, 1))
    outgoing = cfg.get('body')
    if outgoing is not None and not isinstance(outgoing, (str, bytes)):
        outgoing = json.dumps(outgoing, ensure_ascii=False, allow_nan=False)
    if outgoing is not None and len(outgoing.encode() if isinstance(outgoing, str) else outgoing) > number(cfg,'maxRequestBodyBytes',64*1024**2,1):
        raise HTTPFault('WebSocket message exceeds the request byte limit', 'HTTP_CONFIGURATION', 400)
    deadline = time.monotonic() + number(cfg, 'activityTimeoutSeconds', 30, 1)
    options = {'ssl':tls_context(cfg)} if parts.scheme == 'wss' else {}
    pairs = [(name, value) for name, values in headers.items() for value in (values if isinstance(values, list) else [values])]
    events, size = [], 0
    try:
        with connect(url, additional_headers=pairs, proxy=None, max_size=maximum,
                     open_timeout=max(.001, deadline - time.monotonic()), close_timeout=1, **options) as socket:
            if outgoing is not None:
                socket.send(outgoing)
            for _ in range(count):
                try:
                    value = socket.recv(timeout=max(0, deadline - time.monotonic()))
                except ConnectionClosedOK:
                    break
                size += len(value.encode() if isinstance(value, str) else value)
                if size > maximum:
                    raise HTTPFault('WebSocket messages exceed the response byte limit', 'HTTP_BAD_RESPONSE', 502)
                events.append({'type':'text','data':value} if isinstance(value, str)
                              else {'type':'binary','data':base64.b64encode(value).decode()})
    except TimeoutError:
        raise HTTPFault('WebSocket activity timed out', 'HTTP_TIMEOUT', 504) from None
    except (OSError, WebSocketException):
        raise HTTPFault('WebSocket exchange failed', 'HTTP_CONNECTIVITY', 502) from None
    return events
