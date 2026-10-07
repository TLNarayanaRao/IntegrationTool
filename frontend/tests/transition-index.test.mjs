import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';
import vm from 'node:vm';
import ts from 'typescript';

const source = await readFile(new URL('../src/transitionIndex.ts', import.meta.url), 'utf8');
const context = vm.createContext({ exports: {} });
vm.runInContext(ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS } }).outputText, context);
const lanes = context.exports.transitionLanes;

test('branch lanes preserve interleaved source order and center each fan-out', () => {
  const edges = ['a', 'b', 'a', 'c', 'b', 'a'].map((source, id) => ({ source, id }));
  assert.deepEqual(Array.from(lanes(edges)), [-1, -0.5, 0, 0, 0.5, 1]);
  assert.deepEqual(Array.from(lanes([])), []);
});

test('large graphs visit each source a bounded number of times', () => {
  let reads = 0;
  const edges = Array.from({ length: 5000 }, (_, i) => ({ get source() { reads++; return `node-${i % 100}`; } }));
  assert.equal(lanes(edges).length, edges.length);
  assert.ok(reads <= edges.length * 6, `unexpected repeated scans: ${reads}`);
});
