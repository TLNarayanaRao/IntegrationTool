"""Opt-in private MySQL instance: MINA_TEST_MYSQLD points to an installed mysqld.

The fixture creates its own datadir, TLS certificates and database under tmp.
It never reads an installed server configuration or its existing data.
"""
import os
import asyncio
import json
import sys
import socket
import subprocess
import tempfile
import time
import unittest
import uuid
from pathlib import Path
from app.jdbc import execute,connect,JdbcAdapterError


@unittest.skipUnless(os.environ.get('MINA_TEST_MYSQLD'),'Set MINA_TEST_MYSQLD to run disposable real MySQL integration tests')
class MySQLLiveTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from tests.connector_fixtures import certificates
        cls.workspace=tempfile.TemporaryDirectory(prefix='mysql-qualification-',dir=Path(__file__).resolve().parents[2]/'tmp')
        root=Path(cls.workspace.name);data=root/'data';log=root/'server.log';exe=Path(os.environ['MINA_TEST_MYSQLD']).resolve()
        cls.process=None
        try:
            tls=certificates(root)
            init=subprocess.run([str(exe),'--no-defaults','--initialize-insecure',f'--basedir={exe.parents[1]}',f'--datadir={data}',f'--log-error={log}'],capture_output=True,text=True,timeout=90,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            if init.returncode:raise RuntimeError('Disposable MySQL initialization failed: '+log.read_text(errors='replace')[-2000:])
            with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
            cls.process=subprocess.Popen([str(exe),'--no-defaults',f'--basedir={exe.parents[1]}',f'--datadir={data}','--bind-address=127.0.0.1',f'--port={port}','--mysqlx=OFF','--skip-log-bin',f'--log-error={log}',f'--ssl-ca={tls["ca"]}',f'--ssl-cert={tls["cert"]}',f'--ssl-key={tls["key"]}'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            cls.config={'driver':'mysql','host':'127.0.0.1','port':port,'username':'root','password':'','sslCaFile':str(tls['ca']),'timeoutSeconds':3}
            deadline=time.monotonic()+60
            while True:
                try:
                    connection=connect(cls.config);connection.close();break
                except Exception:
                    if cls.process.poll() is not None or time.monotonic()>deadline:raise RuntimeError('Disposable MySQL failed to start: '+log.read_text(errors='replace')[-2000:])
                    time.sleep(.2)
            execute(cls.config,{'operation':'dynamic','sql':'CREATE DATABASE mina_connector_qa'})
            cls.config['database']='mina_connector_qa'
        except BaseException:
            cls.tearDownClass();raise

    @classmethod
    def tearDownClass(cls):
        if cls.process is not None and cls.process.poll() is None:
            try:
                connection=connect(cls.config)
                try:connection.cursor().execute('SHUTDOWN')
                finally:connection.close()
            except Exception:cls.process.terminate()
            try:cls.process.wait(15)
            except subprocess.TimeoutExpired:cls.process.kill();cls.process.wait(5)
        cls.workspace.cleanup()

    def test_live_crud_run_debug_and_both_archives(self):
        from tests.test_python_mapper_parity import PythonMapperParityTests
        helper=PythonMapperParityTests();table='crud_'+uuid.uuid4().hex
        execute(self.config,{'operation':'dynamic','sql':f'CREATE TABLE {table}(id INT PRIMARY KEY,name VARCHAR(40))'})
        try:
            specs=[('Insert','insert',f'INSERT INTO {table} VALUES (:id,:name)',{'parameters':{'id':1,'name':'Ada'}}),('Update','update',f'UPDATE {table} SET name=:name WHERE id=:id',{'parameters':{'id':1,'name':'Updated'}}),('Query','query',f'SELECT * FROM {table}',{}),('Delete','delete',f'DELETE FROM {table}',{})]
            project=helper.project();project['resources']=[{'id':'db','type':'jdbc','name':'db','config':self.config}]
            task=project['tasks'][0];nodes=[task['activities'][0],*[{'id':name,'type':'jdbc','name':name,'config':{'resourceId':'db','operation':operation,'sql':sql,**options}} for name,operation,sql,options in specs],task['activities'][-1]]
            nodes[-1]['config']['inputMappings']={'result.rows':'${Query.rows}'}
            task['activities']=nodes;task['transitions']=[{'id':str(i),'source':a['id'],'target':b['id']} for i,(a,b) in enumerate(zip(nodes,nodes[1:]))]
            helper.assert_studio(project,{}, {'rows':[{'id':1,'name':'Updated'}]});helper.assert_exports(project,{}, {'rows':[{'id':1,'name':'Updated'}]})
        finally:execute(self.config,{'operation':'dynamic','sql':f'DROP TABLE {table}'})

    def test_live_batch_rollback_paging_and_typed_procedure_out(self):
        table='batch_'+uuid.uuid4().hex;procedure='total_'+uuid.uuid4().hex
        execute(self.config,{'operation':'dynamic','sql':f'CREATE TABLE {table}(id INT PRIMARY KEY,amount INT)'})
        try:
            with self.assertRaises(JdbcAdapterError):execute(self.config,{'operation':'insert','sql':f'INSERT INTO {table} VALUES (:id,:amount)','batchUpdate':True,'records':[{'id':1,'amount':2},{'id':1,'amount':3}]})
            self.assertEqual(execute(self.config,{'sql':f'SELECT * FROM {table}'})['rows'],[])
            execute(self.config,{'operation':'insert','sql':f'INSERT INTO {table} VALUES (?,?)','batchUpdate':True,'preparedParameters':[{'name':'id','type':'integer'},{'name':'amount','type':'integer'}],'records':[['1','2'],['2','3']]})
            page=execute(self.config,{'sql':f'SELECT * FROM {table} ORDER BY id','processInSubsets':True,'subsetSize':1})
            self.assertFalse(page['lastSubset']);self.assertEqual(page['nextRowOffset'],1)
            execute(self.config,{'operation':'dynamic','sql':f'CREATE PROCEDURE {procedure}(IN first INT, OUT total INT) BEGIN SET total=first+10; SELECT first AS original; END'})
            cfg={'operation':'call','procedure':procedure,'parameters':{'first':'7'},'preparedParameters':[{'name':'first','type':'integer'},{'name':'total','type':'integer','direction':'OUT'}]}
            result=execute(self.config,cfg);self.assertEqual(result['outParameters'],{'total':17});self.assertEqual(result['resultSets'][0],[{'original':7}])
            from tests.test_python_mapper_parity import PythonMapperParityTests
            helper=PythonMapperParityTests();project=helper.project();project['resources']=[{'id':'db','name':'db','type':'jdbc','config':self.config}]
            task=project['tasks'][0];task['activities'].insert(1,{'id':'Call','name':'Call','type':'jdbc','config':{'resourceId':'db',**cfg}})
            task['activities'][-1]['config']['inputMappings']={'result.total':'${Call.outParameters.total}'}
            task['transitions']=[{'id':str(i),'source':a['id'],'target':b['id']} for i,(a,b) in enumerate(zip(task['activities'],task['activities'][1:]))]
            helper.assert_studio(project,{}, {'total':17});helper.assert_exports(project,{}, {'total':17})
        finally:
            execute(self.config,{'operation':'dynamic','sql':f'DROP PROCEDURE IF EXISTS {procedure}'})
            execute(self.config,{'operation':'dynamic','sql':f'DROP TABLE {table}'})

    def test_live_transaction_group_rolls_back_in_run_debug_and_both_archives(self):
        from tests.test_python_mapper_parity import PythonMapperParityTests
        from app.models import Project
        from app.runtime import WorkflowRuntime
        from app.debugger import DebugManager
        from app.raw_python import raw_python_files,engine_python_files
        table='tx_'+uuid.uuid4().hex
        execute(self.config,{'operation':'dynamic','sql':f'CREATE TABLE {table}(id INT)'})
        try:
            project=PythonMapperParityTests().project();project['resources']=[{'id':'db','type':'jdbc','name':'db','config':self.config}]
            task=project['tasks'][0];nodes=task['activities'];nodes[1:1]=[{'id':'Insert','name':'Insert','type':'jdbc','config':{'operation':'insert','resourceId':'db','sql':f'INSERT INTO {table} VALUES (1)'}},{'id':'Fail','name':'Fail','type':'throw','config':{'message':'rollback qualification'}}]
            task['groups']=[{'id':'tx','name':'tx','type':'transaction_jdbc','member_activity_ids':['Insert','Fail'],'config':{'resourceId':'db'}}]
            task['transitions']=[{'id':str(i),'source':a['id'],'target':b['id']} for i,(a,b) in enumerate(zip(nodes,nodes[1:]))]
            model=Project.model_validate(project);resources={item.id:item for item in model.resources}
            async def run():
                runtime=WorkflowRuntime();result=await runtime.run(model.tasks[0],{},resources=resources,project=model)
                self.assertEqual(result.status,'failed')
                debug=DebugManager(runtime);session=debug.start(model,'main',{},resources,{},[])['sessionId']
                result=await debug.action(session,'continue');self.assertEqual(result['status'],'failed')
            asyncio.run(run())
            for compiler in (raw_python_files,engine_python_files):
                with tempfile.TemporaryDirectory() as folder:
                    for name,data in compiler(project,{'local':[]}).items():
                        path=Path(folder)/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(data)
                    command=['run.py'] if compiler is raw_python_files else ['-m','application.main']
                    result=subprocess.run([sys.executable,*command,'--task','main'],cwd=folder,capture_output=True,text=True,timeout=30)
                    self.assertNotEqual(result.returncode,0,result.stdout)
            self.assertEqual(execute(self.config,{'sql':f'SELECT * FROM {table}'})['rows'],[])
        finally:execute(self.config,{'operation':'dynamic','sql':f'DROP TABLE {table}'})

    def test_live_mysql_socket_read_timeout_is_enforced(self):
        start=time.monotonic()
        with self.assertRaises(JdbcAdapterError):execute({**self.config,'readTimeoutSeconds':1},{'sql':'SELECT SLEEP(3)'})
        self.assertLess(time.monotonic()-start,2.8)

    def test_live_shared_transaction_serializes_concurrent_operations(self):
        from concurrent.futures import ThreadPoolExecutor
        table='parallel_'+uuid.uuid4().hex
        execute(self.config,{'operation':'dynamic','sql':f'CREATE TABLE {table}(id INT PRIMARY KEY)'})
        connection=connect(self.config)
        try:
            with ThreadPoolExecutor(max_workers=8) as pool:
                list(pool.map(lambda number:execute(self.config,{'operation':'insert','sql':f'INSERT INTO {table} VALUES (:id)','parameters':{'id':number}},connection,False),range(24)))
            connection.commit()
            self.assertEqual(execute(self.config,{'sql':f'SELECT COUNT(*) AS total FROM {table}'})['rows'],[{'total':24}])
        finally:
            connection.close();execute(self.config,{'operation':'dynamic','sql':f'DROP TABLE {table}'})

    def test_live_failed_sessions_release_sockets_before_traceback_gc(self):
        import gc,weakref
        from unittest.mock import patch
        references=[];errors=[]
        def opened(config):
            connection=connect(config);references.append(weakref.ref(connection));return connection
        with patch('app.jdbc.connect',side_effect=opened):
            for _ in range(50):
                try:execute(self.config,{'sql':'SELECT * FROM definitely_missing_gc_qa_table'})
                except JdbcAdapterError as error:errors.append(error)
        self.assertEqual(len(errors),50)
        self.assertTrue(all(reference() is None or reference()._mina_closed and reference()._mina_connection._sock is None for reference in references))
        errors.clear();gc.collect()
        self.assertEqual(sum(reference() is not None for reference in references),0)
