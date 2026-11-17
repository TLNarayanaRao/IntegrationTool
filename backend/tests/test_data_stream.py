"""Nested Data records, recoverable quoting and bounded file/archive flows."""
import asyncio
import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from app.data_formats import DataFormats, execute_format
from app.faults import MinaFault
from app.models import Project

NESTED_XSD='''<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema"><xs:element name="records"><xs:complexType><xs:sequence>
<xs:element name="row" maxOccurs="unbounded"><xs:complexType><xs:sequence>
<xs:element name="customer"><xs:complexType><xs:sequence><xs:element name="id" type="xs:int"/><xs:element name="city" type="xs:string"/></xs:sequence></xs:complexType></xs:element>
<xs:element name="lines" minOccurs="0" maxOccurs="unbounded"><xs:complexType><xs:sequence><xs:element name="sku" type="xs:string"/><xs:element name="qty" type="xs:int"/></xs:sequence></xs:complexType></xs:element>
</xs:sequence></xs:complexType></xs:element></xs:sequence></xs:complexType></xs:element></xs:schema>'''
CFG={'nestedRecords':True,'fields':'id,city,items','fieldTypes':'integer,string,json',
     'fieldPaths':{'id':'/customer/id','city':'/customer/address/city','items':'/lines'},'strictColumns':True}
ROWS=[{'customer':{'id':7,'address':{'city':'A\nB'}},'lines':[{'sku':'A','qty':2},{'sku':'B','qty':1}]}]


class DataStreamTests(unittest.TestCase):
    def test_nested_objects_repeating_json_and_fixed_paths_round_trip(self):
        before=copy.deepcopy(ROWS)
        rendered=execute_format('flat','render',{**CFG,'records':ROWS},None)
        result=execute_format('flat','parse',CFG,rendered['text'])
        self.assertEqual(result['records'],ROWS);self.assertEqual(ROWS,before)
        self.assertIn('<customer>',result['xml']);self.assertIn('<lines>',result['xml'])
        fixed={**CFG,'fields':'id,city','fieldTypes':'integer,string','fieldPaths':{'id':'/customer/id','city':'/customer/city'},
               'format':'fixed','widths':'3,4','header':False}
        records=[{'customer':{'id':7,'city':'NY'}}]
        text=execute_format('flat','render',{**fixed,'records':records},None)['text']
        self.assertEqual(execute_format('flat','parse',fixed,text)['records'],records)

    def test_nested_xsd_inference_preserves_parent_paths_and_repeats(self):
        cfg={'nestedRecords':True,'schemaText':NESTED_XSD,'validateInput':True,'validateOutput':True,'strictColumns':True}
        records=[{'customer':{'id':1,'city':'Paris'},'lines':[{'sku':'A','qty':2}]}]
        text=execute_format('flat','render',{**cfg,'records':records},None)['text']
        self.assertTrue(text.startswith('customer.id,customer.city,lines'))
        self.assertEqual(execute_format('flat','parse',cfg,text)['records'],records)
        schema={'type':'object','properties':{'id':{'type':'integer'},'details':{'type':'object','properties':{'city':{'type':'string'}}},'lines':{'type':'array','items':{'type':'object'}}}}
        cfg={'nestedRecords':True,'schemaText':json.dumps(schema)}
        records=[{'id':1,'details':{'city':'Paris'},'lines':[{'sku':'A'}]}]
        text=execute_format('flat','render',{**cfg,'records':records},None)['text']
        self.assertEqual(execute_format('flat','parse',cfg,text)['records'],records)

    def test_array_positions_escaped_keys_and_conflicting_paths(self):
        cfg={'nestedRecords':True,'fields':'sku,key','fieldPaths':{'sku':'/items/0/sku','key':'/a~1b/~0key'}}
        self.assertEqual(execute_format('flat','parse',cfg,'sku,key\nA,value')['records'],[{'items':[{'sku':'A'}],'a/b':{'~key':'value'}}])
        for paths in ({'sku':'/a','key':'/a/b'},{'sku':'/a','key':'/a'},{'sku':'','key':'/key'}):
            with self.assertRaises(MinaFault): execute_format('flat','parse',{**cfg,'fieldPaths':paths},'sku,key\nA,v')
        with self.assertRaises(MinaFault): execute_format('flat','render',{**CFG,'records':[{'customer':{'id':1,'address':{'city':'X'},'extra':1},'lines':[]}]},None)

    def test_quote_recovery_preserves_following_rows_and_batch_cursor(self):
        text='id,name\n1,"unclosed\n2,Good\n3,AlsoGood'
        cfg={'continueOnError':True,'fieldTypes':'integer,string','noOfRecords':1,'streamMaxRecordBytes':1024}
        cursors={}; first=execute_format('flat','parse',cfg,text,cursors,'p')
        self.assertEqual(first['records'],[]);self.assertEqual(len(first['ErrorRows']['error']),1);self.assertFalse(first['done'])
        self.assertEqual(execute_format('flat','parse',cfg,text,cursors,'p')['records'],[{'id':2,'name':'Good'}])
        last=execute_format('flat','parse',cfg,text,cursors,'p');self.assertEqual(last['records'],[{'id':3,'name':'AlsoGood'}]);self.assertTrue(last['done'])
        cfg={**cfg,'noOfRecords':-1,'quoteRecovery':'physical-line'}
        self.assertEqual(len(execute_format('flat','parse',cfg,text)['records']),2)
        with self.assertRaises(MinaFault): execute_format('flat','parse',{'continueOnError':False},text)
        for separator,rule in [('||','single'),(';\t','any-character')]:
            sep=separator if rule=='single' else ';'
            result=execute_format('flat','parse',{'delimiter':separator,'separatorRule':rule,'continueOnError':True},f'id{sep}name\n1{sep}"bad\n2{sep}Good')
            self.assertEqual(result['records'],[{'id':'2','name':'Good'}])

    def test_stream_metadata_byte_batches_rejects_and_atomic_failure(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);source=root/'input.csv';parsed=root/'records.jsonl';reject=root/'reject.jsonl';target=root/'output.csv'
            source.write_text('id,name\n1,"bad\n'+''.join(f'{i},'+('X'*250)+'\n' for i in range(2,42)),encoding='utf-8')
            cfg={'streaming':True,'fileName':str(source),'streamOutputFile':str(parsed),'streamErrorFile':str(reject),'continueOnError':True,
                 'streamMaxRecordBytes':1024,'streamMaxBatchBytes':2048,'streamBatchSize':100,'fieldTypes':'integer,string'}
            result=execute_format('flat','parse',cfg,None)
            self.assertTrue(result['streamed']);self.assertNotIn('records',result);self.assertEqual(result['recordCount'],40);self.assertEqual(result['errorCount'],1)
            self.assertGreater(result['batchCount'],1);self.assertEqual(len(reject.read_text().splitlines()),1)
            rendered=execute_format('flat','render',{'streaming':True,'streamInputFile':str(parsed),'streamOutputFile':str(target),'fields':'id,name','includeFinalLineSeparator':False,'streamBatchSize':3},None)
            self.assertEqual(rendered['recordCount'],40);self.assertFalse(target.read_text().endswith('\n'))
            self.assertEqual(len(target.read_text().splitlines()),41)
            target.write_text('KEEP',encoding='utf-8');parsed.write_text('{bad json}\n',encoding='utf-8')
            with self.assertRaises(MinaFault): execute_format('flat','render',{'streaming':True,'streamInputFile':str(parsed),'streamOutputFile':str(target)},None)
            self.assertEqual(target.read_text(),'KEEP');self.assertEqual(list(root.glob('*.mina-part')),[])
            with self.assertRaises(MinaFault): execute_format('flat','parse',{**cfg,'streamOutputFile':str(source)},None)
            source.write_text('id\n'+''.join(f'{i}\n' for i in range(100)),newline='')
            calls=0
            def mutate():
                nonlocal calls
                calls+=1
                if calls==5:
                    with source.open('a') as handle:handle.write('1001\n')
                return False
            with self.assertRaisesRegex(MinaFault,'changed'):DataFormats().run_format('flat','parse',{'operation':'parse','streaming':True,'streamBatchSize':10,'fileName':str(source),'streamOutputFile':str(target)}, {'last':{},'_formatCancelled':mutate})
            self.assertEqual(target.read_text(),'KEEP')

    def test_async_cancel_stops_worker_before_commit(self):
        from app.data_formats import run_format_async
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);source=root/'in.csv';target=root/'out.jsonl'
            source.write_text('id\n1\n');target.write_text('KEEP');started=threading.Event()
            original=DataFormats.flat_data
            def delayed(formats,cfg,ctx):
                if cfg.get('streaming'):started.set();time.sleep(.1)
                return original(formats,cfg,ctx)
            async def cancel():
                with patch.object(DataFormats,'flat_data',delayed):
                    task=asyncio.create_task(run_format_async('flat','parse',{'operation':'parse','streaming':True,'fileName':str(source),'streamOutputFile':str(target)}, {'last':{}}))
                    self.assertTrue(await asyncio.to_thread(started.wait,2))
                    task.cancel()
                    with self.assertRaises(asyncio.CancelledError):await task
                    await asyncio.sleep(.2)
            asyncio.run(cancel())
            self.assertEqual(target.read_text(),'KEEP');self.assertEqual(list(root.glob('*.mina-part')),[])

    def test_cancellation_and_mutation_preserve_existing_output(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);source=root/'in.csv';target=root/'out.jsonl'
            source.write_text('id\n'+''.join(f'{i}\n' for i in range(1000)));target.write_text('KEEP')
            calls=0
            def cancelled():
                nonlocal calls
                calls+=1;return calls>20
            with self.assertRaises(MinaFault): DataFormats().run_format('flat','parse',{'operation':'parse','streaming':True,'fileName':str(source),'streamOutputFile':str(target)}, {'last':{},'_formatCancelled':cancelled})
            self.assertEqual(target.read_text(),'KEEP');self.assertEqual(list(root.glob('*.mina-part')),[])

    def test_streamed_encoding_separators_and_final_newline_match_legacy(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);source=root/'records.jsonl'
            source.write_text(''.join(json.dumps(row)+'\n' for row in ROWS+ROWS),encoding='utf-8',newline='')
            for delimiter in (',','||',';\t'):
                cfg={**CFG,'delimiter':delimiter,'separatorRule':'any-character' if delimiter==';\t' else 'single','lineSeparator':'CRLF','includeFinalLineSeparator':False}
                expected=execute_format('flat','render',{**cfg,'records':ROWS+ROWS},None)['text']
                target=root/('output'+str(len(delimiter))+'.txt')
                execute_format('flat','render',{**cfg,'streaming':True,'streamBatchSize':1,'streamInputFile':str(source),'streamOutputFile':str(target),'fileEncoding':'utf-16'},None)
                self.assertEqual(target.read_bytes().decode('utf-16'),expected)
            with self.assertRaises(MinaFault):execute_format('flat','render',{'format':'fixed','fields':'v','widths':'5','records':[{'v':'A\nB'}]},None)
            with self.assertRaises(MinaFault):execute_format('flat','render',{'format':'fixed','fields':'v','widths':'5','fillCharacter':'\n','records':[{'v':'A'}]},None)

    def test_nested_streams_and_recovery_run_debug_both_archives(self):
        nodes=[{'id':'s','name':'Start','type':'start'},
               {'id':'p','name':'Parse-Stream','type':'flat','config':{**CFG,'operation':'parse','streaming':True,'streamBatchSize':2,'continueOnError':True,
                  'inputMappings':{'fileName':'${input.source}','streamOutputFile':'${input.records}','streamErrorFile':'${input.errors}'}}},
               {'id':'r','name':'Render-Stream','type':'flat','config':{**CFG,'operation':'render','streaming':True,'streamBatchSize':1,
                  'inputMappings':{'streamInputFile':'${input.records}','streamOutputFile':'${input.target}'}}},
               {'id':'e','name':'End','type':'end'}]
        project=Project.model_validate({'id':'stream-data','name':'Stream-Data','tasks':[{'id':'main','name':'Main','kind':'subtask','activities':nodes,
            'transitions':[{'id':str(i),'source':a['id'],'target':b['id']} for i,(a,b) in enumerate(zip(nodes,nodes[1:]))]}]})
        spec=importlib.util.spec_from_file_location('data_stream_flow',Path(__file__).parents[2]/'scripts/flow-throughput.py')
        flow=importlib.util.module_from_spec(spec);spec.loader.exec_module(flow)
        async def run(root):
            for mode in ('run','debug','python-direct','python-engine'):
                source=root/(mode+'.csv');target=root/(mode+'.out.csv');records=root/(mode+'.jsonl');errors=root/(mode+'.errors.jsonl')
                valid=execute_format('flat','render',{**CFG,'records':ROWS+ROWS},None)['text']
                source.write_text(valid.split('\n',1)[0]+'\n9,"bad\n'+valid.split('\n',1)[1],encoding='utf-8',newline='')
                executor=flow.Executor(mode,project,str(root/(mode+'.log')))
                try:
                    await executor.start();result=await executor.execute('main',{'source':str(source),'target':str(target),'records':str(records),'errors':str(errors)})
                    self.assertEqual(result['recordCount'],2,mode)
                    self.assertEqual([json.loads(line) for line in records.read_text().splitlines()],ROWS+ROWS,mode)
                    self.assertEqual(execute_format('flat','parse',CFG,target.read_text())['records'],ROWS+ROWS,mode)
                    self.assertEqual(len(errors.read_text().splitlines()),1,mode)
                    print('Nested Data stream complete flow:',mode,'passed',flush=True)
                finally:await executor.close()
        with tempfile.TemporaryDirectory() as folder:asyncio.run(run(Path(folder)))


if __name__=='__main__':unittest.main()
