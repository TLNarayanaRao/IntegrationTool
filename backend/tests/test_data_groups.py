"""HDT framing, EOF rules and complete XSD identity validation in every runtime."""
import asyncio
import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

from app.data_formats import execute_format, DataFormats
from app.faults import MinaFault
from app.models import Project

LAYOUTS={
 'header':{'match':{'column':0,'value':'H'},'fields':'kind,orderId','fieldTypes':'string,string'},
 'detail':{'match':{'column':0,'value':'D'},'fields':'kind,sku,amount,orderRef','fieldTypes':'string,string,string,string'},
 'trailer':{'match':{'column':0,'value':'T'},'fields':'kind,count,total','fieldTypes':'string,integer,string','defaults':{'kind':'T'}},
 'trailerChecks':[{'kind':'count','trailerPath':'/count'},{'kind':'sum','detailPath':'/amount','trailerPath':'/total','scale':2}]}
SOURCE='H,A\nD,A1,10.25,B\nD,A2,2.75,A\nT,2,13.00\nH,B\nD,B1,0.10,A\nD,B2,0.20,B\nT,2,0.30\n'
RULES={'minRecords':8,'maxRecords':8,'minGroups':2,'maxGroups':2,'minDetails':4,'maxDetails':4,
       'uniqueKeys':[['/header/orderId']],'totals':[{'name':'amount','path':'/amount','expected':'13.30'}]}
XSD='''<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema"><xs:element name="records"><xs:complexType><xs:sequence>
<xs:element name="group" maxOccurs="unbounded"><xs:complexType><xs:sequence>
<xs:element name="header"><xs:complexType><xs:sequence><xs:element name="kind" type="xs:string"/><xs:element name="orderId" type="xs:string"/></xs:sequence></xs:complexType></xs:element>
<xs:element name="details" maxOccurs="unbounded"><xs:complexType><xs:sequence><xs:element name="kind" type="xs:string"/><xs:element name="sku" type="xs:string"/><xs:element name="amount" type="xs:decimal"/><xs:element name="orderRef" type="xs:string"/></xs:sequence></xs:complexType></xs:element>
<xs:element name="trailer"><xs:complexType><xs:sequence><xs:element name="kind" type="xs:string"/><xs:element name="count" type="xs:nonNegativeInteger"/><xs:element name="total" type="xs:decimal"/></xs:sequence></xs:complexType></xs:element>
</xs:sequence></xs:complexType></xs:element></xs:sequence></xs:complexType>
<xs:key name="orderKey"><xs:selector xpath="group/header"/><xs:field xpath="orderId"/></xs:key>
<xs:keyref name="orderRef" refer="orderKey"><xs:selector xpath="group/details"/><xs:field xpath="orderRef"/></xs:keyref>
</xs:element></xs:schema>'''
CFG={'streaming':True,'groupRecords':True,'recordLayouts':LAYOUTS,'wholeFileValidation':True,'wholeFileRules':RULES,
     'wholeFileXsd':True,'schemaText':XSD,'recordElement':'group','strictColumns':True,'streamBatchSize':1}


class DataGroupTests(unittest.TestCase):
    def parse(self,root,source=SOURCE,**overrides):
        file=root/'input.csv';file.write_text(source,encoding='utf-8',newline='')
        return execute_format('flat','parse',{**CFG,'fileName':str(file),'streamOutputFile':str(root/'groups.jsonl'),**overrides},None)

    def test_multiple_groups_trailer_controls_and_forward_xsd_keyrefs(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);result=self.parse(root)
            self.assertEqual(result['groupCount'],2);self.assertEqual(result['detailCount'],4);self.assertEqual(result['sourceRecordCount'],8)
            self.assertEqual(result['validation']['totals'],{'amount':'13.30'});self.assertTrue(result['validation']['xsdValidated'])
            groups=[json.loads(line) for line in (root/'groups.jsonl').read_text().splitlines()]
            self.assertEqual(groups[0]['header']['orderId'],'A');self.assertEqual(len(groups[1]['details']),2)
            target=root/'render.csv'
            rendered=execute_format('flat','render',{**CFG,'streamInputFile':str(root/'groups.jsonl'),'streamOutputFile':str(target)},None)
            self.assertEqual(target.read_bytes().decode(),SOURCE);self.assertEqual(rendered['groupCount'],2)

    def test_framing_counts_totals_and_eof_fail_atomically(self):
        invalid=[SOURCE.replace('T,2,13.00','T,3,13.00'),SOURCE.replace('T,2,0.30','T,2,0.31'),
                 SOURCE.rstrip().rsplit('\n',1)[0]+'\n','D,A1,1,A\n'+SOURCE,SOURCE.replace('D,A1','H,A1',1),SOURCE.replace('D,A1','X,A1',1)]
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);target=root/'groups.jsonl'
            for source in invalid:
                target.write_text('KEEP')
                with self.subTest(source=source[:40]),self.assertRaises(MinaFault):self.parse(root,source)
                self.assertEqual(target.read_text(),'KEEP');self.assertFalse(list(root.glob('*.mina-part')))

    def test_whole_file_unique_keys_and_global_xsd_fail_across_groups(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            with self.assertRaisesRegex(MinaFault,'duplicate key'):self.parse(root,SOURCE.replace('H,B','H,A'))
            with self.assertRaisesRegex(MinaFault,'Whole-file XSD'):self.parse(root,SOURCE.replace('H,B','H,A'),wholeFileValidation=False)
            with self.assertRaisesRegex(MinaFault,'Whole-file XSD'):self.parse(root,SOURCE.replace('10.25,B','10.25,UNKNOWN'),wholeFileValidation=False)
            with self.assertRaisesRegex(MinaFault,'minimum'):self.parse(root,wholeFileRules={**RULES,'minGroups':3,'maxGroups':4})
            with self.assertRaisesRegex(MinaFault,'total mismatch'):self.parse(root,wholeFileRules={**RULES,'totals':[{'name':'amount','path':'/amount','expected':'999'}]})
            self.assertFalse(list(root.glob('.mina-keys-*')))
            self.parse(root)
            groups=[json.loads(line) for line in (root/'groups.jsonl').read_text().splitlines()]
            groups[-1]['details'][-1]['orderRef']='UNKNOWN'
            (root/'invalid.jsonl').write_text(''.join(json.dumps(group)+'\n' for group in groups))
            (root/'out.csv').write_text('KEEP')
            with self.assertRaisesRegex(MinaFault,'Whole-file XSD'):
                execute_format('flat','render',{**CFG,'streamInputFile':str(root/'invalid.jsonl'),'streamOutputFile':str(root/'out.csv')},None)
            self.assertEqual((root/'out.csv').read_text(),'KEEP')

    def test_root_attributes_and_invalid_settings(self):
        schema=XSD.replace('</xs:sequence></xs:complexType>\n<xs:key','</xs:sequence><xs:attribute name="batchId" type="xs:string" use="required"/></xs:complexType>\n<xs:key')
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            self.assertTrue(self.parse(root,schemaText=schema,wholeFileRules={**RULES,'rootAttributes':{'batchId':'QA'}})['validation']['xsdValidated'])
            with self.assertRaises(MinaFault):self.parse(root,schemaText=schema)
            for overrides in ({'wholeFileRules':{'unknown':1}}, {'wholeFileRules':{'minRecords':2,'maxRecords':1}},
                              {'recordLayouts':{**LAYOUTS,'trailerChecks':LAYOUTS['trailerChecks']*2}}, {'blankLinePolicy':'Stop'}):
                with self.subTest(overrides=overrides),self.assertRaises(MinaFault):self.parse(root,**overrides)

    def test_derive_trailer_and_size_controls(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);self.parse(root)
            groups=[json.loads(line) for line in (root/'groups.jsonl').read_text().splitlines()]
            for group in groups:group.pop('trailer')
            source=root/'derive.jsonl';source.write_text(''.join(json.dumps(group)+'\n' for group in groups))
            target=root/'derived.csv'
            execute_format('flat','render',{**CFG,'recordLayouts':{**LAYOUTS,'deriveTrailer':True},'streamInputFile':str(source),'streamOutputFile':str(target)},None)
            self.assertEqual(target.read_bytes().decode(),SOURCE)
            with self.assertRaises(MinaFault):self.parse(root,recordLayouts={**LAYOUTS,'maxGroupDetails':1})
            with self.assertRaises(MinaFault):self.parse(root,recordLayouts={**LAYOUTS,'maxGroupBytes':50})

    def test_rejected_detail_controls_and_group_cancellation(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);layout=copy.deepcopy(LAYOUTS);layout['detail']['fieldTypes']='string,string,decimal,string'
            source=SOURCE.replace('10.25,B','bad,B').replace('T,2,13.00','T,1,2.75')
            rules={**RULES,'minRecords':7,'maxRecords':7,'minDetails':3,'maxDetails':3,'maxErrors':1,
                   'totals':[{'name':'amount','path':'/amount','expected':'3.05'}]}
            result=self.parse(root,source,recordLayouts=layout,continueOnError=True,wholeFileRules=rules,streamErrorFile=str(root/'errors.jsonl'))
            self.assertEqual(result['errorCount'],1);self.assertEqual(result['detailCount'],3)
            self.assertEqual(len((root/'errors.jsonl').read_text().splitlines()),1)
            with self.assertRaises(MinaFault):self.parse(root,source,recordLayouts=layout,continueOnError=True,wholeFileRules={**rules,'maxErrors':0})
            (root/'input.csv').write_text(SOURCE,newline='');(root/'groups.jsonl').write_text('KEEP');calls=0
            def cancelled():
                nonlocal calls
                calls+=1;return calls>4
            with self.assertRaises(MinaFault):DataFormats().run_format('flat','parse',{**CFG,'operation':'parse','fileName':str(root/'input.csv'),'streamOutputFile':str(root/'groups.jsonl')},{'last':{},'_formatCancelled':cancelled})
            self.assertEqual((root/'groups.jsonl').read_text(),'KEEP');self.assertFalse(list(root.glob('.mina-keys-*')))

    def test_fixed_width_hdt_layout_round_trip(self):
        layout={'header':{'match':{'start':0,'end':1,'value':'H'},'fields':'kind,id','widths':'1,2'},
                'detail':{'match':{'start':0,'end':1,'value':'D'},'fields':'kind,amount','fieldTypes':'string,string','widths':'1,3'},
                'trailer':{'match':{'start':0,'end':1,'value':'T'},'fields':'kind,count','fieldTypes':'string,integer','widths':'1,1'},
                'trailerChecks':[{'kind':'count','trailerPath':'/count'}]}
        text='HAA\nD100\nD200\nT2\n'
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);source=root/'fixed';source.write_text(text,newline='')
            cfg={'streaming':True,'groupRecords':True,'recordLayouts':layout,'format':'fixed','strictColumns':True}
            execute_format('flat','parse',{**cfg,'fileName':str(source),'streamOutputFile':str(root/'fixed.jsonl')},None)
            execute_format('flat','render',{**cfg,'streamInputFile':str(root/'fixed.jsonl'),'streamOutputFile':str(root/'out')},None)
            self.assertEqual((root/'out').read_bytes().decode(),text)

    def test_ungrouped_whole_file_validation_across_tiny_batches(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);source=root/'rows.csv';target=root/'rows.jsonl';source.write_text('id,amount\n1,0.1\n2,0.2\n1,0.3\n',newline='')
            cfg={'streaming':True,'streamBatchSize':1,'wholeFileValidation':True,'wholeFileRules':{'minRecords':3,'uniqueKeys':[['/id']]},'fileName':str(source),'streamOutputFile':str(target)}
            target.write_text('KEEP')
            with self.assertRaisesRegex(MinaFault,'duplicate'):execute_format('flat','parse',cfg,None)
            self.assertEqual(target.read_text(),'KEEP')
            result=execute_format('flat','parse',{**cfg,'wholeFileRules':{'minRecords':3,'totals':[{'name':'sum','path':'/amount','expected':'0.6'}]}},None)
            self.assertEqual(result['validation']['totals']['sum'],'0.6')

    def test_complete_xsd_overrides_batch_identity_checks_and_supports_root_attributes(self):
        schema='''<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema"><xs:element name="rows"><xs:complexType><xs:sequence><xs:element name="row" minOccurs="2" maxOccurs="unbounded"><xs:complexType><xs:sequence><xs:element name="id" type="xs:int"/><xs:element name="ref" type="xs:int"/></xs:sequence></xs:complexType></xs:element></xs:sequence><xs:attribute name="batch" type="xs:string" use="required"/></xs:complexType><xs:key name="ids"><xs:selector xpath="row"/><xs:field xpath="id"/></xs:key><xs:keyref name="refs" refer="ids"><xs:selector xpath="row"/><xs:field xpath="ref"/></xs:keyref></xs:element></xs:schema>'''
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);source=root/'in';source.write_text('id,ref\n1,2\n2,1\n',newline='')
            cfg={'streaming':True,'wholeFileXsd':True,'schemaText':schema,'recordElement':'row','streamBatchSize':1,'strictColumns':True,
                 'wholeFileRules':{'rootAttributes':{'batch':'QA'}},'validateOutput':True,'validateInput':True}
            result=execute_format('flat','parse',{**cfg,'fileName':str(source),'streamOutputFile':str(root/'rows.jsonl')},None)
            self.assertTrue(result['validation']['xsdValidated'])
            execute_format('flat','render',{**cfg,'streamInputFile':str(root/'rows.jsonl'),'streamOutputFile':str(root/'out')},None)
            self.assertEqual((root/'out').read_text(),source.read_text())

    def test_grouped_run_debug_and_both_archives(self):
        nodes=[{'id':'s','name':'Start','type':'start'},
               {'id':'p','name':'Parse-Groups','type':'flat','config':{**CFG,'operation':'parse','inputMappings':{'fileName':'${input.source}','streamOutputFile':'${input.jsonl}','formatOptions.recordLayouts':'${input.layouts}','formatOptions.wholeFileRules':'${input.rules}'}}},
               {'id':'r','name':'Render-Groups','type':'flat','config':{**CFG,'operation':'render','inputMappings':{'streamInputFile':'${input.jsonl}','streamOutputFile':'${input.target}','formatOptions.recordLayouts':'${input.layouts}','formatOptions.wholeFileRules':'${input.rules}'}}},
               {'id':'e','name':'End','type':'end'}]
        project=Project.model_validate({'id':'groups-qa','name':'Groups-QA','tasks':[{'id':'main','name':'Main','kind':'subtask','activities':nodes,
            'transitions':[{'id':str(i),'source':a['id'],'target':b['id']} for i,(a,b) in enumerate(zip(nodes,nodes[1:]))]}]})
        spec=importlib.util.spec_from_file_location('group_flows',Path(__file__).parents[2]/'scripts/flow-throughput.py')
        flow=importlib.util.module_from_spec(spec);spec.loader.exec_module(flow)
        async def run(root):
            for mode in ('run','debug','python-direct','python-engine'):
                source=root/(mode+'.in');source.write_text(SOURCE,newline='');target=root/(mode+'.out');groups=root/(mode+'.jsonl')
                executor=flow.Executor(mode,project,str(root/(mode+'.log')))
                try:
                    await executor.start();result=await executor.execute('main',{'source':str(source),'target':str(target),'jsonl':str(groups),'layouts':LAYOUTS,'rules':RULES})
                    self.assertTrue(result['validation']['xsdValidated'],mode);self.assertEqual(result['groupCount'],2,mode)
                    self.assertEqual(target.read_bytes(),source.read_bytes(),mode)
                    source.write_text(SOURCE.replace('H,B','H,A'),newline='');groups.write_text('KEEP');target.write_text('KEEP')
                    with self.assertRaises(RuntimeError):await executor.execute('main',{'source':str(source),'target':str(target),'jsonl':str(groups),'layouts':LAYOUTS,'rules':RULES})
                    self.assertEqual(groups.read_text(),'KEEP');self.assertEqual(target.read_text(),'KEEP')
                    print('HDT and whole-file XSD/rules:',mode,'valid and atomic-invalid passed',flush=True)
                finally:await executor.close()
        with tempfile.TemporaryDirectory() as folder:asyncio.run(run(Path(folder)))


if __name__=='__main__':unittest.main()
