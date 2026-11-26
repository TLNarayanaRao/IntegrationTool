import base64
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock,patch
from app.file_operations import file_activity,staged_file
from app.jdbc import execute,_parameters,_write_batch,_java_execute,_connect_mysql,JdbcAdapterError


class ConnectorProductionTests(unittest.TestCase):
    def test_file_copy_finishes_attributes_before_publishing(self):
        import stat
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source, target = root / 'source', root / 'target'
            source.write_bytes(b'new')
            target.write_bytes(b'old')
            config = {'path': str(source), 'destination': str(target)}
            with patch('app.file_operations.shutil.copystat', side_effect=PermissionError('cannot copy attributes')):
                with self.assertRaisesRegex(PermissionError, 'cannot copy attributes'):
                    file_activity('copy', {**config, 'overwrite': True}, None)
            self.assertEqual(target.read_bytes(), b'old')
            self.assertFalse(list(root.glob('.mina-*')))
            target.unlink()
            source.chmod(stat.S_IREAD)
            try:
                file_activity('copy', config, None)
                self.assertEqual(target.read_bytes(), b'new')
                self.assertEqual(target.stat().st_mtime_ns, source.stat().st_mtime_ns)
                self.assertFalse(list(root.glob('.mina-*')))
                with self.assertRaises(FileExistsError):
                    with staged_file(target) as stage:
                        stage.write_bytes(b'candidate')
                        stage.chmod(stat.S_IREAD)
                self.assertEqual(target.read_bytes(), b'new')
                self.assertFalse(list(root.glob('.mina-*')))
            finally:
                source.chmod(stat.S_IREAD | stat.S_IWRITE)
                if target.exists():
                    target.chmod(stat.S_IREAD | stat.S_IWRITE)

    def test_failed_file_write_copy_and_directory_replacement_preserve_destination(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);source=root/'source';target=root/'target';source.write_text('new');target.write_text('old')
            for mode in ('write','copy','rename'):
                with patch('app.file_operations.os.replace',side_effect=PermissionError('locked')),self.assertRaises(PermissionError):
                    file_activity(mode,{'path':str(target) if mode=='write' else str(source),'destination':str(target),'overwrite':True,'textContent':'new'},None)
                self.assertEqual(target.read_text(),'old');self.assertTrue(source.exists())
            self.assertFalse(list(root.glob('.mina-*')))
            source.unlink();source.mkdir();(source/'new').write_text('new');target.unlink();target.mkdir();(target/'old').write_text('old')
            import os
            replace=os.replace
            def fail_publish(a,b):
                if Path(b)==target and '.mina-backup-' not in str(a):raise PermissionError('publish failed')
                return replace(a,b)
            with patch('app.file_operations.os.replace',side_effect=fail_publish),self.assertRaises(PermissionError):file_activity('copy',{'path':str(source),'destination':str(target),'overwrite':True},None)
            self.assertEqual((target/'old').read_text(),'old');self.assertTrue((source/'new').exists())
            self.assertFalse(list(root.glob('.mina-*')))

    def test_exclusive_publication_and_gzip_decompression_limit(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);path=root/'file'
            with self.assertRaises(FileExistsError):
                with staged_file(path) as stage:stage.write_text('new');path.write_text('concurrent')
            self.assertEqual(path.read_text(),'concurrent')
            file_activity('write',{'path':str(path),'overwrite':True,'compression':'gzip','textContent':'x'*100000},None)
            with self.assertRaisesRegex(ValueError,'maximum read'):file_activity('read',{'path':str(path),'compression':'gzip','maxReadBytes':1000},None)
            with self.assertRaises(Exception):file_activity('write',{'path':str(path),'overwrite':True,'binaryContent':'%%%bad-base64'},None)
            self.assertEqual(file_activity('read',{'path':str(path),'compression':'gzip'},None)['textContent'],'x'*100000)

    def test_positional_database_types_batch_validation_and_timeouts(self):
        cfg={'preparedParameters':[{'name':'id','type':'integer'},{'name':'enabled','type':'boolean'}],'parameters':['2','false']}
        self.assertEqual(_parameters(cfg),[2,False])
        self.assertEqual(_parameters({**cfg,'parameters':['',''],'interpretEmptyStringAsNull':True}),[None,None])
        self.assertEqual(_parameters({'parameters':[{'value':'','type':'integer'}],'interpretEmptyStringAsNull':True}),[None])
        with self.assertRaises(JdbcAdapterError):_write_batch({**cfg,'batchUpdate':True,'records':[['2.8','false']]},'insert')
        for value in (-1,1.5,'NaN'):
            with self.assertRaises(JdbcAdapterError):execute({'driver':'sqlite'},{'timeout':value})
        for driver,field,multiplier in (('oracle','call_timeout',1000),('sqlserver','timeout',1)):
            connection=MagicMock();setattr(connection,field,7);cursor=connection.cursor.return_value;cursor.description=None;cursor.rowcount=1
            with patch('app.jdbc._uses_java',return_value=False):execute({'driver':driver},{'operation':'update','sql':'UPDATE t SET x=1','timeout':2},connection,False)
            self.assertEqual(getattr(connection,field),7)

    def test_mysql_verified_tls_and_bounded_io(self):
        with patch('pymysql.connect') as connect:_connect_mysql({'host':'localhost','sslCaFile':'trusted.pem','timeoutSeconds':10,'readTimeoutSeconds':3,'writeTimeoutSeconds':4})
        self.assertEqual((connect.call_args.kwargs['read_timeout'],connect.call_args.kwargs['write_timeout']),(3,4))
        self.assertTrue(connect.call_args.kwargs['ssl_verify_cert']);self.assertTrue(connect.call_args.kwargs['ssl_verify_identity'])

    def test_jdbc_call_typed_directions_and_identifier_validation(self):
        config={'operation':'call','procedure':'schema.total','parameters':{'id':'2'},'preparedParameters':[{'name':'id','type':'integer'},{'name':'total','type':'integer','direction':'OUT'}]}
        with patch('app.jdbc.invoke_java',return_value={}) as invoke:_java_execute({'driver':'oracle','serviceName':'qa'},config)
        values=invoke.call_args.args[2]
        self.assertEqual(values['sql'],'{call schema.total(?,?)}');self.assertEqual(values['parameter.1.direction'],'OUT');self.assertEqual(values['parameter.1.declaredType'],'integer')
        for name in ('p; DROP TABLE items','p(1)','p --comment'):
            with self.assertRaises(JdbcAdapterError):_java_execute({'driver':'oracle','serviceName':'qa'},{**config,'procedure':name})

    def test_native_and_jdbc_decimal_parameters_retain_precision(self):
        exact='12345678901234567890.123456789'
        for driver in ('java','oracle','mysql','sqlserver'):
            values=_parameters({'parameters':[exact],'preparedParameters':[{'name':'amount','type':'decimal'}]},driver)
            self.assertEqual(str(values[0]),exact)
        with patch('app.jdbc.invoke_java',return_value={}) as invoke:_java_execute({'driver':'oracle','serviceName':'qa'},{'operation':'insert','sql':'INSERT INTO values_table VALUES (?)','parameters':[exact],'preparedParameters':[{'name':'amount','type':'decimal'}]})
        values=invoke.call_args.args[2]
        self.assertEqual(values['parameter.0.type'],'decimal');self.assertEqual(str(values['parameter.0.value']),exact)
