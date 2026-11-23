import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';
import ts from 'typescript';

const source = await readFile(new URL('../src/groupDesigner.ts', import.meta.url), 'utf8');
const compiled = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.ESNext } }).outputText;
const { groupCatalog, groupTypes, groupCategories, describeGroupWiring } = await import(
  'data:text/javascript;base64,' + Buffer.from(compiled).toString('base64')
);

test('every group type has distinct picker wording and setup guidance', () => {
  assert.equal(groupTypes.length, 15);
  assert.equal(new Set(groupTypes.map(type => groupCatalog[type].label)).size, groupTypes.length);
  assert.ok(groupTypes.every(type => groupCategories.includes(groupCatalog[type].category) && groupCatalog[type].help));
});

test('route previews identify the actual entry activities and shared continuation', () => {
  const edges = [
    { source: 'start', target: 'one' }, { source: 'start', target: 'two' },
    { source: 'one', target: 'after' }, { source: 'two', target: 'after' },
  ];
  for (const type of ['scatter_gather', 'first_successful']) {
    assert.deepEqual(describeGroupWiring(type, new Set(['one', 'two']), edges),
      { entryIds: ['one', 'two'], nextIds: ['after'], issues: [] });
    assert.match(describeGroupWiring(type, new Set(['one', 'two']), [...edges, {source: 'one', target: 'two'}]).issues.join(), /Keep routes separate/);
    assert.match(describeGroupWiring(type, new Set(['one', 'two']), [...edges, {source: 'one', target: 'end'}]).issues.join(), /same activity outside/);
  }
  assert.deepEqual(describeGroupWiring('scope', new Set(['one']), edges).entryIds, ['one']);
});
