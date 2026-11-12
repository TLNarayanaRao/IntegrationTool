import asyncio
import socket
import ssl
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

import h11
import httpx
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from app.http1_protocol import StatusLineConnection
from app.http_listener import wire_status_line
from app.http_messages import response_message
from app.http_server import serve
from app.http_transport import HTTPFault


class WireStatusTests(unittest.TestCase):
    def connection(self):
        conn=StatusLineConnection(h11.SERVER)
        conn.receive_data(b'GET / HTTP/1.1\r\nHost: localhost\r\n\r\n')
        conn.next_event();conn.next_event()
        return conn

    def test_status_serialization_is_connection_local_and_preserves_framing(self):
        for version in ('1.0','1.1'):
            for phrase in ('','Mapped phrase','Cr\u00e9\u00e9'):
                conn=self.connection();conn.response_line={'httpVersion':'HTTP/'+version,'reasonPhrase':phrase}
                data=conn.send(h11.Response(status_code=201,headers=[(b'Content-Length',b'4'),(b'Set-Cookie',b'a=1'),(b'Set-Cookie',b'b=2')]))
                data+=conn.send(h11.Data(data=b'abcd'))+conn.send(h11.EndOfMessage())
                self.assertTrue(data.startswith(b'HTTP/'+version.encode()+b' 201 '+phrase.encode('latin1')+b'\r\n'))
                self.assertEqual(data.split(b'\r\n\r\n',1)[1],b'abcd')
                self.assertEqual(data.lower().count(b'set-cookie:'),2)
                if version=='1.0':self.assertIs(conn.our_state,h11.MUST_CLOSE)
                else:
                    conn.start_next_cycle();conn.receive_data(b'GET / HTTP/1.1\r\nHost: localhost\r\n\r\n');conn.next_event();conn.next_event()
                    self.assertTrue(conn.send(h11.Response(status_code=200,headers=[(b'Content-Length',b'0')],reason=b'OK')).startswith(b'HTTP/1.1 200 OK\r\n'))
        first=self.connection();second=self.connection();first.response_line={'reasonPhrase':'First only'}
        self.assertIn(b'First only',first.send(h11.Response(status_code=200,headers=[(b'Content-Length',b'0')],reason=b'OK')))
        self.assertNotIn(b'First only',second.send(h11.Response(status_code=200,headers=[(b'Content-Length',b'0')],reason=b'OK')))

    def test_injected_status_cannot_bypass_protocol_validation(self):
        for phrase in ('Bad\r\nInjected: yes','Bad\x00'):
            conn=self.connection();conn.response_line={'reasonPhrase':phrase}
            with self.assertRaises(ValueError):conn.send(h11.Response(status_code=200,headers=[(b'Content-Length',b'0')]))

    def test_http2_http3_and_external_asgi_capabilities_fail_explicitly(self):
        for version in ('2','3'):
            scope={'http_version':version}
            response=response_message({'HTTPHeaders':{'StatusLine':{'httpVersion':version,'reasonPhrase':''}}})
            self.assertEqual(wire_status_line(response,scope)['httpVersion'],'HTTP/'+version)
            for line in ({'httpVersion':'1.1'},{'httpVersion':version,'reasonPhrase':'Unsupported custom phrase'}):
                with self.subTest(version=version,line=line),self.assertRaises(HTTPFault):
                    wire_status_line(response_message({'HTTPHeaders':{'StatusLine':line}}),scope)
        for line in ({'httpVersion':'1.0'},{'reasonPhrase':'Needs native extension'}):
            with self.assertRaises(HTTPFault):wire_status_line(response_message({'HTTPHeaders':{'StatusLine':line}}),{'http_version':'1.1'})


class TLSWireStatusTests(unittest.IsolatedAsyncioTestCase):
    async def test_native_https1_and_negotiated_http2(self):
        key=rsa.generate_private_key(public_exponent=65537,key_size=2048)
        name=x509.Name([x509.NameAttribute(x509.oid.NameOID.COMMON_NAME,'localhost')]);now=datetime.now(timezone.utc)
        cert=(x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
              .serial_number(x509.random_serial_number()).not_valid_before(now-timedelta(days=1)).not_valid_after(now+timedelta(days=1))
              .add_extension(x509.SubjectAlternativeName([x509.DNSName('localhost')]),critical=False).sign(key,hashes.SHA256()))
        with tempfile.TemporaryDirectory() as folder:
            certfile=Path(folder)/'cert.pem';certfile.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
            keyfile=Path(folder)/'key.pem';keyfile.write_bytes(key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()))
            for protocol in ('1.1','2'):
                with socket.socket() as probe:probe.bind(('127.0.0.1',0));port=probe.getsockname()[1]
                cfg={'connectorMode':'server','httpVersion':protocol,'scheme':'https','host':'127.0.0.1','port':port,
                     'certificateFile':str(certfile),'privateKeyFile':str(keyfile),'minimumQtpThreads':1,'maximumQtpThreads':2}
                async def handle(_,payload):
                    line={'httpVersion':payload['headers'].get('x-version')}
                    if 'x-reason' in payload['headers']:line['reasonPhrase']=payload['headers']['x-reason']
                    return response_message({'body':'secure reply','HTTPHeaders':{'StatusLine':line}})
                ready=asyncio.Event();job=asyncio.create_task(serve([(None,cfg,{'path':'/','methods':'GET'})],handle,ready))
                try:
                    await asyncio.wait_for(ready.wait(),10)
                    context=ssl.create_default_context(cafile=str(certfile))
                    async with httpx.AsyncClient(http2=protocol=='2',verify=context,trust_env=False) as client:
                        url=f'https://localhost:{port}/'
                        if protocol=='1.1':
                            response=await client.get(url,headers={'X-Version':'1.0','X-Reason':'Secured custom reply'})
                            self.assertEqual((response.http_version,response.reason_phrase,response.text),('HTTP/1.0','Secured custom reply','secure reply'))
                            # Separate concurrent requests cannot share reason/version overrides.
                            replies=await asyncio.gather(*(client.get(url,headers={'X-Version':'1.1','X-Reason':f'Request-{index}'}) for index in range(8)))
                            self.assertEqual([reply.reason_phrase for reply in replies],[f'Request-{index}' for index in range(8)])
                            self.assertTrue(all(reply.http_version=='HTTP/1.1' for reply in replies))
                        else:
                            response=await client.get(url,headers={'X-Version':'2'})
                            self.assertEqual((response.status_code,response.http_version),(200,'HTTP/2'))
                            for headers in ({'X-Version':'1.0'},{'X-Version':'2','X-Reason':'Not available'}):
                                rejected=await client.get(url,headers=headers)
                                self.assertEqual(rejected.status_code,500,rejected.text)
                            empty=await client.get(url,headers={'X-Version':'2','X-Reason':''})
                            self.assertEqual(empty.status_code,200,empty.text)
                    if protocol=='2':
                        async with httpx.AsyncClient(http2=False,verify=context,trust_env=False) as client:
                            fallback=await client.get(url,headers={'X-Version':'1.1'})
                            self.assertEqual((fallback.status_code,fallback.http_version),(200,'HTTP/1.1'))
                            self.assertEqual((await client.get(url,headers={'X-Version':'1.1','X-Reason':'Unsupported fallback'})).status_code,500)
                finally:
                    job.cancel()
                    with self.assertRaises(asyncio.CancelledError):await job


if __name__=='__main__':unittest.main()
