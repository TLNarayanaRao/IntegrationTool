"""Connection-local status-line extension for MINA's Uvicorn HTTP/1 listener.

h11 retains header validation and body framing; this extension validates the
reason phrase. HTTP/1.0 uses the same
length-delimited framing with Connection: close; only its serialized version
token differs. No global protocol tables or shared response state are patched.
"""
from __future__ import annotations
import h11
import re
from uvicorn.protocols.http.h11_impl import H11Protocol

EXTENSION='mina.http.response.status_line'


class StatusLineConnection(h11.Connection):
    response_line=None

    def send(self, event):
        if not isinstance(event,h11.Response):return super().send(event)
        settings=self.response_line or {};self.response_line=None
        version=settings.get('httpVersion','HTTP/1.1').removeprefix('HTTP/')
        if version not in ('1.0','1.1'):raise ValueError('HTTP/1 listener cannot switch to another HTTP protocol')
        reason=settings.get('reasonPhrase')
        if reason is not None and (not isinstance(reason,str) or not re.fullmatch(r'[\x20-\x7e\x80-\xff]*',reason)):
            raise ValueError('Invalid HTTP response reason phrase')
        headers=list(event.headers.raw_items())
        if version=='1.0':
            if any(name.lower()==b'transfer-encoding' for name,_ in headers):raise ValueError('HTTP/1.0 cannot use chunked transfer encoding')
            if event.status_code not in (204,304) and not any(name.lower()==b'content-length' for name,_ in headers):
                raise ValueError('HTTP/1.0 response requires Content-Length')
            headers=[(name,value) for name,value in headers if name.lower()!=b'connection']+[(b'connection',b'close')]
        event=h11.Response(status_code=event.status_code,headers=headers,
                           reason=event.reason if reason is None else reason.encode('latin1'))
        output=super().send(event)
        if version=='1.0':
            if not output.startswith(b'HTTP/1.1 '):raise RuntimeError('Unexpected HTTP/1 status serialization')
            output=b'HTTP/1.0 '+output[len(b'HTTP/1.1 '):]
        return output


class StatusLineProtocol(H11Protocol):
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        self.conn=StatusLineConnection(h11.SERVER,max_incomplete_event_size=self.config.h11_max_incomplete_event_size or 16384)
        application=self.app
        async def extended_app(scope,receive,send):
            scope={**scope,'extensions':{**scope.get('extensions',{}),EXTENSION:{'versions':['1.0','1.1'],'reason_phrase':True}}}
            async def extended_send(message):
                if message['type']=='http.response.start':self.conn.response_line=message.get(EXTENSION)
                await send(message)
            await application(scope,receive,extended_send)
        self.app=extended_app
