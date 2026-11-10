"""Run generated archives outside Studio to verify Mapper/Input execution parity."""
import asyncio
import json
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

from app.raw_python import engine_python_files, raw_python_files


class PythonMapperParityTests(unittest.TestCase):
    def project(self, mappings=None, input_mappings=None):
        activities = [dict(id='Start', name='Start', type='start', config={})]
        if mappings is not None:
            activities.append(dict(id='Mapper', name='Mapper', type='mapper', config={'mappings': mappings}))
        activities.append(dict(id='End', name='End', type='end', config={'inputMappings': input_mappings or {}}))
        return dict(id='parity', name='Parity', resources=[], tasks=[dict(
            id='main', name='Main', kind='starter', groups=[], activities=activities,
            transitions=[dict(id=f't{i}', source=a['id'], target=b['id'])
                         for i, (a, b) in enumerate(zip(activities, activities[1:]))])])

    def exported_result(self, compiler, project, payload):
        files = compiler(project, {'local': []})
        with tempfile.TemporaryDirectory() as directory:
            for name, body in files.items():
                path = Path(directory) / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(body)
            command = [sys.executable, 'run.py'] if compiler is raw_python_files else [sys.executable, '-m', 'application.main']
            run = subprocess.run([*command, '--task', 'main', '--input', json.dumps(payload)],
                                 cwd=directory, capture_output=True, text=True, timeout=30)
            self.assertEqual(run.returncode, 0, run.stderr)
            result = json.loads(run.stdout)
            if compiler is raw_python_files:
                archive = Path(directory) / 'application.pympkg'
                with zipfile.ZipFile(archive, 'w') as output:
                    for name, body in files.items(): output.writestr(name, body)
                zipped = subprocess.run([sys.executable, str(archive), '--task', 'main', '--input', json.dumps(payload)],
                                        cwd=directory, capture_output=True, text=True, timeout=30)
                self.assertEqual(zipped.returncode, 0, zipped.stderr)
                self.assertEqual(json.loads(zipped.stdout), result)
            return result

    def assert_exports(self, project, payload, expected):
        for compiler in (raw_python_files, engine_python_files):
            with self.subTest(archive=compiler.__name__):
                self.assertEqual(self.exported_result(compiler, project, payload), expected)

    def assert_studio(self, project, payload, expected, starter_event=False):
        from app.debugger import DebugManager
        from app.models import Project
        from app.runtime import WorkflowRuntime

        async def run():
            studio_project = Project.model_validate(project)
            resources = {resource.id: resource for resource in studio_project.resources}
            runtime = WorkflowRuntime()
            result = await runtime.run(studio_project.tasks[0], payload, resources=resources, project=studio_project)
            self.assertEqual((result.status, result.output), ('completed', expected), result.logs if result.status == 'failed' else None)
            debugger = DebugManager(runtime)
            session = debugger.start(studio_project, 'main', payload, resources, {}, [])['sessionId']
            if starter_event:
                entry = studio_project.tasks[0].activities[0].id
                view = await debugger.trigger_event(session, result.activity_outputs[entry]['output'])
                self.assertEqual((view['status'], view['output']), ('listening', expected))
            else:
                view = await debugger.action(session, 'continue')
                self.assertEqual((view['status'], view['output']), ('completed', expected))

        asyncio.run(run())

    def test_grouped_conditions_preserve_literals_in_archives(self):
        expressions = ['${input.text} = "A and B > C"',
                       'not (${input.n} < 3 or ${input.n} >= 9)',
                       'contains(${input.text}, "and B >") and ${input.n} = 5']
        rules = [dict(target=f'value{i}', operator='if', condition=expression, source='"passed"')
                 for i, expression in enumerate(expressions)]
        self.assert_exports(self.project(rules), {'text': 'A and B > C', 'n': 5},
                            {f'value{i}': 'passed' for i in range(len(expressions))})

    def test_repeating_complex_copy_and_for_each_across_runtimes(self):
        payload = {'rows': [{'Name': 'Ada', 'Marks': 9}]}
        copy = [dict(target='report.Record', operator='copy-of', source='${input.rows}', targetType='object[]')]
        loop = [dict(target='report.Record', operator='for-each', source='${input.rows}'),
                dict(target='report.Record.Name', source='${input.rows.Name}', targetType='string')]
        for rules, expected in ((copy, {'report': {'Record': payload['rows']}}),
                                (loop, {'report': {'Record': [{'Name': 'Ada'}]}})):
            with self.subTest(operator=rules[0]['operator']):
                project = self.project(rules)
                self.assert_studio(project, payload, expected)
                self.assert_exports(project, payload, expected)

    def test_repeating_copy_round_trips_as_an_xml_binding(self):
        from app.mapper_binding import generate_binding, reopen_binding
        rules = [dict(target='report.Record', operator='copy-of', source='${input.notes.note}')]
        binding = generate_binding(rules)
        restored = reopen_binding(binding)
        self.assertEqual(restored['mappings'], rules)
        project = self.project(rules)
        project['tasks'][0]['activities'][1]['config'].update(restored, xmlSource='${input.xmlString}')
        payload = {'xmlString': '<notes><note><name>Ada</name></note><note><name>Lin</name></note></notes>'}
        xml = '<report><Record><name>Ada</name></Record><Record><name>Lin</name></Record></report>'
        result = {'Record': [{'name': 'Ada'}, {'name': 'Lin'}]}
        expected = {'report': result, 'value': result, 'xml': xml, 'xmlString': xml, 'root': 'report'}
        self.assert_studio(project, payload, expected)
        self.assert_exports(project, payload, expected)

    def test_xpath_versions_and_namespace_predicates(self):
        payload = {'minimum': 2, 'xmlString': '<o:orders xmlns:o="urn:orders"><o:order id="1">skip</o:order><o:order id="2">west</o:order></o:orders>'}
        for version, formula, expected in [('1.0', 'string(/p:orders/p:order[@id=$minimum])', 'west'),
                                           ('2.0', 'upper-case(string(/p:orders/p:order[@id=$minimum]))', 'WEST')]:
            project = self.project([dict(target='region', source=f'xpath("{formula}")')])
            project['tasks'][0]['activities'][1]['config'].update(xpathVersion=version, xmlNamespaces={'p': 'urn:orders'}, xmlVariables={'minimum': '${input.minimum}'})
            self.assert_studio(project, payload, {'region': expected})
            self.assert_exports(project, payload, {'region': expected})
            for compiler in (raw_python_files, engine_python_files):
                manifest = compiler(project, {'local': []})['requirements-mapper.txt'].decode()
                self.assertIn('lxml', manifest)
                self.assertEqual('elementpath' in manifest, version == '2.0')

    def test_xslt_binding_validates_project_schema_imports_and_preserves_nil(self):
        project = self.project([])
        project['schemas'] = [
            dict(id='contract', name='target.xsd', content='''<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema"
                xmlns:t="urn:target" targetNamespace="urn:target"><xs:include schemaLocation="type.xsd"/>
                <xs:element name="result" type="t:Result" nillable="true"/></xs:schema>'''),
            dict(id='type', name='type.xsd', content='''<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema"
                targetNamespace="urn:target"><xs:simpleType name="Result"><xs:restriction base="xs:string"/></xs:simpleType></xs:schema>'''),
        ]
        project['tasks'][0]['activities'][1]['config'].update(targetSchemaId='contract', xmlStylesheet='''
            <xsl:stylesheet xmlns:xsl="http://www.w3.org/1999/XSL/Transform" version="1.0"
              xmlns:t="urn:target" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
              <xsl:template match="/"><t:result xsi:nil="true"/></xsl:template>
            </xsl:stylesheet>'''.strip())
        xml = '<t:result xmlns:t="urn:target" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xsi:nil="true"/>'
        expected = {'xmlString': xml, 'xml': xml, 'root': '{urn:target}result', 'value': None, 'result': None}
        payload = {'xmlString': '<source/>'}
        self.assert_studio(project, payload, expected)
        self.assert_exports(project, payload, expected)
        from app.main import mapper_test
        preview = mapper_test({'input': '<source/>', 'targetSchemaText': project['schemas'][0]['content'], 'options': {
            **project['tasks'][0]['activities'][1]['config'], 'xmlSchemaDocuments': {'type.xsd': project['schemas'][1]['content']},
        }})
        self.assertEqual((preview['outputFormat'], preview['outputText'], preview['valid']), ('xml', xml, True))

    def test_mapper_preview_and_archives_resolve_nested_relative_xsd(self):
        from app.main import mapper_test
        project = self.project([])
        xs = '<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema">'
        project['schemas'] = [
            dict(id='root', name='root.xsd', source_path='orders/contract/root.xsd',
                 content=xs + '<xs:include schemaLocation="../types/container.xsd"/><xs:element name="orders" type="Orders"/></xs:schema>'),
            dict(id='container', name='container.xsd', source_path='orders/types/container.xsd',
                 content=xs + '<xs:include schemaLocation="entry.xsd"/><xs:complexType name="Orders"><xs:sequence><xs:element name="entry" type="Entry" maxOccurs="unbounded"/></xs:sequence></xs:complexType></xs:schema>'),
            dict(id='entry', name='entry.xsd', source_path='orders/types/entry.xsd',
                 content=xs + '<xs:complexType name="Entry"><xs:sequence><xs:element name="note" nillable="true"/></xs:sequence></xs:complexType></xs:schema>'),
            dict(id='other', name='entry.xsd', source_path='other/entry.xsd', content=xs + '</xs:schema>'),
        ]
        config = project['tasks'][0]['activities'][1]['config']
        config.update(targetSchemaId='root', xmlStylesheet='''<xsl:stylesheet xmlns:xsl="http://www.w3.org/1999/XSL/Transform" version="1.0">
          <xsl:template match="/"><orders xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
            <entry><note xsi:nil="true"/></entry>
          </orders></xsl:template></xsl:stylesheet>''')
        options = {**config, 'xmlTargetSchemaPath': project['schemas'][0]['source_path'],
                   'xmlSchemaDocuments': {asset['source_path']: asset['content'] for asset in project['schemas']}}
        request = {'input': '<source/>', 'targetSchemaText': project['schemas'][0]['content'], 'options': options}
        preview = mapper_test(request)
        self.assertTrue(preview['valid'], preview)
        expected = preview['output']
        self.assertEqual(expected['orders'], {'entry': [{'note': None}]})
        self.assert_studio(project, {'xmlString': '<source/>'}, expected)
        self.assert_exports(project, {'xmlString': '<source/>'}, expected)
        from fastapi import HTTPException
        with self.assertRaisesRegex(HTTPException, 'Target schema validation failed'):
            mapper_test({**request, 'options': {**options, 'xmlStylesheet': config['xmlStylesheet'].replace('note', 'unexpected')}})

    def test_smart_mapper_branch_levels_and_exact_names(self):
        from app.main import mapper_suggest
        payload = {'sourceSchema': {'origin': {'id': 1, 'nested': {'item': 2}}, 'other': {'name': 'x'}},
                   'targetSchema': {'dest': {'id': 0, 'nested': {'item': 0}, 'names': ''}},
                   'sourceScope': 'origin', 'targetScope': 'dest', 'sourceLevel': 1, 'targetLevel': 1,
                   'exactNames': True}
        first = mapper_suggest(payload)['recommendations']
        self.assertEqual({row['target']: row['selected'] for row in first}, {'dest.id': 'origin.id', 'dest.names': None})
        second = mapper_suggest({**payload, 'targetLevel': 2})['recommendations']
        self.assertIsNone(next(row['selected'] for row in second if row['target'] == 'dest.nested.item'))
        third = mapper_suggest({**payload, 'sourceLevel': 2, 'targetLevel': 2})['recommendations']
        self.assertEqual(next(row['selected'] for row in third if row['target'] == 'dest.nested.item'), 'origin.nested.item')

    def test_xml_bindings_reject_external_resources(self):
        from app.mapper_xml import parse_xml, transform_xml, xpath_value
        from lxml import etree

        with self.assertRaisesRegex(ValueError, 'DTDs are disabled'):
            parse_xml('<!DOCTYPE root SYSTEM "file:///secret"><root/>')
        root = parse_xml('<root/>')
        binding = '''<xsl:stylesheet xmlns:xsl="http://www.w3.org/1999/XSL/Transform" version="1.0">
            <xsl:template match="/"><out><xsl:value-of select="document('file:///secret')"/></out></xsl:template>
            </xsl:stylesheet>'''
        with self.assertRaisesRegex(etree.XSLTApplyError, 'denied'):
            transform_xml(root, binding)
        for formula in ("doc('file:///secret')", "fn:doc('file:///secret')"):
            with self.assertRaises(ValueError):
                xpath_value(root, formula, '2.0', {})

    def test_businessworks_import_executes_xslt2_in_studio_and_archives(self):
        from html import escape
        from io import BytesIO
        from unittest.mock import patch

        from app.project_import import project_payload

        binding = '''<xsl:stylesheet xmlns:xsl="http://www.w3.org/1999/XSL/Transform" version="2.0">
          <xsl:output encoding="ISO-8859-1"/>
          <xsl:param name="order"/><xsl:param name="minimum"/>
          <xsl:template match="/"><result><xsl:value-of select="upper-case($order/order[@id = $minimum]/text())"/>
            <xsl:value-of select="environment-variable('MINA_XSLT_TEST_SECRET')"/></result></xsl:template>
        </xsl:stylesheet>'''
        process = ('<process xmlns:tibex="http://www.tibco.com/bpel/2007/extensions">'
                   '<activity name="SelectOrder"><tibex:inputBindings><tibex:inputBinding expression="'
                   + escape(binding, quote=True) + '"/></tibex:inputBindings></activity></process>')
        archive = BytesIO()
        with zipfile.ZipFile(archive, 'w') as package:
            package.writestr('Orders/Processes/Select.bwp', process)
            package.writestr('Orders/Schemas/order.xsd', '<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema"/>')
        project = json.loads(project_payload(archive.getvalue(), 'Orders.zip'))
        self.assertEqual(project['schemas'][0]['name'], 'order.xsd')
        self.assertEqual(len(json.loads(project_payload(process.encode(), 'Select.bwp'))['tasks']), 1)
        project['tasks'][0]['id'] = project['active_task_id'] = 'main'
        project['tasks'][0]['activities'][1]['config']['sourceTypeOverrides'] = {'input.minimum': 'integer'}
        payload = {'order': '<order id="2">café</order>', 'minimum': '2'}
        xml = '<result>CAFÉ</result>'
        expected = {'xml': xml, 'xmlString': xml, 'root': 'result', 'value': 'CAFÉ', 'result': 'CAFÉ'}
        with patch.dict('os.environ', {'MINA_XSLT_TEST_SECRET': 'must-not-leak'}):
            self.assert_studio(project, payload, expected)
            self.assert_exports(project, payload, expected)
        for compiler in (raw_python_files, engine_python_files):
            self.assertIn(b'saxonche', compiler(project, {'local': []})['requirements-mapper.txt'])

    def test_businessworks_graph_preserves_links_and_static_call(self):
        from app.bw_process import BPEL, BW
        from app.project_import import bw_project
        from app.mapper_xml import XSL

        def process(name, body):
            return f'<b:process xmlns:b="{BPEL[1:-1]}" xmlns:t="{BW[1:-1]}" name="{name}">{body}</b:process>'.encode()

        top = process('Main', '''
          <b:flow><b:links><b:link name="left"/><b:link name="right"/></b:links>
            <b:extensionActivity><t:extActivity type="bw.generalactivities.callprocess" name="Call">
              <b:targets><b:target linkName="left"/><b:target linkName="right"/></b:targets>
              <t:CallProcess subProcessName="Child"/>
            </t:extActivity></b:extensionActivity>
            <b:empty name="Left"><b:sources><b:source linkName="left"/></b:sources></b:empty>
            <b:empty name="Right"><b:sources><b:source linkName="right"/></b:sources></b:empty>
          </b:flow>''')
        child = process('Child', f'''
          <b:sequence><b:extensionActivity><t:extActivity type="bw.generalactivities.mapper" name="Mapper">
            <t:inputBindings><x:stylesheet xmlns:x="{XSL[1:-1]}" version="2.0"
               xmlns:tib="http://www.tibco.com/bw/xslt/custom-functions" exclude-result-prefixes="#all">
              <x:param name="name"/>
              <x:template match="/"><result><x:value-of select="tib:upper-case(tib:trim($name))"/></result></x:template>
            </x:stylesheet></t:inputBindings>
          </t:extActivity></b:extensionActivity></b:sequence>''')
        project = json.loads(bw_project({'1/Main.bwp': top, '2/Child.bwp': child}, 'workflows.zip'))
        parent, child = project['tasks']
        self.assertEqual([item['type'] for item in parent['activities']], ['start', 'basic', 'basic', 'call_task', 'end'])
        self.assertEqual(sum(link['target'] == parent['activities'][3]['id'] for link in parent['transitions']), 2)
        self.assertEqual(parent['activities'][3]['config']['taskId'], child['id'])
        parent['id'] = project['active_task_id'] = 'main'
        xml = '<result>ADA</result>'
        expected = {'xml': xml, 'xmlString': xml, 'root': 'result', 'value': 'ADA', 'result': 'ADA'}
        self.assert_studio(project, {'name': ' Ada '}, expected)
        self.assert_exports(project, {'name': ' Ada '}, expected)

    def test_businessworks_http_connection_executes_in_runtime_and_archives(self):
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
        from threading import Thread
        from app.bw_process import BPEL, BW, HTTP_CLIENT_NS, JNDI
        from app.project_import import bw_project

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(b'{"ok":true}')

            def log_message(self, *args):
                pass

        with ThreadingHTTPServer(('127.0.0.1', 0), Handler) as server:
            thread = Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                process = f'''
                  <b:process xmlns:b="{BPEL[1:-1]}" xmlns:t="{BW[1:-1]}" name="HTTP">
                    <b:extensionActivity><t:extActivity type="bw.http.sendHTTPRequest" name="Get">
                      <t:SendHTTPRequest><t:httpClient>Connections/Client</t:httpClient>
                        <t:method>GET</t:method><t:requestURI>/check</t:requestURI>
                      </t:SendHTTPRequest>
                    </t:extActivity></b:extensionActivity>
                  </b:process>'''
                connection = f'''<jndi:namedResource xmlns:jndi="{JNDI[1:-1]}"
                  xmlns:http="{HTTP_CLIENT_NS}" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
                  <jndi:configuration xsi:type="http:HttpClientConfiguration" httpClientVersion="httpcomponents">
                    <tcpDetails host="127.0.0.1" port="{server.server_port}" socketTimeout="2000"
                                maxTotalConnections="10" maxConnectionsPerHost="3" idleConnectionTimeout="5000"/>
                  </jndi:configuration>
                </jndi:namedResource>'''
                project = json.loads(bw_project({'App/Process.bwp': process.encode(),
                    'App/Connections/Client.httpClientResource': connection.encode()}, 'http.zip'))
                task = project['tasks'][0]
                task['id'] = project['active_task_id'] = 'main'
                self.assertEqual(project['resources'][0]['config']['socketTimeoutMs'], 2000)
                self.assertEqual(project['resources'][0]['config']['maximumTotalConnections'], 10)
                self.assertEqual(project['resources'][0]['config']['maximumConnectionsPerHost'], 3)
                self.assertEqual(project['resources'][0]['config']['idleConnectionTimeoutMs'], 5000)
                # Compare a stable output, independent of server date and transport metadata.
                task['activities'][-1]['config'] = {'inputMappings': {'result': '${last.body}'}}
                self.assert_studio(project, {}, {'ok': True})
                self.assert_exports(project, {}, {'ok': True})
            finally:
                server.shutdown()
                thread.join()

    def test_generated_binding_round_trips_and_executes_in_both_archives(self):
        from app.mapper_binding import generate_binding, reopen_binding

        rules = [{'target': 'result.name', 'source': 'person.name', 'functions': ['trim', 'upperCase']},
                 {'target': 'result.type', 'constant': "O'Reilly"}]
        stylesheet = generate_binding(rules)
        restored = reopen_binding(stylesheet)
        self.assertEqual(restored['mappings'], rules)
        self.assertEqual(generate_binding(restored['mappings']), stylesheet)
        with self.assertRaisesRegex(ValueError, 'was edited'):
            reopen_binding(stylesheet.replace('match="/"', 'match="/person"'))
        with self.assertRaisesRegex(ValueError, 'Choose requires'):
            generate_binding([{'target': 'result', 'operator': 'choose', 'source': 'people'}])
        project = self.project(rules)
        project['tasks'][0]['activities'][1]['config'].update(restored, xmlSource='${input.source}')
        payload = {'source': '<person><name> Ada </name></person>'}
        xml = "<result><name>ADA</name><type>O'Reilly</type></result>"
        result = {'name': 'ADA', 'type': "O'Reilly"}
        expected = {'xml': xml, 'xmlString': xml, 'root': 'result', 'value': result, 'result': result}
        self.assert_studio(project, payload, expected)
        self.assert_exports(project, payload, expected)

    def test_generated_binding_preserves_simple_repeating_xml(self):
        from app.mapper_binding import generate_binding, reopen_binding
        from app.mapper_xml import parse_xml, transform_xml

        rules = [{'target': 'team.member', 'select': 'people.person', 'operator': 'for-each', 'occurrenceId': 'loop'},
                 {'target': 'team.member.name', 'source': 'name', 'occurrenceId': 'loop'}]
        binding = generate_binding(rules)
        self.assertEqual(reopen_binding(binding)['mappings'], rules)
        previous_format = binding.replace('test="exists(zero-or-one(name))"', 'test="name"')
        self.assertNotEqual(previous_format, binding)
        self.assertEqual(reopen_binding(previous_format)['mappings'], rules)
        result = transform_xml(parse_xml('<people><person><name>Ada</name></person><person><name>Grace</name></person></people>'), binding)
        self.assertEqual(result.xpath('/team/member/name/text()'), ['Ada', 'Grace'])

    def test_named_source_coercions_and_cardinality_in_both_archives(self):
        from app.main import mapper_test
        from app.mapper import execute

        schema = '''<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema"
                     targetNamespace="urn:order" xmlns:o="urn:order" elementFormDefault="qualified">
          <xs:complexType name="Base"><xs:sequence><xs:element name="id" type="xs:string"/></xs:sequence></xs:complexType>
          <xs:complexType name="Retail"><xs:complexContent><xs:extension base="o:Base"><xs:sequence>
            <xs:element name="store" type="xs:string"/></xs:sequence></xs:extension></xs:complexContent></xs:complexType>
          <xs:element name="order" type="o:Base"/>
        </xs:schema>'''
        views = {'Retail': {'path':'input.order', 'schema':schema, 'type':'Retail', 'cardinality':'1'},
                 'Repeat': {'path':'input.order', 'schema':schema, 'type':'Retail', 'cardinality':'+'},
                 'Optional': {'path':'input.absent', 'cardinality':'?'},
                 'Empty': {'path':'input.absent', 'cardinality':'*'},
                 'Unused': {'path':'input.absent', 'cardinality':'1'}}
        rules = [
            {'target':'store', 'source':'${coerced.Retail.store}'},
            {'target':'rows', 'operator':'for-each', 'source':'${coerced.Repeat}'},
            {'target':'rows.id', 'source':'${coerced.Repeat.id}'},
            {'target':'missing', 'source':'${coerced.Optional}'},
            {'target':'empty', 'source':'count(${coerced.Empty})'},
        ]
        payload = {'order':'<o:order xmlns:o="urn:order"><o:id>01</o:id><o:store>East</o:store></o:order>'}
        expected = {'store':'East', 'rows':[{'id':'01'}], 'empty':0}
        project = self.project(rules)
        project['tasks'][0]['activities'][1]['config']['sourceCoercions'] = views
        self.assertEqual(mapper_test({'input':payload, 'mappings':rules, 'options':{'sourceCoercions':views}})['output'], expected)
        self.assert_studio(project, payload, expected)
        self.assert_exports(project, payload, expected)
        with self.assertRaisesRegex(ValueError, 'cardinality 1 rejects 2'):
            execute({'input':{'order':[payload['order'], payload['order']]}}, rules, {'sourceCoercions':views})
        with self.assertRaisesRegex(ValueError, "Mapper source coercion 'Retail'"):
            execute({'input':{'order':'<o:order xmlns:o="urn:order"><o:id>01</o:id></o:order>'}}, rules, {'sourceCoercions':views})

    def test_xpath_palette_and_per_expression_version_quick_fix(self):
        from app.mapper_xml import xpath_function_palette, xpath_value, transform_xml, parse_xml, BW_FUNCTIONS

        one = {item['name'] for item in xpath_function_palette('1.0')}
        two = {item['name'] for item in xpath_function_palette('2.0')}
        self.assertIn('substring', one)
        self.assertNotIn('upper-case', one)
        self.assertTrue({'xs:dateTime', 'round-half-to-even', 'ext:substring-after-last', 'matches', 'replace', 'tokenize'} <= two)
        self.assertTrue({'doc', 'collection'}.isdisjoint(two))
        rules = [
            {'target':'old', 'source':'xpath1("string(/record/id)")'},
            {'target':'new', 'source':'''xpath2("tib:substring-after-last(string(/record/id), '.')")'''},
            {'target':'regex', 'source':'''xpath2("replace(string(/record/id), '[.]', '-')")'''},
        ]
        project = self.project(rules)
        payload = {'xmlString':'<record><id>a.b.c</id></record>'}
        expected = {'old':'a.b.c', 'new':'c', 'regex':'a-b-c'}
        self.assert_studio(project, payload, expected)
        self.assert_exports(project, payload, expected)
        root = parse_xml(payload)
        self.assertEqual(xpath_value(root, "tib:substring-before-last(string(/record/id), '.')", '1.0', {}), 'a.b')
        with self.assertRaisesRegex(ValueError, 'XPath 2.0 regex'):
            xpath_value(root, "matches('abc','abc') and exists(doc('file:///private.xml'))", '2.0', {})
        stylesheet = f'''<xsl:stylesheet xmlns:xsl="http://www.w3.org/1999/XSL/Transform" xmlns:tib="{BW_FUNCTIONS}"
          version="2.0" exclude-result-prefixes="tib"><xsl:template match="/">
            <out><xsl:value-of select="tib:substring-after-last(string(/record/id), '.')"/></out>
          </xsl:template></xsl:stylesheet>'''
        self.assertEqual(transform_xml(root, stylesheet).text, 'c')

    def test_generated_mapper_keeps_binding_in_sync_and_distinguishes_missing_from_nil(self):
        from app.main import mapper_test
        from app.mapper_binding import generate_binding, reopen_binding
        from app.mapper_xml import parse_xml

        schema = '''<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema"><xs:element name="out">
          <xs:complexType><xs:sequence>
            <xs:element name="keep" type="xs:string" minOccurs="0" nillable="true"/>
            <xs:element name="drop" type="xs:string" minOccurs="0"/>
            <xs:element name="missing" type="xs:string" minOccurs="0"/>
            <xs:element name="count" type="xs:integer"/>
          </xs:sequence></xs:complexType></xs:element></xs:schema>'''
        rules = [
            {'target': 'out.keep', 'source': 'raw.nil'},
            {'target': 'out.drop', 'source': 'raw.nil'},
            {'target': 'out.missing', 'source': 'raw.absent'},
            {'target': 'out.count', 'source': 'xpath("xs:integer(/raw/value)")'},
        ]
        preferences = {'implicitExistence': True, 'omitOptionalNil': True, 'copyNil': True}
        stylesheet = generate_binding(rules, schema, preferences=preferences)
        self.assertEqual(reopen_binding(stylesheet)['xmlBindingPreferences'], preferences)
        config = {'generatedXmlBinding': True, 'xmlBindingPreferences': preferences,
                  'xmlStylesheet': '<stale/>', 'targetSchemaText': schema}
        payload = {'xmlString': '<raw xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"><nil xsi:nil="true"/><value>007</value></raw>'}
        result = mapper_test({'input': payload, 'options': config, 'mappings': rules})
        root = parse_xml(result['outputText'])
        self.assertEqual(root.xpath('local-name()'), 'out')
        self.assertEqual(root.xpath('string(keep/@xsi:nil)', namespaces={'xsi': 'http://www.w3.org/2001/XMLSchema-instance'}), 'true')
        self.assertEqual(root.xpath('count(drop|missing)'), 0)
        self.assertEqual(root.xpath('string(count)'), '7')
        alternate = {**config, 'xmlBindingPreferences': {'implicitExistence': False, 'omitOptionalNil': False, 'copyNil': False}}
        other = parse_xml(mapper_test({'input': payload, 'options': alternate, 'mappings': rules})['outputText'])
        self.assertEqual(other.xpath('count(keep|drop|missing)'), 3)
        self.assertFalse(other.xpath('keep/@*'))
        project = self.project(rules)
        project['tasks'][0]['activities'][1]['config'].update(config)
        self.assert_studio(project, payload, result['output'])
        self.assert_exports(project, payload, result['output'])

    def test_generated_complex_xml_round_trip_runtime_and_archives(self):
        from app.mapper_binding import generate_binding, reopen_binding

        rules = [
            {'target': 'out.label', 'operator': 'choose', 'whens': [
                {'condition': '${input.mode} = "full"', 'source': '"Full"'}], 'otherwise': '"Short"'},
            {'target': 'out.group', 'operator': 'for-each-group', 'source': 'input.line', 'groupBy': 'category'},
            {'target': 'out.group.name', 'source': 'category'},
            {'target': 'out.group.entry', 'operator': 'for-each', 'source': 'current-group()'},
            {'target': 'out.group.entry.item', 'operator': 'if', 'condition': '${show} = "yes"', 'source': 'item'},
            {'target': 'out.group', 'operator': 'for-each', 'source': 'input.extra',
             'duplicateOf': 'group', 'occurrenceId': 'copy'},
            {'target': 'out.group.name', 'source': 'category', 'occurrenceId': 'copy'},
        ]
        stylesheet = generate_binding(rules)
        restored = reopen_binding(stylesheet)
        self.assertEqual(restored['mappings'], rules)
        project = self.project(rules)
        project['tasks'][0]['activities'][1]['config'].update(restored, xmlSource='${input.xmlString}')
        payload = {'xmlString': '<input><mode>full</mode><line><category>A</category><show>yes</show><item>X</item></line>'
                   '<line><category>A</category><show>yes</show><item>Y</item></line>'
                   '<extra><category>B</category></extra></input>'}
        xml = '<out><label>Full</label><group><name>A</name><entry><item>X</item></entry><entry><item>Y</item></entry></group><group><name>B</name></group></out>'
        result = {'label': 'Full', 'group': [{'name': 'A', 'entry': [{'item': 'X'}, {'item': 'Y'}]}, {'name': 'B'}]}
        expected = {'out': result, 'value': result, 'xml': xml, 'xmlString': xml, 'root': 'out'}
        self.assert_studio(project, payload, expected)
        self.assert_exports(project, payload, expected)

    def test_businessworks_xpath_links_and_no_match(self):
        from app.bw_process import BPEL, BW
        from app.mapper_xml import XSL
        from app.project_import import bw_project

        def mapper(name, value, target, variable):
            return f'''<b:extensionActivity><t:extActivity name="{name}" outputVariable="{variable}" type="bw.generalactivities.mapper">
            <b:targets><b:target linkName="{target}"/></b:targets><b:sources><b:source linkName="{name}ToJoin"/></b:sources>
            <t:inputBindings><x:stylesheet version="2.0" exclude-result-prefixes="#all">
            <x:template match="/"><value>{value}</value></x:template></x:stylesheet></t:inputBindings>
            </t:extActivity></b:extensionActivity>'''
        process = f'''<b:process xmlns:b="{BPEL[1:-1]}" xmlns:t="{BW[1:-1]}" xmlns:x="{XSL[1:-1]}">
          <b:flow><b:links>
            <b:link name="left" t:linkType="SUCCESSWITHCONDITION"/><b:link name="right" t:linkType="SUCCESSWITHCONDITION"/>
            <b:link name="default" t:linkType="SUCCESSWITHNOCONDITION"/>
            <b:link name="LeftToJoin"/><b:link name="RightToJoin"/><b:link name="DefaultToJoin"/>
          </b:links>
          <b:extensionActivity><t:receiveEvent name="Start" variable="Start"><t:eventSource><t:StartEvent/></t:eventSource>
            <b:sources><b:source linkName="left"><b:transitionCondition expressionLanguage="xpath2.0">matches(string($Start/mode), 'both')</b:transitionCondition></b:source>
            <b:source linkName="right"><b:transitionCondition expressionLanguage="xpath2.0">$Start/mode = 'both'</b:transitionCondition></b:source>
            <b:source linkName="default"/></b:sources>
          </t:receiveEvent></b:extensionActivity>
          {mapper('Left', 'A', 'left', 'Left')}{mapper('Right', 'B', 'right', 'Right')}{mapper('Default', 'Z', 'default', 'Default')}
          <b:extensionActivity><t:extActivity name="Join" type="bw.generalactivities.mapper">
            <b:targets><b:target linkName="LeftToJoin"/><b:target linkName="RightToJoin"/><b:target linkName="DefaultToJoin"/></b:targets>
            <t:inputBindings><x:stylesheet version="2.0" exclude-result-prefixes="#all">
              <x:param name="Left" select="()"/><x:param name="Right" select="()"/><x:param name="Default" select="()"/>
              <x:template match="/"><result><x:value-of select="($Left/value, $Right/value, $Default/value)" separator=""/></result></x:template>
            </x:stylesheet></t:inputBindings>
          </t:extActivity></b:extensionActivity></b:flow></b:process>'''
        project = json.loads(bw_project({'Links.bwp': process.encode()}, 'Links.bwp'))
        task = project['tasks'][0]
        task['id'] = project['active_task_id'] = 'main'
        self.assertEqual(sum(bool(edge.get('bw_xpath')) for edge in task['transitions']), 2)
        left = next(activity for activity in task['activities'] if activity['name'] == 'Left')
        for edge in task['transitions']:
            for endpoint in ('source', 'target'):
                if edge[endpoint] == left['id']:
                    edge[endpoint] = 'Left'
        left['id'] = 'Left'
        join = next(activity for activity in task['activities'] if activity['name'] == 'Join')
        join['config']['xmlVariables']['Left'] = '${Left.xmlString}'
        for mode, value in [('both', 'AB'), ('neither', 'Z')]:
            payload = {'xmlString': f'<input><mode>{mode}</mode></input>'}
            xml = f'<result>{value}</result>'
            expected = {'result': value, 'value': value, 'xml': xml, 'xmlString': xml, 'root': 'result'}
            self.assert_studio(project, payload, expected)
            self.assert_exports(project, payload, expected)

    def test_businessworks_jdbc_query_and_jms_text(self):
        from app.bw_process import BPEL, BW, BW_ACTIVITY, JDBC_NS, JNDI
        from app.mapper_xml import XSL
        from app.project_import import bw_project

        process = f'''<b:process xmlns:b="{BPEL[1:-1]}" xmlns:t="{BW[1:-1]}"
             xmlns:bwext="{BW_ACTIVITY[1:].split('}')[0]}" xmlns:x="{XSL[1:-1]}">
          <b:sequence>
            <b:extensionActivity><t:activityExtension name="Query"><t:config>
              <bwext:BWActivity activityTypeID="bw.jdbc.JDBCQuery"><activityConfig><properties name="config">
                <value sharedResourceProperty="Database" sqlStatement="SELECT 'hello' AS message" maxRows="1"/>
              </properties></activityConfig></bwext:BWActivity></t:config>
            </t:activityExtension></b:extensionActivity>
            <b:extensionActivity><t:activityExtension name="Send">
              <t:inputBindings><x:stylesheet version="2.0" exclude-result-prefixes="#all">
                <x:template match="/"><message><text>hello</text></message></x:template>
              </x:stylesheet></t:inputBindings>
              <t:config><bwext:BWActivity activityTypeID="bw.jms.SendMessage"><activityConfig><properties name="config">
                <value sharedResourceProperty="Broker" destination="bw-test" messageType="Text"/>
              </properties></activityConfig></bwext:BWActivity></t:config>
            </t:activityExtension></b:extensionActivity>
            <b:extensionActivity><t:activityExtension name="Receive"><t:config>
              <bwext:BWActivity activityTypeID="bw.jms.GetQueueMessage"><activityConfig><properties name="config">
                <value sharedResourceProperty="Broker" destination="bw-test" timeout="500"/>
              </properties></activityConfig></bwext:BWActivity></t:config>
            </t:activityExtension></b:extensionActivity>
          </b:sequence></b:process>'''
        jdbc = f'''<jndi:namedResource xmlns:jndi="{JNDI[1:-1]}" xmlns:jdbc="{JDBC_NS}"
                   xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" name="Database">
            <jndi:configuration xsi:type="jdbc:JdbcDataSource">
                <connectionConfig xsi:type="jdbc:NonXaConnection" jdbcDriver="org.sqlite.JDBC" dbURL="jdbc:sqlite::memory:"/>
            </jndi:configuration></jndi:namedResource>'''
        jms = '<JMSConnection><mode>memory</mode></JMSConnection>'
        project = json.loads(bw_project({'Connectors.bwp': process.encode(),
                            'Database.jdbcResource': jdbc.encode(), 'Broker.jmsConnResource': jms.encode()}, 'Connectors.zip'))
        task = project['tasks'][0]
        task['id'] = project['active_task_id'] = 'main'
        query = next(item['id'] for item in task['activities'] if item['type'] == 'jdbc')
        task['activities'][-1]['config'] = {'inputMappings': {'message': '${last.body}', 'query': '${activities.' + query + '.output.rowCount}'}}
        payload = {'xmlString': '<input/>'}
        self.assert_studio(project, payload, {'message': 'hello', 'query': 1})
        self.assert_exports(project, payload, {'message': 'hello', 'query': 1})

    def test_businessworks_timer_is_a_native_starter(self):
        from app.bw_process import BPEL, BW
        from app.project_import import bw_project

        process = f'''<b:process xmlns:b="{BPEL[1:-1]}" xmlns:t="{BW[1:-1]}">
            <b:extensionActivity><t:receiveEvent name="Schedule" variable="Schedule"><t:eventSource>
              <t:TimerEvent><scheduledDateTime>2020-01-01T00:00:00Z</scheduledDateTime></t:TimerEvent>
            </t:eventSource></t:receiveEvent></b:extensionActivity></b:process>'''
        project = json.loads(bw_project({'Timer.bwp': process.encode()}, 'Timer.bwp'))
        task = project['tasks'][0]
        task['id'] = project['active_task_id'] = 'main'
        self.assertEqual((task['kind'], task['activities'][0]['type']), ('starter', 'timer'))
        task['activities'][-1]['config'] = {'inputMappings': {'fired': '${last.sequence}'}}
        self.assert_studio(project, {}, {'fired': 1}, starter_event=True)
        self.assert_exports(project, {}, {'fired': 1})

    def test_businessworks_http_event_and_reply_binding(self):
        from app.bw_process import BPEL, BW, HTTP_SERVER_NS, JNDI
        from app.mapper_xml import XSL
        from app.project_import import bw_project

        process = f'''<b:process xmlns:b="{BPEL[1:-1]}" xmlns:t="{BW[1:-1]}" xmlns:x="{XSL[1:-1]}">
          <b:sequence><b:extensionActivity><t:receiveEvent name="Listen" variable="Request"><t:eventSource>
            <t:HTTPReceiveEvent><httpConnection>Listener</httpConnection><path>/hello</path><method>POST</method></t:HTTPReceiveEvent>
          </t:eventSource></t:receiveEvent></b:extensionActivity>
          <b:reply name="Reply"><t:inputBindings><x:stylesheet version="2.0" exclude-result-prefixes="#all">
            <x:param name="Request"/><x:template match="/"><greet><x:value-of select="$Request/name"/></greet></x:template>
          </x:stylesheet></t:inputBindings></b:reply></b:sequence></b:process>'''
        connection = f'''<jndi:namedResource xmlns:jndi="{JNDI[1:-1]}" xmlns:h="{HTTP_SERVER_NS}"
                          xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" name="Listener">
          <jndi:configuration xsi:type="h:HttpConnectorConfiguration" port="8181" minThreads="2" maxThreads="12"/>
        </jndi:namedResource>'''
        project = json.loads(bw_project({'Http.bwp': process.encode(), 'Listener.httpConnResource': connection.encode()}, 'Http.zip'))
        task = project['tasks'][0]
        task['id'] = project['active_task_id'] = 'main'
        self.assertEqual([item['type'] for item in task['activities']], ['http_listener', 'mapper', 'http_response'])
        self.assertEqual(project['resources'][0]['config']['maximumQtpThreads'], 12)
        payload = {'body': '<input><name>Ada</name></input>'}
        expected = {'body': '<greet>Ada</greet>', 'statusCode': 200, 'headers': {'content-type': 'application/xml'}}
        self.assert_studio(project, payload, {**expected, '__httpResponse': True})
        self.assertEqual(self.exported_result(raw_python_files, project, payload), {**expected, 'sent': True})
        self.assertEqual(self.exported_result(engine_python_files, project, payload), {**expected, '__httpResponse': True})

    def test_businessworks_xmi_file_binding_writes_from_start_xml(self):
        from app.bw_process import BPEL, BW, BW_ACTIVITY
        from app.mapper_xml import XSL
        from app.project_import import bw_project
        from xml.sax.saxutils import escape

        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'result.txt'
            process = f'''
              <b:process xmlns:b="{BPEL[1:-1]}" xmlns:t="{BW[1:-1]}"
                  xmlns:bwext="{BW_ACTIVITY[1:].split('}')[0]}" xmlns:x="{XSL[1:-1]}">
                <b:sequence>
                  <b:extensionActivity><t:receiveEvent name="Start" variable="Start" createInstance="yes">
                    <t:eventSource><t:StartEvent/></t:eventSource>
                  </t:receiveEvent></b:extensionActivity>
                  <b:extensionActivity><t:activityExtension name="WriteFile" outputVariable="WriteFile">
                    <t:inputBindings><x:stylesheet version="2.0" exclude-result-prefixes="#all">
                      <x:param name="Start"/>
                      <x:template match="/"><WriteInput>
                        <fileName><x:value-of select="$Start/path"/></fileName>
                        <textContent><x:value-of select="$Start/text"/></textContent>
                      </WriteInput></x:template>
                    </x:stylesheet></t:inputBindings>
                    <t:config><bwext:BWActivity activityTypeID="bw.file.write">
                      <activityConfig><properties name="config"><value encoding="text" overwrite="true"/></properties></activityConfig>
                    </bwext:BWActivity></t:config>
                  </t:activityExtension></b:extensionActivity>
                </b:sequence>
              </b:process>'''
            project = json.loads(bw_project({'Write.bwp': process.encode()}, 'Write.bwp'))
            task = project['tasks'][0]
            task['id'] = project['active_task_id'] = 'main'
            self.assertEqual([item['type'] for item in task['activities']], ['start', 'basic', 'mapper', 'file', 'end'])
            task['activities'][-1]['config'] = {'inputMappings': {'written': '${last.written}'}}
            payload = {'xmlString': f'<job><path>{escape(str(output))}</path><text>hello</text></job>'}
            self.assert_studio(project, payload, {'written': True})
            self.assertEqual(output.read_text(), 'hello')
            output.unlink()
            self.assert_exports(project, payload, {'written': True})
            self.assertEqual(output.read_text(), 'hello')

    def test_tibco_text_functions_use_the_extension_namespace(self):
        from app.mapper_xml import BW_FUNCTIONS, BW_RUNTIME_FUNCTIONS, XSL, parse_xml, transform_xml, xpath_value

        root = parse_xml('<person><name> Ada </name></person>')
        formula = '''concat(vendor:upper-case(vendor:trim(vendor:concat-sequence(/person/name))),
                            vendor:left("!x", 1), vendor:right("x?", 1), bw:getModuleProperty("suffix"))'''
        for version in ('1.0', '2.0'):
            self.assertEqual(xpath_value(root, formula, version, {'vendor': BW_FUNCTIONS, 'bw': BW_RUNTIME_FUNCTIONS},
                                         properties={'suffix': '#'}), 'ADA!?#')
            binding = f'''<x:stylesheet xmlns:x="{XSL[1:-1]}" xmlns:vendor="{BW_FUNCTIONS}" xmlns:bw="{BW_RUNTIME_FUNCTIONS}"
              exclude-result-prefixes="vendor bw" version="{version}">
              <x:template match="/"><result><x:value-of select='{formula}'/></result></x:template>
            </x:stylesheet>'''
            self.assertEqual(transform_xml(root, binding, properties={'suffix': '#'}).text, 'ADA!?#')

    def test_shared_mapper_learning_ranks_only_reviewed_schema_paths(self):
        from unittest.mock import patch
        from app.mapper import recommend
        from app.mapper_learning import shared_paths

        source = {'name': 'same name', 'legalLabel': 'private sample value', 'unrelated': 12}
        target = {'name': ''}
        rules = [{'source': 'legalLabel', 'target': 'name'},
                 {'source': 'name', 'target': 'name', 'pending': True},
                 {'source': 'name', 'target': 'name', 'functions': ['trim']},
                 {'source': 'unrelated', 'target': 'name'},
                 {'source': '"private literal"', 'target': 'name'}]
        with tempfile.TemporaryDirectory() as folder, patch('app.mapper_learning.DATA_DIR', Path(folder)):
            self.assertEqual(shared_paths(source, target), {})
            self.assertEqual(shared_paths(source, target, rules), 1)
            learned = shared_paths({**source, 'legalLabel': 'different payload'}, target)
            self.assertEqual(learned, {'name': 'legalLabel'})
            chosen = recommend(source, target, 1.0, learned=learned)[0]
            self.assertEqual(chosen['selected'], 'legalLabel')
            self.assertTrue(chosen['alternatives'][0]['learned'])
            self.assertEqual(shared_paths({**source, 'legalLabel': 14}, target), {})
            database = (Path(folder) / 'mapper-learning.sqlite3').read_bytes()
            self.assertNotIn(b'private', database)

    def test_xslt2_worker_rejects_external_files(self):
        from app.mapper_xml import parse_xml, transform_xml

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'private.xml'
            path.write_text('<secret/>', encoding='utf-8')
            sheet = f'''<xsl:stylesheet xmlns:xsl="http://www.w3.org/1999/XSL/Transform" version="2.0">
                <xsl:template match="/"><out><xsl:copy-of select="doc('{path.as_uri()}')"/></out></xsl:template>
            </xsl:stylesheet>'''
            with self.assertRaisesRegex(ValueError, 'prohibited'):
                transform_xml(parse_xml('<input/>'), sheet)
            output = Path(directory) / 'secondary.xml'
            sheet = f'''<xsl:stylesheet xmlns:xsl="http://www.w3.org/1999/XSL/Transform" version="2.0">
                <xsl:template match="/"><xsl:result-document href="{output.as_uri()}"><out/></xsl:result-document><main/></xsl:template>
            </xsl:stylesheet>'''
            with self.assertRaisesRegex(ValueError, 'result-document|external'):
                transform_xml(parse_xml('<input/>'), sheet)
            self.assertFalse(output.exists())

    def test_conditional_routing_supports_functions_and_grouping(self):
        project = self.project()
        task = project['tasks'][0]
        task['activities'][-1]['config']['inputMappings'] = {'result.route': '"match"'}
        task['activities'].append(dict(id='Fallback', name='Fallback', type='end', config={'inputMappings': {'result.route': '"fallback"'}}))
        task['transitions'] = [dict(id='match', source='Start', target='End', type='success_condition',
                                    condition='(${input.n} > 3 and contains(${input.text}, "and >")) or false'),
                               dict(id='fallback', source='Start', target='Fallback', type='success_no_match')]
        for n, expected in ((5, 'match'), (1, 'fallback')):
            self.assert_exports(project, {'n': n, 'text': 'and >'}, {'route': expected})

    def test_inline_activity_schema_enforces_literal_types(self):
        project = self.project(input_mappings={'result.name': 'unquoted'})
        project['tasks'][0]['activities'][-1]['config']['interfaceSchemaText'] = {
            'type': 'object', 'properties': {'result': {'type': 'object', 'properties': {'name': {'type': 'string'}}}}}
        for compiler in (raw_python_files, engine_python_files):
            with self.subTest(compiler=compiler.__name__), self.assertRaisesRegex(ValueError, 'string literals require'):
                compiler(project, {'local': []})

    def test_selected_schema_replaces_stale_cached_contract(self):
        project = self.project([dict(target='name', source='"current"')])
        project['schemas'] = [dict(id='contract', name='contract.json', content=json.dumps({'type': 'object', 'required': ['name'], 'additionalProperties': False, 'properties': {'name': {'type': 'string'}}}))]
        project['tasks'][0]['activities'][1]['config'].update(targetSchemaId='contract', targetSchema={'type': 'object', 'required': ['obsolete']}, targetSchemaText='{"type":"object","required":["obsolete"]}')
        self.assert_exports(project, {}, {'name': 'current'})

    def test_schema_literal_references_are_preserved_in_archives(self):
        project = self.project([dict(target='literal', constant='${input.missing}')])
        project['tasks'][0]['activities'][1]['config']['targetSchema'] = {'type': 'object', 'properties': {'literal': {'enum': ['${input.missing}']}}}
        self.assert_exports(project, {}, {'literal': '${input.missing}'})

    def test_json_parse_and_render_match_studio_shapes_and_policies(self):
        project = self.project()
        task = project['tasks'][0]
        task['activities'].insert(1, dict(id='Parse',name='Parse',type='json',config={'operation':'parse','jsonString':'{"name":"old","name":"new","count":2}', 'duplicateKeyPolicy':'First wins'}))
        task['transitions'] = [dict(id='a',source='Start',target='Parse'),dict(id='b',source='Parse',target='End')]
        self.assert_exports(project, {}, {'name':'old','count':2})
        task['activities'][1] = dict(id='Render',name='Render',type='json',config={'operation':'render','prettyPrint':False,'inputMappings':{'name':'"mapped"','count':'2'}})
        task['transitions'] = [dict(id='a',source='Start',target='Render'),dict(id='b',source='Render',target='End')]
        self.assert_exports(project, {'unmapped':'ignored'}, {'content':'{"name":"mapped","count":2}','jsonString':'{"name":"mapped","count":2}'})

    def test_contract_failure_is_enforced_by_standalone_archives(self):
        project = self.project([dict(target='rows', source='${input.rows}')])
        project['tasks'][0]['activities'][1]['config']['targetSchema'] = {'type': 'object', 'properties': {'rows': {'type': 'array', 'minItems': 1, 'items': {'type': 'integer', 'minimum': 1}}}}
        for compiler in (raw_python_files, engine_python_files):
            files = compiler(project, {'local': []})
            with tempfile.TemporaryDirectory() as directory:
                for name, body in files.items():
                    path = Path(directory) / name; path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(body)
                command = [sys.executable, 'run.py'] if compiler is raw_python_files else [sys.executable, '-m', 'application.main']
                run = subprocess.run([*command, '--task', 'main', '--input', '{"rows":[]}'], cwd=directory, capture_output=True, text=True, timeout=30)
                self.assertNotEqual(run.returncode, 0)
                self.assertIn('minItems', run.stderr)

    def test_project_custom_functions_in_mapper_and_all_activity_inputs(self):
        definitions = [dict(id='normalize', name='normalize', parameters=['value'], expression='upperCase(trim($value))'),
                       dict(id='label', name='label', parameters=['value'], expression='concat(custom:normalize($value), "!")')]
        rules = [dict(target='rows', operator='for-each', source='${input.rows}'),
                 dict(target='rows.name', source='custom:label(${input.rows.name})'),
                 dict(target='literal', operator='if', condition='${input.text} = "${input.missing}"', source='"kept"')]
        project = self.project(rules)
        project['custom_functions'] = definitions
        self.assert_exports(project, {'rows': [{'name': '  ada  '}], 'text': '${input.missing}'},
                            {'rows': [{'name': 'ADA!'}], 'literal': 'kept'})
        project = self.project(input_mappings={'result.name': 'custom:label(${input.name})'})
        project['custom_functions'] = definitions
        self.assert_exports(project, {'name': '  ada  '}, {'name': 'ADA!'})

    def test_loops_nested_children_independent_copies_and_blank_duplicate(self):
        rules = [dict(target='rows', operator='for-each', source='${input.rows}'),
                 dict(target='rows.name', source='${input.rows.name}', targetType='string'),
                 dict(target='rows.items', operator='for-each', source='${input.rows.items}'),
                 dict(target='rows.items.value', source='${input.rows.items.value}'),
                 dict(target='rows', operator='for-each', source='${input.other}', occurrenceId='copy'),
                 dict(target='rows.name', source='${input.other.name}', occurrenceId='copy'),
                 dict(target='rows', operator='for-each', source='', occurrenceId='empty')]
        payload = {'rows': [{'name': 'A', 'items': [{'value': 1}, {'value': 2}]}], 'other': [{'name': 'B'}]}
        self.assert_exports(self.project(rules), payload, {'rows': [payload['rows'][0], {'name': 'B'}]})

    def test_nested_for_each_uses_the_group_members_and_keeps_the_group_context(self):
        rules = [dict(target='groups', operator='for-each-group', source='${input.rows}', groupBy='region'),
                 dict(target='groups.region', source='${input.rows.region}'),
                 dict(target='groups.members', operator='for-each', source='current-group()'),
                 dict(target='groups.members.code', source='${input.rows.code}'),
                 dict(target='groups.members.groupSize', source='count(current-group())')]
        payload = {'rows': [{'region': 'West', 'code': 'PHX'}, {'region': 'East', 'code': 'JFK'}, {'region': 'West', 'code': 'LAX'}]}
        expected = {'groups': [
            {'region': 'West', 'members': [{'code': 'PHX', 'groupSize': 2}, {'code': 'LAX', 'groupSize': 2}]},
            {'region': 'East', 'members': [{'code': 'JFK', 'groupSize': 1}]},
        ]}
        project = self.project(rules)
        self.assert_studio(project, payload, expected)
        self.assert_exports(project, payload, expected)

    def test_empty_and_configured_copies_preserve_direct_and_nested_mappings(self):
        rules = [dict(target='airports', source='${input.primary}'),
                 dict(target='airports', operator='for-each', source='', occurrenceId='empty', duplicateOf='primary'),
                 dict(target='airports', operator='for-each', source='${input.extra}', occurrenceId='extra', duplicateOf='primary'),
                 dict(target='airports.terminals', operator='for-each', source='${input.extra.terminals}', occurrenceId='terminals',
                      duplicateOf='extra', parentOccurrenceId='extra'),
                 dict(target='airports.code', source='${input.extra.code}', occurrenceId='extra')]
        payload = {'primary': {'code': 'PHX'}, 'extra': [{'code': 'LAX', 'terminals': ['A', 'B']}]}
        self.assert_exports(self.project(rules[:2]), payload, {'airports': payload['primary']})
        self.assert_exports(self.project(rules), payload, {'airports': [payload['primary'], *payload['extra']]})

    def test_new_functions_conditions_grouping_and_activity_references(self):
        rules = [dict(target=target, source=source) for target, source in [
            ('add', 'add(${input.n}, 2)'), ('subtract', 'subtract(${input.n}, 2)'),
            ('multiply', 'multiply(${input.n}, 2)'), ('divide', 'divide(${input.n}, 2)'),
            ('mod', 'mod(${input.n}, 3)'), ('floor', 'floor(1.9)'),
            ('eq', 'equal(${input.n}, 8)'), ('ne', 'notEqual(${input.n}, 3)'),
            ('gt', 'greaterThan(${input.n}, 3)'), ('lt', 'lessThan(3, ${input.n})'),
            ('ge', 'greaterOrEqual(${input.n}, 8)'), ('le', 'lessOrEqual(${input.n}, 8)'),
            ('group', 'group(${input.rows}, "name")'), ('top', 'top(${input.numbers}, 2)'),
            ('escaped', "'can\\'t'"), ('alias', '${Start.n}'), ('legacy', '${activities.Start.output.n}'), ('scientific', 'add(1e2, .5)')]]
        rules.extend([dict(target='conditional', operator='if', condition='greaterThan(${input.n}, 3)', source='"yes"'),
                      dict(target='choice', operator='choose', whens=[dict(condition='${input.n} > 3', source='add(${input.n}, 2)')], otherwise='"low"'),
                      dict(target='fallback', operator='when-otherwise', condition='false', source='"unused"', otherwise='add(${input.n}, 2)'),
                      dict(target='groups', operator='for-each-group', source='${input.rows}', groupBy='name'),
                      dict(target='groups.name', source='${input.rows.name}')])
        payload = {'n': 8, 'rows': [{'name': 'A'}, {'name': 'A'}, {'name': 'B'}], 'numbers': [2, 9, 4]}
        expected = {'add': 10, 'subtract': 6, 'multiply': 16, 'divide': 4, 'mod': 2, 'floor': 1,
                    'eq': True, 'ne': True, 'gt': True, 'lt': True, 'ge': True, 'le': True,
                    'group': [[{'name': 'A'}, {'name': 'A'}], [{'name': 'B'}]], 'top': [9, 4],
                    'escaped': "can't", 'alias': 8, 'legacy': 8, 'conditional': 'yes', 'choice': 10,
                    'fallback': 10, 'groups': [{'name': 'A'}, {'name': 'B'}], 'scientific': 100.5}
        self.assert_exports(self.project(rules), payload, expected)

    def test_all_activity_input_conditions_and_loop_children(self):
        entries = {'result.rows': {'$rule': 'for-each', 'source': '${input.rows}'},
                   'result.rows.name': '${input.rows.name}',
                   'result.rows.tag': {'$rule': 'if', 'condition': 'equal(${input.rows.name}, "A")', 'source': '"matched"'},
                   'result.rows.items': {'$rule': 'for-each', 'source': '${input.rows.items}'},
                   'result.rows.items.value': '${input.rows.items.value}',
                   'result.choice': {'$rule': 'choose', 'whens': [{'condition': '${input.n} > 3', 'source': 'add(${input.n}, 2)'}], 'otherwise': '"low"'},
                   'result.literal': "'test'"}
        payload = {'n': 8, 'rows': [{'name': 'A', 'items': [{'value': 1}]}, {'name': 'B', 'items': []}]}
        self.assert_exports(self.project(input_mappings=entries), payload,
                            {'rows': [{'name': 'A', 'tag': 'matched', 'items': [{'value': 1}]}, {'name': 'B', 'items': []}], 'choice': 10, 'literal': 'test'})

    def test_plain_input_quotes_are_editor_syntax_not_output_characters(self):
        self.assert_exports(self.project(input_mappings={'result.text': "'test'"}), {}, {'text': 'test'})
        self.assert_exports(self.project([dict(target='literal',constant='${input.missing}',targetType='string')]), {}, {'literal': '${input.missing}'})

    def test_input_leaf_loops_grouping_and_current_element_alias(self):
        entries = {'result.values': {'$rule': 'for-each', 'source': '${input.numbers}'},
                   'result.groups': {'$rule': 'for-each-group', 'source': '${input.rows}', 'groupBy': 'name'},
                   'result.records': {'$rule': 'for-each', 'source': '${input.rows}'},
                   'result.records.name': '${vars.current.name}'}
        payload = {'numbers': [1, 2], 'rows': [{'name': 'A'}, {'name': 'A'}, {'name': 'B'}]}
        self.assert_exports(self.project(input_mappings=entries), payload,
                            {'values': [1, 2], 'groups': [{'key': 'A', 'items': payload['rows'][:2]}, {'key': 'B', 'items': payload['rows'][2:]}], 'records': payload['rows']})

    def test_invalid_mappings_are_rejected_by_archive_download_api(self):
        from fastapi.testclient import TestClient
        from app.main import app
        import uuid
        project = self.project([dict(target='name', targetType='string', source='unquoted')])
        project['id'] = 'archive-validation-' + uuid.uuid4().hex
        project.update(properties={'local': []}, active_environment='local', schemas=[])
        client = TestClient(app)
        created = client.post('/api/projects', json=project)
        self.assertEqual(created.status_code, 200, created.text)
        try:
            for archive in ('python-direct', 'python-engine', 'python'):
                with self.subTest(archive=archive):
                    response = client.get(f'/api/projects/{project["id"]}/package?target=on-prem&environments=local&starters=main&archive={archive}')
                    self.assertEqual(response.status_code, 400, response.text)
                    self.assertIn('string literals require', response.json()['detail'])
        finally:
            client.delete(f'/api/projects/{project["id"]}')

    def test_invalid_typed_literals_and_conditions_are_rejected_by_both_compilers(self):
        invalid = [dict(target='name', targetType='string', source='unquoted'),
                   dict(target='name', targetType='string', source='123'),
                   dict(target='amount', targetType='number', source='"123"'),
                   dict(target='count', targetType='integer', constant='123'),
                   dict(target='name', targetType='string', source='"unfinished'),
                   dict(target='name', source='unknownFunction(${input.value})'),
                   dict(target='name', source='upperCase(${input.value}'),
                   dict(target='name', operator='if', condition='', source='"value"'),
                   dict(target='name', operator='choose', whens=[], otherwise='"value"'),
                   dict(target='name', targetType='string', operator='choose', whens=[dict(condition='true', source='unquoted')])]
        for compiler in (raw_python_files, engine_python_files):
            for rule in invalid:
                with self.subTest(archive=compiler.__name__, rule=rule):
                    with self.assertRaisesRegex(ValueError, 'Invalid input mappings'):
                        compiler(self.project([rule]), {'local': []})

    def test_schema_types_override_stale_rule_types_in_export_validation(self):
        project = self.project([dict(target='name', source='123', targetType='number')])
        project['tasks'][0]['activities'][1]['config']['targetSchema'] = {'type': 'object', 'properties': {'name': {'type': 'string'}}}
        for compiler in (raw_python_files, engine_python_files):
            with self.subTest(archive=compiler.__name__):
                with self.assertRaisesRegex(ValueError, 'string literals require'):
                    compiler(project, {'local': []})

    def test_generic_input_type_metadata_is_enforced_at_export(self):
        project = self.project(input_mappings={'result.text': 'unquoted'})
        project['tasks'][0]['activities'][-1]['config']['inputMappingTypes'] = {'result.text': 'string'}
        for compiler in (raw_python_files, engine_python_files):
            with self.subTest(archive=compiler.__name__):
                with self.assertRaisesRegex(ValueError, 'string literals require'):
                    compiler(project, {'local': []})

    def test_named_xsd_types_are_used_for_literal_validation(self):
        xsd = '''<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema">
          <xs:element name="Root" type="RootType"/>
          <xs:complexType name="RootType"><xs:sequence><xs:element name="name" type="xs:string"/></xs:sequence></xs:complexType>
        </xs:schema>'''
        project = self.project([dict(target='Root.name', source='123')])
        project['tasks'][0]['activities'][1]['config']['targetSchemaText'] = xsd
        for compiler in (raw_python_files, engine_python_files):
            with self.subTest(archive=compiler.__name__):
                with self.assertRaisesRegex(ValueError, 'Root.name: string literals require'):
                    compiler(project, {'local': []})

    def test_named_xsd_repeating_fields_and_absent_optional_structures_execute(self):
        xsd = '''<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema">
          <xs:element name="Root" type="RootType"/>
          <xs:complexType name="RootType"><xs:sequence>
            <xs:element name="rows" type="RowType" minOccurs="0" maxOccurs="unbounded"/>
            <xs:element name="optional" type="RowType" minOccurs="0"/>
          </xs:sequence></xs:complexType>
          <xs:complexType name="RowType"><xs:sequence>
            <xs:element name="name" type="xs:string"/>
            <xs:element name="amount" type="xs:decimal" minOccurs="0"/>
          </xs:sequence></xs:complexType>
        </xs:schema>'''
        rules = [dict(target='Root.rows', operator='for-each', source='${input.rows}'),
                 dict(target='Root.rows.name', source='${input.rows.name}'),
                 dict(target='Root.rows.amount', source='${input.rows.amount}')]
        project = self.project(rules)
        project['tasks'][0]['activities'][1]['config']['targetSchemaText'] = xsd
        payload = {'rows': [{'name': 'A', 'amount': 12.5}, {'name': 'B'}]}
        self.assert_exports(project, payload, {'Root': payload})
        from app.mapper import validate_output
        self.assertEqual(validate_output({'Root': {'rows': []}}, xsd), [])
        self.assertTrue(validate_output({'Root': {'rows': [{'name': 123}]}}, xsd))
        self.assertTrue(validate_output({'Root': {'rows': [{}]}}, xsd))

    def test_selected_xsd_accepts_direct_mapping_of_one_repeating_element(self):
        from app.mapper import validate_output

        xsd = '''<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema">
          <xs:element name="airports"><xs:complexType><xs:sequence>
            <xs:element name="airportlist" minOccurs="1" maxOccurs="2">
              <xs:complexType><xs:sequence><xs:element name="code" type="xs:string"/></xs:sequence></xs:complexType>
            </xs:element>
          </xs:sequence></xs:complexType></xs:element>
        </xs:schema>'''
        project = self.project([dict(target='airports.airportlist', source='${input.airportlist}')])
        project['schemas'] = [dict(id='contract', name='airports.xsd', content=xsd)]
        project['tasks'][0]['activities'][1]['config']['targetSchemaId'] = 'contract'
        airport = {'code': 'PHX'}
        payload = {'airportlist': airport}
        expected = {'airports': payload}

        self.assert_studio(project, payload, expected)
        self.assert_exports(project, payload, expected)
        self.assertEqual(validate_output({'airports': {'airportlist': [airport, airport]}}, xsd), [])
        for invalid in ([], [airport] * 3, {'code': 123}):
            with self.subTest(value=invalid):
                self.assertTrue(validate_output({'airports': {'airportlist': invalid}}, xsd))

    def test_local_json_refs_enforce_export_literal_types(self):
        project = self.project([dict(target='person.name', source='123')])
        schema = {'type':'object','properties':{'person':{'$ref':'#/$defs/person'}},'$defs':{'person':{'type':'object','properties':{'name':{'type':['string','null']}}}}}
        project['tasks'][0]['activities'][1]['config']['targetSchema'] = schema
        for compiler in (raw_python_files, engine_python_files):
            with self.subTest(archive=compiler.__name__), self.assertRaisesRegex(ValueError, 'string literals require'):
                compiler(project, {'local': []})
        project['tasks'][0]['activities'][1]['config']['mappings'][0]['source'] = '"Ada"'
        self.assert_exports(project, {}, {'person': {'name': 'Ada'}})

    def test_generic_literal_types_and_quoted_references_survive_export(self):
        project = self.project(input_mappings={'result.text': "'${input.missing}'", 'result.number':'-1.25e2', 'result.enabled':'false', 'result.items':'[1,2]', 'result.object':'{"text":"${input.missing}"}'})
        self.assert_exports(project, {}, {'text':'${input.missing}', 'number':-125.0,'enabled':False,'items':[1,2], 'object':{'text':'${input.missing}'}})
