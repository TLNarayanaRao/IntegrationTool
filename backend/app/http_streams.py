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
