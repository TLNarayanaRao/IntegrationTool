"""Portable document-function bindings and root-removal parity."""
import asyncio
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from app.mapper_binding import generate_binding, reopen_binding
from app.mapper_xml import etree, parse_xml, transform_xml
from app.mapping_documents import FUNCTIONS, json_patch
from app.models import Project
from app.raw_python import mapper_xml_dependencies


def cases():
    document = {'rows': [{'id': 1}, {'id': 2}], 'old': 'remove', 'a/b': {'~': None}}
    patch = [{'op': 'test', 'path': '/rows/0/id', 'value': 1.0},
             {'op': 'add', 'path': '/rows/-', 'value': {'id': 3}},
             {'op': 'copy', 'from': '/rows/0', 'path': '/copied'},
             {'op': 'replace', 'path': '/copied/id', 'value': 10},
             {'op': 'move', 'from': '/rows/1', 'path': '/rows/0'},
             {'op': 'remove', 'path': '/old'}]
    result = [('jsonPatch', document, [patch]),
              ('jsonPatch', document, [[{'op': 'remove', 'path': ''}]]),
              ('jsonPatch', None, [[{'op': 'remove', 'path': ''}, {'op': 'add', 'path': '', 'value': [None, 3]}]]),
              ('jsonPatch', {'a': 1}, [[{'op': 'move', 'from': '/a', 'path': ''}]]),
              ('jsonPointer', document, ['/a~1b/~0', 'fallback']),
              ('jsonPointer', {'café': 9007199254740993}, ['#/caf%C3%A9']),
              ('jsonPointer', document, ['/missing', {'default': True}]),
              ('jsonPointer', {'': 2}, ['/']),
              ('jsonMergePatch', document, [{'old': None, 'rows': [None, 4], 'new': {'empty': None, 'keep': 2}}]),
              ('jsonMergePatch', document, [None]),
              ('jsonMergePatch', {}, [{'tiny': 1e-30, 'negative': -1.23e-10, 'large': 1e20}]),
              ('jsonDiff', {'a/b': 1, '~': [None, 2], 'flag': True}, [{'a/b': 2, '~': [None], 'flag': 1, 'x': None}]),
              ('jsonDiff', True, [1]), ('jsonDiff', 1, [1.0]),
              ('jsonDiff', 1e30, [10**30]),
              ('reconcileRecords', [{'id': 1, 'value': 1e30}], [[{'id': 1, 'value': 10**30}], ['/id']]),
              ('aggregateRecords', [{'id': 'A', 'v': 1e30}], [['/id'], [{'name': op, 'op': op, 'path': '/v'} for op in ('min','max','sum','average')]]),
              ('deduplicateRecords', [{'id': 1}, {'id': 2}, {'id': 1.0}, {}, {'id': None}], [['/id'], 'first']),
              ('deduplicateRecords', [{'id': 1}, {'id': 2}, {'id': 1.0}, {}, {'id': None}], [['/id'], 'last']),
              ('deduplicateRecords', [None, {}, {'id': 1}, None], [['/id']]),
              ('redactKeys', {'Straße': 1, 'ﬃ': 2, 'rows': [None, {'PASSWORD': 'secret'}]}, [['STRASSE', 'FFI', 'password']]),
              ('redactKeys', {'secret': 1}, [['secret'], {'redacted': True}]),
              ('maskText', '12345678', [4]), ('maskText', 'private', [0, '#']),
              ('maskText', 'short', [20]), ('maskText', None, [])]
    left = [{'id': 1, 'org': 'A'}, {'id': 2, 'org': 'B'}, {'id': True, 'org': 'A'}, {'id': None}]
    right = [{'key': 1.0, 'org': 'A'}, {'key': 1, 'org': 'A'}, {'key': 3, 'org': 'C'}]
    for mode in ('inner', 'left', 'right', 'full', 'semi', 'anti'):
        result.append(('joinRecords', left, [right, ['/id', '/org'], ['/key', '/org'], mode]))
    from tests.test_mapping_records import fixture as records_fixture
    payload, metrics, _, _ = records_fixture()
    result.extend([('aggregateRecords', payload['records'], [['/region'], metrics]),
                   ('reconcileRecords', payload['before'], [payload['after'], ['/id']]),
                   ('aggregateRecords', [], [['/id'], [{'name': 'n', 'op': 'count'}]]),
                   ('aggregateRecords', [{'id': 1, 'amount': None}], [['/id'], [{'name': op, 'op': op, 'path': '/amount'} for op in ('sum','average','min','max','count')]]),
                   ('reconcileRecords', [{'id': True}, {'id': 1}], [[{'id': 1.0}, {'id': True}], ['/id']])])
    for values in ([1, 2, 2], [1e-30, 2e-30], [-0.1, 0.2], [1e-308, 2e-308]):
        result.append(('aggregateRecords', [{'id': 'A', 'v': value} for value in values],
                       [['/id'], [{'name': 'mean', 'op': 'average', 'path': '/v'}, {'name': 'sum', 'op': 'sum', 'path': '/v'}]]))
    return result


def fixture():
    root = etree.Element('input'); rules = []; expected = {}
    for i, (name, value, args) in enumerate(cases()):
        field = 'v' + str(i)
        # Text is the boundary representation of JSON inside an XML document.
        etree.SubElement(root, field).text = value if name == 'maskText' and value is not None else json.dumps(value)
        source = 'null' if name == 'maskText' and value is None else '${input.' + field + '}'
        rules.append({'target': 'result.' + field, 'source': source, 'functions': [{'name': name, 'args': args}]})
        expected[field] = FUNCTIONS[name.lower()](value, *args)
    return root, rules, expected


def decode(output, expected):
    actual = {}
    for field, value in expected.items():
        element = output.find(field)
        if element is None and value is None:
            actual[field] = None
        else:
            text = element.text or ''
            actual[field] = text if isinstance(value, str) else json.loads(text)
    return actual


def target_schema(expected):
    return '<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema"><xs:element name="result"><xs:complexType><xs:sequence>' + ''.join(
        '<xs:element name="' + field + '" type="xs:string" minOccurs="0"/>' for field in expected) + '</xs:sequence></xs:complexType></xs:element></xs:schema>'


class MapperDocumentXsltTests(unittest.TestCase):
    def test_generated_binding_round_trip_and_standalone_execution(self):
        root, rules, expected = fixture()
        stylesheet = generate_binding(rules)
        self.assertEqual(parse_xml(stylesheet).get('version'), '3.0')
        self.assertEqual(reopen_binding(stylesheet)['mappings'], rules)
        self.assertEqual(decode(transform_xml(root, stylesheet), expected), expected)
        # Only Saxon is imported by this subprocess: proves no MINA callback,
        # extension function, or external stylesheet is needed for the binding.
        code = """import json,sys
from saxonche import PySaxonProcessor
source, stylesheet = json.load(sys.stdin)
with PySaxonProcessor(license=False) as p:
 e=p.new_xslt30_processor().compile_stylesheet(stylesheet_text=stylesheet)
 sys.stdout.buffer.write(e.transform_to_string(xdm_node=p.parse_xml(xml_text=source)).encode('utf-8'))
"""
        result = subprocess.run([sys.executable, '-I', '-c', code], input=json.dumps([etree.tostring(root, encoding='unicode'), stylesheet]),
                                capture_output=True, text=True, encoding='utf-8', timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(decode(parse_xml(result.stdout), expected), expected)

    def test_nested_expressions_dynamic_arguments_and_pipelines(self):
        rules = [{'target': 'result.v', 'source': 'jsonPointer(jsonPatch(${input.doc}, ${input.patch}), "/name")', 'functions': ['upperCase']},
                 {'target': 'result.array', 'source': 'jsonMergePatch(${input.doc}, {"rows":[null,2]})'},
                 {'target': 'result.masked', 'source': 'maskText(${input.text}, ${input.suffix})'},
                 {'target': 'result.upper', 'source': 'upperCase(jsonPointer(${input.doc}, "/name"))'}]
        root = parse_xml('<input><doc>{"name":"Ada"}</doc><patch>[{"op":"replace","path":"/name","value":"Grace"}]</patch><text>12345678</text><suffix>4</suffix></input>')
        output = transform_xml(root, generate_binding(rules, preferences={'copyNil': True}))
        self.assertEqual(output.findtext('v'), 'GRACE')
        self.assertEqual(output.findtext('masked'), '****5678')
        self.assertEqual(output.findtext('upper'), 'ADA')
        self.assertEqual(json.loads(output.findtext('array')), {'name': 'Ada', 'rows': [None, 2]})
        ordinary = rules + [{'target': 'result.empty', 'source': 'null'}]
        output = transform_xml(root, generate_binding(ordinary, preferences={'implicitExistence': False}))
        self.assertEqual(output.findtext('empty'), '')
        binding = parse_xml(generate_binding([{'target': 'r.v', 'source': 'jsonPointer(${input.doc}, "/name")'}]))
        template = binding.find('{http://www.w3.org/1999/XSL/Transform}template')
        for child in list(template): template.remove(child)
        node = etree.SubElement(template, 'manual')
        etree.SubElement(node, '{http://www.w3.org/1999/XSL/Transform}value-of',
                         select="md:maskText(md:jsonPointer(parse-json('{\"name\":\"12345678\"}'), '/name'), 4)")
        self.assertEqual(transform_xml(root, etree.tostring(binding)).text, '****5678')

    def test_invalid_patches_and_pointer_indices_fail_without_mutating_source(self):
        removed = [{'op': 'remove', 'path': ''}]
        operations = [[{'op': 'test', 'path': '/id', 'value': True}],
                      [{'op': 'move', 'from': '', 'path': '/descendant'}],
                      [{'op': 'replace', 'path': '/missing', 'value': 2}],
                      [{'op': 'add', 'path': '#/id', 'value': 2}],
                      removed + [{'op': 'test', 'path': '', 'value': None}],
                      removed + [{'op': 'remove', 'path': ''}],
                      removed + [{'op': 'replace', 'path': '', 'value': 1}],
                      removed + [{'op': 'add', 'path': '/child', 'value': 1}]]
        root = parse_xml('<input><doc>{"id":1}</doc></input>'); before = etree.tostring(root)
        for patch in operations:
            with self.subTest(patch=patch):
                rule = {'target': 'r.v', 'source': '${input.doc}', 'functions': [{'name': 'jsonPatch', 'args': [patch]}]}
                with self.assertRaises(ValueError): transform_xml(root, generate_binding([rule]))
                self.assertEqual(etree.tostring(root), before)
        for pointer in ('/01', '#/%xx', '/~2'):
            with self.subTest(pointer=pointer), self.assertRaises(ValueError):
                transform_xml(parse_xml('<input><doc>[1]</doc></input>'), generate_binding([
                    {'target': 'r.v', 'source': '${input.doc}', 'functions': [{'name': 'jsonPointer', 'args': [pointer, 2]}]}]))

    def test_existing_version_and_export_dependencies(self):
        self.assertEqual(parse_xml(generate_binding([{'target': 'r.v', 'source': '"old"'}])).get('version'), '2.0')
        manual = '<xsl:stylesheet xmlns:xsl="http://www.w3.org/1999/XSL/Transform" version="3.0"><xsl:template match="/"><result/></xsl:template></xsl:stylesheet>'
        self.assertEqual(reopen_binding(manual), {'xmlStylesheet': manual})
        requirements = mapper_xml_dependencies({'tasks': [{'activities': [{'config': {'xmlStylesheet': manual}}]}]})
        self.assertTrue(any('saxonche' in requirement for requirement in requirements))

    def test_output_expansion_depth_and_invalid_arguments_are_bounded(self):
        large = 'x' * (2 * 1024 * 1024)
        checks = [('redactKeys', {str(i): 1 for i in range(8)}, [[str(i) for i in range(8)], large]),
                  ('reconcileRecords', [{'a': large, 'b': large, 'v': 1}], [[{'a': large, 'b': large, 'v': 2}], ['/a', '/b']]),
                  ('reconcileRecords', [{'id': 1}, {'id': 1.0}], [[], ['/id']]),
                  ('reconcileRecords', [], [[{}], ['/id']]),
                  ('reconcileRecords', [], [[{'id': 1}, {'id': 1.0}], ['/id']]),
                  ('reconcileRecords', [{}], [[], ['/id']]),
                  ('aggregateRecords', [{'id': 1, 'v': True}], [['/id'], [{'name': 'n', 'op': 'sum', 'path': '/v'}]]),
                  ('aggregateRecords', [], [['/id'], [{'name': 'n', 'op': 'unknown'}]]),
                  ('aggregateRecords', [], [['/id'], [{'name': 'n', 'op': 'count', 'path': 'bad'}]]),
                  ('aggregateRecords', [], [['/id'], [{'name': 'n', 'op': 'count'}] * 2]),
                  ('joinRecords', [{'id': 1}] * 8, [[{'id': 1, 'data': large}], ['/id'], ['/id']]),
                  ('joinRecords', [], [[], ['/id'], ['/id', '/org']]),
                  ('jsonPointer', {}, [None]), ('maskText', 'secret', [-1])]
        deep = 1
        for _ in range(130): deep = {'child': deep}
        checks.append(('jsonPointer', deep, ['']))
        for name, value, args in checks:
            with self.subTest(name=name, size=len(json.dumps(value))):
                root = etree.Element('input')
                etree.SubElement(root, 'doc').text = value if name == 'maskText' else json.dumps(value)
                stylesheet = generate_binding([{'target': 'r.v', 'source': '${input.doc}', 'functions': [{'name': name, 'args': args}]}])
                with self.assertRaises(ValueError): transform_xml(root, stylesheet)

    def test_preview_run_debug_and_archives_generated_manual_and_root_removal(self):
        from app.main import mapper_test
        root, rules, expected = fixture()
        schema = target_schema(expected)
        stylesheet = generate_binding(rules, schema)
        tasks = []
        for name, config in [('generated', {'mappings': rules, 'generatedXmlBinding': True}),
                             ('manual', {'xmlStylesheet': stylesheet}),
                             ('native', {'nullPolicy': 'preserve', 'mappings': [{'target': 'removed', 'source': 'jsonPatch(${input.doc}, [{"op":"remove","path":""}])'},
                                                      {'target': 'recreated', 'source': 'jsonPatch(${input.doc}, [{"op":"remove","path":""},{"op":"add","path":"","value":{"new":1}}])'}]}),
                             ('failed', {'mappings': [{'target': 'result.bad', 'source': 'jsonPatch(${input.v0}, [{"op":"test","path":"","value":false}])'}], 'generatedXmlBinding': True})]:
            nodes = [{'id': name+'s', 'type': 'start', 'name': 'Start'}, {'id': name+'m', 'type': 'mapper', 'name': 'Mapper', 'config': {**config, **({'targetSchemaText': schema} if name in ('generated', 'manual') else {}), 'xmlSource': '${input.xml}'}}, {'id': name+'e', 'type': 'end', 'name': 'End'}]
            tasks.append({'id': name, 'name': name, 'kind': 'subtask', 'activities': nodes,
                          'transitions': [{'id': name+str(i), 'source': a['id'], 'target': b['id']} for i, (a,b) in enumerate(zip(nodes,nodes[1:]))]})
        project = Project.model_validate({'id': 'xslt-documents', 'name': 'XSLT-documents', 'tasks': tasks})
        payload = {'xml': etree.tostring(root, encoding='unicode'), 'doc': {'id': 1}}
        preview = mapper_test({'input': payload, 'mappings': rules, 'targetSchemaText': schema, 'options': {'generatedXmlBinding': True, 'xmlSource': '${input.xml}'}})
        self.assertEqual(decode(parse_xml(preview['output']['xmlString']), expected), expected)
        spec = importlib.util.spec_from_file_location('xslt_document_flows', Path(__file__).parents[2] / 'scripts/flow-throughput.py')
        flow = importlib.util.module_from_spec(spec); spec.loader.exec_module(flow)
        async def run(folder):
            for mode in ('run', 'debug', 'python-direct', 'python-engine'):
                executor = flow.Executor(mode, project, str(Path(folder) / (mode + '.log')))
                try:
                    await executor.start()
                    for task in ('generated', 'manual'):
                        try: result = await executor.execute(task, payload)
                        except RuntimeError as error:
                            executor.log.flush() if hasattr(executor, 'log') else None
                            log = Path(folder, mode + '.log')
                            self.fail(f'{task}/{mode}: {error}\n' + (log.read_text(encoding='utf-8')[-6000:] if log.exists() else ''))
                        self.assertEqual(decode(parse_xml(result['xmlString']), expected), expected, (task, mode))
                    self.assertEqual(await executor.execute('native', payload), {'removed': None, 'recreated': {'new': 1}}, mode)
                    with self.assertRaises(RuntimeError): await executor.execute('failed', payload)
                finally: await executor.close()
        with tempfile.TemporaryDirectory() as folder: asyncio.run(run(folder))


if __name__ == '__main__': unittest.main()
