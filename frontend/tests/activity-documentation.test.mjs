import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';
import vm from 'node:vm';
import ts from 'typescript';

const source = await readFile(new URL('../src/ActivityEditor.tsx', import.meta.url), 'utf8');
const ast = ts.createSourceFile('ActivityEditor.tsx', source, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
const functionSource = ast.statements.find(statement => statement.name?.text === 'ActivityEditorGuidance').getText(ast);
const guidanceSource = await readFile(new URL('../src/activityGuidance.ts', import.meta.url), 'utf8');
const { activityGuidance } = await import(`data:text/javascript;base64,${Buffer.from(ts.transpileModule(guidanceSource, { compilerOptions: { module: ts.ModuleKind.ESNext } }).outputText).toString('base64')}`);
const context = vm.createContext({ activityGuidance, React: { createElement: (type, props, ...children) => ({ type, props, children }) } });
vm.runInContext(ts.transpileModule(functionSource, { compilerOptions: { jsx: ts.JsxEmit.React, target: ts.ScriptTarget.ES2022 } }).outputText, context);
const documentation = type => JSON.stringify(context.ActivityEditorGuidance({ type }));

test('Mediation documentation retains relocated schema and preview explanations', async () => {
  const docs = documentation('mediation');
  assert.match(docs, /Make messages speak the same business language/);
  assert.match(docs, /Object schemas describe each output record/);
  assert.match(docs, /Supply synthetic earlier outputs/);
  const editor = await readFile(new URL('../src/MediationStudio.tsx', import.meta.url), 'utf8');
  assert.doesNotMatch(editor, /Make messages speak|Object schemas describe|Supply synthetic earlier outputs/);
  assert.match(editor, /role="alert"/);
  assert.match(editor, /role="status"/);
});
test('all activity types receive common mapping and advanced guidance', () => {
  for (const type of ['kafka', 'http', 'jdbc', 'sap', 'timer', 'log', 'mediation']) {
    assert.match(documentation(type), /Logs activity input and output/);
    assert.match(documentation(type), /Map simple schema elements/);
  }
});
test('specialized guidance is shown for the relevant activity only', () => {
  assert.match(documentation('jdbc'), /Prepared SQL editor/);
  assert.doesNotMatch(documentation('kafka'), /Prepared SQL editor|Five fields: minute/);
  assert.match(documentation('timer'), /Five fields: minute/);
});
