"""Nested tabular records, bounded logical-row recovery and atomic file streams."""
from collections import deque
from contextlib import ExitStack
from dataclasses import dataclass
import csv
import codecs
import io
import json
import math
import os
from pathlib import Path
import tempfile

from .mapping_documents import pointer_parts, select, MissingPointer

# Set once under Python's import lock. Individual readers enforce their own
# smaller logical-record budget before invoking the shared C CSV parser.
csv.field_size_limit(max(csv.field_size_limit(), 64 * 1024**2))


def integer(value, default, maximum):
    if value in (None, ''): return default
    if isinstance(value, bool) or isinstance(value, float) and not value.is_integer(): raise ValueError('Stream limits must be integers')
    result = int(value)
    if not 1 <= result <= maximum: raise ValueError('Stream limit is outside its supported range')
    return result


def json_value(text):
    def bad(value): raise ValueError('Non-finite JSON value')
    def number(value):
        parsed = float(value)
        return parsed if math.isfinite(parsed) else bad(value)
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result: raise ValueError('Duplicate JSON field')
            result[key] = value
        return result
    value=json.loads(text, parse_constant=bad, parse_float=number, object_pairs_hook=pairs)
    pending=[(value,0)]; visited=0
    while pending:
        item,depth=pending.pop();visited+=1
        if depth>64 or visited>1000000: raise ValueError('JSON record exceeds nesting/complexity limit')
        if isinstance(item,dict): pending.extend((child,depth+1) for child in item.values())
        elif isinstance(item,list): pending.extend((child,depth+1) for child in item)
    return value


def paths_for(names, mapping=None):
    if len(names)>10000: raise ValueError('Data layout exceeds 10000 columns')
    if isinstance(mapping, str): mapping = json_value(mapping)
    if mapping is None: mapping = {}
    if not isinstance(mapping, dict) or any(key not in names for key in mapping):
        raise ValueError('Field paths must map declared column names to JSON Pointers')
    paths = {name: pointer_parts(mapping.get(name, '/' + '/'.join(part.replace('~','~0').replace('/','~1') for part in name.split('.')))) for name in names}
    tree = {}
    for parts in paths.values():
        if not parts or len(parts) > 64: raise ValueError('Nested field paths require one to 64 segments')
        current=tree
        for part in parts:
            if None in current: raise ValueError('Nested field paths overlap or duplicate another column')
            current=current.setdefault(part,{})
        if current: raise ValueError('Nested field paths overlap or duplicate another column')
        current[None]=True
    return paths


def schema_columns(shape, record_name='', unwrap=True):
    properties = shape.get('properties',{})
    repeated = [(name,field) for name,field in properties.items() if field.get('type')=='array']
    if record_name:
        chosen = next((field for name,field in repeated if name==record_name),None)
        if chosen is None: raise ValueError('recordElement must select a repeating schema child')
        shape = chosen.get('items',{})
    elif unwrap and len(repeated)==1 and len([name for name in properties if not name.startswith('@')])==1:
        shape = repeated[0][1].get('items',{})
    if shape.get('type')=='array': shape=shape.get('items',{})
    names=[];types=[];paths={}
    def walk(node,parts):
        if node.get('properties') and node.get('type')!='array':
            for name,child in node['properties'].items(): walk(child,parts+[name])
        elif parts:
            name='.'.join(parts)
            if name in paths: raise ValueError('Schema column names conflict; supply explicit fields and fieldPaths')
            names.append(name);types.append('json' if node.get('type') in ('array','object') else node.get('type','string'))
            paths[name]='/'+'/'.join(part.replace('~','~0').replace('/','~1') for part in parts)
    walk(shape,[])
    return names,types,paths


def nest_record(record, paths):
    result = {}; slots=0
    for name, parts in paths.items():
        current = result
        for i, part in enumerate(parts):
            last = i == len(parts)-1
            if isinstance(current, list):
                if not part.isdigit() or str(int(part)) != part or int(part) > 1000: raise ValueError('Nested array index must be 0 to 1000')
                index = int(part)
                slots+=max(0,index+1-len(current))
                if slots>10000: raise ValueError('Nested array allocation exceeds 10000 slots')
                while len(current) <= index: current.append(None)
                if last: current[index] = record[name]; break
                if current[index] is None: current[index] = [] if parts[i+1].isdigit() else {}
                current = current[index]
            else:
                if not isinstance(current, dict): raise ValueError('Conflicting nested field containers')
                if last: current[part] = record[name]; break
                current = current.setdefault(part, [] if parts[i+1].isdigit() else {})
    return result


def flatten_record(record, paths, strict=False):
    result = {}
    for name, parts in paths.items():
        try: result[name] = select(record, parts)
        except MissingPointer:
            if strict: raise ValueError('Missing nested field: ' + name) from None
            result[name] = None
    if strict:
        tree={}
        for parts in paths.values():
            current=tree
            for part in parts: current=current.setdefault(part,{})
            current[None]=True
        def check(value, branch):
            if None in branch: return
            if isinstance(value, dict):
                for key, child in value.items():
                    if key not in branch: raise ValueError('Undeclared nested field')
                    check(child,branch[key])
            elif isinstance(value, list):
                for i, child in enumerate(value):
                    if str(i) not in branch: raise ValueError('Undeclared nested field')
                    check(child,branch[str(i)])
        check(record, tree)
    return result


@dataclass
class Row:
    values: object
    raw: str
    error: str
    position: object


def logical_rows(handle, delimiter, any_character, fixed, maximum, max_lines, recovery, continuing, parser):
    """Read bounded physical lines, retaining seek cookies for replay/batching."""
    pending = deque()
    def line():
        if pending: return pending.popleft()
        text = handle.readline(maximum+1)
        if not text: return None
        if len(text.encode('utf-8')) > maximum:
            while text and not text.endswith(('\n','\r')):
                more = handle.readline(maximum+1)
                if not more or more.endswith(('\n','\r')): break
            return (text.encode('utf-8')[:maximum].decode('utf-8',errors='replace'), handle.tell(), True)
        return text, handle.tell(), False
    while True:
        first = line()
        if first is None: return
        buffer = [first]; size = len(first[0].encode('utf-8')); message = ''
        while True:
            raw = ''.join(item[0] for item in buffer)
            if first[2]: message = 'Data record exceeds byte limit'; break
            if fixed:
                yield Row(raw.rstrip('\r\n'), raw.rstrip('\r\n'), '', first[1]); break
            try:
                values = list(csv.reader(io.StringIO(raw, newline=''), delimiter=delimiter, strict=True)) if len(delimiter)==1 else list(parser(raw,delimiter,any_character))
                if len(values) != 1: raise ValueError('Unexpected record boundary')
                message = ''
                yield Row(values[0],raw.rstrip('\r\n'),'',buffer[-1][1]); break
            except (csv.Error, ValueError) as error:
                message = str(error)
                incomplete = 'unexpected end of data' in message.lower() or 'unterminated' in message.lower()
                if not incomplete or recovery == 'physical-line' or len(buffer) >= max_lines: break
                following = line()
                if following is None: break
                buffer.append(following); size += len(following[0].encode('utf-8'))
                if size > maximum or following[2]: message = 'Data record exceeds byte limit'; break
        if message:
            if not continuing: raise ValueError(message)
            # The first physical line is rejected; re-evaluate following lines
            # rather than swallowing good rows after an unterminated quote.
            for item in reversed(buffer[1:]): pending.appendleft(item)
            yield Row(None, first[0].rstrip('\r\n'), message, first[1])


class AtomicText:
    def __init__(self, path, encoding):
        codecs.lookup(encoding)
        self.path = Path(path).expanduser().resolve()
        fd, name = tempfile.mkstemp(prefix='.'+self.path.name+'.',suffix='.mina-part',dir=self.path.parent)
        self.temp = Path(name); self.handle = os.fdopen(fd,'w',encoding=encoding,newline='')
    def __enter__(self): return self
    def commit(self):
        self.handle.flush(); os.fsync(self.handle.fileno()); self.handle.close()
        os.replace(self.temp,self.path)
    def __exit__(self,*args):
        self.handle.close()
        self.temp.unlink(missing_ok=True)


def execute_stream(formats, cfg, ctx):
    from .data_groups import FileValidator, execute_grouped
    if any(formats.as_bool(cfg.get(key)) for key in ('groupRecords','wholeFileValidation','wholeFileXsd')) and str(cfg.get('blankLinePolicy','Skip')).lower()=='stop':
        raise ValueError('Whole-file processing cannot stop at a blank line; choose Skip or Keep')
    if formats.as_bool(cfg.get('groupRecords')):return execute_grouped(formats,cfg,ctx)
    parsing = cfg.get('operation') == 'parse'
    source = cfg.get('fileName') or cfg.get('filePath') if parsing else cfg.get('streamInputFile')
    target = cfg.get('streamOutputFile'); reject = cfg.get('streamErrorFile')
    if not source or not target: raise ValueError('Streaming Data requires an input file and streamOutputFile')
    source, target = Path(str(source)).expanduser().resolve(), Path(str(target)).expanduser().resolve()
    paths = [source,target]+([Path(str(reject)).expanduser().resolve()] if reject else [])
    for i, path in enumerate(paths):
        for other in paths[:i]:
            if path == other or path.exists() and other.exists() and os.path.samefile(path,other):
                raise ValueError('Streaming input, output and error files must be different')
    batch_size = integer(cfg.get('streamBatchSize'),500,10000)
    maximum = integer(cfg.get('streamMaxRecordBytes'),1048576,64*1024**2)
    if maximum < 256: raise ValueError('Streaming record limit must be at least 256 bytes')
    batch_bytes = integer(cfg.get('streamMaxBatchBytes'),8*1024**2,64*1024**2)
    if maximum > batch_bytes: raise ValueError('Record byte limit must not exceed batch byte limit')
    initial = source.stat(); identity = (initial.st_size,initial.st_mtime_ns)
    def unchanged():
        if callable(ctx.get('_formatCancelled')) and ctx['_formatCancelled'](): raise ValueError('Data streaming cancelled')
        info = source.stat()
        if (info.st_size,info.st_mtime_ns) != identity: raise ValueError('Streaming input file changed during processing')
    count = errors = batches = 0; wrote = False
    with ExitStack() as stack:
        output = stack.enter_context(AtomicText(target,'utf-8' if parsing else str(cfg.get('fileEncoding') or 'utf-8')))
        rejects = stack.enter_context(AtomicText(paths[2],'utf-8')) if reject else None
        validator=stack.enter_context(FileValidator(formats,cfg,ctx,target))
        def write_record(value, destination):
            text = json.dumps(value,ensure_ascii=False,allow_nan=False,separators=(',',':'))
            if len(text.encode('utf-8')) > maximum: raise ValueError('Stream output record exceeds byte limit')
            destination.handle.write(text+'\n')
        if parsing:
            local = {**ctx,'formatCursors':{},'context':{**ctx.get('context',{}),'activityId':'data-stream'}}
            options = {**cfg,'streaming':False,'inputSource':'File path','fileName':str(source),'manualStartRecord':False,
                       'noOfRecords':batch_size,'streamMaxRecordBytes':maximum,'_maxBatchBytes':batch_bytes,'_streamRecordsOnly':True,'_inStream':True}
            if validator.xsd:
                options['validateOutput']=False
                options['_recordShape']=validator.shape['properties'][validator.record_name]['items']
            options.pop('startRecord',None)
            while True:
                unchanged(); result = formats.flat_data(options,local); batches += 1
                for record in result['records']:
                    validator.physical(record);validator.logical(record)
                    write_record(record,output); count += 1
                for error in result['ErrorRows']['error']:
                    errors += 1
                    if rejects:
                        safe = dict(error)
                        raw = safe.get('raw','').encode('utf-8'); message = safe.get('message','').encode('utf-8')
                        safe['raw'] = raw[:maximum//4].decode('utf-8',errors='replace')
                        safe['message'] = message[:maximum//4].decode('utf-8',errors='replace')
                        safe['rawTruncated'] = len(raw)>maximum//4
                        write_record(safe,rejects)
                if result['done']: break
        else:
            fixed = str(cfg.get('format','delimited')).lower() in ('fixed','fixed width')
            ending = {'auto':'\n','lf':'\n','cr':'\r','crlf':'\r\n'}.get(str(cfg.get('lineSeparator',cfg.get('lineEnding','Auto'))).lower(),cfg.get('lineEnding','\n'))
            final = formats.as_bool(cfg.get('includeFinalLineSeparator'),not fixed and len(str(cfg.get('delimiter',',')))==1)
            batch = []; size = 0
            def flush():
                nonlocal count,batches,wrote,batch,size
                unchanged()
                for record in batch:validator.physical(record);validator.logical(record)
                options={**cfg,'streaming':False,'records':batch,'header':formats.as_bool(cfg.get('header'),True) and batches==0,
                         'includeFinalLineSeparator':False,'_inStream':True}
                if validator.xsd:
                    options['validateInput']=False
                    options['_recordShape']=validator.shape['properties'][validator.record_name]['items']
                result = formats.flat_data(options, {**ctx,'last':batch})
                text = result['text']
                if len(text.encode('utf-8')) > 8*batch_bytes: raise ValueError('Rendered stream batch exceeds expansion limit')
                if wrote and text: output.handle.write(ending)
                output.handle.write(text); wrote = wrote or bool(text)
                count += len(batch); batches += 1; batch=[];size=0
            with source.open(encoding='utf-8-sig',newline='') as handle:
                while True:
                    if callable(ctx.get('_formatCancelled')) and ctx['_formatCancelled'](): raise ValueError('Data streaming cancelled')
                    line = handle.readline(maximum+1)
                    if not line: break
                    length = len(line.encode('utf-8'))
                    if length > maximum: raise ValueError('JSON Lines input record exceeds byte limit')
                    if not line.strip(): continue
                    value = json_value(line)
                    if not isinstance(value,dict): raise ValueError('Render Data stream requires JSON Lines record objects')
                    if batch and (len(batch)>=batch_size or size+length>batch_bytes): flush()
                    batch.append(value);size+=length
                if batch or not batches: flush()
            if wrote and final: output.handle.write(ending)
        unchanged()
        validation=validator.finish(errors)
        unchanged()
        if rejects: rejects.commit()
        output.commit()
    return {'streamed':True,'filePath':str(target),'recordCount':count,'errorCount':errors,'batchCount':batches,
            'errorFile':str(paths[2]) if reject else None,'done':True,
            **({'validation':validation} if validator.enabled or validator.xsd else {})}
