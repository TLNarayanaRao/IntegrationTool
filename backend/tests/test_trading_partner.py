import base64
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import os
from pathlib import Path
import ssl
import tempfile
import threading
import unittest
from unittest.mock import patch

from app import edi, trading_partner


ISA = 'ISA*00*          *00*          *ZZ*SENDER         *ZZ*RECEIVER       *250101*1230*U*00401*000000001*0*T*>~'
X12 = ISA + 'GS*PO*SENDER*RECEIVER*20250101*1230*1*X*004010~ST*850*0001~BEG*00*NE*TEST-1~SE*3*0001~GE*1*1~IEA*1*000000001~'
EDIFACT = "UNA:+.? 'UNB+UNOC:3+SENDER+RECEIVER+250101:1230+1'UNH+1+ORDERS:D:96A:UN'FTX+AAI+++A?+B?'C'UNT+3+1'UNZ+1+1'"


def identity(folder, name, *, issuer=None, ca=False, tls_server=False):
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from ipaddress import ip_address
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = x509.Name([x509.NameAttribute(x509.NameOID.COMMON_NAME, name)])
    now = datetime.now(timezone.utc)
    issuer_cert, issuer_key = (x509.load_pem_x509_certificate(Path(issuer[0]).read_bytes()),
                              serialization.load_pem_private_key(Path(issuer[1]).read_bytes(), password=None)) if issuer else (None, key)
    certificate = (x509.CertificateBuilder().subject_name(subject).issuer_name(issuer_cert.subject if issuer_cert else subject)
                   .public_key(key.public_key()).serial_number(x509.random_serial_number())
                   .not_valid_before(now - timedelta(days=1)).not_valid_after(now + timedelta(days=1)))
    if ca or issuer:
        certificate = (certificate.add_extension(x509.BasicConstraints(ca=ca, path_length=None), critical=True)
                       .add_extension(x509.KeyUsage(True, False, True, False, False, ca, ca, None, None), critical=True)
                       .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False)
                       .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(issuer_key.public_key()), critical=False))
    if tls_server:
        certificate = certificate.add_extension(x509.SubjectAlternativeName([x509.IPAddress(ip_address('127.0.0.1'))]), critical=False)
    certificate = certificate.sign(issuer_key, hashes.SHA256())
    private_path = Path(folder) / f'{name}-key.pem'
    certificate_path = Path(folder) / f'{name}-cert.pem'
    private_path.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    certificate_path.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
    return str(certificate_path), str(private_path)


class TradingPartnerTests(unittest.TestCase):
    def test_parse_render_counts_and_partner_rules(self):
        for format_name, original, txn in (('x12', X12, '850'), ('edifact', EDIFACT, 'ORDERS')):
            parsed = edi.parse(original, format_name, allowed_types=[txn])
            self.assertEqual(parsed['transactions'][0]['type'], txn)
            self.assertEqual(edi.render(parsed)['text'], original)
        with self.assertRaisesRegex(ValueError, 'count'):
            edi.parse(X12.replace('SE*3', 'SE*9'))
        with self.assertRaisesRegex(ValueError, 'control reference'):
            edi.parse(EDIFACT.replace("UNT+3+1'", "UNT+3+2'"))
        with self.assertRaisesRegex(ValueError, 'required segments'):
            edi.parse(X12, rules={'850': {'requiredSegments': ['PO1']}})

    def test_as2_documents_authentication_and_retry_in_run_debug_and_both_python_formats(self):
        from tests.test_python_mapper_parity import PythonMapperParityTests
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {'MINA_AS2_LEDGER_FILE': str(Path(folder) / 'ledger.sqlite3')}):
            a_cert, a_key = identity(folder, 'sender')
            b_cert, b_key = identity(folder, 'receiver')
            ca = identity(folder, 'tls-ca', ca=True)
            server_cert, server_key = identity(folder, 'tls-server', issuer=ca, tls_server=True)
            client_cert, client_key = identity(folder, 'tls-client', issuer=ca)
            inbound = {'localAs2Id': 'Receiver', 'partnerAs2Id': 'Sender', 'localCertificateFile': b_cert,
                       'localPrivateKeyFile': b_key, 'partnerCertificateFile': a_cert, 'ediFormat': 'x12'}
            outbound = {'localAs2Id': 'Sender', 'partnerAs2Id': 'Receiver', 'localCertificateFile': a_cert,
                        'localPrivateKeyFile': a_key, 'partnerCertificateFile': b_cert, 'receiptAddress': 'test@example.invalid',
                        'compressOutbound': True, 'tlsCaFile': ca[0], 'as2TlsClientCertFile': client_cert,
                        'as2TlsClientKeyFile': client_key, 'as2HttpUsername': 'qa', 'as2HttpPassword': 'fixture-only',
                        'as2ResponseRetries': '1'}
            trading_partner.validate_profile(inbound)
            received = []
            failures = []
            attempts = []
            rejected_auth = []
            drop_response = [True]

            class Receiver(BaseHTTPRequestHandler):
                def do_POST(self):
                    try:
                        assert self.connection.getpeercert()['subject'] == ((('commonName', 'tls-client'),),)
                        if self.headers.get('Authorization') != 'Basic ' + base64.b64encode(b'qa:fixture-only').decode():
                            rejected_auth.append(True)
                            self.send_error(401)
                            return
                        wire = self.rfile.read(int(self.headers['Content-Length']))
                        attempts.append((self.headers['Message-ID'], self.headers['Date'], self.headers['Content-Type'], wire))
                        request = {'headers': dict(self.headers), 'binaryContent': base64.b64encode(wire).decode()}
                        delivery = trading_partner.execute('as2_receive', {}, request, 'receiver', inbound)
                        if not delivery['duplicate']:
                            content = delivery.get('text')
                            if 'binaryContent' in delivery:
                                assert delivery['contentType'] == inbound['as2PayloadMediaType']
                                content = base64.b64decode(delivery['binaryContent'])
                            received.append((delivery['messageId'], content))
                            if delivery.get('status') != 'rejected':
                                delivery = trading_partner.execute('as2_receipt', delivery, None, 'receiver', inbound)
                        if drop_response:
                            drop_response.pop()
                            self.close_connection = True
                            return
                        self.send_response(200)
                        response = delivery['receipt']
                        for key, value in response['headers'].items():
                            self.send_header(key, value)
                        body = base64.b64decode(response['binaryContent'])
                        self.send_header('Content-Length', str(len(body)))
                        self.end_headers()
                        self.wfile.write(body)
                    except Exception as error:
                        failures.append(error)
                        self.send_error(500)

                def log_message(self, *_args):
                    pass

            with ThreadingHTTPServer(('127.0.0.1', 0), Receiver) as server:
                context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
                context.load_cert_chain(server_cert, server_key)
                context.load_verify_locations(cafile=ca[0])
                context.verify_mode = ssl.CERT_REQUIRED
                server.socket = context.wrap_socket(server.socket, server_side=True)
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()
                try:
                    outbound['endpointUrl'] = f'https://127.0.0.1:{server.server_port}/as2'
                    trading_partner.validate_profile(outbound)
                    with self.assertRaisesRegex(ValueError, 'requires both'):
                        trading_partner.validate_profile({**outbound, 'as2TlsClientKeyFile': ''})
                    with self.assertRaisesRegex(ValueError, 'HTTPS delivery failed'):
                        trading_partner._post({**outbound, 'as2TlsClientCertFile': '', 'as2TlsClientKeyFile': ''}, {}, b'')
                    with self.assertRaisesRegex(ValueError, 'HTTP 401'):
                        trading_partner._post({**outbound, 'as2HttpPassword': 'wrong'}, {}, b'')
                    self.assertEqual(len(rejected_auth), 1)
                    parity = PythonMapperParityTests()
                    project = parity.project()
                    project['resources'].append(dict(id='partner', name='Partner', type='trading_partner', config=outbound))
                    task = project['tasks'][0]
                    task['activities'][1:1] = [dict(id='Send', name='Send', type='basic', config={
                        'operation': 'as2_send', 'resourceId': 'partner', 'payload': '${input.edi}'
                    })]
                    task['activities'][-1]['config'] = {'inputMappings': {
                        'accepted': '${last.accepted}', 'status': '${last.status}', 'controlNumber': '${last.controlNumber}'
                    }}
                    task['transitions'] = [dict(id='t1', source='Start', target='Send'), dict(id='t2', source='Send', target='End')]
                    expected = {'accepted': True, 'status': 'processed', 'controlNumber': '000000001'}
                    try:
                        parity.assert_studio(project, {'edi': X12}, expected)
                        parity.assert_exports(project, {'edi': X12}, expected)
                    except AssertionError:
                        if failures:
                            raise failures[0]
                        raise
                    self.assertFalse(failures)
                    self.assertEqual([item[1] for item in received], [X12] * 5)
                    self.assertEqual(len(attempts), 6)
                    self.assertEqual(attempts[0], attempts[1])
                    message_id = received[0][0]
                    self.assertEqual(trading_partner.execute('as2_lookup', {'messageId': message_id, 'direction': 'outbound'},
                                                             None, 'partner', outbound)['status'], 'processed')
                    inbound.update(rejectInvalidEdiWithMdn=True, allowedTransactionTypes='860')
                    rejection = trading_partner.execute('as2_send', {}, X12, 'partner', outbound)
                    self.assertEqual((rejection['status'], rejection['accepted'], rejection['receiptMicVerified']), ('rejected', False, True))
                    self.assertIsNone(received[-1][1])
                    inbound['as2PayloadMediaType'] = outbound['as2PayloadMediaType'] = 'application/xml'
                    xml = '<?xml version="1.0" encoding="utf-8"?><order>café</order>'
                    expected['controlNumber'] = ''
                    parity.assert_studio(project, {'edi': xml}, expected)
                    parity.assert_exports(project, {'edi': xml}, expected)
                    self.assertEqual([item[1] for item in received[-5:]], [xml.encode('utf-8')] * 5)
                    inbound['as2PayloadMediaType'] = outbound['as2PayloadMediaType'] = 'application/octet-stream'
                    binary = b'\xff\x00\r\n\x80'
                    result = trading_partner.execute('as2_send', {'contentBase64': base64.b64encode(binary).decode()}, None, 'partner', outbound)
                    self.assertTrue(result['accepted'])
                    self.assertEqual(received[-1][1], binary)
                    inbound['as2PayloadMediaType'] = 'application/json'
                    self.assertEqual(trading_partner.execute('as2_send', {}, 'bytes', 'partner', outbound)['status'], 'rejected')
                    self.assertFalse(failures)
                    with self.assertRaisesRegex(ValueError, 'requires HTTPS'):
                        trading_partner.validate_profile({**outbound, 'endpointUrl': 'http://127.0.0.1:9999', 'allowLoopbackHttp': True})
                finally:
                    server.shutdown()
                    thread.join(timeout=5)

    def test_tampered_content_and_wrong_partner_signatures_are_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            certificate, key = identity(folder, 'sender')
            other, _ = identity(folder, 'other')
            profile = {'localCertificateFile': certificate, 'localPrivateKeyFile': key, 'partnerCertificateFile': certificate}
            entity = trading_partner._entity('application/edi-x12', X12.encode('ascii'))
            content_type, wire = trading_partner._signed(entity, profile)
            self.assertEqual(trading_partner._verified(content_type, wire, profile), entity)
            with self.assertRaisesRegex(ValueError, 'digest'):
                trading_partner._verified(content_type, wire.replace(b'TEST-1', b'TEST-2'), profile)
            with self.assertRaisesRegex(ValueError, 'signer'):
                trading_partner._verified(content_type, wire, {**profile, 'partnerCertificateFile': other})

    def test_native_http_listener_emits_wire_mdn_and_rejects_wrong_correlation(self):
        import asyncio
        import httpx
        from app.http_server import ListenerApp, listener_config
        from app.models import Project
        from app.runtime import WorkflowRuntime

        async def check(folder):
            a_cert, a_key = identity(folder, 'sender')
            b_cert, b_key = identity(folder, 'receiver')
            sender = {'localAs2Id': 'Sender', 'partnerAs2Id': 'Receiver', 'localCertificateFile': a_cert,
                      'localPrivateKeyFile': a_key, 'partnerCertificateFile': b_cert}
            receiver = {'localAs2Id': 'Receiver', 'partnerAs2Id': 'Sender', 'localCertificateFile': b_cert,
                        'localPrivateKeyFile': b_key, 'partnerCertificateFile': a_cert, 'requireEncryption': False,
                        'localEdiId': 'RECEIVER', 'partnerEdiId': 'SENDER'}
            partner = {'resourceId': 'partner'}
            listener = {'operation': 'listen', 'path': '/as2', 'method': 'POST'}
            project = Project.model_validate({'id': 'as2-native', 'name': 'AS2 Native', 'resources': [
                {'id': 'partner', 'type': 'trading_partner', 'name': 'Partner', 'config': receiver}
            ], 'tasks': [{'id': 'task', 'activities': [
                {'id': 'Listen', 'type': 'http_listener', 'name': 'Listen', 'config': listener},
                {'id': 'Receive', 'type': 'basic', 'name': 'Receive', 'config': {**partner, 'operation': 'as2_receive'}},
                {'id': 'Receipt', 'type': 'basic', 'name': 'Receipt', 'config': {**partner, 'operation': 'as2_receipt',
                 'inputMappings': {'messageId': '${last.messageId}', 'claimToken': '${last.claimToken}'}}},
                {'id': 'Response', 'type': 'http_response', 'name': 'Response', 'config': {'inputMappings': {
                    'headers': '${last.receipt.headers}', 'binaryContent': '${last.receipt.binaryContent}'}}}
            ], 'transitions': [
                {'id': '1', 'source': 'Listen', 'target': 'Receive'}, {'id': '2', 'source': 'Receive', 'target': 'Receipt'},
                {'id': '3', 'source': 'Receipt', 'target': 'Response'}
            ]}]})
            resources = {resource.id: resource for resource in project.resources}
            runtime = WorkflowRuntime()
            async def handle(metadata, payload):
                result = await runtime.run(project.tasks[0], payload, resources, entry_activity_id=metadata,
                                           project=project, event_output=payload)
                self.assertEqual(result.status, 'completed', result.logs)
                return result.output
            host = ListenerApp([('Listen', listener_config({}, listener))], handle, {}, warm_workers=False)
            entity = trading_partner._entity('application/edi-x12', X12.encode())
            signed_type, signed_body = trading_partner._signed(entity, sender)
            compressed = trading_partner._compress(trading_partner._entity(signed_type, signed_body))
            encrypted_type, encrypted_body = trading_partner._encrypt(trading_partner.COMPRESSED_TYPE, compressed, sender)
            messages = [('signed', signed_type, signed_body, 'binary'),
                        ('compressed', trading_partner.COMPRESSED_TYPE, base64.b64encode(compressed), 'base64'),
                        ('encrypted', encrypted_type, encrypted_body, 'binary')]
            try:
                async with httpx.AsyncClient(transport=httpx.ASGITransport(app=host), base_url='http://test') as client:
                    for variant, content_type, body, transfer in messages:
                        with self.subTest(variant=variant):
                            message_id = f'{variant}@mina.invalid'
                            response = await client.post('/as2', content=body, headers={
                                'Content-Type': content_type, 'Content-Transfer-Encoding': transfer,
                                'AS2-From': 'Sender', 'AS2-To': 'Receiver', 'Message-ID': f'<{message_id}>'
                            })
                            self.assertEqual(response.status_code, 200, response.text)
                            self.assertEqual(trading_partner._verify_mdn(dict(response.headers), response.content, sender,
                                                                       message_id, trading_partner._mic(entity)), (True, True))
                with self.assertRaisesRegex(ValueError, 'different Message-ID'):
                    trading_partner._verify_mdn(dict(response.headers), response.content, sender,
                                               'other@mina.invalid', trading_partner._mic(entity))
            finally:
                host.executor.shutdown(wait=True, cancel_futures=True)

        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {'MINA_AS2_LEDGER_FILE': str(Path(folder) / 'ledger.sqlite3')}):
            asyncio.run(check(folder))
