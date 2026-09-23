import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';
import ts from 'typescript';
const source = await readFile(new URL('../src/mappingCompletion.ts', import.meta.url), 'utf8');
const compiled = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.ESNext } }).outputText;
const { completeMapping } = await import(`data:text/javascript;base64,${Buffer.from(compiled).toString('base64')}`);
test('completes plain, wrapped and XML attribute paths', () => {
  assert.equal(completeMapping('Order.customer.na', '', '${Order.customer.name}'), '${Order.customer.name}');
  assert.equal(completeMapping('${Order.customer.na', '}', '${Order.customer.name}'), '${Order.customer.name}');
  assert.equal(completeMapping('Order.@i', '', '${Order.@id}'), '${Order.@id}');
});
test('preserves surrounding function arguments and nested mapping expressions', () => {
  assert.equal(completeMapping('concat(${Order.na', '}, "!")', '${Order.name}'), 'concat(${Order.name}, "!")');
  assert.equal(completeMapping('upper', '', 'upperCase($value)'), 'upperCase($value)');
});
