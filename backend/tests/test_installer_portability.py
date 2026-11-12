"""Packaged designer checks catch a healthy backend with missing frontend files."""
import importlib.util
import unittest
from email.message import Message
from pathlib import Path
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[2]
spec=importlib.util.spec_from_file_location('installer_smoke',ROOT/'scripts/smoke-test-packaged-runtime.py')
smoke=importlib.util.module_from_spec(spec);spec.loader.exec_module(smoke)


class Response:
    def __init__(self,body,content_type='text/html'):
        self.body=body;self.headers=Message();self.headers['Content-Type']=content_type
    def read(self):return self.body
    def __enter__(self):return self
    def __exit__(self,*args):return False


class InstallerPortabilityTests(unittest.TestCase):
    def test_packaged_designer_fetches_both_assets_from_the_current_runtime(self):
        base='http://127.0.0.1:12345'
        replies={base+'/':Response(b'<script src="/assets/app.js"></script><link href="/assets/app.css">'),
                 base+'/assets/app.js':Response(b'console.log("ready")','application/javascript'),
                 base+'/assets/app.css':Response(b'body{}','text/css')}
        with patch.object(smoke.urllib.request,'urlopen',side_effect=lambda url,**_:replies[url]) as fetch:
            self.assertEqual(smoke.verify_designer(base),2)
        self.assertEqual({call.args[0] for call in fetch.call_args_list},set(replies))

    def test_healthy_api_does_not_hide_missing_or_fallback_designer_assets(self):
        for body,content_type in ((b'<html>SPA fallback</html>','text/html'),(b'','application/javascript')):
            with self.subTest(content_type=content_type),patch.object(smoke.urllib.request,'urlopen',side_effect=[
                    Response(b'<script src="/assets/missing.js"></script>'),Response(body,content_type)]):
                with self.assertRaises(RuntimeError):smoke.verify_designer('http://localhost:12345')
        with patch.object(smoke.urllib.request,'urlopen',return_value=Response(b'<html>No built designer</html>')):
            with self.assertRaisesRegex(RuntimeError,'no generated asset'):smoke.verify_designer('http://localhost:12345')
