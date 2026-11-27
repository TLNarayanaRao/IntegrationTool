import base64
import hashlib
import os
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import ssl
import tempfile
import threading
import unittest
from unittest.mock import patch
import uuid

from app import edi_ack, trading_partner
from app.as2_ledger import record
from tests.test_trading_partner import EDIFACT, X12, identity


def _parity():
    from tests.test_python_mapper_parity import PythonMapperParityTests
    return PythonMapperParityTests()


def flow(operations, resources=(), outputs=None):
    project = _parity().project()
    project['resources'] = list(resources)
    task = project['tasks'][0]
    task['activities'][1:1] = [
        {'id': name, 'name': name, 'type': 'basic', 'config': config} for name, config in operations
    ]
    if outputs:
        task['activities'][-1]['config'] = {'inputMappings': outputs}
    task['transitions'] = [{'id': f't{i}', 'source': a['id'], 'target': b['id']}
                           for i, (a, b) in enumerate(zip(task['activities'], task['activities'][1:]))]
    return project


def partner(identifier, config):
    return {'id': identifier, 'name': identifier, 'type': 'trading_partner', 'config': config}


class PartnerAcknowledgementTests(unittest.TestCase):
    def test_authenticated_decompression_failure_returns_cached_negative_receipt(self):
        with tempfile.TemporaryDirectory() as root, patch.dict(os.environ, {'MINA_AS2_LEDGER_FILE': str(Path(root) / 'ledger.sqlite3')}):
            ca, ka = identity(root, 'A')
            cb, kb = identity(root, 'B')
            sender = {'localAs2Id': 'A', 'partnerAs2Id': 'B', 'localCertificateFile': ca,
                      'localPrivateKeyFile': ka, 'partnerCertificateFile': cb}
            receiver = {'localAs2Id': 'B', 'partnerAs2Id': 'A', 'localCertificateFile': cb,
                        'localPrivateKeyFile': kb, 'partnerCertificateFile': ca, 'requireEncryption': False,
                        'rejectInvalidEdiWithMdn': True}
            entity = trading_partner._entity(trading_partner.COMPRESSED_TYPE, b'invalid CMS content')
            media, body = trading_partner._signed(entity, sender)
            identifier = 'decompression@mina.invalid'
            headers = {'AS2-From': 'A', 'AS2-To': 'B', 'Message-ID': f'<{identifier}>', 'Content-Type': media}
            request = {'headers': headers.copy(), 'binaryContent': base64.b64encode(body).decode('ascii')}
            with self.assertRaisesRegex(ValueError, 'decompression failed'):
                trading_partner.execute('as2_receive', {}, request, 'B', receiver)
            request['headers']['Disposition-Notification-To'] = 'qa@example.invalid'
            rejection = trading_partner.execute('as2_receive', {}, request, 'B', receiver)
            self.assertEqual((rejection['status'], rejection['errorCode']), ('rejected', 'decompression-failed'))
            receipt = rejection['receipt']
            self.assertEqual(trading_partner._verify_mdn(receipt['headers'], base64.b64decode(receipt['binaryContent']),
                                                        sender, identifier, trading_partner._mic(entity)), (False, True))
            duplicate = trading_partner.execute('as2_receive', {}, request, 'B', receiver)
            self.assertTrue(duplicate['duplicate'])
            self.assertEqual(duplicate['receipt'], receipt)
            request['headers']['Date'] = 'Thu, 26 Nov 2026 10:00:00 GMT'
            with self.assertRaisesRegex(ValueError, 'Message-ID was already used'):
                trading_partner.execute('as2_receive', {}, request, 'B', receiver)

    def test_quoted_as2_identifier_round_trips(self):
        identifier = ' "Sales" \\ West '
        header = trading_partner._wire_id(identifier)
        self.assertEqual(trading_partner._as2_id(header, wire=True), identifier)
        with self.assertRaisesRegex(ValueError, 'quoting'):
            trading_partner._as2_id('Sales West', wire=True)
        with self.assertRaisesRegex(ValueError, 'quoting'):
            trading_partner._as2_id('"Sales\\West"', wire=True)

    def test_unresolved_encryption_settings_fail_closed(self):
        profile = {'localAs2Id': 'Sender', 'partnerAs2Id': 'Receiver', 'requireEncryption': '${properties.as2Encryption}'}
        with self.assertRaisesRegex(ValueError, 'requireEncryption must be a boolean'):
            trading_partner.validate_profile(profile)
        self.assertTrue(trading_partner._flag({}, 'requireEncryption', True))
        self.assertFalse(trading_partner._flag({'requireEncryption': 'false'}, 'requireEncryption', True))

    def test_signed_negative_mdn_without_mic_and_success_requires_mic(self):
        with tempfile.TemporaryDirectory() as root, patch.dict(os.environ, {'MINA_AS2_LEDGER_FILE': str(Path(root) / 'ledger.sqlite3')}):
            cert, key = identity(root, 'receiver')
            receiver = {'localAs2Id': 'Receiver', 'partnerAs2Id': 'Sender', 'localCertificateFile': cert, 'localPrivateKeyFile': key}
            sender = {'localAs2Id': 'Sender', 'partnerAs2Id': 'Receiver', 'partnerCertificateFile': cert}
            identifier = 'negative@mina.invalid'
            digest = trading_partner._mic(b'EDI')
            claim = record('A', identifier, 'outbound', 'claim', entry={
                'fingerprint': 'wire', 'mic': digest, 'controlNumber': '9', 'receiptMode': 'asynchronous'})
            record('A', identifier, 'outbound', 'awaiting_mdn', token=claim['claimToken'])
            impostor = trading_partner._receipt(receiver, identifier, None, False)
            with self.assertRaisesRegex(ValueError, 'integrity check failed'):
                trading_partner.execute('as2_mdn_receive', {}, impostor, 'A', sender)
            mismatch = trading_partner._receipt(receiver, identifier, trading_partner._mic(b'wrong'), True)
            with self.assertRaisesRegex(ValueError, 'integrity check failed'):
                trading_partner.execute('as2_mdn_receive', {}, mismatch, 'A', sender)
            negative = trading_partner._receipt(receiver, identifier, None, True)
            self.assertEqual(trading_partner._verify_mdn(negative['headers'], base64.b64decode(negative['binaryContent']),
                                                        sender, identifier, digest), (False, False))
            result = trading_partner.execute('as2_mdn_receive', {}, negative, 'A', sender)
            self.assertEqual((result['status'], result['receiptMicVerified']), ('rejected', False))
            self.assertFalse(record('A', identifier, 'outbound', 'read')['receiptMicVerified'])
            self.assertTrue(trading_partner.execute('as2_mdn_receive', {}, negative, 'A', sender)['duplicate'])

    def test_cms_compression_size_and_stream_validation(self):
        from asn1crypto import cms
        import zlib

        headers, _ = trading_partner._parse_entity(trading_partner._entity(trading_partner.COMPRESSED_TYPE, b''))
        compressed = trading_partner._compress(b'x' * 1024)
        self.assertEqual(trading_partner._decompress(headers, compressed, 1024), b'x' * 1024)
        for invalid in (compressed, compressed[:-1]):
            with self.assertRaisesRegex(ValueError, 'decompression failed'):
                trading_partner._decompress(headers, invalid, 128)
        envelope = cms.ContentInfo.load(compressed)
        content = envelope['content']['encap_content_info']
        content['content'] = content['content'].native + b'extra zlib data'
        with self.assertRaisesRegex(ValueError, 'decompression failed'):
            trading_partner._decompress(headers, envelope.dump(), 1024)

        # Streaming CMS implementations can emit an indefinite-length BER envelope and split OCTET STRINGs.
        fixture = b'Content-Type: application/edi-x12\r\n\r\nExample'
        stream = zlib.compress(fixture)
        chunks = b''.join(bytes((4, len(chunk))) + chunk for chunk in (stream[:7], stream[7:]))
        ber = (bytes.fromhex('3080060b2a864886f70d0109100109a0803080020100') +
               bytes.fromhex('300d060b2a864886f70d0109100308') +
               bytes.fromhex('308006092a864886f70d010701a0802480') + chunks + b'\0\0' * 6)
        self.assertEqual(trading_partner._decompress(headers, ber, 128), fixture)

    def test_mdn_warning_counts_as_processed(self):
        profile = {'localAs2Id': 'Receiver', 'partnerAs2Id': 'Sender'}
        headers = {'AS2-From': 'Sender', 'AS2-To': 'Receiver'}
        mic = trading_partner._mic(b'EDI content')
        for modifier, accepted in (('warning: authentication-weak', True), ('error: authentication-failed', False)):
            with self.subTest(modifier=modifier):
                fields = trading_partner._entity('message/disposition-notification', (
                    'Original-Message-ID: <example@mina.invalid>\r\n'
                    f'Disposition: automatic-action/MDN-sent-automatically; processed/{modifier}\r\n'
                    f'Received-Content-MIC: {mic}, sha-256\r\n').encode('ascii'), '7bit')
                kind, report = trading_partner._multipart('report', 'report-type=disposition-notification', [
                    trading_partner._entity('text/plain', b'Test receipt', '7bit'), fields])
                with patch.object(trading_partner, '_verified', return_value=trading_partner._entity(kind, report, '7bit')):
                    self.assertEqual(trading_partner._read_mdn(headers, b'', profile), ('example@mina.invalid', mic, accepted))

    def test_997_999_and_contrl_round_trip_in_all_runtimes(self):
        parity = _parity()
        project = flow([
            ('Acknowledge', {'operation': 'edi_ack_create', 'ackType': '${input.kind}', 'payload': '${input.edi}',
                            'ackDecisions': '${input.decisions}', 'ackInterchangeControl': '000000009',
                            'ackGroupControl': '21', 'ackTimestamp': '2026-03-14T15:09:00Z'}),
            ('Read', {'operation': 'edi_ack_read', 'payload': '${last.text}'}),
        ])
        for kind, source, control, source_control, decision, status in (
            ('997', X12, '0001', '1', True, 'A'),
            ('999', X12, '0001', '1', False, 'R'),
            ('CONTRL', EDIFACT, '1', None, False, '4'),
        ):
            with self.subTest(kind=kind):
                decisions = [{'controlNumber': control, 'groupControlNumber': source_control, 'accepted': decision, 'errorCode': '12'}]
                payload = {'kind': kind, 'edi': source, 'decisions': decisions}
                expected = {'ackType': kind, 'controlNumber': '000000009',
                            'groups': [{'controlNumber': '1', 'status': status, 'included': 1, 'received': 1,
                                        'accepted': int(decision)}] if kind != 'CONTRL' else [],
                            'interchanges': [{'controlNumber': '1', 'status': '7'}] if kind == 'CONTRL' else [],
                            'transactions': [{'controlNumber': control, 'groupControlNumber': source_control, 'status': status}]}
                parity.assert_studio(project, payload, expected)
                parity.assert_exports(project, payload, expected)

    def test_wrong_acknowledgement_type_or_unmatched_decisions_fail(self):
        config = {'ackType': 'CONTRL', 'ackInterchangeControl': '9', 'ackGroupControl': '1'}
        with self.assertRaisesRegex(ValueError, 'does not match'):
            edi_ack.generate(X12, config)
        with self.assertRaisesRegex(ValueError, 'absent'):
            edi_ack.generate(EDIFACT, {**config, 'ackDecisions': [{'controlNumber': 'missing', 'accepted': False}]})
        with self.assertRaisesRegex(ValueError, 'syntax error code'):
            edi_ack.generate(EDIFACT, {**config, 'ackDecisions': [{'controlNumber': '1', 'accepted': False}]})

    def test_async_wire_callbacks_in_run_debug_and_both_python_formats(self):
        parity = _parity()
        with tempfile.TemporaryDirectory() as root, patch.dict(os.environ, {'MINA_AS2_LEDGER_FILE': str(Path(root) / 'ledger.sqlite3')}):
            local_cert, local_key = identity(root, 'sender')
            remote_cert, remote_key = identity(root, 'receiver')
            ca = identity(root, 'tls-ca', ca=True)
            server_cert, server_key = identity(root, 'tls-server', issuer=ca, tls_server=True)
            client_a, client_a_key = identity(root, 'tls-sender', issuer=ca)
            client_b, client_b_key = identity(root, 'tls-receiver', issuer=ca)
            received, failed, reject_next = [], [], []
            a = {'localAs2Id': 'Sender', 'partnerAs2Id': 'Receiver', 'localCertificateFile': local_cert,
                 'localPrivateKeyFile': local_key, 'partnerCertificateFile': remote_cert, 'receiptAddress': 'test@example.invalid',
                 'compressOutbound': True, 'tlsCaFile': ca[0], 'as2TlsClientCertFile': client_a, 'as2TlsClientKeyFile': client_a_key,
                 'receiptMode': 'asynchronous'}
            b = {'localAs2Id': 'Receiver', 'partnerAs2Id': 'Sender', 'localCertificateFile': remote_cert,
                 'localPrivateKeyFile': remote_key, 'partnerCertificateFile': local_cert, 'tlsCaFile': ca[0],
                 'as2TlsClientCertFile': client_b, 'as2TlsClientKeyFile': client_b_key,
                 'as2HttpUsername': 'data-fixture-user', 'as2HttpPassword': 'data-fixture-password'}
            dsn = os.getenv('MINA_QA_AS2_POSTGRES_DSN')
            if dsn:
                import psycopg
                os.environ['MINA_AS2_LEDGER_POSTGRES_DSN'] = dsn
                profile_keys = []
                for config in (a, b):
                    key = uuid.uuid4().hex
                    config.update(reconciliationBackend='postgresql', reconciliationKey=key)
                    profile_keys.append(hashlib.sha256('\0'.join((key, config['localAs2Id'], config['partnerAs2Id'])).encode()).hexdigest())
                def cleanup():
                    with psycopg.connect(dsn) as db:
                        db.execute('DELETE FROM mina_as2.exchange WHERE profile=ANY(%s)', (profile_keys,))
                self.addCleanup(cleanup)

            class Wire(BaseHTTPRequestHandler):
                def do_POST(self):
                    try:
                        body = self.rfile.read(int(self.headers['Content-Length']))
                        request = {'headers': dict(self.headers), 'binaryContent': base64.b64encode(body).decode()}
                        if self.path == '/as2':
                            assert self.connection.getpeercert()['subject'] == ((('commonName', 'tls-sender'),),)
                            bad_headers = {k: v for k, v in request['headers'].items() if k.lower() != 'receipt-delivery-option'}
                            bad_headers['Receipt-Delivery-Option'] = b['partnerMdnUrl'] + '/different'
                            with self_case.assertRaisesRegex(ValueError, 'does not match'):
                                trading_partner.execute('as2_receive', {}, {**request, 'headers': bad_headers}, 'B', b)
                            delivery = trading_partner.execute('as2_receive', {}, request, 'B', b)
                            assert delivery['receiptMode'] == 'asynchronous'
                            current = trading_partner.execute('as2_lookup', {'messageId': delivery['messageId'], 'direction': 'outbound'}, None, 'A', a)
                            assert current['status'] == 'awaiting_mdn'
                            ack = delivery if delivery.get('status') == 'rejected' else trading_partner.execute('as2_receipt', delivery, None, 'B', b)
                            assert ack['callbackStatus'] == 'pending' and ack['receipt']['binaryContent'] == ''
                        elif self.path == '/mdn':
                            assert self.connection.getpeercert()['subject'] == ((('commonName', 'tls-receiver'),),)
                            assert 'Authorization' not in self.headers
                            if reject_next:
                                reject_next.pop()
                                self.send_error(503)
                                return
                            receipt = trading_partner.execute('as2_mdn_receive', {}, request, 'A', a)
                            assert receipt['status'] == ('rejected' if b.get('rejectInvalidEdiWithMdn') else 'processed')
                            duplicate = trading_partner.execute('as2_mdn_receive', {}, request, 'A', a)
                            assert duplicate['duplicate']
                            received.append(request)
                        else:
                            self.send_error(404)
                            return
                        self.send_response(200)
                        self.send_header('Content-Length', '0')
                        self.end_headers()
                    except Exception as error:
                        failed.append(error)
                        self.send_error(500)

                def log_message(self, *_args):
                    pass

            with ThreadingHTTPServer(('127.0.0.1', 0), Wire) as server:
                context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
                context.load_cert_chain(server_cert, server_key)
                context.load_verify_locations(cafile=ca[0])
                context.verify_mode = ssl.CERT_REQUIRED
                server.socket = context.wrap_socket(server.socket, server_side=True)
                self_case = self
                worker = threading.Thread(target=server.serve_forever, daemon=True)
                worker.start()
                try:
                    origin = f'https://127.0.0.1:{server.server_port}'
                    a.update(endpointUrl=origin + '/as2', localMdnUrl=origin + '/mdn')
                    b['partnerMdnUrl'] = a['localMdnUrl']
                    project = flow([
                        ('Send', {'operation': 'as2_send', 'resourceId': 'A', 'payload': '${input.edi}'}),
                        ('Deliver', {'operation': 'as2_mdn_deliver', 'resourceId': 'B', 'messageId': '${last.messageId}'}),
                        ('Lookup', {'operation': 'as2_lookup', 'resourceId': 'A', 'direction': 'outbound', 'messageId': '${last.messageId}'}),
                    ], [partner('A', a), partner('B', b)], {'status': '${last.status}', 'receiptMode': '${last.receiptMode}'})
                    expected = {'status': 'processed', 'receiptMode': 'asynchronous'}
                    try:
                        parity.assert_studio(project, {'edi': X12}, expected)
                        parity.assert_exports(project, {'edi': X12}, expected)
                    except AssertionError:
                        if failed:
                            raise failed[0]
                        raise
                    self.assertEqual(len(received), 5)
                    callback_flow = flow([('Callback', {'operation': 'as2_mdn_receive', 'resourceId': 'A'})],
                                         [partner('A', a)], {'status': '${last.status}', 'duplicate': '${last.duplicate}'})
                    parity.assert_studio(callback_flow, received[0], {'status': 'processed', 'duplicate': True})
                    parity.assert_exports(callback_flow, received[0], {'status': 'processed', 'duplicate': True})
                    pending = trading_partner.execute('as2_send', {}, X12, 'A', a)
                    self.assertEqual(pending['status'], 'awaiting_mdn')
                    reject_next.append(True)
                    key = {'messageId': pending['messageId']}
                    with self.assertRaisesRegex(ValueError, 'HTTP 503'):
                        trading_partner.execute('as2_mdn_deliver', key, None, 'B', b)
                    self.assertEqual(trading_partner.execute('as2_lookup', key, None, 'B', b)['callbackStatus'], 'pending')
                    self.assertEqual(trading_partner.execute('as2_mdn_deliver', key, None, 'B', b)['callbackStatus'], 'sent')
                    self.assertTrue(trading_partner.execute('as2_mdn_deliver', key, None, 'B', b)['duplicate'])
                    b.update(rejectInvalidEdiWithMdn=True, allowedTransactionTypes='860')
                    rejected = trading_partner.execute('as2_send', {}, X12, 'A', a)
                    key = {'messageId': rejected['messageId']}
                    self.assertEqual(trading_partner.execute('as2_mdn_deliver', key, None, 'B', b)['callbackStatus'], 'sent')
                    history = trading_partner.execute('as2_lookup', {**key, 'direction': 'outbound'}, None, 'A', a)
                    self.assertEqual((history['status'], history['receiptMicVerified']), ('rejected', True))
                finally:
                    server.shutdown()
                    worker.join(timeout=5)

    @unittest.skipUnless(os.getenv('MINA_QA_AS2_POSTGRES_DSN'), 'Disposable PostgreSQL was not provided')
    def test_shared_reconciliation_from_independent_archive_processes(self):
        import psycopg
        parity = _parity()
        dsn = os.environ['MINA_QA_AS2_POSTGRES_DSN']
        scope = uuid.uuid4().hex
        message_id = f'{scope}@mina.invalid'
        with patch.dict(os.environ, {'MINA_AS2_LEDGER_POSTGRES_DSN': dsn}):
            config = {'localAs2Id': 'Sender', 'partnerAs2Id': 'Receiver', 'reconciliationBackend': 'postgresql'}
            key = hashlib.sha256('\0'.join((scope, 'Sender', 'Receiver')).encode()).hexdigest()
            entry = {'fingerprint': 'wire', 'mic': 'digest', 'controlNumber': '9', 'receiptMode': 'asynchronous'}
            claim = record(key, message_id, 'outbound', 'claim', backend='postgresql', entry=entry)
            record(key, message_id, 'outbound', 'awaiting_mdn', backend='postgresql', token=claim['claimToken'])
            try:
                def reconcile(_):
                    return record(key, message_id, 'outbound', 'reconcile_mdn', backend='postgresql',
                                  entry={'mic': 'digest', 'status': 'processed'}, receipt={'confirmed': True})
                with ThreadPoolExecutor(max_workers=6) as workers:
                    results = list(workers.map(reconcile, range(12)))
                self.assertEqual(sum(not result['duplicate'] for result in results), 1)
                project = flow([('Lookup', {'operation': 'as2_lookup', 'resourceId': 'different-resource-id',
                                            'direction': 'outbound', 'messageId': '${input.messageId}'})],
                               [partner('different-resource-id', {**config, 'reconciliationKey': scope})],
                               {'status': '${last.status}', 'controlNumber': '${last.controlNumber}'})
                parity.assert_studio(project, {'messageId': message_id}, {'status': 'processed', 'controlNumber': '9'})
                parity.assert_exports(project, {'messageId': message_id}, {'status': 'processed', 'controlNumber': '9'})
            finally:
                with psycopg.connect(dsn) as db:
                    db.execute('DELETE FROM mina_as2.exchange WHERE profile=%s', (key,))
