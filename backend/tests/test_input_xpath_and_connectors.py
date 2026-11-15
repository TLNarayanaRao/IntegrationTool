import asyncio
import base64
import io
import ssl
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch
from app.file_operations import file_activity
from app.jdbc import execute, metadata, test_connection, _coerce_parameter, JdbcAdapterError
from app.raw_python import mapper_xml_dependencies, raw_python_files
from app.runtime import WorkflowRuntime
from app.transfer import transfer


class InputXPathAndConnectorTests(unittest.TestCase):
    def test_xpath_in_generic_input_run_debug_and_both_archives(self):
        from tests.test_python_mapper_parity import PythonMapperParityTests
        helper=PythonMapperParityTests()
        mappings={'result.total':'xpath2("sum(/orders/order/@amount)")',
                  'result.name':'xpath1("local-name(/*)")',
                  'result.encoded':'xpath2("encode-for-uri(\'a b\')")',
                  'result.explicit':'xpath2("floor(9.8)", ${input.xmlString})'}
        project=helper.project(input_mappings=mappings)
        payload={'xmlString':'<orders><order amount="2"/><order amount="3"/></orders>'}
        expected={'total':5.0,'name':'orders','encoded':'a%20b','explicit':'9'}
        helper.assert_studio(project,payload,expected)
        helper.assert_exports(project,payload,expected)
        self.assertIn('elementpath>=5.1.4,<6',mapper_xml_dependencies(project))
        self.assertIn('application/native/mapper_xml.py',raw_python_files(project,{'local':[]}))

    def test_xpath_runtime_nested_function_and_conditions(self):
        runtime=WorkflowRuntime();ctx={'last':'<root/>','input':{},'vars':{},'properties':{},'activities':{}}
        self.assertEqual(runtime.resolve('concat("value:", xpath2("floor(2.8)"))',ctx),'value:2')
        self.assertTrue(runtime.condition('xpath2("count(/*)") = 1',ctx))
        ctx['properties']['source']='<root>property</root>'
        self.assertEqual(runtime.resolve('xpath2("string(/*)",${properties.source})',ctx),'property')
        ctx['last']={}
        self.assertEqual(runtime.resolve('xpath2("xs:integer(floor(2.8))")',ctx),2)
        with self.assertRaises(Exception): runtime.resolve('xpath2("doc(\'file:///secret\')")',ctx)

    def test_jdbc_input_xpath_parameter_in_run_debug_and_archives(self):
        from tests.test_python_mapper_parity import PythonMapperParityTests
        helper=PythonMapperParityTests()
        with tempfile.TemporaryDirectory() as folder:
            cfg={'driver':'sqlite','url':str(Path(folder)/'db.sqlite')}
            execute(cfg,{'operation':'dynamic','sql':'CREATE TABLE items(id INTEGER PRIMARY KEY, name TEXT)'})
            execute(cfg,{'operation':'insert','sql':"INSERT INTO items VALUES (2,'selected')"})
            project=helper.project();project['resources']=[{'id':'db','name':'db','type':'jdbc','config':cfg}]
            task=project['tasks'][0];nodes=task['activities'];nodes.insert(1,{'id':'Query','name':'Query','type':'jdbc','config':{'operation':'query','resourceId':'db','sql':'SELECT name FROM items WHERE id=:id','inputMappings':{'parameters.id':'xpath2("xs:integer(floor(2.8))")'}}})
            nodes[-1]['config']['inputMappings']={'result.rows':'${Query.rows}'}
            task['transitions']=[{'id':str(i),'source':a['id'],'target':b['id']} for i,(a,b) in enumerate(zip(nodes,nodes[1:]))]
            helper.assert_studio(project,{}, {'rows':[{'name':'selected'}]});helper.assert_exports(project,{}, {'rows':[{'name':'selected'}]})

    def test_context_free_xpath_with_json_payload_in_all_formats(self):
        from tests.test_python_mapper_parity import PythonMapperParityTests
        helper=PythonMapperParityTests();project=helper.project(input_mappings={'result.number':'xpath2("xs:integer(floor(2.8))")'})
        helper.assert_studio(project,{}, {'number':2});helper.assert_exports(project,{}, {'number':2})
        project=helper.project(input_mappings={'result.number':'custom:rounded(${input.number})'})
        project['custom_functions']=[{'id':'rounded','name':'rounded','parameters':['value'],'expression':'xpath2(concat("xs:integer(floor(", $value, "))"))'}]
        self.assertIn('elementpath>=5.1.4,<6',mapper_xml_dependencies(project))
        helper.assert_studio(project,{'number':2.8},{'number':2});helper.assert_exports(project,{'number':2.8},{'number':2})

    def test_file_guards_do_not_remove_source_or_destination(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);source=root/'source.txt';source.write_text('original')
            for operation in ('read','write','delete','list','poll','copy','rename'):
                with self.subTest(operation=operation),self.assertRaisesRegex(ValueError,'File path'):
                    file_activity(operation,{},'bad')
            for operation in ('copy','rename'):
                with self.assertRaisesRegex(ValueError,'different'):file_activity(operation,{'path':str(source),'destination':str(source),'overwrite':True},None)
                with self.assertRaisesRegex(ValueError,'Destination'):file_activity(operation,{'path':str(source)},None)
            with self.assertRaises(FileExistsError):file_activity('write',{'path':str(source)},'bad')
            self.assertEqual(source.read_text(),'original')
            with self.assertRaisesRegex(ValueError,'contain each other'):file_activity('copy',{'path':str(root),'destination':str(root/'nested')},None)
            with self.assertRaises(FileNotFoundError):file_activity('copy',{'path':str(root/'missing'),'destination':str(source),'overwrite':True},None)
            self.assertEqual(source.read_text(),'original')
            compressed=str(root/'data.gz')
            file_activity('write',{'path':compressed,'textContent':'round trip','compression':'gzip'},None)
            self.assertEqual(file_activity('read',{'path':compressed,'compression':'gzip'},None)['textContent'],'round trip')

    def test_file_operations_in_runtime_and_both_archives(self):
        from tests.test_python_mapper_parity import PythonMapperParityTests
        helper=PythonMapperParityTests()
        with tempfile.TemporaryDirectory() as folder:
            project=helper.project()
            task=project['tasks'][0];path=str(Path(folder)/'output.txt')
            specs=[('write',{'path':path,'textContent':'hello','overwrite':True}),('copy',{'path':path,'destination':path+'.copy','overwrite':True}),('read',{'path':path+'.copy'})]
            nodes=[task['activities'][0],*[{'id':op,'name':op,'type':'file','config':{'operation':op,**cfg}} for op,cfg in specs],task['activities'][-1]]
            nodes[-1]['config']['inputMappings']={'result.content':'${read.content}'}
            task['activities']=nodes;task['transitions']=[{'id':str(i),'source':a['id'],'target':b['id']} for i,(a,b) in enumerate(zip(nodes,nodes[1:]))]
            helper.assert_studio(project,{}, {'content':'hello'});helper.assert_exports(project,{}, {'content':'hello'})

    def test_ftp_tls_passive_mode_and_cleanup_even_on_login_failure(self):
        client=MagicMock()
        sent=[];client.storbinary.side_effect=lambda command,stream:sent.append(stream.read())
        with patch('app.transfer.ftplib.FTP_TLS',return_value=client),patch('app.transfer.ssl.create_default_context',return_value=ssl.create_default_context()):
            result=transfer('ftp','put',{'host':'host','tls':'true','passiveMode':'false','remotePath':'file','content':base64.b64encode(b'\x00\xff').decode(),'binary':True})
            self.assertEqual(result['size'],2);client.prot_p.assert_called_once();client.set_pasv.assert_called_once_with(False)
            self.assertEqual(sent,[b'\x00\xff']);self.assertTrue(client.storbinary.call_args.args[1].closed);client.close.assert_called_once()
        client=MagicMock();client.login.side_effect=RuntimeError('login failed')
        with patch('app.transfer.ftplib.FTP',return_value=client),self.assertRaisesRegex(RuntimeError,'login failed'):
            transfer('ftp','get',{'host':'host','remotePath':'file','tls':'false'})
        client.close.assert_called_once()

    def test_transfer_download_limits_unknown_operations_and_cleanup(self):
        for kind in ('ftp','sftp'):
            client=MagicMock();ssh=MagicMock();client.file.return_value=io.BytesIO(b'abcdef')
            client.retrbinary.side_effect=lambda _,callback:callback(b'abcdef')
            with patch('app.transfer.ftplib.FTP',return_value=client),patch('app.transfer.open_connection',return_value=(ssh,client)):
                with self.assertRaisesRegex(ValueError,'maximum download'):transfer(kind,'get',{'remotePath':'file','maxDownloadBytes':3})
            client.close.assert_called_once()
            if kind=='sftp':ssh.close.assert_called_once()
        with self.assertRaisesRegex(ValueError,'Unsupported'):transfer('ftp','unknown',{})
        with self.assertRaisesRegex(ValueError,'control characters'):transfer('ftp','delete',{'remotePath':'file\r\nDELE other'})

    def test_database_probe_sql_and_cleanup(self):
        for driver,sql in (('oracle','SELECT 1 FROM DUAL'),('db2','VALUES 1'),('postgresql','SELECT 1'),('mysql','SELECT 1')):
            connection=MagicMock()
            with patch('app.jdbc.connect',return_value=connection),patch('app.jdbc._uses_java',return_value=False):test_connection({'driver':driver})
            connection.cursor.return_value.execute.assert_called_once_with(sql)
            connection.cursor.return_value.close.assert_called_once();connection.close.assert_called_once()

    def test_database_strict_types_flags_and_atomic_batch_rollback(self):
        for value,kind in ((1.2,'integer'),('NaN','integer'),('maybe','boolean')):
            with self.subTest(value=value),self.assertRaises((ValueError,JdbcAdapterError)):_coerce_parameter(value,kind)
        self.assertEqual(_coerce_parameter('false','boolean'),False)
        with tempfile.TemporaryDirectory() as folder:
            cfg={'driver':'sqlite','url':str(Path(folder)/'db.sqlite')}
            execute(cfg,{'operation':'dynamic','sql':'CREATE TABLE items(id INTEGER PRIMARY KEY, name TEXT)'})
            execute(cfg,{'operation':'insert','sql':'INSERT INTO items VALUES (:id,:name)','parameters':{'id':1,'name':''},'batchUpdate':'false','interpretEmptyStringAsNull':'false'})
            with self.assertRaises(JdbcAdapterError):execute(cfg,{'operation':'insert','sql':'INSERT INTO items VALUES (:id,:name)','batchUpdate':True,'records':[{'id':2,'name':'temporary'},{'id':1,'name':'duplicate'}]})
            self.assertEqual(execute(cfg,{'operation':'query','sql':'SELECT * FROM items','processInSubsets':'false','subsetSize':1})['rows'],[{'id':1,'name':''}])
            from app.jdbc import connect
            connection=connect(cfg)
            try:
                before=connection.execute('PRAGMA busy_timeout').fetchone()[0]
                execute(cfg,{'operation':'query','sql':'SELECT * FROM items','timeout':1},connection,False)
                self.assertEqual(connection.execute('PRAGMA busy_timeout').fetchone()[0],before)
            finally:connection.close()

    def test_mysql_metadata_uses_selected_database(self):
        connection=MagicMock();connection.cursor.return_value.fetchall.return_value=[]
        with patch('app.jdbc.connect',return_value=connection):metadata({'driver':'mysql','url':'jdbc:mysql://localhost/integration'})
        self.assertEqual(connection.cursor.return_value.execute.call_args.args[1],('integration',))
