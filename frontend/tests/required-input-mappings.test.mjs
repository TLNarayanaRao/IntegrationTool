import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';
import ts from 'typescript';

const source = await readFile(new URL('../src/requiredInputMappings.ts', import.meta.url), 'utf8');
const compiled = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.ESNext } }).outputText;
const { missingRequiredInputs: findMissing } = await import('data:text/javascript;base64,' + Buffer.from(compiled).toString('base64'));
const missingRequiredInputs = (...args) => findMissing(...args).map(({ path }) => path);
const required = (path, repeating = false) => ({ path, required: true, repeating });

test('reports unmapped, whitespace-only and disabled required inputs while accepting configured and falsy values', () => {
  const fields = ['file.path', 'flag', 'count', 'text', 'disabled', 'empty', 'optional.required', 'synthetic.required']
    .map(path => required(path)).concat([{ path: 'optional' }]);
  const rules = [
    { target: 'flag', constant: false },
    { target: 'count', constant: 0 },
    { target: 'text', constant: '' },
    { target: 'disabled', source: '${last}', enabled: false },
    { target: 'empty', source: '  ' },
  ];
  assert.deepEqual(missingRequiredInputs(fields, rules, { file: { path: '/input.xml' } }), ['disabled', 'empty', 'synthetic.required']);
});

test('checks required children within a mapped optional branch or literal object and defers dynamic payloads', () => {
  const fields = [required('order'), required('order.id'), required('order.delivery.street'), { path: 'order.delivery' }, { path: 'order.delivery.instructions' }];
  assert.deepEqual(missingRequiredInputs(fields, []), ['order.id']);
  assert.deepEqual(missingRequiredInputs(fields, [{ target: 'order.id', source: '"A"' }]), []);
  assert.deepEqual(missingRequiredInputs(fields, [{ target: 'order', source: '{"id":"A","delivery":{}}' }]), ['order.delivery.street']);
  assert.deepEqual(missingRequiredInputs(fields, [{ target: 'order', source: '${last.order}', operator: 'copy-of' }]), []);
  assert.deepEqual(missingRequiredInputs(fields, [{ target: 'order.delivery.instructions', source: '"Ring bell"' }]), ['order.id', 'order.delivery.street']);
});

test('checks required repeating children independently in configured loops and ignores blank duplicate placeholders', () => {
  const fields = [required('records', true), required('records.id'), required('records.quantity')];
  const primary = [
    { target: 'records', operator: 'for-each', select: '${last.records}', mapChildren: true },
    { target: 'records.id', source: '${last.records.id}' },
    { target: 'records.quantity', constant: 0 },
  ];
  const duplicate = { target: 'records', operator: 'for-each', occurrenceId: 'copy', duplicateOf: 'primary', mapChildren: true };
  assert.deepEqual(missingRequiredInputs(fields, [...primary, duplicate]), []);
  assert.deepEqual(findMissing(fields, [...primary, { ...duplicate, source: '${input.records}' },
    { target: 'records.quantity', occurrenceId: 'copy', constant: 5 }]), [
    { path: 'records (duplicate 1).id', target: { path: 'records.id', occurrenceId: 'copy' } }
  ]);
  assert.deepEqual(missingRequiredInputs(fields, [{ target: 'records', source: '[{"id":"A","quantity":0},{"id":"B"}]' }]), ['records[2].quantity']);
});
