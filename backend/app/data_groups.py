"""Explicit HDT framing and end-of-file validation for bounded Data streams."""
from contextlib import ExitStack
from decimal import Decimal, localcontext, InvalidOperation, ROUND_HALF_EVEN
import json
import os
from pathlib import Path
import sqlite3
import tempfile

from .data_stream import AtomicText, integer, json_value, logical_rows, paths_for
from .mapping_documents import pointer_parts, select, key_paths, record_key, clone
from .faults import MinaFault


def config_object(value, label):
    if isinstance(value,str): value=json_value(value)
    if not isinstance(value,dict): raise ValueError(label+' must be a JSON object')
    return value


def number(value):
    if isinstance(value,bool) or not isinstance(value,(int,float,str)): raise ValueError('Control totals require finite decimal values')
    try: result=Decimal(str(value))
    except InvalidOperation: raise ValueError('Control totals require finite decimal values') from None
    if not result.is_finite() or len(result.as_tuple().digits)>1000 or abs(result.adjusted())>1000:
        raise ValueError('Control total exceeds decimal limits')
    return result


def add(left,right):
    with localcontext() as context:
        context.prec=2048
        return left+right


def put(record,parts,value):
    current=record
    for part in parts[:-1]:
        current=current.setdefault(part,{})
        if not isinstance(current,dict): raise ValueError('Computed trailer paths require object containers')
    current[parts[-1]]=value


class FileValidator:
    def __init__(self,formats,cfg,ctx,target):
        self.formats,self.cfg,self.ctx,self.target=formats,cfg,ctx,target
        self.enabled=formats.as_bool(cfg.get('wholeFileValidation'))
        self.xsd=formats.as_bool(cfg.get('wholeFileXsd'))
        self.rules=config_object(cfg.get('wholeFileRules') or {},'Whole-file rules') if self.enabled or self.xsd else {}
        allowed={'minRecords','maxRecords','minGroups','maxGroups','minDetails','maxDetails','maxErrors','uniqueKeys','totals','rootAttributes'}
        if self.rules.keys()-allowed: raise ValueError('Unknown whole-file validation setting')
        self.bounds={}
        for key in allowed-{'uniqueKeys','totals','rootAttributes'}:
            if self.enabled and key in self.rules:
                value=self.rules[key]
                if isinstance(value,bool) or not str(value).isdigit() or len(str(value))>13: raise ValueError('Whole-file count bounds must be nonnegative integers')
                self.bounds[key]=int(value)
        for unit in ('Records','Groups','Details'):
            if self.bounds.get('min'+unit,0)>self.bounds.get('max'+unit,10**13): raise ValueError('Whole-file minimum exceeds maximum')
        self.keys=self.rules.get('uniqueKeys',[]) if self.enabled else []
        if not isinstance(self.keys,list) or len(self.keys)>16: raise ValueError('Supply at most sixteen unique-key rules')
        self.keys=[key_paths(paths) for paths in self.keys]
        totals=self.rules.get('totals',[]) if self.enabled else []
        if not isinstance(totals,list) or len(totals)>16: raise ValueError('Supply at most sixteen file totals')
        self.total_specs=[];names=set()
        for spec in totals:
            if not isinstance(spec,dict) or spec.keys()-{'name','path','expected'} or not {'name','path','expected'}<=spec.keys(): raise ValueError('File total requires name, path and expected')
            name=spec['name']
            if not isinstance(name,str) or not 1<=len(name)<=128 or name in names: raise ValueError('File total names must be unique nonempty strings')
            names.add(name);self.total_specs.append((name,pointer_parts(spec['path']),number(spec['expected'])))
        self.totals={name:Decimal(0) for name,_,_ in self.total_specs}
        self.records=self.groups=self.details=0
        self.resources=ExitStack();self.writers=ExitStack();self.db=None;self.xml=None

    def __enter__(self):
        try:
            if self.keys:
                folder=self.resources.enter_context(tempfile.TemporaryDirectory(prefix='.mina-keys-',dir=self.target.parent))
                self.db=sqlite3.connect(str(Path(folder)/'keys.sqlite'))
                self.resources.callback(self.db.close)
                self.db.execute('PRAGMA journal_mode=OFF');self.db.execute('PRAGMA synchronous=OFF')
                self.db.execute('CREATE TABLE keys(rule INTEGER, value TEXT, PRIMARY KEY(rule,value)) WITHOUT ROWID');self.db.execute('BEGIN')
            if self.xsd:
                from .data_formats import xsd_shape, xml_from_value, compiled_xsd
                from lxml import etree
                schema=self.formats.configured_schema(self.cfg,self.ctx)
                if not isinstance(schema,str) or not schema.lstrip().startswith('<'): raise ValueError('Whole-file XSD validation requires a selected XSD')
                bundle=self.formats.schema_bundle(self.cfg,self.ctx,schema)
                self.validator,self.lock=compiled_xsd(schema,bundle)
                self.shape=xsd_shape(schema,self.cfg.get('rootElement') or '',bundle)
                arrays=[name for name,field in self.shape.get('properties',{}).items() if field.get('type')=='array']
                self.record_name=self.cfg.get('recordElement') or (arrays[0] if len(arrays)==1 else '')
                if self.record_name not in arrays: raise ValueError('Whole-file XSD requires recordElement selecting a repeating root child')
                attrs=config_object(self.rules.get('rootAttributes') or {},'Root attributes')
                self.root_name=self.shape.get('xml',{}).get('name') or 'records'
                root=xml_from_value(self.root_name,{**{'@'+key:value for key,value in attrs.items()},self.record_name:[]},self.shape,tree_input=True)
                self.xml=self.resources.enter_context(tempfile.TemporaryFile('w+b',dir=self.target.parent))
                writer=self.writers.enter_context(etree.xmlfile(self.xml,encoding='utf-8',close=False))
                self.writers.enter_context(writer.element(root.tag,attrib=root.attrib,nsmap=root.nsmap))
                self.xml_writer=writer
            return self
        except sqlite3.Error as error:
            self.__exit__(None,None,None);raise ValueError('Whole-file uniqueness storage failed') from error
        except BaseException:
            self.__exit__(None,None,None);raise

    def __exit__(self,*args):
        try:self.writers.close()
        finally:self.resources.close()

    def _cancel(self):
        if callable(self.ctx.get('_formatCancelled')) and self.ctx['_formatCancelled'](): raise ValueError('Whole-file validation cancelled')

    def _bounds(self):
        for name,value in [('Records',self.records),('Groups',self.groups),('Details',self.details)]:
            if value>self.bounds.get('max'+name,10**13): raise ValueError('Whole-file maximum '+name.lower()+' exceeded')

    def physical(self,record,detail=False):
        self.records+=1
        if detail:self.details+=1
        self._bounds()
        if detail or not self.formats.as_bool(self.cfg.get('groupRecords')):
            for name,path,_ in self.total_specs:self.totals[name]=add(self.totals[name],number(select(record,path)))

    def logical(self,record,group=False):
        self._cancel()
        if group:self.groups+=1;self._bounds()
        for index,paths in enumerate(self.keys):
            key=record_key(record,paths)
            if key is None: raise ValueError('Whole-file unique keys must exist and be non-null')
            values=[]
            for kind,value in key:
                if kind=='number':
                    value=format(value,'f')
                    if '.' in value:value=value.rstrip('0').rstrip('.')
                    if value=='-0':value='0'
                values.append([kind,value])
            text=json.dumps(values,ensure_ascii=False,separators=(',',':'))
            if len(text.encode())>65536: raise ValueError('Whole-file unique key exceeds 64 KiB')
            try:self.db.execute('INSERT INTO keys VALUES (?,?)',(index,text))
            except sqlite3.IntegrityError: raise ValueError('Whole-file duplicate key for rule '+str(index+1)) from None
            except sqlite3.Error as error:raise ValueError('Whole-file uniqueness storage failed') from error
        if self.xsd:
            from .data_formats import xml_from_value
            root=xml_from_value(self.root_name,{self.record_name:[record]},self.shape,tree_input=True)
            for child in root:self.xml_writer.write(child)

    def finish(self,errors):
        self._cancel()
        if self.enabled:
            for name,value in [('Records',self.records),('Groups',self.groups),('Details',self.details)]:
                if value<self.bounds.get('min'+name,0): raise ValueError('Whole-file minimum '+name.lower()+' not met')
            if errors>self.bounds.get('maxErrors',0): raise ValueError('Whole-file rejected-record limit exceeded')
            for name,_,expected in self.total_specs:
                if self.totals[name]!=expected: raise ValueError('Whole-file total mismatch: '+name)
        self.writers.close()
        if self.xsd:
            from lxml import etree
            self.xml.flush();self.xml.seek(0)
            with self.lock:
                try:
                    for _,element in etree.iterparse(self.xml,events=('end',),schema=self.validator,resolve_entities=False,load_dtd=False,no_network=True,huge_tree=False):
                        self._cancel();element.clear()
                        while element.getprevious() is not None:del element.getparent()[0]
                except etree.XMLSyntaxError as error:raise ValueError('Whole-file XSD validation failed: '+str(error)) from error
        return {'valid':True,'rulesValidated':self.enabled,'recordCount':self.records,'groupCount':self.groups,'detailCount':self.details,
                'totals':{name:format(value,'f') for name,value in self.totals.items()},'uniqueKeyRules':len(self.keys),'xsdValidated':self.xsd}


class GroupLayout:
    def __init__(self,formats,cfg):
        self.formats,self.cfg=formats,cfg
        data=config_object(cfg.get('recordLayouts'),'Record layouts')
        if data.keys()-{'header','detail','trailer','trailerChecks','deriveTrailer','maxGroupDetails','maxGroupBytes'}:raise ValueError('Unknown record-group setting')
        self.maximum=integer(data.get('maxGroupBytes'),8388608,64*1024**2)
        self.max_details=integer(data.get('maxGroupDetails'),10000,1000000)
        self.derive=formats.as_bool(data.get('deriveTrailer'))
        self.layouts={};self.matches=set()
        mode=str(cfg.get('format','delimited')).lower()
        if mode not in ('delimited','fixed','fixed width'):raise ValueError('Unknown grouped data format')
        fixed=mode in ('fixed','fixed width')
        for role in ('header','detail','trailer'):
            spec=config_object(data.get(role),'Layout '+role)
            if spec.keys()-{'match','fields','fieldTypes','fieldPaths','widths','fieldOffsets','lineLength','fillCharacter','defaults'}:raise ValueError('Unknown '+role+' layout setting')
            if 'defaults' in spec:
                if role!='trailer':raise ValueError('Defaults are only supported for derived trailers')
                spec={**spec,'defaults':config_object(spec['defaults'],'Trailer defaults')}
            match=config_object(spec.get('match'),'Record match')
            if match.keys()-{'column','start','end','value'} or not isinstance(match.get('value'),str):raise ValueError('Record match needs a literal value and column or fixed span')
            if 'column' in match:
                if fixed:raise ValueError('Fixed layouts require start/end match spans')
                if set(match)!= {'column','value'} or isinstance(match['column'],bool) or not isinstance(match['column'],int) or not 0<=match['column']<10000:raise ValueError('Match column must be zero-based')
                identity=('column',match['column'],match['value'])
            else:
                if not fixed:raise ValueError('Delimited layouts require column matches')
                if set(match)!={'start','end','value'} or any(isinstance(match[k],bool) or not isinstance(match[k],int) for k in ('start','end')) or not 0<=match['start']<match['end']<=65536:raise ValueError('Invalid fixed record match span')
                identity=('span',match['start'],match['end'],match['value'])
            if identity in self.matches:raise ValueError('Record role matches must be distinct')
            self.matches.add(identity)
            fields=[part.strip() for part in str(spec.get('fields') or '').split(',')]
            if not fields or any(not field for field in fields) or len(set(fields))!=len(fields):raise ValueError('Each record role requires unique field names')
            if 'column' in match and match['column']>=len(fields):raise ValueError('Match column is outside declared fields')
            self.layouts[role]=spec
            options=self.options(role)
            for key in ('fileName','filePath','startRecord','_maxBatchBytes'):options.pop(key,None)
            formats.flat_data({**options,'operation':'parse','text':''},{'last':''})
        checks=data.get('trailerChecks',[])
        if not isinstance(checks,list) or len(checks)>16:raise ValueError('Supply at most sixteen trailer checks')
        self.checks=[]
        for check in checks:
            if not isinstance(check,dict) or check.keys()-{'kind','trailerPath','detailPath','scale'} or check.get('kind') not in ('count','sum') or 'trailerPath' not in check:raise ValueError('Invalid trailer check')
            path=pointer_parts(check['trailerPath'])
            if not path:raise ValueError('Trailer check requires a member path')
            detail=pointer_parts(check['detailPath']) if check.get('kind')=='sum' and 'detailPath' in check else None
            if check['kind']=='sum' and detail is None:raise ValueError('Trailer sum needs detailPath')
            scale=check.get('scale')
            if scale is not None and (isinstance(scale,bool) or not isinstance(scale,int) or not 0<=scale<=12):raise ValueError('Trailer scale must be 0 to 12')
            self.checks.append((check['kind'],path,detail,scale))
        paths_for([str(i) for i in range(len(self.checks))],{str(i):check['trailerPath'] for i,check in enumerate(checks)})

    def matches_row(self,role,token):
        match=self.layouts[role]['match']
        if 'column' in match:
            return isinstance(token.values,list) and match['column']<len(token.values) and token.values[match['column']]==match['value']
        return isinstance(token.values,str) and token.values[match['start']:match['end']]==match['value']

    def options(self,role):
        spec=self.layouts[role]
        return {**self.cfg,**{k:v for k,v in spec.items() if k not in ('match','defaults')},'streaming':False,'groupRecords':False,
                'nestedRecords':bool(spec.get('fieldPaths')) or self.formats.as_bool(self.cfg.get('nestedRecords')),
                'dataFormatId':'','schemaId':'','schemaText':'','validateInput':False,'validateOutput':False,'header':False,'noOfRecords':-1,'manualStartRecord':True,
                'inputSource':'String','continueOnError':False,'_streamRecordsOnly':True,'_inStream':True,'wholeFileValidation':False,'wholeFileXsd':False}

    def parse(self,role,raw):
        options=self.options(role)
        for key in ('fileName','filePath','startRecord','_maxBatchBytes'):options.pop(key,None)
        result=self.formats.flat_data({**options,'operation':'parse','text':raw},{'last':raw})
        if len(result['records'])!=1:raise ValueError('A grouped physical record must decode to one row')
        return result['records'][0]

    def render(self,role,record):
        options=self.options(role)
        for key in ('text','Text','Rows','source'):options.pop(key,None)
        result=self.formats.flat_data({**options,'operation':'render','records':[record],'includeFinalLineSeparator':False},{'last':[record]})
        text=result['text'];fixed=str(options.get('format','delimited')).lower() in ('fixed','fixed width')
        values=text if fixed else next(iter(self.formats.delimited_rows(text,str(options.get('delimiter',',')),str(options.get('separatorRule','single')).lower()=='any-character')),[])
        from .data_stream import Row
        if not self.matches_row(role,Row(values,text,'',None)):raise ValueError('Rendered '+role+' does not match its discriminator')
        return text

    def close(self,group,derive=False):
        details=group['details']
        if len(details)>self.max_details:raise ValueError('Group detail limit exceeded')
        supplied=group.get('trailer')
        if supplied is not None and not isinstance(supplied,dict):raise ValueError('Trailer must be a record object')
        if not derive and not isinstance(supplied,dict):raise ValueError('Trailer must be a record object')
        defaults=self.layouts['trailer'].get('defaults') or {}
        if not isinstance(defaults,dict):raise ValueError('Trailer defaults must be an object')
        trailer={**clone(defaults),**clone(supplied or {})} if derive else clone(supplied)
        if not isinstance(trailer,dict):raise ValueError('Trailer must be a record object')
        for kind,path,detail,scale in self.checks:
            value=Decimal(len(details)) if kind=='count' else Decimal(0)
            if kind=='sum':
                for row in details:value=add(value,number(select(row,detail)))
            if scale is not None:
                with localcontext() as context:context.prec=2048;context.rounding=ROUND_HALF_EVEN;value=value.quantize(Decimal(1).scaleb(-scale))
            if derive:put(trailer,path,int(value) if kind=='count' else format(value,'f'))
            elif number(select(trailer,path))!=value:raise ValueError('Trailer '+kind+' control mismatch')
        group={**group,'trailer':trailer}
        if len(json.dumps(group,ensure_ascii=False,separators=(',',':')).encode())>self.maximum:raise ValueError('Group exceeds byte limit')
        return group


def execute_grouped(formats,cfg,ctx):
    parsing=cfg.get('operation')=='parse';layout=GroupLayout(formats,cfg)
    source=cfg.get('fileName') or cfg.get('filePath') if parsing else cfg.get('streamInputFile')
    target=cfg.get('streamOutputFile');reject=cfg.get('streamErrorFile') if parsing else None
    if not source or not target:raise ValueError('Grouped streaming requires input and output files')
    paths=[Path(str(path)).expanduser().resolve() for path in [source,target]+([reject] if reject else [])]
    for index,path in enumerate(paths):
        for other in paths[:index]:
            if path==other or path.exists() and other.exists() and os.path.samefile(path,other):raise ValueError('Grouped stream paths must be different')
    source,target=paths[:2];initial=source.stat();identity=(initial.st_size,initial.st_mtime_ns)
    maximum=integer(cfg.get('streamMaxRecordBytes'),1048576,64*1024**2)
    if maximum<256:raise ValueError('Streaming record limit must be at least 256 bytes')
    ending={'auto':'\n','lf':'\n','cr':'\r','crlf':'\r\n'}.get(str(cfg.get('lineSeparator',cfg.get('lineEnding','Auto'))).lower(),cfg.get('lineEnding','\n'))
    if ending not in ('\n','\r','\r\n'):raise ValueError('Invalid grouped record separator')
    def check():
        if callable(ctx.get('_formatCancelled')) and ctx['_formatCancelled']():raise ValueError('Grouped Data stream cancelled')
        info=source.stat()
        if (info.st_size,info.st_mtime_ns)!=identity:raise ValueError('Grouped input changed during processing')
    errors=groups=0;wrote=False
    with ExitStack() as stack:
        output=stack.enter_context(AtomicText(target,'utf-8' if parsing else str(cfg.get('fileEncoding') or 'utf-8')))
        rejects=stack.enter_context(AtomicText(paths[2],'utf-8')) if reject else None
        validator=stack.enter_context(FileValidator(formats,cfg,ctx,target))
        def rejected(token,message):
            nonlocal errors
            errors+=1
            if rejects:
                raw=token.raw.encode('utf-8');snippet=raw[:maximum//8].decode('utf-8',errors='ignore')
                text=str(message).encode('utf-8')[:min(256,maximum//8)].decode('utf-8',errors='ignore')
                value={'recordNumber':validator.records+errors,'message':text,'raw':snippet,'rawTruncated':len(snippet.encode('utf-8'))<len(raw)}
                encoded=json.dumps(value,ensure_ascii=False,separators=(',',':'))
                while len(encoded.encode('utf-8'))>maximum:
                    value['raw']=value['raw'][:len(value['raw'])//2];value['message']=value['message'][:len(value['message'])//2];value['rawTruncated']=True
                    encoded=json.dumps(value,ensure_ascii=False,separators=(',',':'))
                rejects.handle.write(encoded+'\n')
        def emit(group):
            nonlocal groups,wrote
            validator.logical(group,group=True);groups+=1
            if parsing:output.handle.write(json.dumps(group,ensure_ascii=False,allow_nan=False,separators=(',',':'))+'\n')
            else:
                from itertools import chain
                for role,record in chain([('header',group['header'])],(('detail',row) for row in group['details']),[('trailer',group['trailer'])]):
                    validator.physical(record,detail=role=='detail')
                    text=layout.render(role,record)
                    if len(text.encode('utf-8'))>maximum:raise ValueError('Rendered grouped record exceeds byte limit')
                    if wrote:output.handle.write(ending)
                    output.handle.write(text);wrote=True
        if parsing:
            fixed=str(cfg.get('format','delimited')).lower() in ('fixed','fixed width');delimiter=str(cfg.get('delimiter',','))
            if not fixed and (not delimiter or any(char in delimiter for char in '\r\n"')):raise ValueError('Invalid grouped delimiter')
            recovery=str(cfg.get('quoteRecovery') or 'bounded').lower()
            if recovery not in ('bounded','physical-line'):raise ValueError('Unknown quote recovery')
            continuing=formats.as_bool(cfg.get('continueOnError'));current=None;size=0
            with source.open(encoding=str(cfg.get('fileEncoding') or 'utf-8-sig'),newline='') as handle:
                for token in logical_rows(handle,delimiter,str(cfg.get('separatorRule','single')).lower()=='any-character',fixed,maximum,integer(cfg.get('maxRecordLines'),1000,10000),recovery,continuing,formats.delimited_rows):
                    check()
                    if token.error:
                        rejected(token,token.error)
                        continue
                    if not token.values:continue
                    roles=[role for role in layout.layouts if layout.matches_row(role,token)]
                    if len(roles)!=1:raise ValueError('Grouped record matches zero or multiple roles')
                    role=roles[0]
                    if role=='header' and current is not None:raise ValueError('New header before previous trailer')
                    if role!='header' and current is None:raise ValueError(role+' record without an open header')
                    try:record=layout.parse(role,token.raw)
                    except (ValueError,MinaFault) as error:
                        if continuing and role=='detail':rejected(token,str(error));continue
                        raise
                    validator.physical(record,detail=role=='detail')
                    if role=='header':
                        current={'header':record,'details':[]};size=len(json.dumps(record).encode())
                    elif current is None:raise ValueError(role+' record without an open header')
                    elif role=='detail':
                        size+=len(json.dumps(record).encode())
                        if len(current['details'])>=layout.max_details or size>layout.maximum:raise ValueError('Group size/detail limit exceeded')
                        current['details'].append(record)
                    else:
                        current['trailer']=record;emit(layout.close(current));current=None
                if current is not None:raise ValueError('End of file before group trailer')
        else:
            with source.open(encoding='utf-8-sig',newline='') as handle:
                while True:
                    check();line=handle.readline(layout.maximum+1)
                    if not line:break
                    if len(line.encode('utf-8'))>layout.maximum:raise ValueError('Grouped JSON Lines record exceeds group byte limit')
                    if not line.strip():continue
                    group=json_value(line)
                    if not isinstance(group,dict) or group.keys()-{'header','details','trailer'} or not isinstance(group.get('header'),dict) or not isinstance(group.get('details'),list) or any(not isinstance(row,dict) for row in group['details']):raise ValueError('Grouped JSON Lines requires header/details/trailer objects')
                    if 'trailer' not in group and not layout.derive:raise ValueError('Missing trailer; enable deriveTrailer and configure defaults/checks to create it')
                    emit(layout.close(group,layout.derive))
            if wrote and formats.as_bool(cfg.get('includeFinalLineSeparator'),True):output.handle.write(ending)
        check();validation=validator.finish(errors);check()
        if rejects:rejects.commit()
        output.commit()
    return {'streamed':True,'filePath':str(target),'recordCount':groups,'groupCount':groups,'detailCount':validator.details,
            'sourceRecordCount':validator.records,'errorCount':errors,'batchCount':groups,'errorFile':str(paths[2]) if reject else None,'validation':validation,'done':True}
