import shutil
import subprocess
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from app import java_bridge as bridge


@unittest.skipUnless(shutil.which('javac') and shutil.which('java'), 'JDK required')
class JmsSenderWorkerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.folder = tempfile.TemporaryDirectory()
        cls.classes = Path(cls.folder.name)
        root = Path(__file__).resolve().parents[2]
        subprocess.run(['javac', '-encoding', 'UTF-8', '-d', str(cls.classes),
            str(root / 'java-bridge/src/com/integrationfabric/bridge/FabricJavaBridge.java'),
            str(Path(__file__).parent / 'fixtures/FakeJmsFactory.java')], check=True, capture_output=True)

    @classmethod
    def tearDownClass(cls):
        bridge.close_jms_senders(force=True)
        cls.folder.cleanup()

    def setUp(self):
        self.cp = patch.object(bridge, '_classpath', return_value=(str(self.classes), []))
        self.java = patch.object(bridge, '_java_executable', return_value=shutil.which('java'))
        self.cp.start(); self.java.start()
        self.config = {'connectionFactoryClass': 'fixture.FakeJmsFactory', 'serverUrl': 'fake',
                       'username': 'test', 'password': 'test', '_executionScope': 'debug-one'}

    def tearDown(self):
        bridge.close_jms_senders(force=True)
        self.cp.stop(); self.java.stop()

    def test_reuses_connection_and_producer_and_resets_delivery_options(self):
        first = bridge.execute_jms(self.config, 'send', 'queue', 'one', {'deliveryMode': 'Non-Persistent', 'priority': 8, 'expiration': 99})
        second = bridge.execute_jms(self.config, 'send', 'queue', 'two')
        self.assertFalse(first['senderReused'])
        self.assertTrue(second['senderReused'])
        self.assertEqual(first['messageId'], '1:1:1:1:8:99:one')
        self.assertEqual(second['messageId'], '1:1:2:2:4:0:two')
        self.assertIn('providerSendMs', second)

    def test_failed_send_is_not_replayed_and_next_send_reconnects(self):
        bridge.execute_jms(self.config, 'send', 'queue', 'one')
        with self.assertRaises(bridge.JavaBridgeError):
            bridge.execute_jms(self.config, 'send', 'queue', 'FAIL')
        self.assertFalse(bridge._jms_senders)
        result = bridge.execute_jms(self.config, 'send', 'queue', 'next')
        self.assertFalse(result['senderReused'])
        self.assertEqual(result['messageId'], '1:1:1:2:4:0:next')

    def test_multiple_destinations_share_connection_not_producer(self):
        bridge.execute_jms(self.config, 'send', 'first', 'one')
        second = bridge.execute_jms(self.config, 'send', 'second', 'two')
        third = bridge.execute_jms(self.config, 'send', 'first', 'three')
        self.assertEqual(second['messageId'], '1:2:2:2:4:0:two')
        self.assertEqual(third['messageId'], '1:2:3:2:4:0:three')
        self.assertEqual(len(bridge._jms_senders), 1)

    def test_debug_stop_closes_only_its_scope(self):
        bridge.execute_jms(self.config, 'send', 'queue', 'one')
        other = {**self.config, '_executionScope': 'debug-two'}
        bridge.execute_jms(other, 'send', 'queue', 'two')
        stopped = next(entry['worker'] for entry in bridge._jms_senders.values() if entry['scope'] == 'debug-one')
        bridge.terminate_execution_processes('debug-one')
        self.assertIsNotNone(stopped.process.poll())
        self.assertTrue(bridge.execute_jms(other, 'send', 'queue', 'three')['senderReused'])

    def test_concurrent_sends_keep_session_serialized_and_results_correlated(self):
        bridge.execute_jms(self.config, 'send', 'queue', 'warmup')
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(lambda index: bridge.execute_jms(self.config, 'send', 'queue', f'body-{index}'), range(40)))
        for index, result in enumerate(results):
            self.assertTrue(result['senderReused'])
            self.assertTrue(result['messageId'].startswith('1:1:'))
            self.assertTrue(result['messageId'].endswith(f':body-{index}'))
        self.assertEqual(len({result['messageId'] for result in results}), 40)
