import io
import json
import tarfile
import unittest
import warnings
import zipfile
from unittest.mock import patch

from starlette.requests import Request
from administrator.app import main


def request(host='127.0.0.1', headers=None):
    values = {'host': 'localhost:9080', **(headers or {})}
    return Request({'type': 'http', 'method': 'GET', 'path': '/api/session', 'scheme': 'http',
                    'server': ('localhost', 9080), 'client': (host, 50000), 'query_string': b'',
                    'headers': [(key.encode(), value.encode()) for key, value in values.items()]})


class SecurityHardeningTests(unittest.TestCase):
    def test_credential_free_owner_requires_direct_local_same_origin_access(self):
        with patch.object(main, 'API_KEY', ''):
            self.assertIsNotNone(main.resolve_identity(request()))
            self.assertIsNotNone(main.resolve_identity(request('::1', {'origin': 'http://localhost:9080'})))
            for value in (request('10.0.0.5'), request(headers={'origin': 'https://attacker.example'}),
                          request(headers={'origin': 'null'}), request(headers={'origin': 'http://[invalid'}),
                          request(headers={'host': 'attacker.example', 'origin': 'http://attacker.example'}),
                          request(headers={'sec-fetch-site': 'cross-site'}), request(headers={'x-forwarded-for': '127.0.0.1'})):
                with self.subTest(headers=dict(value.headers)):
                    self.assertIsNone(main.resolve_identity(value))
        with patch.object(main, 'API_KEY', 'owner-key'):
            self.assertIsNotNone(main.resolve_identity(request('10.0.0.5', {'x-admin-key': 'owner-key'})))
            self.assertIsNone(main.resolve_identity(request()))

    def test_invalid_token_expiry_fails_closed(self):
        token = {'tokenHash': main.token_hash('token'), 'status': 'ACTIVE', 'expiresAt': '2027-01-01', 'teamId': 'delivery'}
        with patch.object(main, 'API_KEY', 'owner-key'), patch.object(main, 'read_json', return_value=[token]):
            self.assertIsNone(main.resolve_identity(request(headers={'x-control-plane-key': 'token'})))
        for timestamp in ('2027-01-01', 'invalid'):
            with self.assertRaises(ValueError): main.token_expiry(timestamp)
        self.assertIsNotNone(main.token_expiry('2027-01-01T00:00:00Z').tzinfo)

    def test_invalid_expiry_is_a_validation_error_when_issuing_token(self):
        with patch.object(main, 'require_technology'), patch.object(main, 'team_record', return_value={}):
            with self.assertRaises(main.HTTPException) as error:
                main.issue_team_token('delivery', main.TeamTokenRequest(expiresAt='2027-01-01'), request())
            self.assertEqual(error.exception.status_code, 400)

    def test_portable_package_paths_reject_devices_streams_and_ambiguous_names(self):
        self.assertEqual(main.checked_name('application/core.py'), 'application/core.py')
        for name in ('../escape.py', '.', 'CON', 'application/NUL.py', 'application/core.py:payload', 'application/space ', 'application/trailing.', 'application/a\x00.py'):
            with self.subTest(name=name), self.assertRaises(ValueError): main.checked_name(name)

    def test_duplicate_and_symbolic_link_zip_entries_are_rejected(self):
        for names in (('manifest.json', 'manifest.json'), ('manifest.json', 'MANIFEST.JSON')):
            output = io.BytesIO()
            with warnings.catch_warnings(), zipfile.ZipFile(output, 'w') as archive:
                warnings.simplefilter('ignore')
                for name in names: archive.writestr(name, '{}')
            with self.assertRaisesRegex(ValueError, 'Duplicate'): main.inspect_archive(output.getvalue())
        output = io.BytesIO()
        with zipfile.ZipFile(output, 'w') as archive:
            link = zipfile.ZipInfo('application/link')
            link.external_attr = (0o120777 << 16)
            archive.writestr(link, '../outside')
        with self.assertRaisesRegex(ValueError, 'symbolic link'): main.inspect_archive(output.getvalue())

    def test_duplicate_tar_paths_and_upload_size_are_rejected(self):
        output = io.BytesIO()
        with tarfile.open(fileobj=output, mode='w:gz') as archive:
            for _ in range(2):
                info = tarfile.TarInfo('manifest.json'); info.size = 2
                archive.addfile(info, io.BytesIO(b'{}'))
        with self.assertRaisesRegex(ValueError, 'Duplicate'): main.inspect_archive(output.getvalue())
        with patch.object(main, 'MAX_PACKAGE_BYTES', 4), self.assertRaisesRegex(ValueError, 'upload limit'):
            main.inspect_archive(b'12345')
