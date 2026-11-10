"""An HTTPX transport for direct HTTPS over QUIC."""
from __future__ import annotations

import asyncio
import ssl

import httpx


class HTTP3Transport(httpx.BaseTransport):
    def __init__(self, trust: ssl.SSLContext, max_request: int, max_response: int, timeout: float):
        self.ca_data = ''.join(ssl.DER_cert_to_PEM_cert(cert) for cert in trust.get_ca_certs(binary_form=True)).encode()
        self.max_request = max_request
        self.max_response = max_response
        self.timeout = timeout

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        if request.url.scheme != 'https':
            raise httpx.UnsupportedProtocol('HTTP/3 requires HTTPS', request=request)
        content = bytearray()
        for chunk in request.stream:
            if len(content) + len(chunk) > self.max_request:
                raise httpx.WriteError('HTTP/3 request exceeds its byte limit', request=request)
            content.extend(chunk)
        try:
            status, headers, body = asyncio.run(self.exchange(request, content))
        except TimeoutError as error:
            raise httpx.ReadTimeout('HTTP/3 request timed out', request=request) from error
        except (ConnectionError, OSError) as error:
            raise httpx.ConnectError('HTTP/3 connection failed', request=request) from error
        return httpx.Response(status, headers=headers, stream=httpx.ByteStream(body),
                              extensions={'http_version':b'HTTP/3'})

    async def exchange(self, request, content):
        from aioquic.asyncio import QuicConnectionProtocol, connect
        from aioquic.h3.connection import H3_ALPN, H3Connection
        from aioquic.h3.events import DataReceived, HeadersReceived
        from aioquic.quic.configuration import QuicConfiguration
        from aioquic.quic.events import ConnectionTerminated

        maximum = self.max_response
        result = asyncio.get_running_loop().create_future()

        class Protocol(QuicConnectionProtocol):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                self.http = H3Connection(self._quic, enable_webtransport=False)
                self.stream = None
                self.status = None
                self.headers = []
                self.content = bytearray()

            def quic_event_received(self, event):
                if result.done():
                    return
                if isinstance(event, ConnectionTerminated):
                    if self.stream is not None:
                        result.set_exception(ConnectionError('HTTP/3 connection closed before the response completed'))
                    return
                for message in self.http.handle_event(event):
                    if result.done() or getattr(message, 'stream_id', None) != self.stream:
                        continue
                    if isinstance(message, HeadersReceived):
                        status = next((value for name, value in message.headers if name == b':status'), None)
                        if status is not None and status.isdigit() and int(status) >= 200:
                            self.status = int(status)
                            self.headers = [(name, value) for name, value in message.headers if not name.startswith(b':')]
                    elif isinstance(message, DataReceived):
                        if len(self.content) + len(message.data) > maximum:
                            result.set_exception(httpx.ReadError('HTTP/3 response exceeds its byte limit', request=request))
                            continue
                        self.content.extend(message.data)
                    if isinstance(message, (HeadersReceived, DataReceived)) and message.stream_ended:
                        if self.status is None:
                            result.set_exception(httpx.RemoteProtocolError('HTTP/3 response has no final status', request=request))
                        else:
                            result.set_result((self.status, self.headers, bytes(self.content)))

        configuration = QuicConfiguration(is_client=True, alpn_protocols=H3_ALPN, cadata=self.ca_data)
        configuration.server_name = request.url.host
        omitted = {b'host', b'connection', b'proxy-connection', b'keep-alive', b'upgrade', b'transfer-encoding', b'accept-encoding'}
        headers = [(b':method', request.method.encode()), (b':scheme', b'https'),
                   (b':authority', request.url.netloc), (b':path', request.url.raw_path)]
        headers.extend((name.lower(), value) for name, value in request.headers.raw if name.lower() not in omitted)
        headers.append((b'accept-encoding', b'identity'))
        timeouts = request.extensions.get('timeout') or {}
        phase = sum(timeouts.get(name) or self.timeout for name in ('connect', 'read'))
        async with asyncio.timeout(min(self.timeout, phase)):
            async with connect(request.url.host, request.url.port or 443, configuration=configuration,
                               create_protocol=Protocol) as protocol:
                protocol.stream = protocol._quic.get_next_available_stream_id()
                protocol.http.send_headers(protocol.stream, headers, end_stream=not content)
                if content:
                    protocol.http.send_data(protocol.stream, bytes(content), end_stream=True)
                protocol.transmit()
                return await result
