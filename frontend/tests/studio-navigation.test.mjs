import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import test from 'node:test';
import ts from 'typescript';

const source = await readFile(new URL('../src/studioNavigation.ts', import.meta.url), 'utf8');
const code = ts.transpileModule(source, {compilerOptions: {module: ts.ModuleKind.ESNext}}).outputText;
const {locationKey, rememberLocation, navigationIndex, recentNavigationEntries, isTaskSelectionChange} = await import(`data:text/javascript;base64,${Buffer.from(code).toString('base64')}`);
const begin = () => ({entries: [], index: -1});

test('history retains the latest 15 previous steps and the current step', () => {
  let history = begin();
  for (let i = 0; i < 40; i++) history = rememberLocation(history, {kind: 'task', id: String(i)});
  assert.equal(history.entries.length, 16);
  assert.equal(history.index, 15);
  assert.equal(history.entries[0].id, '24');
  assert.equal(history.entries[15].id, '39');
});

test('entries distinguish activities and folders and skip missing destinations', () => {
  const entries = [
    {kind: 'task', id: 'main'},
    {kind: 'task', id: 'main', activityId: 'call'},
    {kind: 'package', category: 'schemas', path: 'Default'},
    {kind: 'package', category: 'resources', path: 'Default'},
    {kind: 'resource', id: 'database'},
    {kind: 'schema', id: 'orders'},
  ];
  const history = entries.reduce(rememberLocation, begin());
  assert.equal(new Set(entries.map(locationKey)).size, entries.length);
  assert.equal(navigationIndex(history, -1, location => location.kind !== 'resource'), 3);
  assert.equal(navigationIndex({...history, index: 3}, 1, location => location.kind !== 'resource'), 5);
  assert.equal(navigationIndex(history, 1, () => true), -1);
});

test('opening a new location after Back replaces the Forward path', () => {
  const a = {kind: 'task', id: 'main'};
  const b = {kind: 'task', id: 'child'};
  const c = {kind: 'schema', id: 'contract'};
  const history = rememberLocation(rememberLocation(begin(), a), b);
  assert.equal(rememberLocation(history, b), history);
  assert.deepEqual(rememberLocation({...history, index: 0}, c), {entries: [a, c], index: 1});
});

test('changing only the active task can bypass full edit-undo snapshots', () => {
  const project = {id: 'workspace', active_task_id: 'one', tasks: [{id: 'one'}, {id: 'two'}]};
  assert.equal(isTaskSelectionChange(project, {...project, active_task_id: 'two'}), true);
  assert.equal(isTaskSelectionChange(project, {...project, active_task_id: 'two', tasks: project.tasks.slice(1)}), false);
  assert.equal(isTaskSelectionChange(project, {...project, active_task_id: 'two', id: 'other'}), false);
});

test('recent locations show up to 15 other steps newest first and keep the original cursor indices', () => {
  const entries = Array.from({length: 16}, (_, index) => ({kind: 'task', id: String(index)}));
  const history = {entries, index: 7};
  const full = recentNavigationEntries(history, location => location.id);
  assert.equal(full.length, 15);
  assert.deepEqual(full[0], {index: 15, label: '15'});
  assert.deepEqual(full.at(-1), {index: 0, label: '0'});
  const recent = recentNavigationEntries(history, location => location.id === '10' ? undefined : location.id);
  assert.ok(!recent.some(({index}) => index === 7 || index === 10));
  assert.equal(navigationIndex({...history, index: recent[0].index}, -1, () => true), 14);
  assert.equal(history.index, 7);
});
