"""Small, bounded regressions for the reviewed web dependency security fixes."""
import unittest
import runpy
from pathlib import Path
from tempfile import SpooledTemporaryFile
from unittest.mock import patch

from starlette.concurrency import run_in_threadpool
from starlette.datastructures import Headers, UploadFile
from starlette.formparsers import FormParser, MultiPartException, MultiPartParser


async def chunks(data):
    yield data
    yield b''


class WebDependencySecurityTests(unittest.IsolatedAsyncioTestCase):
    async def test_rollover_write_is_offloaded(self):
        upload = UploadFile(SpooledTemporaryFile(max_size=8), size=0)
        try:
            with patch('starlette.datastructures.run_in_threadpool', wraps=run_in_threadpool) as offload:
                await upload.write(b'123456789')
                offload.assert_awaited_once()
            await upload.seek(0)
            self.assertEqual(await upload.read(), b'123456789')
        finally:
            await upload.close()

    async def test_urlencoded_field_count_limit(self):
        parser = FormParser(Headers(), chunks(b'a=1&b=2'), max_fields=1)
        with self.assertRaises(MultiPartException):
            await parser.parse()

    async def test_urlencoded_field_size_limit(self):
        parser = FormParser(Headers(), chunks(b'a=123456789'), max_part_size=8)
        with self.assertRaises(MultiPartException):
            await parser.parse()

    async def test_small_multipart_upload_still_works(self):
        data = (b'--test\r\nContent-Disposition: form-data; name="file"; '
                b'filename="test.txt"\r\nContent-Type: text/plain\r\n\r\nhello\r\n--test--\r\n')
        form = await MultiPartParser(Headers({'content-type': 'multipart/form-data; boundary=test'}), chunks(data)).parse()
        try:
            self.assertEqual(await form['file'].read(), b'hello')
        finally:
            await form.close()

    def test_web_pins_match_all_distributions(self):
        root = Path(__file__).resolve().parents[2]
        expected = {'fastapi==0.141.1', 'starlette==1.6.0', 'python-multipart==0.0.32'}
        for file in ('backend/requirements.txt', 'backend/requirements-browser.txt', 'administrator/requirements.txt'):
            with self.subTest(file=file):
                self.assertTrue(expected.issubset(set((root / file).read_text().splitlines())))

    def test_build_guard_rejects_stale_stack(self):
        root = Path(__file__).resolve().parents[2]
        guard = runpy.run_path(str(root / 'scripts/verify-web-dependencies.py'))
        with patch('importlib.metadata.version', return_value='0.0.1'):
            guard = runpy.run_path(str(root / 'scripts/verify-web-dependencies.py'))
            with self.assertRaisesRegex(SystemExit, 'Web dependency verification failed'):
                guard['verify']()
