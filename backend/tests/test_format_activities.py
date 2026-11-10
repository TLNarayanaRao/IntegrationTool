import asyncio,base64,io,json,subprocess,sys,tempfile,unittest,zipfile
from pathlib import Path
from xml.etree import ElementTree as ET
from app.runtime import WorkflowRuntime,MinaFault
from app.data_formats import execute_format
from app.debugger import DebugManager
from app.models import Project
from app.raw_python import raw_python_files,engine_python_files
from app.project_import import project_payload

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

    def test_xml_binary_encoding_namespace_and_cdata(self):
        raw = '<?xml version="1.0" encoding="UTF-8"?><order>café</order>'.encode('cp1252')
        parsed = self.run_format('xml','parse',{'inputStyle':'Dynamic','xmlBinary':{'bytes':base64.b64encode(raw).decode(),'forceEncoding':'cp1252','byteCount':len(raw)}})
        self.assertEqual(parsed['value'], 'café')
        text = self.run_format('xml','render',{'value':{'notes':'< & ]]>'},'rootElement':'{urn:items}order','formatUsingDefaultNamespacePrefix':True,'cdataElements':'order.notes','outputStyle':'Binary','byteEncoding':'utf-16'})
        decoded = base64.b64decode(text['xmlBytes']).decode('utf-16')
        self.assertIn('<order xmlns="urn:items">', decoded)
        self.assertIn('<notes xmlns=""><![CDATA[< & ', decoded)
        self.assertEqual(ET.fromstring(decoded).find('notes').text, '< & ]]>')
        with self.assertRaises(MinaFault) as fault:
            self.run_format('xml','parse',{'inputStyle':'Binary','xmlBinary':{'bytes':base64.b64encode(raw).decode(),'byteCount':1}})
        self.assertEqual(fault.exception.fault_type, 'MissingByteCountException')
        repeated = self.run_format('xml','parse',{'schemaText':ITEMS_XSD},'<items xmlns="urn:items"><item>1</item></items>')
        self.assertEqual(repeated['value']['{urn:items}item'], ['1'])

    def test_xsd_json_root_styles_repetition_and_validation(self):
        cfg = {'schemaType':'XSD','schemaText':ITEMS_XSD,'jsonStyle':'Anonymous Array'}
        parsed = self.run_format('json','parse',cfg,'[7]')
        self.assertEqual(parsed['items'], {'item':[7]})
        self.assertEqual(json.loads(self.run_format('json','render',cfg,parsed)['jsonString']), [7])
        wrapped = {**cfg,'jsonStyle':'JSON with Root'}
        source = '{"items":{"item":[2],"future":true}}'
        with self.assertRaises(MinaFault): self.run_format('json','parse',wrapped,source)
        parsed = self.run_format('json','parse',{**wrapped,'ignoreAdditionalJsonFields':True},source)
        self.assertNotIn('future', parsed['xmlString'])
        self.assertEqual(json.loads(self.run_format('json','render',wrapped,parsed)['jsonString']), {'items':{'item':[2]}})

    def test_generic_json_preserves_badgerfish_namespaces_and_empty_arrays(self):
        cfg = {'schemaType':'Generic','jsonStyle':'JSON with Root','badgerfish':True}
        source = {'p:order':{'@xmlns':{'p':'urn:orders'},'@id':'A','p:quantity':{'$':'2'}}}
        parsed = self.run_format('json','parse',cfg,json.dumps(source))
        self.assertEqual(ET.fromstring(parsed['xmlString']).tag, '{urn:orders}order')
        self.assertEqual(json.loads(self.run_format('json','render',cfg,parsed)['jsonString']), source)
        generic = {'schemaType':'Generic','inferPrimitiveTypes':True}
        data = {'single':[3],'empty':[],'object':{},'nil':None,'yes':True}
        self.assertEqual(json.loads(self.run_format('json','render',generic,self.run_format('json','parse',generic,json.dumps(data)))['jsonString']), data)
        parsed = self.run_format('json','parse',{**generic,'useNullForEmptyValues':True},'{"obj":{},"array":[],"scalar":""}')
        self.assertEqual(json.loads(self.run_format('json','render',generic,parsed)['jsonString']), {'obj':None,'array':None,'scalar':''})

    def test_parse_data_batches_reject_records_and_reset_between_runs(self):
        cfg = {'fieldTypes':'integer,string','noOfRecords':2,'skipHeaderCharacters':3,'continueOnError':True}
        text = '---id,name\n1,A\nbad,B\n3,C'
        cursors = {}
        first = execute_format('flat','parse',cfg,text,cursors,'parse')
        second = execute_format('flat','parse',cfg,text,cursors,'parse')
        self.assertEqual(first['records'], [{'id':1,'name':'A'}])
        self.assertEqual(first['ErrorRows']['error'][0]['raw'], 'bad,B')
        self.assertFalse(first['done'])
        self.assertEqual(second['Rows']['schema']['record'], [{'id':3,'name':'C'}])
        self.assertTrue(second['done'])
        self.assertEqual(execute_format('flat','parse',cfg,text,cursors,'parse')['records'], [])
        self.assertEqual(first, execute_format('flat','parse',cfg,text,{},'parse'))
        self.assertEqual(second, self.run_format('flat','parse',{**cfg,'manualStartRecord':True,'startRecord':2},text))
        self.assertEqual(self.run_format('flat','parse',{'blankLinePolicy':'Stop'},'id\n1\n\n2')['recordCount'], 1)

    def test_fixed_layout_supports_gaps_offsets_and_line_length(self):
        cfg = {'format':'fixed','fields':'id,code','fieldTypes':'integer,string','fieldOffsets':'0:2,4:6','lineLength':9,'lineSeparator':'CRLF','strictColumns':True}
        rendered = self.run_format('flat','render',{**cfg,'records':[{'id':3,'code':'AB'}]})
        self.assertEqual(rendered['Text'], ' 3  AB ')
        self.assertEqual(self.run_format('flat','parse',cfg,rendered['text'])['records'], [{'id':3,'code':'AB'}])


ITEMS_XSD='''<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema" targetNamespace="urn:items" elementFormDefault="qualified"><xs:element name="items"><xs:complexType><xs:sequence><xs:element name="item" type="xs:int" minOccurs="0" maxOccurs="unbounded"/></xs:sequence></xs:complexType></xs:element></xs:schema>'''
ROWS_XSD='''<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema" xmlns:r="urn:rows" targetNamespace="urn:rows" elementFormDefault="qualified"><xs:element name="records" type="r:Rows"/><xs:complexType name="Rows"><xs:sequence><xs:element name="row" type="r:Row" maxOccurs="unbounded"/></xs:sequence></xs:complexType><xs:complexType name="Row"><xs:sequence><xs:element name="id" type="xs:int"/><xs:element name="name" type="xs:string"/></xs:sequence></xs:complexType></xs:schema>'''
ROOT_XSD = '''<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema" xmlns:r="urn:records" targetNamespace="urn:records" elementFormDefault="qualified">
  <xs:include schemaLocation="details/Record.xsd"/>
  <xs:element name="records"><xs:complexType><xs:sequence><xs:element name="row" type="r:Row" maxOccurs="unbounded"/></xs:sequence></xs:complexType></xs:element>
</xs:schema>'''
DETAIL_XSD = '''<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema" xmlns:t="urn:types" elementFormDefault="qualified">
  <xs:import namespace="urn:types" schemaLocation="../../common/Types.xsd"/>
  <xs:complexType name="Row"><xs:sequence><xs:element name="id" type="t:Id"/><xs:element name="name" type="xs:string"/></xs:sequence></xs:complexType>
</xs:schema>'''
TYPES_XSD = '''<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema" targetNamespace="urn:types">
  <xs:simpleType name="Id"><xs:restriction base="xs:int"><xs:minInclusive value="1"/></xs:restriction></xs:simpleType>
</xs:schema>'''
BW_LAYOUT = '''<jndi:namedResource xmlns:jndi="http://xsd.tns.tibco.com/amf/models/sharedresource/jndi" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xmlns:df="http://xsd.tns.tibco.com/bw/models/sharedresource/dataformat">
  <jndi:configuration xsi:type="df:DataFormatResource" formatType="Delimiter separated" colSeparator="|" lineSeparator="LF" schemaFile="../Contracts/Root.xsd"/>
</jndi:namedResource>'''
BW_FORMAT_PROCESS = '''<b:process xmlns:b="http://docs.oasis-open.org/wsbpel/2.0/process/executable" xmlns:t="http://www.tibco.com/bpel/2007/extensions">
  <b:sequence>
    <b:extensionActivity><t:extActivity name="Read" type="bw.parse.ParseData"><t:ParseData dataFormatResource="Rows" inputType="String"/></t:extActivity></b:extensionActivity>
    <b:extensionActivity><t:extActivity name="Write" type="bw.parse.RenderData"><t:RenderData dataFormatResource="Rows"/></t:extActivity></b:extensionActivity>
  </b:sequence></b:process>'''


def bw_zip(files):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w') as archive:
        for name, content in files.items(): archive.writestr(name, content)
    return buffer.getvalue()


def bw_assets():
    return {'App/Contracts/Root.xsd': ROOT_XSD, 'App/Contracts/details/Record.xsd': DETAIL_XSD,
            'App/common/Types.xsd': TYPES_XSD, 'App/Resources/Rows.dataFormatResource': BW_LAYOUT}


def bw_substitution_assets():
    files = bw_assets()
    resource = 'App/Resources/Rows.dataFormatResource'
    files[resource] = files[resource].replace('schemaFile="../Contracts/Root.xsd"/>',
        'schemaFile="../Contracts/Root.xsd"><substitutionBindings template="colSeparator" propName="/Formats/Separator"/></jndi:configuration>')
    files['App/Processes/Data.bwp'] = BW_FORMAT_PROCESS
    return files


def bw_profile(name, value, kind='String'):
    return f'<repository><globalVariables><globalVariable><name>{name}</name><value>{value}</value><type>{kind}</type></globalVariable></globalVariables></repository>'


class FormatImportTests(unittest.TestCase):
    def test_bw_data_format_resolves_emf_expanded_schema_qname(self):
        files = bw_assets()
        key = 'App/Resources/Rows.dataFormatResource'
        files[key] = files[key].replace('schemaFile="../Contracts/Root.xsd"', 'schemaElementQName="{urn:records}records"')
        project = json.loads(project_payload(bw_zip(files),'Layouts.zip'))
        layout = json.loads(next(item['content'] for item in project['schemas'] if 'dataFormatResource' in item['name']))['dataFormat']
        self.assertEqual(layout['rootElement'],'records')
        self.assertEqual(next(item['source_path'] for item in project['schemas'] if item['id']==layout['schemaId']),'App/Contracts/Root.xsd')

    def test_reserved_xml_root_does_not_replace_the_round_trip_envelope(self):
        parsed = execute_format('xml','parse',{},'<root><item>1</item></root>')
        self.assertEqual(parsed['root'], 'root')
        self.assertIn('<root><item>1</item></root>', execute_format('xml','render',{},parsed)['xmlString'])

    def test_xsd_catalog_locationless_import_and_access_boundaries(self):
        cfg = {'schemaText': ROOT_XSD, '_formatSchemaPath':'App/Contracts/Root.xsd',
               '_formatSchemaAssets':[('App/Contracts/details/Record.xsd',DETAIL_XSD.replace(' schemaLocation="../../common/Types.xsd"','')),
                                      ('App/common/Types.xsd',TYPES_XSD)], 'validateOutput':True}
        xml = '<records xmlns="urn:records"><row><id>1</id><name>A</name></row></records>'
        self.assertEqual(execute_format('xml','parse',cfg,xml)['records']['row'][0]['id'],'1')
        with self.assertRaisesRegex(MinaFault, 'minInclusive'):
            execute_format('xml','parse',cfg,xml.replace('>1<','>0<'))
        for path in ('https://example.test/schema.xsd','file:///C:/Windows/schema.xsd','../../../outside.xsd','missing.xsd'):
            with self.subTest(path=path),self.assertRaises(MinaFault):
                execute_format('xml','parse',{**cfg,'schemaText':ROOT_XSD.replace('details/Record.xsd',path)},xml)
        with self.assertRaisesRegex(MinaFault,'missing or ambiguous'):
            execute_format('xml','parse',{**cfg,'_formatSchemaAssets':[*cfg['_formatSchemaAssets'],('App/common/Other.xsd',TYPES_XSD)]},xml)

    def test_fixed_bw_resource_preserves_explicit_offsets_and_embedded_schema(self):
        content = '''<DataFormat formatType="Fixed format" lineLength="8" lineSeparator="LF">
          <fieldOffset fieldName="id" startOffset="0" endOffset="2"/><fieldOffset fieldName="name" startOffset="4" endOffset="7"/>
          <xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema"><xs:element name="row"><xs:complexType><xs:sequence>
            <xs:element name="id" type="xs:int"/><xs:element name="name" type="xs:string"/>
          </xs:sequence></xs:complexType></xs:element></xs:schema>
        </DataFormat>'''
        converted = json.loads(project_payload(content.encode(),'Fixed.dataformat'))
        assets = converted['schemas']
        layout = json.loads(assets[-1]['content'])['dataFormat']
        self.assertEqual(layout['fieldOffsets'],'0:2,4:7')
        self.assertEqual(layout['schemaId'],assets[0]['id'])
        self.assertEqual(execute_format('flat','parse',{**layout,'schemaId':'','schemaText':assets[0]['content']},' 2  Ann\n')['records'],[{'id':2,'name':'Ann'}])

    def test_bw_project_links_native_data_activities(self):
        converted = json.loads(project_payload(bw_zip({**bw_assets(),'App/Processes/Data.bwp':BW_FORMAT_PROCESS}),'Formats.zip'))
        data = [activity for activity in converted['tasks'][0]['activities'] if activity['type']=='flat']
        self.assertEqual([activity['config']['operation'] for activity in data],['parse','render'])
        self.assertEqual(data[0]['config']['dataFormatId'],data[1]['config']['dataFormatId'])

    def test_property_binding_reports_missing_and_refuses_secret_or_unsupported_targets(self):
        files = bw_substitution_assets()
        resource = 'App/Resources/Rows.dataFormatResource'
        files[resource] = files[resource].replace(' colSeparator="|"', '')
        converted = json.loads(project_payload(bw_zip(files), 'Formats.zip'))
        self.assertIn('blank value',converted['description'])
        self.assertTrue(any(item['value'] == '' and item['key'].startswith('bw.dataFormat.') for item in converted['properties']['local']))
        with self.assertRaisesRegex(ValueError, 'non-secret string'):
            project_payload(bw_zip({**files,'App/META-INF/default.substvar':bw_profile('/Formats/Separator','secret-value','Password')}),'Formats.zip')
        with self.assertRaisesRegex(ValueError, 'unsupported Data Format module-property binding'):
            project_payload(bw_zip({**files,resource:files[resource].replace('template="colSeparator"','template="lineLength"')}),'Formats.zip')


class ArchiveFormatTests(unittest.TestCase):
    def assert_archives(self, project, payload, expected, case, environment='local', profiles=None):
        for compiler in (raw_python_files,engine_python_files):
            with self.subTest(case=case,compiler=compiler.__name__),tempfile.TemporaryDirectory() as folder:
                for name,data in compiler(project.model_dump(),profiles or {'local':[]}).items():
                    path=Path(folder)/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(data)
                script='import asyncio,json;from application.main import run_task;print("RESULT="+json.dumps(asyncio.run(run_task('+repr(project.tasks[0].id)+','+repr(payload)+','+repr(environment)+'))))'
                result=subprocess.run([sys.executable,'-c',script],cwd=folder,capture_output=True,text=True,timeout=30)
                self.assertEqual(result.returncode,0,result.stdout+result.stderr)
                actual=json.loads(next(line[7:] for line in result.stdout.splitlines() if line.startswith('RESULT=')))
                self.assertEqual(actual,expected)

    def test_bw613_json_model_imports_as_native_parse_and_render(self):
        process = '''<b:process xmlns:b="http://docs.oasis-open.org/wsbpel/2.0/process/executable" xmlns:t="http://www.tibco.com/bpel/2007/extensions" xmlns:m="http://tns.tibco.com/bw/model/core/bwext" xmlns:xsl="http://www.w3.org/1999/XSL/Transform" xmlns:p="urn:items">
        <b:sequence>
          <b:extensionActivity><t:activityExtension name="Parse" outputVariable="Parsed">
            <t:inputBindings><xsl:stylesheet version="2.0"><xsl:template match="/"><jsonString>{"items":{"item":[1,2]}}</jsonString></xsl:template></xsl:stylesheet></t:inputBindings>
            <t:config><m:BWActivity activityTypeID="bw.restjson.JsonParser"><activityConfig><properties name="config"><value schemaType="XSD" outputElementQName="p:items" jsonInputStyle="JsonWithRoot"/></properties></activityConfig></m:BWActivity></t:config>
          </t:activityExtension></b:extensionActivity>
          <b:extensionActivity><t:activityExtension name="Render">
            <t:inputBindings><xsl:stylesheet version="2.0"><xsl:param name="Parsed"/><xsl:template match="/"><xsl:copy-of select="$Parsed"/></xsl:template></xsl:stylesheet></t:inputBindings>
            <t:config><m:BWActivity activityTypeID="bw.restjson.JsonRender"><activityConfig><properties name="config"><value schemaType="XSD" outputElementQName="p:items" jsonOutputStyle="AnonymousArray" validateInput="true"/></properties></activityConfig></m:BWActivity></t:config>
          </t:activityExtension></b:extensionActivity>
        </b:sequence></b:process>'''
        project = Project.model_validate_json(project_payload(bw_zip({'App/Processes/Json.bwp':process,'App/Schemas/Items.xsd':ITEMS_XSD}),'Json.zip'))
        task = project.tasks[0]
        self.assertEqual([activity.config['operation'] for activity in task.activities if activity.type == 'json'],['parse','render'])
        runtime = WorkflowRuntime()
        run = asyncio.run(runtime.run(task,{},project=project))
        self.assertEqual(run.status,'completed',run.logs)
        self.assertEqual(run.output['jsonString'],'[1,2]')
        debug = DebugManager(runtime)
        session = debug.start(project,task.id,{}, {}, {}, [])
        result = asyncio.run(debug.action(session['sessionId'],'continue'))
        self.assertEqual(result['output'],run.output)
        self.assert_archives(project,{},run.output,'BW 6.13 JSON activity model')

    def test_bw_data_format_substitutions_run_debug_and_archive_profiles(self):
        files = bw_substitution_assets()
        files['App/META-INF/default.substvar'] = bw_profile('/Formats/Separator', ';')
        files['App.application/META-INF/qa.substvar'] = bw_profile('//App///Formats/Separator', '|')
        files['Other/META-INF/default.substvar'] = bw_profile('/Formats/Separator', ':')
        project = Project.model_validate_json(project_payload(bw_zip(files), 'Formats.zip'))
        task = project.tasks[0]
        parse, render = [activity for activity in task.activities if activity.type == 'flat']
        target = 'formatOptions.delimiter'
        binding = parse.config['inputMappings'][target]
        self.assertRegex(binding, r'^\$\{properties\.bw\.dataFormat\.')
        self.assertEqual(render.config['inputMappings'][target], binding)
        asset = next(asset for asset in project.schemas if asset.id == parse.config['dataFormatId'])
        self.assertEqual(json.loads(asset.content)['inputMappings'][target],binding)
        property_key = binding.removeprefix('${properties.').removesuffix('}')
        profiles = {name:[item.model_dump() for item in project.properties[name]] for name in ('local','qa')}
        for environment, separator in [('local',';'),('qa','|')]:
            properties = {item['key']:item['value'] for item in profiles[environment]}
            self.assertEqual(properties[property_key],separator)
            payload = '7'+separator+'Ann\n'
            runtime = WorkflowRuntime()
            run = asyncio.run(runtime.run(task,payload,properties=properties,project=project))
            self.assertEqual(run.status,'completed',run.logs)
            self.assertEqual(run.output['text'],payload)
            self.assertEqual(run.activity_outputs[parse.id]['output']['records'],[{'id':7,'name':'Ann'}])
            debug = DebugManager(runtime)
            session = debug.start(project,task.id,payload,{},properties,[],environment=environment)
            result = asyncio.run(debug.action(session['sessionId'],'continue'))
            self.assertEqual(result['status'],'completed',result['logs'])
            self.assertEqual(result['output'],run.output)
            self.assert_archives(project,payload,run.output,environment,environment,profiles)

    def test_parse_data_repeat_until_done_in_run_debug_and_archives(self):
        project = Project.model_validate({'id':'batches','name':'Batches','tasks':[{
            'id':'main','name':'Batch','kind':'subtask',
            'activities':[
                {'id':'start','name':'Start','type':'start'},
                {'id':'parse','name':'Parse','type':'flat','config':{'operation':'parse','fieldTypes':'integer','noOfRecords':1,'inputMappings':{'text':'${input}'}}},
                {'id':'end','name':'End','type':'end'}],
            'transitions':[{'id':'a','source':'start','target':'parse'},{'id':'b','source':'parse','target':'end'}],
            'groups':[{'id':'batch','type':'repeat','name':'Batch','member_activity_ids':['parse'],'config':{'condition':'${last.done} == true','maxIterations':5}}]
        }]})
        payload = 'id\n1\n2\n3'
        runtime = WorkflowRuntime()
        run = asyncio.run(runtime.run(project.tasks[0],payload,project=project))
        self.assertEqual(run.status, 'completed', run.logs)
        self.assertEqual(run.output['records'], [{'id':3}])
        self.assertTrue(run.output['done'])
        self.assertEqual(run.output['nextRecord'],3)
        debug = DebugManager(runtime)
        session = debug.start(project,'main',payload,{}, {}, [])
        result = asyncio.run(debug.action(session['sessionId'],'resume'))
        self.assertEqual(result['status'], 'completed', result['logs'])
        self.assertEqual(result['output'], run.output)
        self.assert_archives(project,payload,run.output,'repeat until done')

    def test_linked_schemas_and_mapped_options_on_all_six_activities(self):
        imported = json.loads(project_payload(bw_zip(bw_assets()),'Formats.zip'))
        root = next(asset['id'] for asset in imported['schemas'] if asset.get('source_path','').endswith('/Root.xsd'))
        data = next(asset['id'] for asset in imported['schemas'] if '.dataFormatResource.' in asset['name'])
        cases = [
            ('xml', {'document':'<records xmlns="urn:records"><row><id>7</id><name>A &amp; B</name></row></records>', 'cdata':'records.row.name','validate':True},
             {'schemaId':root,'inputMappings':{'xmlString':'${input.document}','formatOptions.validateOutput':'${input.validate}'}},
             {'schemaId':root,'validateInput':True,'inputMappings':{'formatOptions.cdataElements':'${input.cdata}'}}, 'xmlString', '<![CDATA[A & B]]>'),
            ('json', {'document':'{"row":[{"id":7,"name":"Ann"}]}','style':'JSON with Root'},
             {'schemaId':root,'schemaType':'XSD','inputMappings':{'jsonString':'${input.document}'}},
             {'schemaId':root,'schemaType':'XSD','inputMappings':{'formatOptions.jsonStyle':'${input.style}'}}, 'jsonString','{"records":{"row":[{"id":7,"name":"Ann"}]}}'),
            ('flat', {'document':'7;Ann\n','separator':';','finalNewline':False},
             {'dataFormatId':data,'inputMappings':{'text':'${input.document}','formatOptions.delimiter':'${input.separator}'}},
             {'dataFormatId':data,'inputMappings':{'formatOptions.includeFinalLineSeparator':'${input.finalNewline}'}}, 'text','7|Ann'),
        ]
        for kind, payload, parse, render, output, expected_text in cases:
            with self.subTest(kind=kind):
                activities = [
                    {'id':'Start','name':'Start','type':'start'},
                    {'id':'Parse','name':'Parse','type':kind,'config':{'operation':'parse',**parse}},
                    {'id':'Render','name':'Render','type':kind,'config':{'operation':'render',**render}},
                    {'id':'End','name':'End','type':'end'},
                ]
                task = {'id':'main','name':'Formats','kind':'subtask','activities':activities,
                        'transitions':[{'id':str(i),'source':a['id'],'target':b['id']} for i,(a,b) in enumerate(zip(activities,activities[1:]))]}
                project = Project.model_validate({**imported,'tasks':[task],'active_task_id':'main'})
                runtime = WorkflowRuntime()
                run = asyncio.run(runtime.run(project.tasks[0],payload,project=project))
                self.assertEqual(run.status,'completed',run.logs)
                if kind == 'xml': self.assertIn(expected_text,run.output[output])
                else: self.assertEqual(run.output[output],expected_text)
                debug = DebugManager(runtime)
                session = debug.start(project,'main',payload,{}, {}, [])
                result = asyncio.run(debug.action(session['sessionId'],'resume'))
                self.assertEqual(result['status'],'completed',result['logs'])
                self.assertEqual(result['output'],run.output)
                self.assert_archives(project,payload,run.output,kind + ' linked XSD')

    def test_all_six_activities_match_studio_in_both_python_archives(self):
        cases=[('xml','<order id="A"><quantity>2</quantity></order>',{'schemaText':XSD,'validateOutput':True},{'schemaText':XSD,'validateInput':True}),('json','{"id":2,"items":[null,3]}',{}, {'omitNulls':True}),('flat','id,text\n1,"hello\nworld"',{'fields':'id,text','fieldTypes':'integer,string'},{'fields':'id,text','fieldTypes':'integer,string'})]
        cases.extend([
            ('xml','<order id="A"><quantity>2</quantity></order>',{'schemaId':'order','validateOutput':True},{'schemaId':'order','validateInput':True,'outputStyle':'Binary','byteEncoding':'UTF-16'}),
            ('json','[7]',{'schemaType':'XSD','schemaId':'items','jsonStyle':'Anonymous Array'},{'schemaType':'XSD','schemaId':'items','jsonStyle':'Anonymous Array'}),
            ('json','{"count":2,"array":[4]}',{'schemaType':'Generic'},{'schemaType':'Generic','inferPrimitiveTypes':True}),
            ('flat','--id,name\n1,A\nbad,B\n3,C',{'dataFormatId':'format','skipHeaderCharacters':2,'noOfRecords':2,'continueOnError':True},{'dataFormatId':'format'}),
        ])
        schemas = [{'id':'items','name':'items.xsd','content':ITEMS_XSD},{'id':'order','name':'order.xsd','content':XSD},
                   {'id':'rows','name':'rows.xsd','content':ROWS_XSD},
                   {'id':'format','name':'rows.json','content':json.dumps({'dataFormat':{'schemaId':'rows','header':True,'includeFinalLineSeparator':False}})}]
        for kind,payload,parse_cfg,render_cfg in cases:
            tasks=[{'id':'main','name':'Main','kind':'starter','activities':[{'id':'Start','name':'Start','type':'start','config':{}},{'id':'Parse','name':'Parse','type':kind,'config':{'operation':'parse',**parse_cfg}},{'id':'Render','name':'Render','type':kind,'config':{'operation':'render',**render_cfg}},{'id':'End','name':'End','type':'end','config':{}}],'transitions':[{'id':'a','source':'Start','target':'Parse'},{'id':'b','source':'Parse','target':'Render'},{'id':'c','source':'Render','target':'End'}]}]
            project=Project.model_validate({'id':'formats','name':'Formats','tasks':tasks,'schemas':schemas})
            runtime = WorkflowRuntime()
            run = asyncio.run(runtime.run(project.tasks[0],payload,project=project))
            self.assertEqual(run.status, 'completed', run.logs)
            expected = run.output
            if parse_cfg.get('dataFormatId'):
                parsed = run.activity_outputs['Parse']['output']
                self.assertEqual(parsed['Rows']['schema']['row'], [{'id':1,'name':'A'}])
                self.assertEqual(ET.fromstring(parsed['xml']).tag,'{urn:rows}records')
            debug = DebugManager(runtime)
            session = debug.start(project,'main',payload,{}, {}, [])
            result = asyncio.run(debug.action(session['sessionId'],'resume'))
            self.assertEqual(result['status'], 'completed', result['logs'])
            self.assertEqual(result['output'], expected)
            self.assert_archives(project,payload,expected,kind)
