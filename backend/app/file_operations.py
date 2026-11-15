"""Shared local file operations for Studio and both Python archives."""
import base64, gzip, io, json, os, shutil, tempfile, uuid
import fnmatch
from contextlib import contextmanager, suppress
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

def _boolean(value, default=False):
    if value is None: return default
    if isinstance(value, str): return value.strip().lower() in {'true','1','yes','on'}
    return bool(value)


def byte_limit(value):
    if value in (None,''): return 0
    try:
        number=int(value)
        if str(number)!=str(value).strip() and number!=value: raise ValueError()
        if number<0: raise ValueError()
        return number
    except (ValueError,TypeError,OverflowError) as error:
        raise ValueError('Byte limit must be a nonnegative integer') from error


def check_cancel(cancel):
    if cancel is not None and cancel.is_set():raise InterruptedError('File/transfer operation cancelled')


async def run_io(function,*args):
    """Propagate coroutine cancellation to off-thread I/O checkpoints."""
    import asyncio,threading
    cancel=threading.Event()
    task=asyncio.create_task(asyncio.to_thread(function,*args,cancel=cancel))
    try:return await asyncio.shield(task)
    except asyncio.CancelledError:
        cancel.set()
        def finished(result):
            if not result.cancelled():result.exception()
        task.add_done_callback(finished)
        raise


@contextmanager
def staged_file(destination, overwrite=False, cancel=None):
    """Publish a completed file without exposing partial content or clobber races."""
    destination=Path(destination)
    fd,name=tempfile.mkstemp(prefix='.mina-',suffix='.tmp',dir=destination.parent)
    os.close(fd);temporary=Path(name)
    try:
        yield temporary
        check_cancel(cancel)
        if overwrite: os.replace(temporary,destination)
        else: os.link(temporary,destination)
    finally:
        with suppress(FileNotFoundError): temporary.unlink()


def _publish_tree(source,destination,overwrite,cancel=None):
    check_cancel(cancel)
    backup=None
    if destination.exists():
        if not overwrite: raise FileExistsError(str(destination))
        if not destination.is_dir() or destination.is_symlink(): raise ValueError('Directory destination must be a directory, not a file or link')
        backup=destination.with_name('.mina-backup-'+uuid.uuid4().hex)
        os.replace(destination,backup)
    try:
        check_cancel(cancel)
        os.replace(source,destination)
    except BaseException:
        if backup is not None and not destination.exists(): os.replace(backup,destination)
        raise
    if backup is not None:
        try: shutil.rmtree(backup)
        except OSError as error: return {'backupPath':str(backup),'cleanupWarning':str(error)}
    return {}


def _read_bytes(stream,limit,cancel=None):
    with io.BytesIO() as result:
        while True:
            check_cancel(cancel)
            data=stream.read(min(65536,limit-result.tell()+1) if limit else 65536)
            if not data:return result.getvalue()
            if limit and result.tell()+len(data)>limit:raise ValueError('File content exceeds maximum read bytes')
            result.write(data)


def _copy_file(source,target,cancel=None):
    with open(source,'rb') as incoming,open(target,'wb') as outgoing:
        while True:
            check_cancel(cancel)
            chunk=incoming.read(65536)
            if not chunk:break
            outgoing.write(chunk)
        outgoing.flush();os.fsync(outgoing.fileno())


def _scan_matches(path,pattern,recursive,cancel):
    # Stream common filename patterns; preserve Path.glob semantics for path patterns.
    if any(token in pattern for token in ('/','\\','**')):
        yield from path.rglob(pattern) if recursive else path.glob(pattern)
        return
    if not path.exists():return
    with os.scandir(path) as entries:
        for entry in entries:
            check_cancel(cancel)
            if fnmatch.fnmatch(entry.name,pattern):yield Path(entry.path)
            if recursive and entry.is_dir(follow_symlinks=False):
                try:reparse=getattr(entry.stat(follow_symlinks=False),'st_file_attributes',0)&0x400
                except FileNotFoundError:continue
                if not reparse:yield from _scan_matches(Path(entry.path),pattern,True,cancel)

def _file_info(item: Path, configured: Path) -> dict[str, Any]:
    stat = item.stat()
    return {'fullName': str(item.resolve()), 'fileName': item.name,
            'location': str(item.parent.resolve()), 'configuredFileName': str(configured),
            'type': 'directory' if item.is_dir() else 'file',
            'readProtected': not os.access(item, os.R_OK), 'writeProtected': not os.access(item, os.W_OK),
            'size': stat.st_size, 'lastModified': datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat()}


def file_activity(operation: str, cfg: dict, payload: Any, *, cancel=None) -> dict:
    check_cancel(cancel)
    raw_path = str(cfg.get('path') or cfg.get('filePath') or '').strip()
    if not raw_path: raise ValueError('File path is required')
    if operation not in {'read','write','list','poll','delete','rename','copy'}: raise ValueError('Unsupported File operation '+str(operation))
    path = Path(raw_path).expanduser()
    if operation == 'write':
        append,overwrite=_boolean(cfg.get('append')),_boolean(cfg.get('overwrite'))
        if path.exists() and not _boolean(cfg.get('overwrite')) and not _boolean(cfg.get('append')):
            raise FileExistsError(f'{path} already exists')
        if _boolean(cfg.get('createDirectories'), True): path.parent.mkdir(parents=True, exist_ok=True)
        binary = str(cfg.get('writeAs') or 'Text').lower() == 'binary' or cfg.get('binaryContent') not in (None, '')
        content = cfg.get('binaryContent') if binary else cfg.get('textContent', cfg.get('content', payload))
        if binary: raw=base64.b64decode(content,validate=True) if isinstance(content,str) else bytes(content or b'')
        else:
            text = content if isinstance(content, str) else json.dumps(content, indent=2, default=str)
            if _boolean(cfg.get('addLineSeparator')): text += os.linesep
            if os.linesep!='\n': text=text.replace('\r\n','\n').replace('\n',os.linesep)
            raw=text.encode(cfg.get('encoding') or 'utf-8')
        if str(cfg.get('compression') or 'None').lower()=='gzip':raw=gzip.compress(raw)
        check_cancel(cancel)
        if append:
            with path.open('ab') as stream:stream.write(raw)
        else:
            with staged_file(path,overwrite,cancel) as stage:
                with stage.open('wb') as stream:stream.write(raw);stream.flush();os.fsync(stream.fileno())
        return {'path': str(path), 'written': True, 'success': True, 'fileInfo': _file_info(path, path)}
    if operation in {'list', 'poll'}:
        limit=byte_limit(cfg.get('maxEntries'));matches=[]
        list_type = str(cfg.get('listType') or 'Files and Directories').lower()
        for item in _scan_matches(path,str(cfg.get('pattern') or '*'),_boolean(cfg.get('recursive')),cancel):
            check_cancel(cancel)
            if list_type=='only files' and not item.is_file() or list_type=='only directories' and not item.is_dir():continue
            try:info=_file_info(item,path)
            except FileNotFoundError:continue  # Poll/list snapshots can race other writers.
            if limit and len(matches)>=limit:raise ValueError('Directory listing exceeds maximum entries')
            matches.append(info)
        sort_by = str(cfg.get('sortBy') or 'Name').lower()
        key = (lambda item:item['size']) if sort_by=='size' else (lambda item:item['lastModified']) if sort_by=='last modified' else (lambda item:item['fileName'].lower())
        matches.sort(key=key, reverse=str(cfg.get('sortOrder') or 'Ascending').lower() == 'descending')
        return {'files': matches, 'count': len(matches),
                **({'eventType': cfg.get('eventType') or 'Created'} if operation == 'poll' else {})}
    if operation == 'delete':
        if not path.exists() and not path.is_symlink() and _boolean(cfg.get('ignoreMissing')): return {'path': str(path), 'deleted': False, 'success': True}
        if path.resolve()==path.resolve().parent:raise ValueError('Deleting a filesystem root is not allowed')
        if path.is_symlink():path.unlink()
        else:shutil.rmtree(path) if path.is_dir() and _boolean(cfg.get('recursive')) else path.rmdir() if path.is_dir() else path.unlink()
        return {'path': str(path), 'deleted': True, 'success': True}
    if operation in {'rename', 'copy'}:
        raw_destination = str(cfg.get('destination') or '').strip()
        if not raw_destination: raise ValueError('Destination path is required')
        destination = Path(raw_destination).expanduser()
        source_path, target_path = path.resolve(), destination.resolve()
        if source_path == target_path or path.exists() and destination.exists() and os.path.samefile(path,destination):
            raise ValueError('Source and destination must be different')
        if path.is_dir() and (source_path in target_path.parents or target_path in source_path.parents):
            raise ValueError('Source and destination directories cannot contain each other')
        if not path.exists(): raise FileNotFoundError(str(path))
        if _boolean(cfg.get('createDirectories')): destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists() and not _boolean(cfg.get('overwrite')): raise FileExistsError(f'{destination} already exists')
        check_cancel(cancel)
        extra={};overwrite=_boolean(cfg.get('overwrite'))
        if path.is_dir():
            if operation=='rename':extra=_publish_tree(path,destination,overwrite,cancel)
            else:
                with tempfile.TemporaryDirectory(prefix='.mina-copy-',dir=destination.parent) as workspace:
                    stage=Path(workspace)/'tree'
                    def copy_entry(source,target):
                        _copy_file(source,target,cancel)
                        (shutil.copystat if _boolean(cfg.get('preserveAttributes'),True) else shutil.copymode)(source,target)
                        return target
                    shutil.copytree(path,stage,symlinks=True,copy_function=copy_entry)
                    extra=_publish_tree(stage,destination,overwrite,cancel)
        elif operation=='rename':
            if overwrite:os.replace(path,destination)
            else:os.link(path,destination);path.unlink()
        else:
            with staged_file(destination,overwrite,cancel) as stage:
                _copy_file(path,stage,cancel)
            (shutil.copystat if _boolean(cfg.get('preserveAttributes'),True) else shutil.copymode)(path,destination)
        return {'source': str(path), 'destination': str(destination), 'path': str(destination), 'operation': operation,
                'success': True, 'fileInfo': _file_info(destination, destination),**extra}
    info = _file_info(path, path)
    if _boolean(cfg.get('excludeFileContent')): return {'path': str(path), 'fileInfo': info, **info}
    compressed = str(cfg.get('compression') or 'None').lower() == 'gzip'
    limit=byte_limit(cfg.get('maxReadBytes'))
    with (gzip.open(path,'rb') if compressed else path.open('rb')) as stream: raw=_read_bytes(stream,limit,cancel)
    if str(cfg.get('readAs') or 'Text').lower() == 'binary':
        return {'path': str(path), 'binaryContent': base64.b64encode(raw).decode(), 'textContent': None, 'content':None, 'fileInfo': info, **info}
    with io.TextIOWrapper(io.BytesIO(raw),encoding=cfg.get('encoding') or 'utf-8') as stream:text=stream.read()
    return {'path': str(path), 'content': text, 'textContent': text, 'fileInfo': info, **info}

