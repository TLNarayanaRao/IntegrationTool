"""Data header/layout, strict rendering and full record XSD regression tests."""
import asyncio
import importlib.util
from pathlib import Path
import tempfile
import unittest

from app.data_formats import execute_format
from app.faults import MinaFault
from app.models import Project

XSD = '''<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema"><xs:element name="records"><xs:complexType><xs:sequence>
<xs:element name="row" maxOccurs="unbounded"><xs:complexType><xs:sequence>
<xs:element name="id" type="xs:positiveInteger"/><xs:element name="name"><xs:simpleType><xs:restriction base="xs:string"><xs:minLength value="2"/></xs:restriction></xs:simpleType></xs:element>
</xs:sequence></xs:complexType></xs:element></xs:sequence></xs:complexType></xs:element></xs:schema>'''


class DataActivityGapsTests(unittest.TestCase):
    def test_reordered_headers_use_named_types_and_strict_names(self):
        cfg = {'fields': 'id,name', 'fieldTypes': 'integer,string', 'strictColumns': True}
        self.assertEqual(execute_format('flat','parse',cfg,'name,id\nAnn,7')['records'], [{'name': 'Ann', 'id': 7}])
        for text in ('other,id\nAnn,7', 'id,\n7,Ann'):
            with self.assertRaises(MinaFault): execute_format('flat','parse',cfg,text)

    def test_strict_rendering_checks_records_for_every_layout(self):
        for layout in ({'delimiter':','}, {'delimiter':'||'}, {'format':'fixed','widths':'3,4'}):
            cfg = {'fields':'id,name','strictColumns':True, **layout}
            for row in ({'id':1}, {'id':1,'name':'Ann','extra':True}):
                with self.subTest(layout=layout,row=row), self.assertRaises(MinaFault): execute_format('flat','render',{**cfg,'records':[row]},None)
        for fields in ('id,id','id,,name'):
            with self.assertRaises(MinaFault): execute_format('flat','render',{'fields':fields,'records':[{'id':1}]},None)

    def test_fixed_negative_zero_fill_keeps_sign_at_the_front(self):
        cfg = {'format':'fixed','fields':'id','fieldTypes':'integer','widths':'5','fillCharacter':'0','header':False,'strictColumns':True}
        rendered = execute_format('flat','render',{**cfg,'records':[{'id':-12}]},None)
        self.assertEqual(rendered['text'],'-0012')
        self.assertEqual(execute_format('flat','parse',cfg,rendered['text'])['records'], [{'id':-12}])

    def test_dynamic_layout_changes_reset_automatic_cursor(self):
        text = 'id\n001\n002\n'; cursors = {}; cfg = {'noOfRecords':1,'fields':'id','fieldTypes':'integer'}
        self.assertEqual(execute_format('flat','parse',cfg,text,cursors,'p')['records'],[{'id':1}])
        self.assertEqual(execute_format('flat','parse',{**cfg,'fieldTypes':'string'},text,cursors,'p')['records'],[{'id':'001'}])
        self.assertEqual(execute_format('flat','parse',{**cfg,'fieldTypes':'string'},text,cursors,'p')['records'],[{'id':'002'}])

    def test_xsd_validation_rejects_facets_and_missing_schema(self):
        cfg = {'schemaText':XSD,'validateOutput':True}
        self.assertEqual(execute_format('flat','parse',cfg,'id,name\n7,Ann')['records'],[{'id':7,'name':'Ann'}])
        for text in ('id,name\n0,Ann','id,name\n7,A'):
            with self.subTest(text=text), self.assertRaises(MinaFault): execute_format('flat','parse',cfg,text)
        with self.assertRaises(MinaFault): execute_format('flat','render',{'schemaText':XSD,'validateInput':True,'records':[{'id':0,'name':'Ann'}]},None)
        with self.assertRaises(MinaFault): execute_format('flat','parse',{'validateOutput':True},'id\n1')
        with self.assertRaises(MinaFault): execute_format('flat','render',{'validateInput':True,'records':[{'id':1}]},None)

    def test_invalid_dynamic_options_fail_explicitly(self):
        for option in ({'format':'unknown'},{'separatorRule':'unknown'},{'lineSeparator':'unknown'},{'blankLinePolicy':'unknown'}):
            with self.subTest(option=option), self.assertRaises(MinaFault): execute_format('flat','parse',option,'id\n1')
        recovered=execute_format('flat','parse',{'continueOnError':True},'id,name\n1,"unclosed\n2,Good')
        self.assertEqual(recovered['records'],[{'id':'2','name':'Good'}])
        self.assertEqual(len(recovered['ErrorRows']['error']),1)

    def test_dynamic_validation_in_run_debug_and_both_archives(self):
        nodes = [{'id':'s','name':'Start','type':'start'},
                 {'id':'p','name':'Parse-Data','type':'flat','config':{'operation':'parse','schemaText':XSD,
                    'inputMappings':{'text':'${input.document}','formatOptions.validateOutput':'${input.validate}','formatOptions.strictColumns':'true'}}},
                 {'id':'r','name':'Render-Data','type':'flat','config':{'operation':'render','schemaText':XSD,
                    'inputMappings':{'formatOptions.validateInput':'${input.validate}','formatOptions.strictColumns':'true'}}},
                 {'id':'e','name':'End','type':'end'}]
        project = Project.model_validate({'id':'data-gaps','name':'Data-Gaps','tasks':[{'id':'main','name':'Main','kind':'subtask','activities':nodes,
            'transitions':[{'id':str(i),'source':a['id'],'target':b['id']} for i,(a,b) in enumerate(zip(nodes,nodes[1:]))]}]})
        spec = importlib.util.spec_from_file_location('data_gap_flows',Path(__file__).parents[2]/'scripts/flow-throughput.py')
        flow = importlib.util.module_from_spec(spec);spec.loader.exec_module(flow)
        async def run(folder):
            for mode in ('run','debug','python-direct','python-engine'):
                executor = flow.Executor(mode,project,str(Path(folder)/(mode+'.log')))
                try:
                    await executor.start()
                    result = await executor.execute('main',{'document':'name,id\nAnn,7','validate':True})
                    self.assertEqual(result['text'],'id,name\n7,Ann\n',mode)
                    with self.assertRaises(RuntimeError): await executor.execute('main',{'document':'name,id\nAnn,0','validate':True})
                    permissive = await executor.execute('main',{'document':'name,id\nAnn,0','validate':False})
                    self.assertIn('0,Ann',permissive['text'])
                    print('Data gap flow:',mode,'validated/rejected/dynamic-off passed',flush=True)
                finally: await executor.close()
        with tempfile.TemporaryDirectory() as folder: asyncio.run(run(folder))


if __name__ == '__main__': unittest.main()
