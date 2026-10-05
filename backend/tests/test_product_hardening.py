import asyncio
import io
import json
import tempfile
import unittest
import warnings
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app import project_import, store
from app.mapper import _coerce, execute, validate_output, flatten_schema, validate_mapping_rules
from app.models import Activity, Project
from app.runtime import WorkflowRuntime, MinaFault
from app.sftp import open_connection


class ProductHardeningTests(unittest.TestCase):
    def archive(self, content, duplicate=False):
        output = io.BytesIO()
        with warnings.catch_warnings(), zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as archive:
            warnings.simplefilter('ignore')
            archive.writestr('manifest.json', json.dumps({'format': 'mina-project'}))
            archive.writestr('project.json', content)
            if duplicate: archive.writestr('project.json', content)
        return output.getvalue()

    def test_project_import_limits_compressed_and_expanded_input(self):
        with patch.object(project_import, 'MAX_IMPORT_BYTES', 1024):
            self.assertEqual(project_import.project_payload(self.archive(b'{}')), b'{}')
            for raw in (b'X' * 1025, self.archive(b'X' * 2048)):
                with self.assertRaisesRegex(ValueError, 'size limit'): project_import.project_payload(raw)
        with self.assertRaisesRegex(ValueError, 'duplicate'): project_import.project_payload(self.archive(b'{}', duplicate=True))

    def test_invalid_child_id_does_not_modify_saved_project(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(store, 'PROJECTS_DIR', Path(folder) / 'projects'), patch.object(store, 'LEGACY_DB', Path(folder) / 'missing.db'):
            project = Project(id='saved', name='Original')
            store.save_project(project)
            project.name = 'Changed'
            project.tasks[0].id = '../outside'
            with self.assertRaises(ValueError): store.save_project(project)
            self.assertEqual(store.get_project('saved').name, 'Original')

    def test_concurrent_saves_and_reads_preserve_a_consistent_project(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(store, 'PROJECTS_DIR', Path(folder) / 'projects'), patch.object(store, 'LEGACY_DB', Path(folder) / 'missing.db'):
            def save(version):
                project = Project(id='saved', name=version)
                project.tasks[0].name = version
                store.save_project(project)
                result = store.get_project('saved')
                self.assertEqual(result.name, result.tasks[0].name)
            with ThreadPoolExecutor(max_workers=8) as executor: list(executor.map(save, [str(index) for index in range(40)]))
            self.assertFalse(list(Path(folder).rglob('*.tmp')))

    def test_sftp_settings_and_failures_are_consistent(self):
        client = MagicMock()
        reject, accept = object(), object()
        module = SimpleNamespace(SSHClient=lambda: client, RejectPolicy=lambda: reject, AutoAddPolicy=lambda: accept)
        with patch.dict('sys.modules', paramiko=module):
            open_connection({'host': 'host', 'knownHostsFile': 'known', 'privateKeyFile': 'key', 'privateKeyPassphrase': 'pass', 'timeoutSeconds': 17, 'useSshAgent': 'false'})
            client.load_host_keys.assert_called_once_with('known')
            client.set_missing_host_key_policy.assert_called_with(reject)
            args = client.connect.call_args.kwargs
            self.assertEqual((args['key_filename'], args['passphrase'], args['timeout']), ('key', 'pass', 17))
            self.assertFalse(args['allow_agent'])
            open_connection({'host': 'host', 'strictHostKeyChecking': True, 'verifyHostKey': 'false'})
            client.set_missing_host_key_policy.assert_called_with(accept)
            client.open_sftp.side_effect = RuntimeError('channel failed')
            with self.assertRaisesRegex(RuntimeError, 'channel failed'): open_connection({'host': 'host'})
            client.close.assert_called_once()

    def test_safe_integer_coercion_does_not_silently_truncate(self):
        self.assertEqual(_coerce(5.0, 'integer', 'safe'), 5)
        for value in (5.9, float('inf'), float('nan')):
            with self.assertRaisesRegex(ValueError, 'losing precision'): _coerce(value, 'integer', 'safe')

    def test_json_contract_constraints_local_refs_and_composition(self):
        schema = {'type': 'object', '$defs': {'line': {'type': 'object', 'required': ['code', 'quantity'], 'additionalProperties': False,
                  'properties': {'code': {'enum': ['A', 'B']}, 'quantity': {'type': 'integer', 'minimum': 1, 'maximum': 9}}}},
                  'properties': {'rows': {'type': 'array', 'minItems': 1, 'maxItems': 2, 'uniqueItems': True, 'items': {'$ref': '#/$defs/line'}},
                                 'name': {'type': ['string', 'null'], 'minLength': 2}}, 'required': ['rows']}
        valid = {'rows': [{'code': 'A', 'quantity': 2}], 'name': None}
        self.assertEqual(validate_output(valid, schema), [])
        self.assertTrue(validate_output({'rows': []}, schema))
        self.assertTrue(validate_output({'rows': [{'code': 'C', 'quantity': 0, 'extra': True}]}, schema))
        self.assertTrue(validate_output({'rows': valid['rows'] * 2, 'name': 'x'}, schema))
        self.assertEqual(validate_output([True, 1], {'type': 'array', 'uniqueItems': True}), [])
        self.assertTrue(validate_output([1, 1.0], {'type': 'array', 'uniqueItems': True}))
        self.assertTrue(validate_output(True, {'enum': [1]}))
        self.assertEqual(validate_output(0.3, {'type': 'number', 'multipleOf': 0.1}), [])
        self.assertTrue(validate_output(3, {'oneOf': [{'type': 'integer'}, {'minimum': 1}]}))
        self.assertTrue(validate_output(3, {'not': {'const': 3}}))
        self.assertTrue(validate_output(3, {'$ref': 'https://example.com/schema'}))
        self.assertTrue(validate_output(3, {'$ref': '#'}))

    def test_boundary_mapping_is_evaluated_once(self):
        runtime = WorkflowRuntime()
        context = {'input': {}, 'last': {}, 'vars': {}, 'properties': {}, 'resources': {}, 'activities': {}}
        for kind, target in (('start', 'payload'), ('end', 'result')):
            with patch('app.runtime.apply_function', return_value='unique') as function:
                activity = Activity(id=kind, name=kind, type=kind, config={'inputMappings': {target + '.id': 'uuid()'}})
                result = asyncio.run(runtime.execute(activity, context))
                self.assertEqual(result, {'id': 'unique'})
                function.assert_called_once()

    def test_json_activity_enforces_nested_contracts(self):
        runtime = WorkflowRuntime()
        with self.assertRaises(MinaFault):
            runtime.validate_json_if_requested({'rows': ['bad']}, {'validateInput': True, 'schemaText': json.dumps({'type': 'object', 'properties': {'rows': {'type': 'array', 'items': {'type': 'integer'}}}})}, {}, 'validateInput')

    def test_loop_plan_is_reused_without_losing_independent_occurrences(self):
        rules = [{'target': 'rows', 'operator': 'for-each', 'source': '${input.rows}'},
                 {'target': 'rows.items', 'operator': 'for-each', 'source': '${input.rows.items}'},
                 {'target': 'rows.items.value', 'source': '${input.rows.items.value}'},
                 {'target': 'rows', 'operator': 'for-each', 'occurrenceId': 'copy', 'source': '${input.rows}'},
                 {'target': 'rows.name', 'occurrenceId': 'copy', 'source': '"copy"'}]
        payload = {'rows': [{'items': [{'value': index}]} for index in range(100)]}
        result = execute({'input': payload}, rules)
        self.assertEqual(len(result['rows']), 200)
        self.assertEqual(result['rows'][:100], payload['rows'])
        self.assertEqual(result['rows'][100:], [{'name': 'copy'}] * 100)

    def test_xsd_inheritance_and_default_optional_attributes_keep_contract_types(self):
        schema = '<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema"><xs:element name="Root" type="Derived"/><xs:complexType name="Base"><xs:sequence><xs:element name="name" type="xs:string"/></xs:sequence><xs:attribute name="id" type="xs:integer"/><xs:attribute name="code" type="xs:string" use="required"/></xs:complexType><xs:complexType name="Derived"><xs:complexContent><xs:extension base="Base"><xs:sequence><xs:element name="count" type="xs:integer"/></xs:sequence></xs:extension></xs:complexContent></xs:complexType></xs:schema>'
        fields = {field['path']: field for field in flatten_schema(schema)}
        self.assertEqual(set(fields), {'Root.name', 'Root.@id', 'Root.@code', 'Root.count'})
        self.assertFalse(fields['Root.@id']['required']); self.assertTrue(fields['Root.@code']['required'])
        self.assertTrue(validate_mapping_rules([{'target':'Root.name','source':'123'}], schema))
