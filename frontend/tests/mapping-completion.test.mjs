import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';
import ts from 'typescript';
const source = await readFile(new URL('../src/mappingCompletion.ts', import.meta.url), 'utf8');
const compiled = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.ESNext } }).outputText;
const { completeMapping, mappingPathSuggestions } = await import(`data:text/javascript;base64,${Buffer.from(compiled).toString('base64')}`);
test('completes plain, wrapped and XML attribute paths', () => {
  assert.equal(completeMapping('Order.customer.na', '', '${Order.customer.name}'), '${Order.customer.name}');
  assert.equal(completeMapping('${Order.customer.na', '}', '${Order.customer.name}'), '${Order.customer.name}');
  assert.equal(completeMapping('Order.@i', '', '${Order.@id}'), '${Order.@id}');
});
test('preserves surrounding function arguments and nested mapping expressions', () => {
  assert.equal(completeMapping('concat(${Order.na', '}, "!")', '${Order.name}'), 'concat(${Order.name}, "!")');
  assert.equal(completeMapping('upper', '', 'upperCase($value)'), 'upperCase($value)');
});

test('dot in the reported SAP expression suggests schema children', () => {
  const paths = ['IDoc-Parser.SAPIDoc.CUSTOM01.IDOC.ROW.VALUE', 'IDoc-Parser.format'];
  const suggestions = mappingPathSuggestions(paths, '${IDoc-Parser.SAPIDoc.');
  assert.equal(suggestions[0], 'IDoc-Parser.SAPIDoc.CUSTOM01');
  assert.ok(suggestions.includes('IDoc-Parser.SAPIDoc.CUSTOM01.IDOC'));
  assert.ok(!suggestions.includes('IDoc-Parser.format'));
  assert.equal(completeMapping('${IDoc-Parser.SAPIDoc.', '}', '${IDoc-Parser.SAPIDoc.CUSTOM01}'), '${IDoc-Parser.SAPIDoc.CUSTOM01}');
});

test('suggestions support plain paths and paths inside functions without SAP assumptions', () => {
  const paths = ['Read-JSON.customer.address.city', 'Read-JSON.customer.@id'];
  assert.equal(mappingPathSuggestions(paths, 'Read-JSON.customer.')[0], 'Read-JSON.customer.@id');
  assert.ok(mappingPathSuggestions(paths, 'concat(${Read-JSON.customer.address.').includes('Read-JSON.customer.address.city'));
});

test('advanced expression editor is connected to the same autocomplete control', async () => {
  const editor = await readFile(new URL('../src/ActivityEditor.tsx', import.meta.url), 'utf8');
  assert.match(editor, /<MappingExpressionInput label="Advanced mapping expression"[^>]*paths=\{completionPaths\}/);
  assert.doesNotMatch(editor, /<input aria-label="Advanced mapping expression"/);
});
