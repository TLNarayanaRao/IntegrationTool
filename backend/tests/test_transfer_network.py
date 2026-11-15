"""Disposable loopback FTP/SFTP services; never use production credentials."""
import base64
import contextlib
import importlib.util
import os
import socket
import tempfile
import threading
import unittest
from pathlib import Path
from app.transfer import transfer


@contextlib.contextmanager
def ftp_server(root,tls=None):
    from pyftpdlib.authorizers import DummyAuthorizer
    from pyftpdlib.handlers import FTPHandler
    from pyftpdlib.servers import FTPServer
    if tls:
        from pyftpdlib.handlers import TLS_FTPHandler
        class Handler(TLS_FTPHandler):pass
        Handler.certfile=str(tls['cert']);Handler.keyfile=str(tls['key']);Handler.tls_control_required=True;Handler.tls_data_required=True
    else:
        class Handler(FTPHandler): pass
    authorizer=DummyAuthorizer();authorizer.add_user('tester','test-only',str(root),perm='elradfmwMT')
    Handler.authorizer=authorizer
    from pyftpdlib.ioloop import IOLoop
    loop=IOLoop()
    server=FTPServer(('127.0.0.1',0),Handler,ioloop=loop)
    thread=threading.Thread(target=lambda:server.serve_forever(timeout=.05,blocking=True,handle_exit=False),daemon=True);thread.start()
    try:yield {'host':'127.0.0.1','port':server.socket.getsockname()[1],'username':'tester','password':'test-only','timeout':3,**({'tls':True,'caFile':str(tls['ca'])} if tls else {})}
    finally:server.close_all();thread.join(3);loop.close()


@contextlib.contextmanager
def sftp_server(root, public_key=None):
    import paramiko
    class Auth(paramiko.ServerInterface):
        def check_auth_password(self,user,password):return paramiko.AUTH_SUCCESSFUL if (user,password)==('tester','test-only') else paramiko.AUTH_FAILED
        def get_allowed_auths(self,user):return 'password,publickey' if public_key is not None else 'password'
        def check_auth_publickey(self,user,key):
            return paramiko.AUTH_SUCCESSFUL if user=='tester' and public_key is not None and key==public_key else paramiko.AUTH_FAILED
        def check_channel_request(self,kind,chanid):return paramiko.OPEN_SUCCEEDED if kind=='session' else paramiko.OPEN_FAILED_ADMINISTRATIVELY_PROHIBITED
    class Files(paramiko.SFTPServerInterface):
        def path(self,path):
            value=(root/path.lstrip('/')).resolve()
            if value!=root and root not in value.parents:raise PermissionError(path)
            return value
        def canonicalize(self,path):return '/'+str(path).lstrip('./')
        def stat(self,path):
            try:return paramiko.SFTPAttributes.from_stat(self.path(path).stat())
            except OSError as exc:return paramiko.SFTPServer.convert_errno(exc.errno)
        lstat=stat
        def open(self,path,flags,attrs):
            try:
                stream=os.fdopen(os.open(self.path(path),flags,0o600),'wb' if flags & os.O_WRONLY else 'rb')
                handle=paramiko.SFTPHandle(flags)
                if flags & os.O_WRONLY:handle.writefile=stream
                else:handle.readfile=stream
                return handle
            except OSError as exc:return paramiko.SFTPServer.convert_errno(exc.errno)
        def list_folder(self,path):
            result=[]
            for child in self.path(path).iterdir():
                attrs=paramiko.SFTPAttributes.from_stat(child.stat());attrs.filename=child.name;result.append(attrs)
            return result
        def remove(self,path):self.path(path).unlink();return paramiko.SFTP_OK
        def rename(self,source,target):
            if self.path(target).exists():return paramiko.SFTP_FAILURE
            self.path(source).rename(self.path(target));return paramiko.SFTP_OK
        def posix_rename(self,source,target):os.replace(self.path(source),self.path(target));return paramiko.SFTP_OK
    listener=socket.socket();listener.bind(('127.0.0.1',0));listener.listen();listener.settimeout(.1)
    port=listener.getsockname()[1];key=paramiko.RSAKey.generate(2048)
    known=root/'known_hosts';known.write_text(f'[127.0.0.1]:{port} {key.get_name()} {key.get_base64()}\n')
    stop=threading.Event();connections=[]
    def serve():
        while not stop.is_set():
            try:channel,_=listener.accept()
            except socket.timeout:continue
            except OSError:break
            connections[:]=[item for item in connections if item.is_active()]
            transport=paramiko.Transport(channel);connections.append(transport);transport.add_server_key(key)
            transport.set_subsystem_handler('sftp',paramiko.SFTPServer,Files)
            try:transport.start_server(server=Auth())
            except (EOFError,paramiko.SSHException):transport.close()
    thread=threading.Thread(target=serve,daemon=True);thread.start()
    try:yield {'host':'127.0.0.1','port':port,'username':'tester','password':'test-only','knownHostsFile':str(known),'timeout':3}
    finally:
        stop.set();listener.close()
        for transport in connections:transport.close()
        thread.join(3)


class TransferNetworkTests(unittest.TestCase):
    def verify(self,kind,connection):
        from tests.test_python_mapper_parity import PythonMapperParityTests
        raw=b'\x00\xffbinary\r\n';encoded=base64.b64encode(raw).decode()
        transfer(kind,'put',{**connection,'remotePath':'file.bin','content':encoded,'binary':True})
        self.assertEqual(transfer(kind,'get',{**connection,'remotePath':'file.bin','binary':True})['contentBase64'],encoded)
        entries=transfer(kind,'dir',connection)['entries']
        self.assertIn('file.bin',[entry if isinstance(entry,str) else entry['name'] for entry in entries])
        transfer(kind,'change_dir',{**connection,'remotePath':'.'})
        helper=PythonMapperParityTests();project=helper.project()
        project['resources']=[{'id':'connection','name':'connection','type':kind,'config':connection}]
        task=project['tasks'][0];nodes=task['activities'];nodes.insert(1,{'id':'Download','name':'Download','type':kind,'config':{'operation':'get','resourceId':'connection','remotePath':'file.bin','binary':True}})
        nodes[-1]['config']['inputMappings']={'result.value':'${Download.contentBase64}'}
        task['transitions']=[{'id':str(i),'source':a['id'],'target':b['id']} for i,(a,b) in enumerate(zip(nodes,nodes[1:]))]
        helper.assert_studio(project,{}, {'value':encoded});helper.assert_exports(project,{}, {'value':encoded})
        with tempfile.TemporaryDirectory() as folder:
            local=Path(folder)/'upload.bin';local.write_bytes(raw*10000)
            transfer(kind,'put',{**connection,'remotePath':'stream.bin','localPath':str(local),'atomicUpload':True})
            result=transfer(kind,'get',{**connection,'remotePath':'stream.bin','localPath':str(local)+'.download'})
            self.assertIsNone(result['contentBase64']);self.assertEqual(Path(result['localPath']).read_bytes(),raw*10000)
            with self.assertRaises(ValueError):transfer(kind,'get',{**connection,'remotePath':'stream.bin','localPath':str(local),'overwrite':True,'maxDownloadBytes':3})
            self.assertEqual(local.read_bytes(),raw*10000)
            nodes[1]['config'].update(remotePath='stream.bin',localPath=str(local)+'.archive',overwrite=True)
            nodes[-1]['config']['inputMappings']={'result.size':'${Download.size}'}
            helper.assert_studio(project,{}, {'size':len(raw)*10000});helper.assert_exports(project,{}, {'size':len(raw)*10000})
            transfer(kind,'delete',{**connection,'remotePath':'stream.bin'})
        transfer(kind,'delete',{**connection,'remotePath':'file.bin'})
        with self.assertRaises(Exception):transfer(kind,'get',{**connection,'remotePath':'file.bin'})

    @unittest.skipUnless(importlib.util.find_spec('pyftpdlib'),'Install test-only pyftpdlib to exercise a live FTP server')
    def test_ftp_binary_operations_run_debug_and_both_archives(self):
        with tempfile.TemporaryDirectory() as folder,ftp_server(Path(folder)) as connection:self.verify('ftp',connection)

    @unittest.skipUnless(importlib.util.find_spec('paramiko'),'Requires optional paramiko adapter')
    def test_sftp_binary_operations_run_debug_and_both_archives(self):
        with tempfile.TemporaryDirectory() as folder,sftp_server(Path(folder)) as connection:
            self.verify('sftp',connection)
            with self.assertRaises(Exception):transfer('sftp','dir',{**connection,'knownHostsFile':''})

    @unittest.skipUnless(importlib.util.find_spec('pyftpdlib') and importlib.util.find_spec('OpenSSL'),'Requires test-only FTP/TLS adapters')
    def test_ftps_verified_certificate_and_rejected_untrusted_chain(self):
        from tests.connector_fixtures import certificates
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);tls=certificates(root)
            with ftp_server(root,tls) as connection:
                self.verify('ftp',connection)
                with self.assertRaises(Exception):transfer('ftp','dir',{**connection,'caFile':''})
