"""XML/JSON conversion contracts and complete Run/Debug/archive parity."""
import asyncio
import base64
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from lxml import etree
from app.data_formats import execute_format as run_format, xsd_shape
from app.debugger import DebugManager
from app.faults import MinaFault
from app.models import Project
from app.raw_python import raw_python_files, engine_python_files
from app.runtime import WorkflowRuntime

SIMPLE = '''<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema">
<xs:complexType name="Amount"><xs:simpleContent><xs:extension base="xs:decimal">
<xs:attribute name="currency" type="xs:string" use="required"/></xs:extension></xs:simpleContent></xs:complexType>
<xs:complexType name="Taxed"><xs:simpleContent><xs:extension base="Amount">
<xs:attribute name="tax" type="xs:boolean"/></xs:extension></xs:simpleContent></xs:complexType>
<xs:element name="invoice"><xs:complexType><xs:sequence>
<xs:element name="total" type="Taxed"/>
<xs:element name="confirmed"><xs:complexType><xs:simpleContent><xs:extension base="xs:boolean"/></xs:simpleContent></xs:complexType></xs:element>
<xs:element name="label"><xs:complexType><xs:simpleContent><xs:extension base="xs:string"><xs:attribute name="lang" type="xs:string"/></xs:extension></xs:simpleContent></xs:complexType></xs:element>
</xs:sequence></xs:complexType></xs:element></xs:schema>'''
NIL = '''<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema"><xs:element name="rows"><xs:complexType><xs:sequence>
<xs:element name="number" type="xs:int" nillable="true" maxOccurs="unbounded"/>
<xs:element name="object" nillable="true"><xs:complexType><xs:sequence><xs:element name="id" type="xs:int" minOccurs="0"/></xs:sequence></xs:complexType></xs:element>
</xs:sequence></xs:complexType></xs:element></xs:schema>'''
ORDER = '''<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema" targetNamespace="urn:order" xmlns:o="urn:order" elementFormDefault="qualified" attributeFormDefault="qualified">
<xs:element name="order"><xs:complexType><xs:sequence><xs:element name="id" type="xs:int"/><xs:element name="description" type="xs:string"/></xs:sequence><xs:attribute name="ref" type="xs:string" use="required"/></xs:complexType></xs:element></xs:schema>'''


def execute_format(kind, operation, config, payload=None):
    return run_format(kind, operation, config, payload)


class XmlJsonConformanceTests(unittest.TestCase):
    def test_simple_content_inheritance_preserves_text_and_attribute_types(self):
        text = '<invoice><total currency="USD" tax=" true ">12.5</total><confirmed> 1 </confirmed><label lang="en"></label></invoice>'
        cfg = {'schemaType':'XSD', 'schemaText':SIMPLE, 'validateInput':True, 'xmlString':text}
        value = json.loads(execute_format('json','render',cfg)['jsonString'])
        self.assertEqual(value, {'total':{'currency':'USD','tax':True,'$':12.5}, 'confirmed':True, 'label':{'lang':'en','$':''}})
        parsed = execute_format('json','parse',{'schemaType':'XSD','schemaText':SIMPLE,'jsonString':json.dumps(value)})
        self.assertEqual(parsed['value'], value)
        root = etree.fromstring(parsed['xmlString'].encode())
        self.assertEqual(root.find('total').text,'12.5')
        self.assertEqual(xsd_shape(SIMPLE)['properties']['total']['x-mina-textSchema']['type'],'number')

    def test_nil_primitives_keep_null_array_positions_under_empty_container_option(self):
        xml = '<rows xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"><number xsi:nil="true"/><number>2</number><object xsi:nil="true"/></rows>'
        for flag, expected_object in ((False,None),(True,{})):
            value = json.loads(execute_format('json','render',{'schemaType':'XSD','schemaText':NIL,'xmlString':xml,'useEmptyValuesForNull':flag})['jsonString'])
            self.assertEqual(value,{'number':[None,2],'object':expected_object})

    def test_clark_names_are_ordered_by_schema_and_qualified_attributes_are_retained(self):
        source = {'{urn:order}description':'café ☕ 漢字','{urn:order}id':7,'@{urn:order}ref':'A'}
        result = execute_format('xml','render',{'schemaText':ORDER,'validateInput':True,'value':source})
        root = etree.fromstring(result['xmlString'].encode())
        self.assertEqual([etree.QName(child).localname for child in root],['id','description'])
        self.assertEqual(root.get('{urn:order}ref'),'A')

    def test_binary_xml_uses_character_references_for_unencodable_text_and_attributes(self):
        result = execute_format('xml','render',{'rootElement':'root','value':{'@label':'漢字','text':'café ☕'},'outputStyle':'Binary','byteEncoding':'ascii'})
        raw = base64.b64decode(result['xmlBytes'])
        self.assertEqual(result['byteCount'],len(raw))
        self.assertIn(b'&#',raw)
        root = etree.fromstring(raw)
        self.assertEqual(root.get('label'),'漢字')
        self.assertEqual(root.find('text').text,'café ☕')

    def test_invalid_styles_and_malformed_documents_fault_explicitly(self):
        cases = [('xml','parse',{'inputStyle':'unknown','xmlString':'<root/>'}),
                 ('xml','render',{'outputStyle':'unknown','value':{}}),
                 ('xml','parse',{'xmlString':'<root><broken></root>'}),
                 ('json','parse',{'jsonString':'{"value":1e999}'}),
                 ('json','parse',{'jsonString':'{"value":1,"value":2}','duplicateKeyPolicy':'Error'})]
        for kind, operation, config in cases:
            with self.subTest(kind=kind,operation=operation,config=config), self.assertRaises(MinaFault):
                execute_format(kind,operation,config)

    def test_cdata_references_are_outside_cdata_and_keep_literal_ampersands(self):
        value = '< & &#123; café ☕ 漢字 ]]>'
        for encoding in ('ascii','iso-8859-1','utf-16'):
            with self.subTest(encoding=encoding):
                result = execute_format('xml','render',{'rootElement':'root','value':{'text':value},'cdataElements':'root.text','outputStyle':'Binary','byteEncoding':encoding})
                raw = base64.b64decode(result['xmlBytes'])
                self.assertEqual(etree.fromstring(raw).find('text').text,value)
                self.assertIn('<![CDATA[',raw.decode(encoding))

    def test_explicit_render_tree_overrides_inherited_xml_and_options_are_not_payload(self):
        value = {'total':{'currency':'USD','tax':True,'$':12.5},'confirmed':True,'label':{'lang':'en','$':'old'}}
        parsed = execute_format('json','parse',{'schemaType':'XSD','schemaText':SIMPLE},json.dumps(value))
        mapped = {'invoice':{'total':{'@currency':'EUR','@tax':False,'#text':99},'confirmed':False,'label':{'@lang':'fr','#text':'new'}},'formatOptions':{'prettyPrint':True}}
        rendered = execute_format('json','render',{'schemaType':'XSD','schemaText':SIMPLE,'_mappedInput':mapped},parsed)
        self.assertEqual(json.loads(rendered['jsonString']),{'total':{'currency':'EUR','tax':False,'$':99},'confirmed':False,'label':{'lang':'fr','$':'new'}})
        for mode, payload, schema in [('Native JSON',{'id':3},{}),('XSD',parsed,{'schemaText':SIMPLE})]:
            result = execute_format('json','render',{'schemaType':mode,**schema,'_mappedInput':{'formatOptions':{'prettyPrint':True}},'formatOptions':{'prettyPrint':True}},payload)
            self.assertEqual(json.loads(result['jsonString']),{'id':3} if mode=='Native JSON' else value)


class XmlJsonFlowParityTests(unittest.TestCase):
    def check_modes(self, kind, configs, payload, audit):
        activities = [{'id':'start','name':'Start','type':'start'}]
        activities += [{'id':f'a{i}','name':f'Activity-{i}','type':kind,'config':cfg} for i,cfg in enumerate(configs)]
        activities += [{'id':'end','name':'End','type':'end'}]
        transitions = [{'id':f't{i}','source':a['id'],'target':b['id']} for i,(a,b) in enumerate(zip(activities,activities[1:]))]
        project = Project.model_validate({'id':'formats','name':'Formats','tasks':[{'id':'main','name':'Main','kind':'subtask','activities':activities,'transitions':transitions}]})
        runtime = WorkflowRuntime()
        run = asyncio.run(runtime.run(project.tasks[0],payload,project=project))
        self.assertEqual(run.status,'completed',run.logs)
        audit(run.output)
        debug = DebugManager(runtime)
        session = debug.start(project,'main',payload,{}, {}, [])
        result = asyncio.run(debug.action(session['sessionId'],'continue'))
        self.assertEqual(result['status'],'completed',result['logs'])
        self.assertEqual(result['output'],run.output)
        audit(result['output'])
        for compiler in (raw_python_files,engine_python_files):
            with self.subTest(archive=compiler.__name__), tempfile.TemporaryDirectory() as folder:
                for name,data in compiler(project.model_dump(),{'local':[]}).items():
                    path = Path(folder)/name
                    path.parent.mkdir(parents=True,exist_ok=True)
                    path.write_bytes(data)
                script = 'import asyncio,json;from application.main import run_task;print("RESULT="+json.dumps(asyncio.run(run_task("main",'+repr(payload)+',"local"))))'
                process = subprocess.run([sys.executable,'-c',script],cwd=folder,capture_output=True,text=True,timeout=45)
                self.assertEqual(process.returncode,0,process.stdout+process.stderr)
                output = json.loads(next(line[7:] for line in process.stdout.splitlines() if line.startswith('RESULT=')))
                self.assertEqual(output,run.output)
                audit(output)

    def test_simple_content_json_parse_render(self):
        value = {'total':{'currency':'USD','tax':True,'$':12.5},'confirmed':False,'label':{'lang':'en','$':''}}
        config = {'schemaType':'XSD','schemaText':SIMPLE}
        self.check_modes('json',[{'operation':'parse',**config},{'operation':'render',**config}],json.dumps(value),lambda out:self.assertEqual(json.loads(out['jsonString']),value))

    def test_xsd_json_nil_repeating_items(self):
        value = {'number':[None,2],'object':None}
        config = {'schemaType':'XSD','schemaText':NIL}
        self.check_modes('json',[{'operation':'parse',**config},{'operation':'render',**config,'useEmptyValuesForNull':True}],json.dumps(value),lambda out:self.assertEqual(json.loads(out['jsonString']),{'number':[None,2],'object':{}}))

    def test_dynamic_render_tree_mappings_override_predecessor_serialization(self):
        value = {'total':{'currency':'USD','tax':True,'$':12.5},'confirmed':True,'label':{'lang':'en','$':'original'}}
        config = {'schemaType':'XSD','schemaText':SIMPLE}
        mappings = {'invoice.total.@currency':'"EUR"','invoice.total.@tax':'false','invoice.total.#text':'${last.invoice.total.$}',
                    'invoice.confirmed':'false','invoice.label.@lang':'"fr"','invoice.label.#text':'"mapped"','formatOptions.prettyPrint':'true'}
        expected = {'total':{'currency':'EUR','tax':False,'$':12.5},'confirmed':False,'label':{'lang':'fr','$':'mapped'}}
        self.check_modes('json',[{'operation':'parse',**config},{'operation':'render',**config,'inputMappings':mappings}],json.dumps(value),lambda out:self.assertEqual(json.loads(out['jsonString']),expected))

    def test_formatting_only_mapping_preserves_native_payload(self):
        payload = {'id':7,'values':[None,2]}
        self.check_modes('json',[{'operation':'render','schemaType':'Native JSON','inputMappings':{'formatOptions.prettyPrint':'true'}}],payload,lambda out:self.assertEqual(json.loads(out['jsonString']),payload))

    def test_xml_parse_to_ascii_binary_round_trip(self):
        text = '<o:order xmlns:o="urn:order" o:ref="A"><o:id>7</o:id><o:description>café ☕ 漢字</o:description></o:order>'
        def audit(out):
            raw = base64.b64decode(out['xmlBytes'])
            self.assertEqual(out['byteCount'],len(raw))
            root = etree.fromstring(raw)
            self.assertEqual(root.find('{urn:order}description').text,'café ☕ 漢字')
            self.assertEqual(root.get('{urn:order}ref'),'A')
        self.check_modes('xml',[{'operation':'parse','schemaText':ORDER,'validateOutput':True},{'operation':'render','schemaText':ORDER,'validateInput':True,'outputStyle':'Binary','inputMappings':{'byteEncoding':'"ascii"'}}],text,audit)

    def test_generic_badgerfish_namespaces_quotes_and_null_arrays(self):
        value = {'p:root':{'@xmlns':{'p':'urn:root'},'@id':'A','p:text':{'$':'He said "it\'s <fine>"'},'p:item':[{'$':'one'},{'$':'two'}]}}
        config = {'schemaType':'Generic','badgerfish':True,'jsonStyle':'JSON with Root'}
        self.check_modes('json',[{'operation':'parse',**config},{'operation':'render',**config}],json.dumps(value),lambda out:self.assertEqual(json.loads(out['jsonString']),value))

    def test_imported_render_wrapper_uses_mapped_encoding_and_qualified_cdata(self):
        text = ('<r:record xmlns:r="urn:record" xmlns:o="urn:other">'
                '<r:notes>café &lt;</r:notes><o:notes>open &lt;</o:notes></r:record>')
        wrapper = ('<p:xmlInput xmlns:p="http://example.test/namespaces/tnt/plugins/xmlpallete">'
                   f'<byteEncoding>US-ASCII</byteEncoding>{text}</p:xmlInput>')

        def audit(output):
            raw = base64.b64decode(output['xmlBytes'], validate=True)
            self.assertTrue(raw.isascii())
            self.assertIn(b'encoding="US-ASCII"', raw)
            self.assertIn(b']]>&#233;<![CDATA[', raw)
            self.assertIn(b'<o:notes>open &lt;</o:notes>', raw)
            root = etree.fromstring(raw)
            self.assertEqual(root.tag, '{urn:record}record')
            self.assertEqual(root.findtext('{urn:record}notes'), 'café <')

        config = {'operation': 'render', 'outputStyle': 'Binary', 'encoding': 'UTF-16',
                  'cdataElements': ['{urn:record}notes'], 'inputMappings': {'bwRenderInput': '${last}'}}
        self.check_modes('xml', [config], wrapper, audit)
