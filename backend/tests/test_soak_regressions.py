import time,unittest
import gc,weakref
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest.mock import patch
from app.jdbc import JdbcConnection,execute,connect
from app.http_server import listener_config


class SoakRegressionTests(unittest.TestCase):
    def test_owned_database_sessions_are_closed_and_collected_on_success_and_failure(self):
        references=[];saved_errors=[]
        def opened(config):
            connection=connect(config);references.append(weakref.ref(connection));return connection
        with patch('app.jdbc.connect',side_effect=opened):
            for number in range(200):
                try:execute({'driver':'sqlite','url':':memory:'},{'sql':'SELECT 1' if number%2 else 'SELECT * FROM missing_table'})
                except Exception as error:saved_errors.append(error)
        # Failed execution tracebacks may retain session objects, but their handles must be closed.
        self.assertTrue(all(reference() is None or reference()._mina_closed for reference in references))
        saved_errors.clear();gc.collect()
        self.assertEqual(sum(reference() is not None for reference in references),0)
    def test_shared_native_transaction_connection_serializes_parallel_branches(self):
        from threading import Lock
        guard=Lock();active=0;peak=0
        def sql(*args):
            nonlocal active,peak
            with guard:active+=1;peak=max(peak,active)
            time.sleep(.01)
            with guard:active-=1
        native=SimpleNamespace(cursor=lambda:SimpleNamespace(execute=sql,description=None,rowcount=1,lastrowid=None,close=lambda:None),close=lambda:None)
        connection=JdbcConnection(native)
        with ThreadPoolExecutor(max_workers=8) as pool:
            results=list(pool.map(lambda _:execute({'driver':'mysql'},{'operation':'update','sql':'UPDATE items SET x=1'},connection,False),range(24)))
        self.assertEqual(peak,1);self.assertEqual(len(results),24)
        connection.close();connection.close()

    def test_connect_listener_config_is_rejected_explicitly(self):
        with self.assertRaisesRegex(Exception,'CONNECT'):
            listener_config({}, {'path':'/invalid','methods':'GET,CONNECT'})

    def test_ai_receiver_does_not_generate_tunnel_method(self):
        from app.ai_builder import local_proposal
        # Check the actual AI planning path, not just a hardcoded test-method list.
        plan=local_proposal('Create a REST API receiver and log the request','project')
        receivers=[item for task in plan['project']['tasks'] for item in task.get('activities',[]) if item.get('type') in ('http_listener','rest')]
        self.assertTrue(receivers)
        for item in receivers:self.assertNotIn('CONNECT',item.get('config',{}).get('methods',''))
