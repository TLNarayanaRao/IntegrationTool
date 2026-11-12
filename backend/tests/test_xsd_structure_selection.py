import io
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from lxml import etree
from fastapi.testclient import TestClient
from app.main import app
from app.data_formats import DataFormats,execute_format,xsd_shape
from app.mapper import flatten_schema
from app.xsd_catalog import SELECTION,inherit_schema_selection,schema_selection
from app.xsd_openapi import describe_xsd

ROOT=Path(__file__).resolve().parents[2]
NS='http://www.petsmart.com/CnDM/item/Enterprise'


class XsdStructureSelectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source=(ROOT/'docs/assets/ItemEnterpriseLakebase.xsd').read_text(encoding='utf-8-sig')
        cls.frontend=False
        if sys.platform=='win32' and shutil.which('node') and (ROOT/'frontend/node_modules/electron/dist/electron.exe').is_file():
            run=subprocess.run(['node',str(ROOT/'frontend/tests/fixtures/xsd-selection-contracts.mjs')],
                cwd=ROOT,text=True,capture_output=True,timeout=60)
            if run.returncode:raise AssertionError(run.stderr)
            cls.cases=json.loads(run.stdout);cls.frontend=True
        else:
            cls.cases=[]
            document=etree.fromstring(cls.source.encode())
            for node in document:
                if etree.QName(node).localname not in ('element','complexType'):continue
                kind='element' if etree.QName(node).localname=='element' else 'type'
                snapshot=etree.fromstring(cls.source.encode());snapshot.set(SELECTION+'structure',kind+'|{'+NS+'}'+node.get('name'))
                contract=inherit_schema_selection(cls.source,etree.tostring(snapshot,encoding='unicode'))
                cls.cases.append({'name':node.get('name'),'text':contract,'root':schema_selection(contract)[1].rsplit('}',1)[-1]})

    def test_frontend_sample_lists_each_global_element_and_named_complex_type(self):
        if not self.frontend:self.skipTest('Real Chromium DOM verification requires Windows Electron build dependencies')
        self.assertEqual(len(self.cases),5)
        for case in self.cases:
            self.assertTrue(all(path==case['root'] or path.startswith(case['root']+'.') for path in case['paths']))
        self.assertEqual({case['name'] for case in self.cases},{'item','itemEnterpriseViewModel','itemResponseType','itemEnterpriseViewModelType','hierarchyResponseType'})

    def test_selected_entries_preserve_refs_and_work_in_xml_json_and_openapi(self):
        for case in self.cases:
            if case['name']=='hierarchyResponseType':continue
            with self.subTest(structure=case['name']):
                contract=case['text'];shape,example=describe_xsd(contract)
                self.assertNotIn('oneOf',shape)
                self.assertEqual(shape['xml']['name'],case['root'])
                DataFormats.validate_xml_document(example,contract)
                self.assertEqual(DataFormats.schema_root_name(contract),case['root'])
                self.assertTrue(all(field['path'].startswith(case['root']+'.') or field['path']==case['root'] for field in flatten_schema(contract)))
                parsed=execute_format('xml','parse',{'schemaText':contract,'validateOutput':True},example)
                rendered=execute_format('xml','render',{'schemaText':contract,'validateInput':True,'xmlString':example},parsed)
                self.assertEqual(etree.fromstring(rendered['xmlString'].encode()).tag,'{'+NS+'}'+case['root'])
                cfg={'schemaType':'XSD','schemaText':contract,'jsonStyle':'JSON with Root'}
                json_value=execute_format('json','render',cfg,{'xmlString':example})['jsonString']
                self.assertEqual(list(json.loads(json_value)),[case['root']])
                back=execute_format('json','parse',cfg,json_value)
                self.assertEqual(etree.fromstring(back['xmlString'].encode()).tag,'{'+NS+'}'+case['root'])
                reloaded=inherit_schema_selection(self.source,contract)
                self.assertEqual(schema_selection(reloaded),schema_selection(contract))

    def test_wrong_root_and_incomplete_selected_type_fail_without_mutating_original(self):
        chosen=next(case for case in self.cases if case['name']=='itemEnterpriseViewModel')
        other=next(case for case in self.cases if case['name']=='item')
        _,example=describe_xsd(other['text'])
        with self.assertRaisesRegex(Exception,'selected XSD root'):DataFormats.validate_xml_document(example,chosen['text'])
        incomplete=next(case for case in self.cases if case['name']=='hierarchyResponseType')
        with self.assertRaisesRegex(Exception,'hierarchyTrustedViewModelType'):
            DataFormats.validate_xml_document('<hierarchyResponseType xmlns="'+NS+'"/>',incomplete['text'])
        self.assertEqual((ROOT/'docs/assets/ItemEnterpriseLakebase.xsd').read_text(encoding='utf-8-sig'),self.source)

    def test_asset_reload_keeps_selection_and_uses_updated_declarations(self):
        from types import SimpleNamespace
        from app.runtime import WorkflowRuntime
        from app.models import Activity
        contract=next(case['text'] for case in self.cases if case['name']=='item')
        updated=self.source.replace('name="ITEM_DESC"','name="ITEM_DESCRIPTION"')
        asset=SimpleNamespace(id='items',name='Items.xsd',source_path='',content=updated)
        project=SimpleNamespace(schemas=[asset])
        config={'schemaId':'items','schemaText':contract}
        loaded=DataFormats().configured_schema(config,{'project':project})
        fields=flatten_schema(loaded)
        self.assertIn('item.ITEM_DESCRIPTION',{field['path'] for field in fields})
        self.assertNotIn('item.ITEM_DESC',{field['path'] for field in fields})
        context={'input':{},'last':{},'properties':{},'vars':{},'resources':{},'context':{},'project':project}
        mapper=WorkflowRuntime().resolve_activity_config(Activity(id='m',name='Mapper',type='mapper',
            config={'targetSchemaId':'items','targetSchemaText':contract}),context)
        self.assertEqual(schema_selection(mapper['targetSchemaText']),schema_selection(contract))
        self.assertIn('item.ITEM_DESCRIPTION',{field['path'] for field in flatten_schema(mapper['targetSchemaText'])})

    def test_named_type_without_a_target_namespace_has_a_valid_wrapper(self):
        source='<schema xmlns="http://www.w3.org/2001/XMLSchema" xmlns:xs="http://www.w3.org/2001/XMLSchema"><complexType name="Record"><sequence><element name="value" type="xs:string"/></sequence></complexType></schema>'
        snapshot=etree.fromstring(source.encode());snapshot.set(SELECTION+'structure','type|{}Record')
        contract=inherit_schema_selection(source,etree.tostring(snapshot,encoding='unicode'))
        DataFormats.validate_xml_document('<Record><value>ok</value></Record>',contract)
        self.assertEqual(DataFormats.schema_root_name(contract),'Record')

    def test_selected_root_keeps_included_types_and_drives_data_record_fields(self):
        source='''<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema" xmlns:r="urn:records" targetNamespace="urn:records" elementFormDefault="qualified">
          <xs:include schemaLocation="Types.xsd"/><xs:element name="orders" type="r:Rows"/><xs:element name="unrelated" type="xs:string"/>
        </xs:schema>'''
        types='''<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema" xmlns:r="urn:records" targetNamespace="urn:records" elementFormDefault="qualified">
          <xs:complexType name="Rows"><xs:sequence><xs:element name="row" minOccurs="0" maxOccurs="unbounded"><xs:complexType><xs:sequence>
          <xs:element name="id" type="xs:int"/><xs:element name="name" type="xs:string"/></xs:sequence></xs:complexType></xs:element></xs:sequence></xs:complexType>
          <xs:complexType name="Unused"><xs:sequence><xs:element name="unknown" type="DoesNotExist"/></xs:sequence></xs:complexType>
          <xs:complexType name="DerivedRows"><xs:complexContent><xs:extension base="r:Rows"><xs:sequence><xs:element name="extra" type="xs:int" minOccurs="0"/></xs:sequence></xs:extension></xs:complexContent></xs:complexType>
        </xs:schema>'''
        snapshot=etree.fromstring(source.encode());snapshot.set(SELECTION+'structure','element|{urn:records}orders')
        contract=inherit_schema_selection(source,etree.tostring(snapshot,encoding='unicode'))
        bundle=('Main.xsd',(('Types.xsd',types),))
        DataFormats.validate_xml_document('<orders xmlns="urn:records"><row><id>7</id><name>A</name></row></orders>',contract,bundle)
        DataFormats.validate_xml_document('<orders xmlns="urn:records" xmlns:r="urn:records" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xsi:type="r:DerivedRows"><extra>1</extra></orders>',contract,bundle)
        self.assertEqual(xsd_shape(contract,bundle=bundle)['xml']['name'],'orders')
        self.assertEqual(DataFormats.schema_leaf_fields(contract,bundle),(['id','name'],['integer','string']))
        cfg={'schemaText':contract,'_formatSchemaPath':'Main.xsd','_formatSchemaAssets':list(bundle[1])}
        parsed=execute_format('flat','parse',cfg,'id,name\n7,A')
        self.assertEqual(parsed['records'],[{'id':7,'name':'A'}])
        self.assertEqual(etree.fromstring(parsed['xmlString'].encode()).tag,'{urn:records}orders')
        rendered=execute_format('flat','render',cfg,parsed)
        self.assertIn('7,A',rendered['Text'])

    def test_mapper_task_boundaries_run_debug_and_both_downloaded_archives(self):
        contract=next(case['text'] for case in self.cases if case['name']=='itemResponseType')
        root=schema_selection(contract)[1].rsplit('}',1)[-1]
        value={'itemEnterpriseViewModel':{}}
        boundary={'interfaceSchemaId':'items','interfaceSchemaText':contract}
        def node(id,type,config=None):return {'id':id,'name':id,'type':type,'config':config or {}}
        def edges(ids):return [{'id':str(i),'source':a,'target':b} for i,(a,b) in enumerate(zip(ids,ids[1:]))]
        payload={'id':'xsd-selection-e2e','name':'XSD-Selection-E2E','resources':[],
            'schemas':[{'id':'items','name':'ItemEnterpriseLakebase.xsd','content':self.source}],
            'properties':{'local':[]},'active_task_id':'main','tasks':[
                {'id':'main','name':'Main','kind':'starter','activities':[
                    node('s','start'),node('m','mapper',{'targetSchemaId':'items','targetSchemaText':contract,
                        'mappings':[{'target':root,'constant':value}]}),
                    node('c','call_task',{'taskId':'child','inputMappings':{root:'${last.'+root+'}'}}),
                    node('r','xml',{'operation':'render','schemaId':'items','schemaText':contract,'validateInput':True}),
                    node('p','xml',{'operation':'parse','schemaId':'items','schemaText':contract,'validateOutput':True,'inputMappings':{'xmlString':'${last.xmlString}'}}),
                    node('e','end',{**boundary,'inputMappings':{root:'${activities.c.output.'+root+'}'}})],'transitions':edges(['s','m','c','r','p','e'])},
                {'id':'child','name':'Child','kind':'subtask','activities':[node('cs','start',boundary),
                    node('ce','end',{**boundary,'inputMappings':{root:'${input.'+root+'}'}})],'transitions':edges(['cs','ce'])}]}
        client=TestClient(app);session=None;expected={root:value}
        try:
            saved=client.post('/api/projects',json=payload);self.assertEqual(saved.status_code,200,saved.text)
            response=client.post('/api/projects/xsd-selection-e2e/run',json={'task_id':'main','input':{}})
            self.assertEqual(response.status_code,200,response.text);run=response.json()
            self.assertEqual(run['status'],'completed',run);self.assertEqual(run['output'],expected)
            debug=client.post('/api/projects/xsd-selection-e2e/debug',json={'task_id':'main','input':{},'test_mode':True})
            self.assertEqual(debug.status_code,200,debug.text);session=debug.json()['sessionId']
            state=client.post(f'/api/debug/{session}/action',json={'action':'continue'}).json()
            self.assertEqual(state['status'],'completed',state);self.assertEqual(state['activityOutputs']['e']['output'],expected)
            for mode in ('python-direct','python-engine'):
                with self.subTest(mode=mode),tempfile.TemporaryDirectory() as folder:
                    export=client.get(f'/api/projects/xsd-selection-e2e/package?archive={mode}&environment=local')
                    self.assertEqual(export.status_code,200,export.text if export.status_code!=200 else '')
                    with zipfile.ZipFile(io.BytesIO(export.content)) as archive:archive.extractall(folder)
                    result=subprocess.run([sys.executable,'-m','application.main','--task','main','--input','{}'],cwd=folder,
                        text=True,capture_output=True,timeout=45)
                    self.assertEqual(result.returncode,0,result.stdout+result.stderr)
                    self.assertEqual(json.loads(result.stdout),expected)
        finally:
            if session:client.post(f'/api/debug/{session}/action',json={'action':'stop'})
            client.delete('/api/projects/xsd-selection-e2e')

    def test_selected_source_view_links_validation_in_both_archives(self):
        from app.raw_python import raw_python_files,engine_python_files
        contract=next(case['text'] for case in self.cases if case['name']=='itemEnterpriseViewModel')
        xml='<itemEnterpriseViewModel xmlns="'+NS+'"><itemEnterpriseViewModel/></itemEnterpriseViewModel>'
        project={'id':'selected-view','name':'Selected-View','resources':[],'tasks':[{
            'id':'main','name':'Main','kind':'starter','activities':[
                {'id':'s','name':'Start','type':'start','config':{}},
                {'id':'m','name':'Mapper','type':'mapper','config':{
                    'sourceCoercions':{'selected':{'path':'input.document','cardinality':'1','schema':contract}},
                    'mappings':[{'target':'value','source':'${coerced.selected}'}]}},
                {'id':'e','name':'End','type':'end','config':{}}],
            'transitions':[{'id':'sm','source':'s','target':'m'},{'id':'me','source':'m','target':'e'}]}]}
        for compiler in (raw_python_files,engine_python_files):
            with self.subTest(compiler=compiler.__name__),tempfile.TemporaryDirectory() as folder:
                for name,data in compiler(project,{'local':[]}).items():
                    file=Path(folder)/name;file.parent.mkdir(parents=True,exist_ok=True);file.write_bytes(data)
                result=subprocess.run([sys.executable,'-m','application.main','--task','main','--input',json.dumps({'document':xml})],
                    cwd=folder,text=True,capture_output=True,timeout=45)
                self.assertEqual(result.returncode,0,result.stdout+result.stderr)
                self.assertEqual(json.loads(result.stdout),{'value':{'itemEnterpriseViewModel':''}})
