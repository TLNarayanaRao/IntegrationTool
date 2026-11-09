import asyncio,base64,json,subprocess,sys,tempfile,unittest
from pathlib import Path
from xml.etree import ElementTree as ET
from app.runtime import WorkflowRuntime,MinaFault
from app.data_formats import execute_format
from app.models import Project
from app.raw_python import raw_python_files,engine_python_files

XSD='''<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema"><xs:element name="order"><xs:complexType><xs:sequence><xs:element name="quantity" type="xs:positiveInteger"/></xs:sequence><xs:attribute name="id" type="xs:string" use="required"/></xs:complexType></xs:element></xs:schema>'''

class FormatTests(unittest.TestCase):
    def run_format(self,kind,operation,config,payload=None):return execute_format(kind,operation,config,payload)

    def test_xml_xsd_validates_children_types_and_required_attributes(self):
        cfg={'schemaText':XSD,'validateOutput':True}
        self.assertEqual(self.run_format('xml','parse',{**cfg,'xmlString':'<order id="A"><quantity>2</quantity></order>'})['value']['quantity'],'2')
        for text in ('<order><quantity>2</quantity></order>','<order id="A"><quantity>-1</quantity></order>','<order id="A"/>'):
            with self.subTest(text=text),self.assertRaises(MinaFault):self.run_format('xml','parse',{**cfg,'xmlString':text})
        self.assertIn('<quantity>2</quantity>',self.run_format('xml','render',{'value':{'@id':'A','quantity':2},'schemaText':XSD,'validateInput':True})['xmlString'])
        with self.assertRaises(MinaFault):self.run_format('xml','render',{'value':{'@id':'A','quantity':0},'schemaText':XSD,'validateInput':True})

    def test_xml_binary_declaration_encoding_and_mixed_content_round_trip(self):
        text='<p>Hello <b id="x">world</b> and <i>MINA</i>!</p>'
        raw=('<?xml version="1.0" encoding="UTF-16"?>'+text).encode('utf-16')
        parsed=self.run_format('xml','parse',{'inputStyle':'Dynamic','xmlBinary':base64.b64encode(raw).decode()})
        result=self.run_format('xml','render',{'value':parsed,'outputStyle':'Binary','encoding':'UTF-16'})
        rendered=ET.fromstring(base64.b64decode(result['binaryContent']))
        self.assertEqual(''.join(rendered.itertext()),'Hello world and MINA!')
        self.assertEqual(rendered[0].attrib,{'id':'x'})

    def test_xml_entity_declarations_and_external_schema_references_are_rejected(self):
        with self.assertRaises(MinaFault):self.run_format('xml','parse',{'xmlString':'<!DOCTYPE x [<!ENTITY e "hello">]><x>&e;</x>'})
        schema='<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema"><xs:include schemaLocation="file:///not-permitted.xsd"/></xs:schema>'
        with self.assertRaises(MinaFault):self.run_format('xml','parse',{'xmlString':'<x/>','schemaText':schema,'validateOutput':True})

    def test_json_duplicate_policies_strict_numbers_and_null_array_positions(self):
        self.assertIs(self.run_format('json','parse',{}, {'body':False}),False)
        for policy,expected in [('First wins',1),('Last wins',2)]:self.assertEqual(self.run_format('json','parse',{'jsonString':'{"id":1,"id":2}','duplicateKeyPolicy':policy})['id'],expected)
        for source in ('{"id":1,"id":2}','{"number":NaN}'):
            with self.assertRaises(MinaFault):self.run_format('json','parse',{'jsonString':source,'duplicateKeyPolicy':'Error'})
        result=self.run_format('json','render',{'value':{'drop':None,'values':[1,None,{'drop':None}]},'omitNulls':True})
        self.assertEqual(json.loads(result['jsonString']),{'values':[1,None,{}]})
        with self.assertRaises(MinaFault):self.run_format('json','render',{'value':float('inf')})

    def test_json_schema_local_refs_and_invalid_schema_do_not_silently_skip_validation(self):
        schema={'$defs':{'ID':{'type':'integer','minimum':1}},'type':'object','required':['id'],'properties':{'id':{'$ref':'#/$defs/ID'}}}
        self.assertEqual(self.run_format('json','parse',{'jsonString':'{"id":2}','validateOutput':True,'schemaText':json.dumps(schema)}),{'id':2})
        for contract,value in [(json.dumps(schema),'{}'),('<not-json-schema/>','{}')]:
            with self.assertRaises(MinaFault):self.run_format('json','parse',{'jsonString':value,'validateOutput':True,'schemaText':contract})

    def test_csv_round_trip_preserves_quoted_newlines_unicode_and_quotes(self):
        records=[{'id':1,'description':'MINA, "hello"\r\nnext line café'}]
        cfg={'fields':'id,description','fieldTypes':'integer,string','header':True,'lineSeparator':'CRLF','strictColumns':True}
        result=self.run_format('flat','render',{**cfg,'records':records})
        self.assertEqual(result['text'],result['content'])
        self.assertEqual(self.run_format('flat','parse',{**cfg,'text':result['text']})['records'],records)

    def test_multicharacter_and_any_character_delimiters_round_trip(self):
        self.assertEqual(self.run_format('flat','parse',{'text':'value\n""\n','delimiter':'||'})['records'],[{'value':''}])
        for delimiter,rule in [('||','single'),(';\t','any-character')]:
            cfg={'fields':'id,text','fieldTypes':'integer,string','delimiter':delimiter,'separatorRule':rule,'strictColumns':True}
            records=[{'id':2,'text':'value||with;tab\tand\nnewline "q"'}]
            text=self.run_format('flat','render',{**cfg,'records':records})['text']
            self.assertEqual(self.run_format('flat','parse',{**cfg,'text':text})['records'],records)

    def test_fixed_width_zero_fill_does_not_remove_significant_trailing_zeroes(self):
        cfg={'format':'fixed','fields':'amount,label','fieldTypes':'integer,string','widths':'5,3','fillCharacter':'0','header':False,'strictColumns':True}
        result=self.run_format('flat','render',{**cfg,'records':[{'amount':100,'label':'abc'}]})
        self.assertEqual(self.run_format('flat','parse',{**cfg,'text':result['text']})['records'][0]['amount'],100)
        with self.assertRaises(MinaFault):self.run_format('flat','render',{**cfg,'records':[{'amount':100000,'label':'abc'}]})

    def test_data_rejects_invalid_booleans_duplicate_fields_and_bad_columns(self):
        for config in ({'text':'flag\nmaybe','fieldTypes':'boolean'},{'text':'id,id\n1,2'},{'text':'id,name\n1','strictColumns':True}):
            with self.subTest(config=config),self.assertRaises(MinaFault):self.run_format('flat','parse',config)

    def test_parse_data_reads_files_with_encoding_and_quoted_newlines(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'data.csv';path.write_bytes('id,text\r\n1,"café\r\nnext"'.encode('utf-16'))
            result=self.run_format('flat','parse',{'inputSource':'File path','filePath':str(path),'fileEncoding':'utf-16','fieldTypes':'integer,string'})
            self.assertEqual(result['records'],[{'id':1,'text':'café\r\nnext'}])

class ArchiveFormatTests(unittest.TestCase):
    def test_all_six_activities_match_studio_in_both_python_archives(self):
        cases=[('xml','<order id="A"><quantity>2</quantity></order>',{'schemaText':XSD,'validateOutput':True},{'schemaText':XSD,'validateInput':True}),('json','{"id":2,"items":[null,3]}',{}, {'omitNulls':True}),('flat','id,text\n1,"hello\nworld"',{'fields':'id,text','fieldTypes':'integer,string'},{'fields':'id,text','fieldTypes':'integer,string'})]
        for kind,payload,parse_cfg,render_cfg in cases:
            tasks=[{'id':'main','name':'Main','kind':'starter','activities':[{'id':'Start','name':'Start','type':'start','config':{}},{'id':'Parse','name':'Parse','type':kind,'config':{'operation':'parse',**parse_cfg}},{'id':'Render','name':'Render','type':kind,'config':{'operation':'render',**render_cfg}},{'id':'End','name':'End','type':'end','config':{}}],'transitions':[{'id':'a','source':'Start','target':'Parse'},{'id':'b','source':'Parse','target':'Render'},{'id':'c','source':'Render','target':'End'}]}]
            project=Project.model_validate({'id':'formats','name':'Formats','tasks':tasks})
            expected=asyncio.run(WorkflowRuntime().run(project.tasks[0],payload,project=project)).output
            for compiler in (raw_python_files,engine_python_files):
                with self.subTest(kind=kind,compiler=compiler.__name__),tempfile.TemporaryDirectory() as folder:
                    for name,data in compiler(project.model_dump(),{'local':[]}).items():
                        path=Path(folder)/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(data)
                    script='import asyncio,json;from application.main import run_task;print("RESULT="+json.dumps(asyncio.run(run_task("main",'+repr(payload)+'))))'
                    result=subprocess.run([sys.executable,'-c',script],cwd=folder,capture_output=True,text=True,timeout=30)
                    self.assertEqual(result.returncode,0,result.stdout+result.stderr)
                    actual=json.loads(next(line[7:] for line in result.stdout.splitlines() if line.startswith('RESULT=')))
                    self.assertEqual(actual,expected)
