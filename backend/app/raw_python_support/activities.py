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


def file_activity(operation: str, cfg: dict, payload: Any, *, cancel=None) -> dict:
    from .native.file_operations import file_activity as execute_file
    return execute_file(operation, cfg, payload,cancel=cancel)


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


def data_activity(kind: str, operation: str, cfg: dict, payload: Any, cursors=None, activity_id=None):
    from .native.data_formats import execute_format
    return execute_format(kind,operation,cfg,payload,cursors,activity_id)


async def data_activity_async(kind,operation,cfg,payload,cursors=None,activity_id=None):
    from .native.data_formats import run_format_async
    return await run_format_async(kind,operation,{**cfg,'operation':operation},
                                  {'last':payload,'formatCursors':cursors,'context':{'activityId':activity_id}})


def excel_read(cfg: dict) -> dict:
    try: from openpyxl import load_workbook
    except ImportError as error: raise RuntimeError('Excel Read requires the optional openpyxl package') from error
    path = Path(str(cfg.get('filePath') or '')).expanduser()
    book = load_workbook(path, read_only=True, data_only=_bool(cfg.get('dataOnly'), True))
    try:
        selected = [book[str(cfg['sheetName'])]] if cfg.get('sheetName') else list(book.worksheets)
        header_row = max(1, int(cfg.get('headerRow') or 1))
        start_row = max(header_row + 1, int(cfg.get('startRow') or header_row + 1))
        maximum = max(0, int(cfg.get('maximumRows') or 0))
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
    finally:
        book.close()



def transfer(kind: str, operation: str, connection: dict, cfg: dict, *, cancel=None) -> dict:
    from .native.transfer import transfer as execute_transfer
    return execute_transfer(kind, operation, {**connection, **cfg},cancel=cancel)


def http_request(cfg: dict, connection: dict | None = None) -> dict:
    from .native.http_transport import request
    return request(cfg, connection)


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
        module_name = str(cfg.get('moduleName') or artifact.stem or 'mina_inline')
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
    """Invoke a Java method without introducing a Mina runtime dependency."""
    class_name, method = str(cfg.get('className') or '').strip(), str(cfg.get('method') or '').strip()
    if not class_name or not method: raise ValueError('Java Invoke requires a class name and method')
    artifact, source = Path(str(cfg.get('artifactPath') or '')).expanduser(), str(cfg.get('sourceCode') or '')
    parameters = cfg.get('parameters')
    if not isinstance(parameters, list): parameters = [cfg.get('payload', payload)]
    helper = '''import java.lang.reflect.*; public class MinaInvoker { public static void main(String[] a) throws Exception { Class<?> c=Class.forName(a[0]); Method found=null; for(Method m:c.getMethods()) if(m.getName().equals(a[1])&&m.getParameterCount()==a.length-2){found=m;break;} if(found==null) throw new NoSuchMethodException(a[0]+"."+a[1]); Object[] v=new Object[found.getParameterCount()]; Class<?>[] t=found.getParameterTypes(); for(int i=0;i<v.length;i++){String s=a[i+2]; v[i]=t[i]==String.class?s:t[i]==int.class||t[i]==Integer.class?Integer.valueOf(s):t[i]==long.class||t[i]==Long.class?Long.valueOf(s):t[i]==double.class||t[i]==Double.class?Double.valueOf(s):t[i]==boolean.class||t[i]==Boolean.class?Boolean.valueOf(s):s;} Object target=Modifier.isStatic(found.getModifiers())?null:c.getDeclaredConstructor().newInstance(); Object out=found.invoke(target,v); if(out!=null) System.out.print(out); }}'''
    with tempfile.TemporaryDirectory(prefix='mina-java-') as folder:
        root = Path(folder); (root / 'MinaInvoker.java').write_text(helper, encoding='utf-8')
        classpath, compile_inputs = str(root), [str(root / 'MinaInvoker.java')]
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
        process = await asyncio.create_subprocess_exec('java', '-cp', classpath, 'MinaInvoker', class_name, method, *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
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
