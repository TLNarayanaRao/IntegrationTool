import asyncio
import contextlib
import gc
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
import tempfile
import subprocess
import sys
import threading
import time
import unittest
import weakref
from unittest.mock import Mock,patch

from app import http_transport as http,jdbc,snowflake


class HttpDatabaseResourceTests(unittest.TestCase):
    def test_reset_connection_cancels_keepalive_and_releases_protocol_without_gc(self):
        from app.http1_protocol import StatusLineProtocol
        from uvicorn import Config
        from uvicorn.server import ServerState
        async def app(scope,receive,send):pass
        config=Config(app,log_config=None,lifespan='off');config.load()
        loop=asyncio.new_event_loop();enabled=gc.isenabled();gc.disable()
        try:
            protocol=StatusLineProtocol(config,ServerState(),{},_loop=loop)
            protocol.transport=Mock()
            handle=loop.call_later(3600,protocol.timeout_keep_alive_handler)
            protocol.timeout_keep_alive_task=handle
            reference=weakref.ref(protocol)
            protocol.connection_lost(ConnectionResetError('test client reset'))
            self.assertTrue(handle.cancelled())
            self.assertIsNone(protocol.timeout_keep_alive_task)
            del protocol
            self.assertIsNone(reference())
        finally:
            if enabled:gc.enable()
            loop.close();gc.collect()

    def test_schema_validator_type_is_reused_without_retaining_values(self):
        from app.schema_validation import schema_errors
        import jsonschema
        class Payload(dict):pass
        with patch('jsonschema.validators.extend',wraps=jsonschema.validators.extend) as extended:
            for _ in range(80):
                value=Payload(data='x'*65536);reference=weakref.ref(value)
                self.assertEqual(schema_errors(value,{'type':'object'}),[])
                del value
                self.assertIsNone(reference())
            self.assertLessEqual(extended.call_count,1)

    def test_cached_schema_types_keep_schemas_and_thread_budgets_independent(self):
        from app.schema_validation import schema_errors,_VALIDATION_BUDGET
        def check(number):
            schema={'$defs':{'value':{'type':'integer' if number%2 else 'string'}},'$ref':'#/$defs/value'}
            value=number if number%2 else str(number)
            for _ in range(30):
                self.assertEqual(schema_errors(value,schema),[])
                self.assertTrue(schema_errors(None,schema))
                self.assertIsNone(_VALIDATION_BUDGET.get())
        with ThreadPoolExecutor(max_workers=8) as pool:list(pool.map(check,range(16)))

    def test_schema_budget_resets_after_timeout(self):
        from app.schema_validation import schema_errors,_VALIDATION_BUDGET
        self.assertEqual(schema_errors(1,{'type':'integer'}),[])
        with patch('app.schema_validation.time.monotonic',side_effect=[0,6]):
            with self.assertRaisesRegex(ValueError,'Invalid or unresolved') as failure:
                schema_errors(1,{'type':'integer'})
        self.assertIn('budget exceeded',str(failure.exception.__cause__))
        self.assertIsNone(_VALIDATION_BUDGET.get())
        self.assertEqual(schema_errors(1,{'type':'integer'}),[])

    def test_status_line_wrapper_does_not_keep_protocol_alive_until_cyclic_gc(self):
        from app.http1_protocol import StatusLineProtocol
        from uvicorn import Config
        from uvicorn.server import ServerState
        async def app(scope,receive,send):pass
        config=Config(app,log_config=None,lifespan='off');config.load()
        loop=asyncio.new_event_loop();enabled=gc.isenabled();gc.disable()
        try:
            protocol=StatusLineProtocol(config,ServerState(),{},_loop=loop)
            reference=weakref.ref(protocol)
            del protocol
            self.assertIsNone(reference(),'Protocol should release by reference counting, not wait for cyclic GC')
        finally:
            if enabled:gc.enable()
            loop.close();gc.collect()

    def jdbc_project(self,driver,mode=None):
        from tests.test_python_mapper_parity import PythonMapperParityTests
        project=PythonMapperParityTests().project()
        cfg={'driver':driver}
        if mode:cfg['connectionMode']=mode
        project['resources']=[{'id':'db','name':'db','type':'jdbc','config':cfg}]
        task=project['tasks'][0];task['activities'].insert(1,{'id':'Query','name':'Query','type':'jdbc','config':{'operation':'query','resourceId':'db','sql':'SELECT 1','maxRows':1}})
        task['transitions']=[{'id':str(i),'source':a['id'],'target':b['id']} for i,(a,b) in enumerate(zip(task['activities'],task['activities'][1:]))]
        return project

    def test_archive_requirements_distinguish_native_and_java_database_modes(self):
        from app.raw_python import raw_python_requirements
        for driver,module in [('mysql','pymysql'),('mariadb','pymysql'),('postgresql','psycopg'),('oracle','oracledb'),('mssql','pyodbc'),('db2','ibm_db_dbi'),('databricks','databricks.sql'),('snowflake','snowflake.connector')]:
            with self.subTest(driver=driver):
                requirements,_=raw_python_requirements(self.jdbc_project(driver,'python'))
                self.assertTrue(any(module in item['modules'] for item in requirements))
                self.assertFalse(any(item['java'] for item in requirements))
        for driver in ('oracle','sqlserver'):
            requirements,_=raw_python_requirements(self.jdbc_project(driver,'jdbc'))
            self.assertTrue(any(item['java'] for item in requirements))
        requirements,_=raw_python_requirements(self.jdbc_project('sqlite'))
        self.assertFalse(any(item['java'] for item in requirements))
        project=self.jdbc_project('${properties.db.driver}','${properties.db.mode}')
        project['properties']={'local':[{'key':'db.driver','value':'mysql'},{'key':'db.mode','value':'python'}],
                               'production':[{'key':'db.driver','value':'oracle'},{'key':'db.mode','value':'jdbc'}]}
        requirements,_=raw_python_requirements(project)
        modules={module for item in requirements for module in item['modules']}
        self.assertIn('pymysql',modules);self.assertNotIn('oracledb',modules)
        self.assertTrue(any(item['java'] for item in requirements))
        project=self.jdbc_project('oracle','jdbc')
        project['tasks'][0]['activities'][1].update(type='log',config={'message':'transaction scope'})
        project['tasks'][0]['groups']=[{'id':'tx','name':'tx','type':'transaction_jdbc','member_activity_ids':['Query'],'config':{'resourceId':'db'}}]
        requirements,_=raw_python_requirements(project)
        self.assertTrue(any(item['java'] for item in requirements))

    def test_snowflake_jdbc_dependency_and_cleanup_in_both_archives(self):
        from app.raw_python import raw_python_files,engine_python_files
        project=self.jdbc_project('snowflake')
        for compiler,package in ((raw_python_files,'application.native'),(engine_python_files,'application.engine')):
            with self.subTest(format=compiler.__name__),tempfile.TemporaryDirectory() as folder:
                for name,data in compiler(project,{'local':[]}).items():
                    path=Path(folder)/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(data)
                code=f'''
from {package} import jdbc,snowflake
from unittest.mock import Mock,patch
connection=Mock();cursor=connection.cursor.return_value
cursor.description=[('VALUE',None)];cursor.fetchmany.return_value=[(1,)];cursor.fetchall.return_value=[(1,)]
with patch.object(snowflake,'connect',return_value=connection):
 result=jdbc.execute({{'driver':'snowflake'}},{{'sql':'SELECT 1','maxRows':1}})
assert result['rows']==[{{'VALUE':1}}],result
cursor.close.assert_called_once();connection.close.assert_called_once()
'''
                result=subprocess.run([sys.executable,'-c',code],cwd=folder,capture_output=True,text=True,timeout=20)
                self.assertEqual(result.returncode,0,result.stdout+result.stderr)

    def test_anonymous_http_avoids_the_authentication_executor(self):
        from app.http_server import ListenerApp, listener_config
        from fastapi.testclient import TestClient

        async def handler(_metadata, _payload):
            return {'body': 'ready'}

        connection = {'minimumQtpThreads': 2, 'maximumQtpThreads': 2}
        config = listener_config(connection, {'path': '/', 'methods': 'GET'})
        with patch.object(ThreadPoolExecutor, 'submit', side_effect=AssertionError('unexpected worker')):
            listener = ListenerApp([(None, config)], handler, connection)
            with TestClient(listener) as client:
                self.assertEqual(client.get('/').json(), {'body': 'ready'})

    def test_listener_worker_warmup_failure_aborts_waiters_and_closes_executor(self):
        from app.http_server import ListenerApp
        created=[]
        def executor(*args,**kwargs):
            pool=ThreadPoolExecutor(*args,**kwargs);created.append(pool)
            submit=pool.submit;calls=0
            def fail(*args,**kwargs):
                nonlocal calls
                calls+=1
                if calls==2:raise RuntimeError('worker startup failed')
                return submit(*args,**kwargs)
            pool.submit=fail
            return pool
        with patch('app.http_server.ThreadPoolExecutor',side_effect=executor):
            with self.assertRaisesRegex(RuntimeError,'worker startup failed'):
                ListenerApp([(None, {'path': '/', 'authentication': 'Basic'})],lambda *_:None,
                            {'minimumQtpThreads':2,'maximumQtpThreads':2})
        for pool in created:
            self.assertTrue(pool._shutdown);pool.shutdown(wait=True)
            self.assertFalse(any(thread.is_alive() for thread in pool._threads))

    def client(self):
        return SimpleNamespace(_mina_lock=threading.Lock(),_mina_routes={},_mina_route_limit=1)

    def test_dynamic_destinations_do_not_retain_idle_gates(self):
        client=self.client()
        for index in range(5000):
            route=f'host-{index}:443'
            gate=http._acquire_route(client,route,.1)
            http._release_route(client,route,gate)
        self.assertEqual(client._mina_routes,{})
        self.assertEqual(client._mina_route_users,{})

    def test_waiting_requests_keep_the_same_route_gate_and_timeout_cleanup(self):
        client=self.client();first=http._acquire_route(client,'host',1)
        acquired=threading.Event();finish=threading.Event()
        def waiter():
            gate=http._acquire_route(client,'host',2)
            try:
                self.assertIs(gate,first);acquired.set();finish.wait(3)
            finally:http._release_route(client,'host',gate)
        with ThreadPoolExecutor(max_workers=1) as pool:
            future=pool.submit(waiter)
            try:
                deadline=time.monotonic()+2
                while client._mina_route_users['host']<2 and time.monotonic()<deadline:time.sleep(.005)
                with self.assertRaises(http.HTTPFault):http._acquire_route(client,'host',.02)
                self.assertEqual(client._mina_route_users['host'],2)
                http._release_route(client,'host',first)
                self.assertTrue(acquired.wait(2))
                with self.assertRaises(http.HTTPFault):http._acquire_route(client,'host',.02)
            finally:finish.set()
            future.result(3)
        self.assertEqual(client._mina_routes,{})

    def test_all_scoped_clients_and_tokens_close_even_if_one_close_fails(self):
        bad=SimpleNamespace(_mina_scope='owned',close=Mock(side_effect=RuntimeError('close failed')))
        good=SimpleNamespace(_mina_scope='owned',close=Mock())
        other=SimpleNamespace(_mina_scope='other',close=Mock())
        with patch.object(http,'_POOL',{'bad':bad,'good':good,'other':other}),patch.object(http,'_TOKENS',{'a':'one','b':'two'}),patch.object(http,'_TOKEN_SCOPES',{'a':'owned','b':'other'}):
            with self.assertRaisesRegex(RuntimeError,'close failed'):http.close_clients('owned')
            good.close.assert_called_once();other.close.assert_not_called()
            self.assertEqual(set(http._POOL),{'other'});self.assertEqual(http._TOKENS,{'b':'two'})

    def test_jdbc_metadata_closes_cursor_and_connection_on_errors(self):
        for failure in (None,RuntimeError('query failed')):
            connection=Mock();cursor=connection.cursor.return_value
            cursor.fetchall.return_value=[];cursor.execute.side_effect=failure
            with patch.object(jdbc,'connect',return_value=connection):
                if failure:
                    with self.assertRaisesRegex(RuntimeError,'query failed'):jdbc.metadata({'driver':'mysql'})
                else:self.assertEqual(jdbc.metadata({'driver':'mysql'})['tables'],[])
            cursor.close.assert_called_once();connection.close.assert_called_once()

    def test_snowflake_cursors_close_on_success_and_failure(self):
        for failure in (None,RuntimeError('query failed')):
            connection=Mock();cursor=connection.cursor.return_value
            cursor.description=[('ID',)];cursor.fetchmany.return_value=[(1,)];cursor.execute.side_effect=failure
            with patch.object(snowflake,'connect',return_value=connection):
                if failure:
                    with self.assertRaises(snowflake.SnowflakeAdapterError):snowflake.execute({}, {'operation':'query','statement':'SELECT 1','maximumRows':1},{})
                else:self.assertEqual(snowflake.execute({}, {'operation':'query','statement':'SELECT 1','maximumRows':1},{})['rows'],[{'ID':1}])
            cursor.close.assert_called_once();connection.close.assert_called_once()

    def test_snowflake_generated_csv_is_removed_on_put_and_csv_writer_failures(self):
        original=tempfile.NamedTemporaryFile
        for writer_failure in (False,True):
            with tempfile.TemporaryDirectory() as folder:
                connection=Mock();cursor=connection.cursor.return_value
                def sql(statement,*args):
                    if statement.startswith('PUT '):raise RuntimeError('upload failed')
                cursor.execute.side_effect=sql
                def temporary(*args,**kwargs):return original(*args,**kwargs,dir=folder)
                with patch.object(snowflake,'connect',return_value=connection),patch.object(snowflake.tempfile,'NamedTemporaryFile',side_effect=temporary):
                    with self.assertRaises(snowflake.SnowflakeAdapterError):
                        snowflake.execute({'database':'DB','schema':'PUBLIC'},{'operation':'bulk_load','tableName':'ORDERS','valueColumns':'ID'},[{'unexpected' if writer_failure else 'ID':1}])
                self.assertEqual(list(Path(folder).iterdir()),[])
                cursor.close.assert_called_once();connection.close.assert_called_once()

    def test_failed_bulk_upload_does_not_delete_user_supplied_file(self):
        with tempfile.TemporaryDirectory() as folder:
            source=Path(folder)/'orders.csv';source.write_text('ID\n1\n')
            connection=Mock();connection.cursor.return_value.execute.side_effect=RuntimeError('upload failed')
            with patch.object(snowflake,'connect',return_value=connection),self.assertRaises(snowflake.SnowflakeAdapterError):
                snowflake.execute({'database':'DB','schema':'PUBLIC'},{'operation':'bulk_load','tableName':'ORDERS','filePath':str(source)},[])
            self.assertEqual(source.read_text(),'ID\n1\n')

    def test_listener_startup_failure_releases_warmed_executor(self):
        from app.http_server import _serve_http1
        created=[]
        def executor(*args,**kwargs):
            value=ThreadPoolExecutor(*args,**kwargs);created.append(value);return value
        async def handler(*args):return {'body':'ok'}
        with patch('app.http_server.ThreadPoolExecutor',side_effect=executor),patch('uvicorn.Config.load',side_effect=RuntimeError('TLS configuration failed')):
            with self.assertRaisesRegex(RuntimeError,'TLS configuration failed'):
                asyncio.run(_serve_http1([(None,{'host':'127.0.0.1','port':12345,'minimumQtpThreads':2},{'path':'/','methods':'GET'})],handler))
        self.assertTrue(created);self.assertTrue(all(pool._shutdown for pool in created))

    def test_policy_failure_cannot_retain_route_permit(self):
        import httpx
        client=self.client()
        client.build_request=Mock(side_effect=RuntimeError('request failed'))
        with patch.object(http,'client_for',return_value=client),patch.object(http,'circuit_result',side_effect=RuntimeError('policy failed')):
            with self.assertRaisesRegex(RuntimeError,'policy failed'):http.request({'url':'http://test'})
        self.assertEqual(client._mina_routes,{})
