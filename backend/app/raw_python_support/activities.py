"""Direct Python implementations for general, data, and transport activities.

The module is copied into every direct archive.  Optional dependencies are
loaded only by the activity that needs them, so a file-only integration stays
dependency free.
"""
from __future__ import annotations

import asyncio
import base64
import csv
import gzip
import importlib
import importlib.util
import io
import json
import os
import shlex
import shutil
import ssl
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


_SHARED_VARIABLES: dict[str, Any] = {}


def _bool(value: Any, default: bool = False) -> bool:
    if value is None: return default
    if isinstance(value, str): return value.strip().lower() in {'true', '1', 'yes', 'on'}
    return bool(value)


def _file_info(item: Path, configured: Path) -> dict[str, Any]:
    stat = item.stat()
    return {'fullName': str(item.resolve()), 'fileName': item.name,
            'location': str(item.parent.resolve()), 'configuredFileName': str(configured),
            'type': 'directory' if item.is_dir() else 'file',
            'readProtected': not os.access(item, os.R_OK), 'writeProtected': not os.access(item, os.W_OK),
            'size': stat.st_size, 'lastModified': datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat()}


def file_activity(operation: str, cfg: dict, payload: Any) -> dict:
    path = Path(str(cfg.get('path') or cfg.get('filePath') or '')).expanduser()
    if not str(path): raise ValueError('File path is required')
    if operation == 'write':
        if path.exists() and not _bool(cfg.get('overwrite')) and not _bool(cfg.get('append')):
            raise FileExistsError(f'{path} already exists')
        if _bool(cfg.get('createDirectories'), True): path.parent.mkdir(parents=True, exist_ok=True)
        binary = str(cfg.get('writeAs') or 'Text').lower() == 'binary' or cfg.get('binaryContent') not in (None, '')
        content = cfg.get('binaryContent') if binary else cfg.get('textContent', cfg.get('content', payload))
        if binary:
            raw = base64.b64decode(content) if isinstance(content, str) else bytes(content or b'')
            if str(cfg.get('compression') or 'None').lower() == 'gzip': raw = gzip.compress(raw)
            with path.open('ab' if _bool(cfg.get('append')) else 'wb') as stream: stream.write(raw)
        else:
            text = content if isinstance(content, str) else json.dumps(content, indent=2, default=str)
            if _bool(cfg.get('addLineSeparator')): text += os.linesep
            if str(cfg.get('compression') or 'None').lower() == 'gzip':
                with gzip.open(path, 'at' if _bool(cfg.get('append')) else 'wt', encoding=cfg.get('encoding') or 'utf-8') as stream: stream.write(text)
            else:
                with path.open('a' if _bool(cfg.get('append')) else 'w', encoding=cfg.get('encoding') or 'utf-8') as stream: stream.write(text)
        return {'path': str(path), 'written': True, 'success': True, 'fileInfo': _file_info(path, path)}
    if operation in {'list', 'poll'}:
        matches = list(path.rglob(str(cfg.get('pattern') or '*')) if _bool(cfg.get('recursive')) else path.glob(str(cfg.get('pattern') or '*')))
        list_type = str(cfg.get('listType') or 'Files and Directories').lower()
        if list_type == 'only files': matches = [item for item in matches if item.is_file()]
        if list_type == 'only directories': matches = [item for item in matches if item.is_dir()]
        sort_by = str(cfg.get('sortBy') or 'Name').lower()
        key = (lambda item: item.stat().st_size) if sort_by == 'size' else ((lambda item: item.stat().st_mtime) if sort_by == 'last modified' else (lambda item: item.name.lower()))
        matches.sort(key=key, reverse=str(cfg.get('sortOrder') or 'Ascending').lower() == 'descending')
        return {'files': [_file_info(item, path) for item in matches], 'count': len(matches),
                **({'eventType': cfg.get('eventType') or 'Created'} if operation == 'poll' else {})}
    if operation == 'delete':
        if not path.exists() and _bool(cfg.get('ignoreMissing')): return {'path': str(path), 'deleted': False, 'success': True}
        shutil.rmtree(path) if path.is_dir() and _bool(cfg.get('recursive')) else path.rmdir() if path.is_dir() else path.unlink()
        return {'path': str(path), 'deleted': True, 'success': True}
    if operation in {'rename', 'copy'}:
        destination = Path(str(cfg.get('destination') or '')).expanduser()
        if not str(destination): raise ValueError('Destination path is required')
        if _bool(cfg.get('createDirectories')): destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists() and not _bool(cfg.get('overwrite')): raise FileExistsError(f'{destination} already exists')
        if destination.exists(): shutil.rmtree(destination) if destination.is_dir() else destination.unlink()
        if operation == 'rename': path.rename(destination)
        elif path.is_dir(): shutil.copytree(path, destination, copy_function=shutil.copy2 if _bool(cfg.get('preserveAttributes'), True) else shutil.copy)
        else: (shutil.copy2 if _bool(cfg.get('preserveAttributes'), True) else shutil.copy)(path, destination)
        return {'source': str(path), 'destination': str(destination), 'path': str(destination), 'operation': operation,
                'success': True, 'fileInfo': _file_info(destination, destination)}
    info = _file_info(path, path)
    if _bool(cfg.get('excludeFileContent')): return {'path': str(path), 'fileInfo': info, **info}
    if str(cfg.get('readAs') or 'Text').lower() == 'binary':
        return {'path': str(path), 'binaryContent': base64.b64encode(path.read_bytes()).decode(), 'textContent': None, 'fileInfo': info, **info}
    text = path.read_text(encoding=cfg.get('encoding') or 'utf-8')
    return {'path': str(path), 'content': text, 'textContent': text, 'fileInfo': info, **info}


def _xml_to_value(element: ET.Element) -> Any:
    children = list(element)
    if not children:
        value: Any = element.text or ''
    else:
        value = {}
        for child in children:
            item = _xml_to_value(child)
            if child.tag in value:
                if not isinstance(value[child.tag], list): value[child.tag] = [value[child.tag]]
                value[child.tag].append(item)
            else: value[child.tag] = item
    if element.attrib:
        if not isinstance(value, dict): value = {'value': value}
        value.update({f'@{key}': item for key, item in element.attrib.items()})
    return value


def _value_to_xml(name: str, value: Any) -> ET.Element:
    node = ET.Element(str(name))
    if isinstance(value, dict):
        for key, item in value.items():
            if str(key).startswith('@'): node.set(str(key)[1:], str(item))
            elif isinstance(item, list):
                for entry in item: node.append(_value_to_xml(str(key), entry))
            else: node.append(_value_to_xml(str(key), item))
    elif value is not None: node.text = str(value)
    return node


def data_activity(kind: str, operation: str, cfg: dict, payload: Any) -> dict:
    if kind == 'json':
        if operation == 'parse':
            text = cfg.get('jsonString', cfg.get('text', payload))
            return {'value': json.loads(text) if isinstance(text, (str, bytes, bytearray)) else text}
        value = cfg.get('value', payload)
        if _bool(cfg.get('omitNulls')) and isinstance(value, dict): value = {k: v for k, v in value.items() if v is not None}
        return {'jsonString': json.dumps(value, indent=int(cfg.get('indent') or 2) if _bool(cfg.get('prettyPrint')) else None,
                                         ensure_ascii=_bool(cfg.get('asciiOnly')), default=str)}
    if kind == 'xml':
        if operation == 'parse':
            raw = cfg.get('xmlBinary') or cfg.get('xmlString', cfg.get('text', payload))
            if cfg.get('xmlBinary') and isinstance(raw, str): raw = base64.b64decode(raw)
            root = ET.fromstring(raw)
            return {'xml': {root.tag: _xml_to_value(root)}, 'rootElement': root.tag}
        value = cfg.get('value', payload)
        if isinstance(value, dict) and len(value) == 1: root_name, body = next(iter(value.items()))
        else: root_name, body = str(cfg.get('rootElement') or 'root'), value
        raw = ET.tostring(_value_to_xml(root_name, body), encoding=cfg.get('encoding') or 'unicode',
                          xml_declaration=not _bool(cfg.get('suppressXmlDeclaration')))
        if isinstance(raw, bytes): raw = raw.decode(cfg.get('encoding') or 'utf-8')
        if _bool(cfg.get('prettyPrint')):
            try:
                from xml.dom import minidom
                raw = minidom.parseString(raw).toprettyxml(indent='  ')
            except Exception: pass
        return {'xmlString': raw}
    text = cfg.get('text', payload)
    if str(cfg.get('inputSource') or '').lower() == 'file path' or cfg.get('filePath'):
        text = Path(str(cfg.get('filePath'))).read_text(encoding=cfg.get('fileEncoding') or 'utf-8-sig')
    delimiter = str(cfg.get('delimiter') or ',')
    fields = [item.strip() for item in str(cfg.get('fields') or '').split(',') if item.strip()]
    if operation == 'parse':
        if str(cfg.get('format') or 'delimited').lower() == 'fixed':
            widths = [int(item.strip()) for item in str(cfg.get('widths') or '').split(',') if item.strip()]
            rows = [[line[sum(widths[:i]):sum(widths[:i + 1])] for i in range(len(widths))] for line in str(text or '').splitlines() if line or not _bool(cfg.get('skipBlankLines'), True)]
        else: rows = list(csv.reader(io.StringIO(str(text or '')), delimiter=delimiter))
        if _bool(cfg.get('header'), True) and rows: fields, rows = rows[0], rows[1:]
        if not fields: fields = [f'field{i + 1}' for i in range(max((len(row) for row in rows), default=0))]
        records = [{name: (row[index].strip() if _bool(cfg.get('trimValues')) else row[index]) if index < len(row) else '' for index, name in enumerate(fields)} for row in rows]
        return {'records': records, 'xml': {str(cfg.get('rootElement') or 'records'): {str(cfg.get('recordElement') or 'record'): records}}, 'recordCount': len(records), 'fields': fields}
    records = cfg.get('records', payload)
    if isinstance(records, dict): records = records.get('records', [records])
    records = list(records or [])
    fields = fields or list(records[0].keys() if records else [])
    output = io.StringIO(); writer = csv.DictWriter(output, fieldnames=fields, delimiter=delimiter, lineterminator='\n')
    if _bool(cfg.get('header'), True): writer.writeheader()
    writer.writerows(records)
    return {'text': output.getvalue(), 'content': output.getvalue(), 'recordCount': len(records), 'fields': fields}


def excel_read(cfg: dict) -> dict:
    try: from openpyxl import load_workbook
    except ImportError as error: raise RuntimeError('Excel Read requires the optional openpyxl package') from error
    path = Path(str(cfg.get('filePath') or '')).expanduser()
    book = load_workbook(path, read_only=True, data_only=_bool(cfg.get('dataOnly'), True))
    selected = [book[str(cfg['sheetName'])]] if cfg.get('sheetName') else list(book.worksheets)
    header_row, start_row, maximum = int(cfg.get('headerRow') or 1), int(cfg.get('startRow') or header_row + 1), int(cfg.get('maximumRows') or 0)
    sheets = []
    for sheet in selected:
        headers = [str(cell.value if cell.value is not None else f'column{cell.column}') for cell in sheet[header_row]]
        rows = []
        for values in sheet.iter_rows(min_row=start_row, values_only=True):
            if _bool(cfg.get('skipBlankRows'), True) and not any(value is not None for value in values): continue
            row: dict[str, Any] = {}
            for key, value in zip(headers, values):
                target = row
                parts = key.split('.') if _bool(cfg.get('nestedHeaders'), True) else [key]
                for part in parts[:-1]: target = target.setdefault(part, {})
                target[parts[-1]] = value
            rows.append(row)
            if maximum and len(rows) >= maximum: break
        sheets.append({'name': sheet.title, 'headers': headers, 'rows': rows, 'rowCount': len(rows)})
    return {'workbook': {'fileName': path.name, 'sheetCount': len(sheets), 'sheets': sheets}}


def transfer(kind: str, operation: str, connection: dict, cfg: dict) -> dict:
    remote = str(cfg.get('remotePath') or '')
    if kind == 'ftp':
        import ftplib
        client = ftplib.FTP_TLS() if _bool(connection.get('tls')) else ftplib.FTP()
        client.connect(str(connection.get('host') or ''), int(connection.get('port') or (990 if _bool(connection.get('implicitTls')) else 21)), timeout=float(cfg.get('timeout') or connection.get('timeout') or 30))
        client.login(str(connection.get('username') or 'anonymous'), str(connection.get('password') or ''))
        if isinstance(client, ftplib.FTP_TLS): client.prot_p()
        try:
            if cfg.get('workingDirectory'): client.cwd(str(cfg['workingDirectory']))
            if operation == 'change_dir': client.cwd(remote); return {'remotePath': client.pwd(), 'success': True}
            if operation == 'dir': return {'entries': [{'name': name} for name in client.nlst(remote or None)], 'directory': client.pwd()}
            if operation == 'delete': client.delete(remote); return {'remotePath': remote, 'success': True}
            if operation == 'put':
                value = cfg.get('content', b''); raw = base64.b64decode(value) if _bool(cfg.get('binary')) and isinstance(value, str) else value.encode() if isinstance(value, str) else bytes(value)
                client.storbinary(f'STOR {remote}', io.BytesIO(raw)); return {'remotePath': remote, 'success': True, 'size': len(raw)}
            output = io.BytesIO(); client.retrbinary(f'RETR {remote}', output.write); raw = output.getvalue()
            return {'contentBase64': base64.b64encode(raw).decode(), 'content': raw.decode(errors='replace') if not _bool(cfg.get('binary')) else None, 'size': len(raw)}
        finally: client.quit()
    try: import paramiko
    except ImportError as error: raise RuntimeError('SFTP requires the optional paramiko package') from error
    client = paramiko.SSHClient()
    if _bool(cfg.get('verifyHostKey'), _bool(connection.get('verifyHostKey'), True)): client.load_system_host_keys()
    else: client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(str(connection.get('host') or ''), port=int(connection.get('port') or 22), username=connection.get('username'), password=connection.get('password'), key_filename=connection.get('privateKeyPath'), timeout=float(cfg.get('timeout') or 30))
    sftp = client.open_sftp()
    try:
        if cfg.get('workingDirectory'): sftp.chdir(str(cfg['workingDirectory']))
        if operation == 'change_dir': sftp.chdir(remote); return {'remotePath': sftp.getcwd(), 'success': True}
        if operation == 'dir': return {'entries': [{'name': item.filename, 'size': item.st_size, 'modified': item.st_mtime} for item in sftp.listdir_attr(remote or '.')], 'directory': sftp.getcwd()}
        if operation == 'delete': sftp.remove(remote); return {'remotePath': remote, 'success': True}
        if operation == 'put':
            value = cfg.get('content', b''); raw = base64.b64decode(value) if _bool(cfg.get('binary')) and isinstance(value, str) else value.encode() if isinstance(value, str) else bytes(value)
            with sftp.file(remote, 'wb') as stream: stream.write(raw)
            return {'remotePath': remote, 'success': True, 'size': len(raw)}
        with sftp.file(remote, 'rb') as stream: raw = stream.read()
        return {'contentBase64': base64.b64encode(raw).decode(), 'content': raw.decode(errors='replace') if not _bool(cfg.get('binary')) else None, 'size': len(raw)}
    finally: sftp.close(); client.close()


def http_request(cfg: dict, connection: dict | None = None) -> dict:
    connection = connection or {}
    url = str(cfg.get('url') or '')
    if not urllib.parse.urlsplit(url).scheme:
        base = str(connection.get('baseUrl') or '')
        url = base.rstrip('/') + '/' + url.lstrip('/')
    query = cfg.get('query') or {}
    if query: url += ('&' if '?' in url else '?') + urllib.parse.urlencode(query, doseq=True)
    headers = {str(key): str(value) for key, value in {**(connection.get('headers') or {}), **(cfg.get('headers') or {})}.items()}
    body = cfg.get('body')
    if body is not None and not isinstance(body, (str, bytes, bytearray)):
        body = json.dumps(body, default=str); headers.setdefault('Content-Type', 'application/json')
    data = body.encode() if isinstance(body, str) else body
    request = urllib.request.Request(url, data=data, headers=headers, method=str(cfg.get('method') or 'GET').upper())
    context = ssl.create_default_context()
    if not _bool(connection.get('verifyTls'), True): context.check_hostname = False; context.verify_mode = ssl.CERT_NONE
    try:
        with urllib.request.urlopen(request, timeout=float(cfg.get('timeout') or connection.get('timeout') or 30), context=context) as response:
            raw = response.read(); content_type = response.headers.get_content_type()
            text = raw.decode(response.headers.get_content_charset() or 'utf-8', errors='replace')
            try: value = json.loads(text) if content_type == 'application/json' else text
            except ValueError: value = text
            return {'statusCode': response.status, 'headers': dict(response.headers), 'body': value}
    except urllib.error.HTTPError as error:
        raw = error.read().decode(errors='replace')
        raise RuntimeError(f'HTTP {error.code}: {raw}') from error


async def external_command(cfg: dict) -> dict:
    command = str(cfg.get('command') or cfg.get('commandToExecute') or '').strip()
    if not command: raise ValueError('External Command requires a command')
    arguments = shlex.split(command, posix=os.name != 'nt')
    environment = cfg.get('environment') or {}
    if isinstance(environment, str): environment = dict(item.split('=', 1) for item in environment.split(',') if '=' in item)
    process_env = {str(k): str(v) for k, v in environment.items()} if _bool(cfg.get('replaceEnvironment')) else {**os.environ, **{str(k): str(v) for k, v in environment.items()}}
    process = await asyncio.create_subprocess_exec(*arguments, cwd=cfg.get('workingDirectory') or None, env=process_env,
                                                   stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    try: stdout, stderr = await asyncio.wait_for(process.communicate(str(cfg.get('input') or '').encode()), timeout=float(cfg.get('timeoutSeconds') or 300))
    except asyncio.TimeoutError: process.kill(); await process.wait(); raise RuntimeError('External command exceeded its timeout')
    encoding = cfg.get('encoding') or 'utf-8'; output, error = stdout.decode(encoding, errors='replace'), stderr.decode(encoding, errors='replace')
    output_file = str(cfg.get('outputFile') or '')
    if output_file: Path(output_file).write_text(output + error, encoding=encoding)
    split = str(cfg.get('outputLineSplitting') or 'None')
    if split == 'AtOperatingSystemLineEnd': output, error = output.splitlines(), error.splitlines()
    elif split == 'AtSpecifiedToken': output, error = output.split(str(cfg.get('splitToken') or '')), error.split(str(cfg.get('splitToken') or ''))
    return {'returnCode': process.returncode, 'output': output if _bool(cfg.get('provideCommandOutput'), True) else None,
            'error': error if _bool(cfg.get('provideCommandOutput'), True) else None, 'outputFile': output_file or None}


async def python_invoke(cfg: dict, payload: Any) -> dict:
    def invoke():
        function_name = str(cfg.get('function') or '').strip()
        if not function_name: raise ValueError('Python Invoke requires a function name')
        source, artifact = str(cfg.get('sourceCode') or ''), Path(str(cfg.get('artifactPath') or '')).expanduser()
        module_name = str(cfg.get('moduleName') or artifact.stem or 'fabric_inline')
        if source:
            namespace = {'__name__': module_name}; exec(compile(source, f'<{module_name}>', 'exec'), namespace); function = namespace.get(function_name)
        elif artifact.suffix.lower() == '.py' and artifact.exists():
            spec = importlib.util.spec_from_file_location(module_name, artifact)
            if not spec or not spec.loader: raise ImportError(f'Cannot load {artifact}')
            module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module); function = getattr(module, function_name, None)
        elif artifact.exists():
            sys.path.insert(0, str(artifact))
            try: function = getattr(importlib.import_module(module_name), function_name, None)
            finally: sys.path.pop(0)
        else: raise FileNotFoundError('Python Invoke requires an existing Python artifact or inline source')
        if not callable(function): raise ValueError(f'Python function {module_name}.{function_name} was not found')
        parameters = cfg.get('parameters')
        result = function(*parameters) if isinstance(parameters, list) else function(**parameters) if isinstance(parameters, dict) else function(cfg.get('payload', payload))
        return {'result': result, 'module': module_name, 'function': function_name}
    return await asyncio.wait_for(asyncio.to_thread(invoke), timeout=float(cfg.get('timeout') or 60))


async def java_invoke(cfg: dict, payload: Any) -> dict:
    """Invoke a Java method without introducing a Fabric runtime dependency."""
    class_name, method = str(cfg.get('className') or '').strip(), str(cfg.get('method') or '').strip()
    if not class_name or not method: raise ValueError('Java Invoke requires a class name and method')
    artifact, source = Path(str(cfg.get('artifactPath') or '')).expanduser(), str(cfg.get('sourceCode') or '')
    parameters = cfg.get('parameters')
    if not isinstance(parameters, list): parameters = [cfg.get('payload', payload)]
    helper = '''import java.lang.reflect.*; public class FabricInvoker { public static void main(String[] a) throws Exception { Class<?> c=Class.forName(a[0]); Method found=null; for(Method m:c.getMethods()) if(m.getName().equals(a[1])&&m.getParameterCount()==a.length-2){found=m;break;} if(found==null) throw new NoSuchMethodException(a[0]+"."+a[1]); Object[] v=new Object[found.getParameterCount()]; Class<?>[] t=found.getParameterTypes(); for(int i=0;i<v.length;i++){String s=a[i+2]; v[i]=t[i]==String.class?s:t[i]==int.class||t[i]==Integer.class?Integer.valueOf(s):t[i]==long.class||t[i]==Long.class?Long.valueOf(s):t[i]==double.class||t[i]==Double.class?Double.valueOf(s):t[i]==boolean.class||t[i]==Boolean.class?Boolean.valueOf(s):s;} Object target=Modifier.isStatic(found.getModifiers())?null:c.getDeclaredConstructor().newInstance(); Object out=found.invoke(target,v); if(out!=null) System.out.print(out); }}'''
    with tempfile.TemporaryDirectory(prefix='fabric-java-') as folder:
        root = Path(folder); (root / 'FabricInvoker.java').write_text(helper, encoding='utf-8')
        classpath, compile_inputs = str(root), [str(root / 'FabricInvoker.java')]
        if source:
            java_file = root / f'{class_name.rsplit(".", 1)[-1]}.java'; java_file.write_text(source, encoding='utf-8'); compile_inputs.append(str(java_file))
        elif artifact.exists() and artifact.suffix.lower() == '.java': compile_inputs.append(str(artifact)); classpath += os.pathsep + str(artifact.parent)
        elif artifact.exists() and artifact.suffix.lower() == '.jar': classpath += os.pathsep + str(artifact)
        elif artifact.exists() and artifact.suffix.lower() == '.class': classpath += os.pathsep + str(artifact.parent)
        else: raise FileNotFoundError('Java Invoke requires an existing JAR/class/source artifact or inline source')
        compiler = await asyncio.create_subprocess_exec('javac', '-cp', classpath, '-d', str(root), *compile_inputs, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        _, compile_error = await compiler.communicate()
        if compiler.returncode: raise RuntimeError(f'Java compilation failed: {compile_error.decode().strip()}')
        args = [json.dumps(value, separators=(',', ':')) if isinstance(value, (dict, list)) else str(value) for value in parameters]
        process = await asyncio.create_subprocess_exec('java', '-cp', classpath, 'FabricInvoker', class_name, method, *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        try: out, err = await asyncio.wait_for(process.communicate(), timeout=float(cfg.get('timeout') or 60))
        except asyncio.TimeoutError: process.kill(); await process.wait(); raise RuntimeError('Java method invocation timed out')
        if process.returncode: raise RuntimeError(err.decode().strip() or 'Java method invocation failed')
        value: Any = out.decode().strip()
        try: value = json.loads(value)
        except ValueError: pass
        return {'methodReturnValue': value, 'className': class_name, 'method': method}


def shared_variable(operation: str, cfg: dict, payload: Any) -> dict:
    name = str(cfg.get('name') or '').strip()
    if not name: raise ValueError('Shared Variable requires a name')
    if operation == 'set_shared_variable': _SHARED_VARIABLES[name] = cfg.get('value', payload)
    return {'name': name, 'value': _SHARED_VARIABLES.get(name, cfg.get('default'))}
