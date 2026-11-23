import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';
import ts from 'typescript';

const source = await readFile(new URL('../src/inputTargetNavigation.ts', import.meta.url), 'utf8');
const compiled = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.ESNext } }).outputText;
const { filterInputTargets, locateInputTarget } = await import('data:text/javascript;base64,' + Buffer.from(compiled).toString('base64'));
const row = (key, path, label, ancestors = [], extra = {}) => ({
  kind: 'field', key, field: { path, name: path.split('.').pop(), label }, ancestors, ...extra,
});
const schema = [
  row('primary:orders:loop', 'orders', 'Orders', [], { kind: 'loop' }),
  row('primary:orders', 'orders', 'Orders', ['primary:orders:loop'], { loopKey: 'primary:orders:loop' }),
  row('primary:orders.id', 'orders.id', 'Order reference', ['primary:orders:loop', 'primary:orders']),
  row('copy:orders', 'orders', 'Orders', [], { occurrenceId: 'copy' }),
  row('copy:orders.id', 'orders.id', 'Order reference', ['copy:orders'], { occurrenceId: 'copy' }),
  row('primary:customers.id', 'customers.id', 'Customer reference'),
];

test('searches labels and paths while retaining ancestor rows and counting only field matches', () => {
  const result = filterInputTargets(schema, 'ORDERS reference');
  assert.deepEqual(result.rows.map(item => item.key), schema.slice(0, 5).map(item => item.key));
  assert.equal(result.count, 2);
  assert.deepEqual(filterInputTargets(schema, 'missing'), { rows: [], count: 0 });
  assert.equal(filterInputTargets(schema, '').rows, schema);
});

test('opens the matching occurrence, its loop source, or the closest visible parent for a hidden child', () => {
  assert.equal(locateInputTarget(schema, { path: 'orders.id', occurrenceId: 'copy' })?.key, 'copy:orders.id');
  assert.equal(locateInputTarget(schema, { path: 'orders' })?.key, 'primary:orders:loop');
  assert.equal(locateInputTarget(schema, { path: 'orders.id.hidden', occurrenceId: 'copy' })?.key, 'copy:orders.id');
  assert.equal(locateInputTarget(schema, { path: 'orders.id', occurrenceId: 'deleted' }), undefined);
});
