import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';
import ts from 'typescript';

const source = await readFile(new URL('../src/copyTask.ts', import.meta.url), 'utf8');
const compiled = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.ESNext } }).outputText;
const { copyTask } = await import(`data:text/javascript;base64,${Buffer.from(compiled).toString('base64')}`);
const task = {
  id: 'original', name: 'Original', kind: 'subtask',
  activities: [
    { id: 'Idoc-parser', name: 'Idoc-parser', config: { schema: 'schema-1' } },
    { id: 'confirm-message', name: 'confirm-message', config: { handle: '${Idoc-parser.ackId}' } },
    { id: 'log3', name: 'log3', config: { message: '${confirm-message}', resourceId: 'ems' } },
  ],
  transitions: [{ id: 'edge', source: 'Idoc-parser', target: 'confirm-message', condition: '${Idoc-parser.count} > 0' }],
  groups: [{ id: 'group', member_activity_ids: ['Idoc-parser', 'confirm-message'], config: { condition: '${Idoc-parser.count} > 0' } }],
};
test('copying a task changes only its identity and name', () => {
  const result = copyTask(task, 'new-task', 'New Name');
  assert.deepEqual(result, { ...task, id: 'new-task', name: 'New Name' });
  assert.deepEqual(result.activities.map(item => item.name), ['Idoc-parser', 'confirm-message', 'log3']);
});
test('editing a copy does not mutate original activities, groups or transitions', () => {
  const result = copyTask(task, 'new-task', 'New Name');
  result.activities[0].config.schema = 'changed';
  result.groups[0].member_activity_ids.push('log3');
  result.transitions[0].target = 'log3';
  assert.equal(task.activities[0].config.schema, 'schema-1');
  assert.equal(task.groups[0].member_activity_ids.length, 2);
  assert.equal(task.transitions[0].target, 'confirm-message');
});
test('copying a copy never adds suffixes to activities', () => {
  const first = copyTask(task, 'copy1', 'Copy 1');
  const second = copyTask(first, 'copy2', 'Copy 2');
  assert.deepEqual(second.activities, task.activities);
  assert.deepEqual(second.groups, task.groups);
  assert.deepEqual(second.transitions, task.transitions);
});
