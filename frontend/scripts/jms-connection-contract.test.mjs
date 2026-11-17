import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import ts from 'typescript';

const text = fs.readFileSync(new URL('../src/main.tsx', import.meta.url), 'utf8');
const source = ts.createSourceFile('main.tsx', text, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
let declaration;
for (const statement of source.statements) {
  if (!ts.isVariableStatement(statement)) continue;
  for (const item of statement.declarationList.declarations) {
    if (item.name.getText(source) === 'connectionFieldSets') declaration = item;
  }
}
assert.ok(declaration, 'actual Studio connection field definitions exist');
// Only evaluate the two real provider definitions; other protocols have their
// own dependencies and are outside this regression's scope.
const entries = declaration.initializer.properties.filter(p => ['jms', 'ems'].includes(p.name.getText(source)));
const code = ts.transpileModule('export const fields = {' + entries.map(p => p.getText(source)).join(',') + '};',
  { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext } }).outputText;
const { fields } = await import('data:text/javascript;base64,' + Buffer.from(code).toString('base64'));
for (const kind of ['jms', 'ems']) test(`${kind}: provider credentials are optional and JNDI has no direct URL requirement`, () => {
  const field = key => fields[kind].find(f => f.key === key);
  for (const key of ['username', 'password', 'jndiUsername', 'jndiPassword']) assert.ok(!field(key).required, key);
  assert.equal(field('serverUrl').required, true);
  assert.equal(field('serverUrl').when({ connectionFactoryType: 'Direct' }), true);
  assert.equal(field('serverUrl').when({ connectionFactoryType: 'JNDI' }), false);
  for (const key of ['connectionFactory', 'jndiProviderUrl']) {
    assert.equal(field(key).required, true);
    assert.equal(field(key).when({ connectionFactoryType: 'JNDI' }), true);
  }
});
