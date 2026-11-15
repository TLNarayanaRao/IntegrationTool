"""Shared FTP/FTPS/SFTP transfers with verified TLS and bounded socket waits."""
import base64
import ftplib
import io
import json
import math
import ssl
import os
import uuid
from pathlib import Path
from contextlib import suppress, ExitStack
from .sftp import _boolean, open_connection
from .file_operations import staged_file, byte_limit, check_cancel


class _CheckedReader:
    def __init__(self,stream,cancel):self.stream,self.cancel=stream,cancel
    def read(self,size=-1):
        check_cancel(self.cancel)
        return self.stream.read(size)
    def __getattr__(self,name):return getattr(self.stream,name)


class _ImplicitFTP(ftplib.FTP_TLS):
    # ftplib's normal FTP_TLS performs explicit AUTH TLS after the greeting.
    @property
    def sock(self): return self._sock

    @sock.setter
    def sock(self, value):
        self._sock = self.context.wrap_socket(value, server_hostname=self.host) if value is not None and not isinstance(value, ssl.SSLSocket) else value


def transfer(kind, operation, config, payload=None, *, cancel=None):
    check_cancel(cancel)
    if kind not in ('ftp','sftp') or operation not in ('get','put','delete','dir','change_dir'):
        raise ValueError('Unsupported file transfer operation')
    timeout = float(config.get('timeout') or config.get('timeoutSeconds') or 30)
    if not math.isfinite(timeout) or timeout <= 0: raise ValueError('Transfer timeout must be positive and finite')
    remote = str(config.get('remotePath') or '')
    if operation != 'dir' and not remote.strip(): raise ValueError('Remote path is required')
    if any(char in str(value) for value in (remote,config.get('workingDirectory') or '') for char in '\r\n\x00'): raise ValueError('Remote path cannot contain control characters')
    limit = byte_limit(config.get('maxDownloadBytes'))
    local=Path(str(config['localPath'])).expanduser() if str(config.get('localPath') or '').strip() else None
    if operation=='get' and local is not None and (local.exists() or local.is_symlink()) and not _boolean(config.get('overwrite')):raise FileExistsError(str(local))
    output = None;size=0
    def receive(chunk):
        nonlocal size
        check_cancel(cancel)
        if limit and size+len(chunk)>limit: raise ValueError('Download exceeds maximum download bytes')
        output.write(chunk)
        size+=len(chunk)
    value = config.get('content', payload)
    if operation == 'put' and local is None:
        raw = base64.b64decode(value, validate=True) if _boolean(config.get('binary')) and isinstance(value,str) else (
            value if isinstance(value,bytes) else value.encode(config.get('encoding') or 'utf-8') if isinstance(value,str) else json.dumps(value).encode('utf-8'))
    ssh = client = None;pending_remote=None
    stack=ExitStack()
    try:
        output=stack.enter_context(io.BytesIO())
        if operation=='get' and local is not None:
            if _boolean(config.get('createDirectories')):local.parent.mkdir(parents=True,exist_ok=True)
            stage=stack.enter_context(staged_file(local,_boolean(config.get('overwrite')),cancel))
            output=stack.enter_context(stage.open('wb'))
        if operation=='put':
            upload=stack.enter_context(local.open('rb')) if local is not None else stack.enter_context(io.BytesIO(raw))
            upload_size=os.fstat(upload.fileno()).st_size if local is not None else len(raw)
            if _boolean(config.get('atomicUpload')):
                pending_remote=remote+'.mina-'+uuid.uuid4().hex+'.tmp'
            upload=_CheckedReader(upload,cancel)
        upload_target=pending_remote or remote
        if kind == 'ftp':
            tls = _boolean(config.get('tls')) or _boolean(config.get('implicitTls'))
            if tls:
                context = ssl.create_default_context(cafile=config.get('caFile') or None, capath=config.get('caDirectory') or None)
                context.minimum_version = ssl.TLSVersion.TLSv1_2
                if config.get('certFile'): context.load_cert_chain(config['certFile'], config.get('keyFile'), config.get('keyPassword'))
                cls = _ImplicitFTP if _boolean(config.get('implicitTls')) else ftplib.FTP_TLS
                client = cls(context=context, encoding=config.get('encoding') or 'utf-8')
            else: client = ftplib.FTP(encoding=config.get('encoding') or 'utf-8')
            client.connect(str(config.get('host') or ''), int(config.get('port') or (990 if _boolean(config.get('implicitTls')) else 21)), timeout=timeout)
            client.login(str(config.get('username') or 'anonymous'), str(config.get('password') or ''))
            if tls: client.prot_p()
            client.set_pasv(_boolean(config.get('passiveMode'),True))
            if config.get('workingDirectory'): client.cwd(config['workingDirectory'])
            check_cancel(cancel)
            if operation == 'get': client.retrbinary('RETR '+remote, receive)
            elif operation == 'put':
                client.storbinary('STOR '+upload_target, upload)
                check_cancel(cancel)
                if pending_remote:client.rename(pending_remote,remote);pending_remote=None
            elif operation == 'delete': client.delete(remote)
            elif operation == 'dir':
                entries=[];maximum=byte_limit(config.get('maxEntries'))
                def entry(name):
                    check_cancel(cancel)
                    if maximum and len(entries)>=maximum:raise ValueError('Directory listing exceeds maximum entries')
                    entries.append(name)
                client.retrlines('NLST'+(' '+remote if remote else ''),entry)
                return {'directory':client.pwd(),'entries':entries}
            else: client.cwd(remote); return {'directory':client.pwd(),'remotePath':client.pwd(),'success':True}
        else:
            ssh, client = open_connection(config)
            if config.get('workingDirectory'): client.chdir(config['workingDirectory'])
            check_cancel(cancel)
            if operation == 'get':
                with client.file(remote,'rb') as stream:
                    while True:
                        chunk=stream.read(65536)
                        if not chunk: break
                        receive(chunk)
            elif operation == 'put':
                client.putfo(upload,upload_target,file_size=upload_size,confirm=True)
                check_cancel(cancel)
                if pending_remote:
                    # Do not delete the destination to emulate rename: failure must retain it.
                    if _boolean(config.get('overwrite')):client.posix_rename(pending_remote,remote)
                    else:client.rename(pending_remote,remote)
                    pending_remote=None
            elif operation == 'delete': client.remove(remote)
            elif operation == 'dir':
                entries=[];maximum=byte_limit(config.get('maxEntries'))
                for item in client.listdir_iter(remote or '.',read_aheads=1):
                    check_cancel(cancel)
                    if maximum and len(entries)>=maximum:raise ValueError('Directory listing exceeds maximum entries')
                    entries.append({'name':item.filename,'size':item.st_size,'modified':item.st_mtime})
                return {'directory':client.getcwd() or '.', 'entries':entries}
            else: client.chdir(remote); return {'directory':client.getcwd(),'remotePath':client.getcwd(),'success':True}
        if operation == 'get':
            if local is not None:
                output.flush();os.fsync(output.fileno());stack.close()
                return {'remotePath':remote,'localPath':str(local),'contentBase64':None,'content':None,'size':size}
            raw=output.getvalue()
            return {'remotePath':remote,'contentBase64':base64.b64encode(raw).decode(),'content':None if _boolean(config.get('binary')) else raw.decode(config.get('encoding') or 'utf-8',errors='replace'),'size':len(raw)}
        return {'remotePath':remote,'success':True, **({'written':True,'size':upload_size} if operation=='put' else {'deleted':True})}
    except BaseException:
        stack.__exit__(*__import__('sys').exc_info())
        raise
    finally:
        raw=None  # Do not retain an intermediate payload through an exception traceback.
        try:stack.close()
        finally:
            if client is not None:
                if pending_remote is not None:
                    with suppress(Exception):client.delete(pending_remote) if kind=='ftp' else client.remove(pending_remote)
                if kind == 'ftp':
                    with suppress(Exception):client.quit()
                with suppress(Exception):client.close()
            if ssh is not None:
                with suppress(Exception):ssh.close()
