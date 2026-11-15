"""Bounded Windows SSH execution must preserve connection lifecycle semantics."""
import gc
import contextlib
import hashlib
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import weakref
from concurrent.futures import ThreadPoolExecutor

from app.sftp import _TransportWorkers, _windows_transport_type, open_connection
from app.transfer import transfer
from tests.test_transfer_network import sftp_server


class SftpTransportWorkerTests(unittest.TestCase):
    def test_parallel_streamed_transfers_keep_servers_and_payloads_isolated(self):
        with tempfile.TemporaryDirectory() as folder,contextlib.ExitStack() as stack:
            root=Path(folder)
            servers=[]
            for number in range(2):
                directory=root/str(number);directory.mkdir()
                servers.append(stack.enter_context(sftp_server(directory)))
            def roundtrip(number):
                server=number%2
                data=bytes([65+number])*2097152
                source=root/f'input-{number}';source.write_bytes(data)
                target=root/f'output-{number}'
                config={**servers[server],'remotePath':f'file-{number//2}.bin'}
                transfer('sftp','put',{**config,'localPath':str(source),'atomicUpload':True})
                result=transfer('sftp','get',{**config,'localPath':str(target),'maxDownloadBytes':len(data)})
                self.assertIsNone(result['contentBase64'])
                self.assertEqual(hashlib.sha256(target.read_bytes()).digest(),hashlib.sha256(data).digest())
                transfer('sftp','delete',config)
            with ThreadPoolExecutor(max_workers=4) as executor:
                list(executor.map(roundtrip,range(4)))
            # A worker previously used with another server must not reuse its trust.
            with self.assertRaises(Exception):
                transfer('sftp','dir',{**servers[0],'knownHostsFile':servers[1]['knownHostsFile']})
            self.assertTrue(transfer('sftp','dir',servers[0])['entries'])

    def test_encrypted_private_key_operations_run_debug_and_both_archives(self):
        import paramiko
        from tests.test_transfer_network import TransferNetworkTests
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            key=paramiko.RSAKey.generate(2048)
            key_file=root/'identity.pem'
            key.write_private_key_file(str(key_file),password='test-only-passphrase')
            with sftp_server(root,public_key=key) as config:
                config.pop('password')
                config.update(privateKeyFile=str(key_file),privateKeyPassphrase='test-only-passphrase')
                with self.assertRaises(Exception):
                    open_connection({**config,'privateKeyPassphrase':'incorrect-test-passphrase'})
                TransferNetworkTests().verify('sftp',config)

    @unittest.skipUnless(os.name == 'nt', 'Windows-specific transport policy')
    def test_invalid_worker_limit_is_rejected_before_using_a_transport(self):
        code='''
import os
from app.sftp import _windows_transport_type
for value in ('0','129','invalid'):
 os.environ['MINA_SFTP_TRANSPORT_WORKERS']=value
 try:_windows_transport_type()
 except ValueError as error:assert '1 to 128' in str(error)
 else:raise AssertionError('Invalid capacity accepted')
print('invalid limits rejected')
'''
        result=subprocess.run([sys.executable,'-c',code],cwd=Path(__file__).resolve().parents[1],capture_output=True,text=True,timeout=10)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)

    def test_worker_capacity_is_bounded_and_reusable_after_failure(self):
        pool = _TransportWorkers(2)
        release = threading.Event()
        first = pool.submit(release.wait, 1)
        second = pool.submit(release.wait, 1)
        try:
            start = time.monotonic()
            with self.assertRaisesRegex(TimeoutError, 'capacity'):
                pool.submit(lambda: None, .03)
            self.assertLess(time.monotonic() - start, .5)
            self.assertEqual(len(pool.workers), 2)
        finally:
            release.set()
            self.assertTrue(first.done.wait(2))
            self.assertTrue(second.done.wait(2))
        class Payload:
            def __call__(self):
                raise SystemExit('test-only fatal transport failure')
        target = Payload()
        reference = weakref.ref(target)
        with self.assertLogs('app.sftp', level='ERROR'):
            job = pool.submit(target, 1)
            self.assertTrue(job.done.wait(2))
        del target
        gc.collect()
        self.assertIsNone(reference())
        for _ in range(100):
            self.assertTrue(pool.submit(lambda: None, 1).done.wait(2))
        self.assertEqual(len(pool.workers), 2)
        self.assertEqual(pool.active, 0)
        self.assertIsNone(job.target)

    @unittest.skipUnless(os.name == 'nt', 'Windows-specific transport policy')
    def test_concurrent_factory_lookup_uses_one_pool(self):
        # A warmed cache would miss a concurrent-first-connection regression.
        code='''
from concurrent.futures import ThreadPoolExecutor
from app.sftp import _windows_transport_type,_build_windows_transport_type
with ThreadPoolExecutor(max_workers=24) as executor:
 types=list(executor.map(lambda _: _windows_transport_type(),range(48)))
assert all(item is types[0] for item in types)
assert _build_windows_transport_type.cache_info().misses==1
'''
        result=subprocess.run([sys.executable,'-c',code],cwd=Path(__file__).resolve().parents[1],capture_output=True,text=True,timeout=15)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)

    def test_closed_real_transports_are_collectable_after_parallel_connections(self):
        with tempfile.TemporaryDirectory() as folder, sftp_server(Path(folder)) as config:
            def connect_and_close(_):
                ssh, client = open_connection(config)
                transport = ssh.get_transport()
                reference = weakref.ref(transport)
                try:
                    self.assertTrue(client.listdir('.'))  # includes known_hosts
                finally:
                    client.close()
                    ssh.close()
                    transport.join(2)
                self.assertFalse(transport.is_alive())
                return reference
            with ThreadPoolExecutor(max_workers=4) as executor:
                references = list(executor.map(connect_and_close, range(24)))
            # Allow the independent server fixture to release its own references.
            gc.collect()
            self.assertTrue(all(reference() is None for reference in references))

    @unittest.skipUnless(os.name == 'nt', 'Windows-specific transport capacity')
    def test_capacity_timeout_closes_waiter_without_disturbing_live_connection(self):
        code = '''
import os,tempfile
from pathlib import Path
os.environ['MINA_SFTP_TRANSPORT_WORKERS']='1'
from app.sftp import open_connection
from tests.test_transfer_network import sftp_server
with tempfile.TemporaryDirectory() as folder,sftp_server(Path(folder)) as config:
 ssh,sftp=open_connection(config)
 try:
  for _ in range(4):
   try:open_connection({**config,'timeout':.15})
   except TimeoutError as error:assert 'capacity' in str(error)
   else:raise AssertionError('Expected bounded capacity timeout')
  assert sftp.listdir('.')
 finally:sftp.close();ssh.close()
 ssh,sftp=open_connection(config)
 sftp.close();ssh.close()
print('capacity and cleanup verified')
'''
        result = subprocess.run([sys.executable, '-c', code], cwd=Path(__file__).resolve().parents[1],
                                capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('capacity and cleanup verified', result.stdout)
