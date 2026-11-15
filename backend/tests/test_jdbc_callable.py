import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


@unittest.skipUnless(shutil.which('javac') and shutil.which('java'),'Requires JDK for actual JDBC bridge compilation')
class JdbcCallableTests(unittest.TestCase):
    def test_compiled_bridge_callable_out_timeout_and_close(self):
        root=Path(__file__).resolve().parents[2]
        with tempfile.TemporaryDirectory() as folder:
            result=subprocess.run([shutil.which('javac'),'-encoding','UTF-8','-d',folder,str(root/'java-bridge/src/com/mina/bridge/MinaJavaBridge.java'),str(root/'backend/tests/fixtures/JdbcCallableHarness.java')],capture_output=True,text=True,timeout=60)
            self.assertEqual(result.returncode,0,result.stderr)
            result=subprocess.run([shutil.which('java'),'-cp',folder,'JdbcCallableHarness'],capture_output=True,text=True,timeout=15)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertIn('verified',result.stdout)
