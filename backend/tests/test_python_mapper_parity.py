"""Run generated archives outside Studio to verify Mapper/Input execution parity."""
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

    def test_grouped_conditions_preserve_literals_in_archives(self):
        expressions = ['${input.text} = "A and B > C"',
                       'not (${input.n} < 3 or ${input.n} >= 9)',
                       'contains(${input.text}, "and B >") and ${input.n} = 5']
        rules = [dict(target=f'value{i}', operator='if', condition=expression, source='"passed"')
                 for i, expression in enumerate(expressions)]
        self.assert_exports(self.project(rules), {'text': 'A and B > C', 'n': 5},
                            {f'value{i}': 'passed' for i in range(len(expressions))})

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
