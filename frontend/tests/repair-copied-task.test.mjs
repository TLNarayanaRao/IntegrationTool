import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';
import ts from 'typescript';
const source = await readFile(new URL('../src/repairCopiedTask.ts', import.meta.url), 'utf8');
const compiled = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.ESNext } }).outputText;
const { repairCopiedTask } = await import(`data:text/javascript;base64,${Buffer.from(compiled).toString('base64')}`);
const activity = id => ({ id, name: id, config: {} });
test('repairs cross-activity inputs, transitions, and group references', () => {
  const source = {
    activities: [activity('Parser-Copy'), { ...activity('Confirm-Copy'), config: { inputMappings: {
      handle: '${Parser.ackId}', legacy: '${activities.Parser.output.body}',
      nested: { expression: 'concat(${Parser.name}, "ok")' }, literal: 'Parser',
      external: '${tasks.original.activities.Parser.output.body}', property: '${properties.Parser}',
    } } }],
    transitions: [{ source: 'Parser-Copy', target: 'Confirm-Copy', condition: '${Parser.count} > 0' }],
    groups: [{ member_activity_ids: ['Parser-Copy'], config: { collection: '${Parser.items}' } }],
  };
  const fixed = repairCopiedTask(source);
  const mappings = fixed.activities[1].config.inputMappings;
  assert.equal(mappings.handle, '${Parser-Copy.ackId}');
  assert.equal(mappings.legacy, '${activities.Parser-Copy.output.body}');
  assert.equal(mappings.nested.expression, 'concat(${Parser-Copy.name}, "ok")');
  assert.equal(mappings.literal, 'Parser');
  assert.equal(mappings.external, '${tasks.original.activities.Parser.output.body}');
  assert.equal(mappings.property, '${properties.Parser}');
  assert.equal(fixed.transitions[0].condition, '${Parser-Copy.count} > 0');
  assert.equal(fixed.groups[0].config.collection, '${Parser-Copy.items}');
  assert.equal(source.activities[1].config.inputMappings.handle, '${Parser.ackId}');
  assert.deepEqual(repairCopiedTask(fixed), fixed);
});
test('preserves valid references and refuses ambiguous copied targets', () => {
  for (const ids of [['Parser', 'Parser-Copy'], ['Parser-Copy', 'Parser-Copy-2']]) {
    const fixed = repairCopiedTask({ activities: [...ids.map(activity), { ...activity('Log'), config: { message: '${Parser.body}' } }] });
    assert.equal(fixed.activities.at(-1).config.message, '${Parser.body}');
  }
});
test('repairs repeated-copy suffixes without changing names or graph identity', () => {
  const fixed = repairCopiedTask({ activities: [activity('Parser-Copy-Copy'), { ...activity('Log-Copy-Copy'), config: { message: '${Parser-Copy.body}', original: '${Parser.body}' } }] });
  assert.equal(fixed.activities[1].config.message, '${Parser-Copy-Copy.body}');
  assert.equal(fixed.activities[1].config.original, '${Parser-Copy-Copy.body}');
  assert.equal(fixed.activities[0].name, 'Parser-Copy-Copy');
});
