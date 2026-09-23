import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';
import ts from 'typescript';

const source = await readFile(new URL('../src/debugTaskTree.ts', import.meta.url), 'utf8');
const compiled = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.ESNext } }).outputText;
const { debugCallTarget, debugTaskMatches } = await import(`data:text/javascript;base64,${Buffer.from(compiled).toString('base64')}`);
const call = (id, config) => ({ id, name: id, type: 'call_task', config });
const tasks = [
  { id: 'root', name: 'Main', kind: 'starter', activities: [call('call-child', { taskId: 'child' })] },
  { id: 'child', name: 'Child Process', kind: 'subtask', activities: [call('call-leaf', { taskId: 'leaf' })] },
  { id: 'leaf', name: 'Leaf', kind: 'subtask', activities: [{ id: 'publish', name: 'Send EMS', type: 'ems' }] },
];
test('resolves called subprocesses by id and case-insensitive name', () => {
  assert.equal(debugCallTarget(tasks, tasks[0].activities[0]).target.id, 'child');
  assert.equal(debugCallTarget(tasks, call('named', { taskId: 'CHILD PROCESS' })).target.id, 'child');
});
test('search finds nested activities through multiple call levels', () => {
  assert.equal(debugTaskMatches(tasks, tasks[0], 'send ems'), true);
  assert.equal(debugTaskMatches(tasks, tasks[0], 'unrelated'), false);
});
test('dynamic targets expose fallback without pretending to resolve expressions', () => {
  const resolved = debugCallTarget(tasks, call('dynamic', { dynamicTaskId: '${input.route}', taskId: 'leaf' }));
  assert.equal(resolved.deferred, true);
  assert.equal(resolved.target.id, 'leaf');
  assert.equal(debugCallTarget(tasks, call('dynamic', { dynamicTaskId: '${input.route}' })).target, undefined);
  assert.equal(debugCallTarget(tasks, call('literal', { dynamicTaskId: 'leaf', taskId: 'child' })).target.id, 'leaf');
});
test('missing targets and circular references terminate safely', () => {
  assert.equal(debugCallTarget(tasks, call('missing', { taskId: 'gone' })).target, undefined);
  const circular = structuredClone(tasks);
  circular[2].activities.push(call('back', { taskId: 'child' }));
  assert.equal(debugTaskMatches(circular, circular[0], 'absent'), false);
  assert.equal(debugTaskMatches(circular, circular[0], 'send ems'), true);
});
