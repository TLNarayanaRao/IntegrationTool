import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';
import vm from 'node:vm';
import ts from 'typescript';

// Exercise the component's actual field definitions against the shared tree builder.
const source = await readFile(new URL('../src/ActivityEditor.tsx', import.meta.url), 'utf8');
const ast = ts.createSourceFile('ActivityEditor.tsx', source, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
const names = new Set(['d', 'dataTreeRows', 'MediationInputEditor']);
const extracted = ast.statements.filter(statement =>
  names.has(statement.name?.text) || (ts.isVariableStatement(statement) &&
    statement.declarationList.declarations.some(declaration => names.has(declaration.name.getText(ast))))
).map(statement => statement.getText(ast)).join('\n');
const compiled = ts.transpileModule(extracted, {
  compilerOptions: { jsx: ts.JsxEmit.React, target: ts.ScriptTarget.ES2022 },
}).outputText;

function render(config = {}, schemaFields = []) {
  let stateIndex = 0;
  const context = vm.createContext({
    useState: () => [stateIndex++ === 0 ? schemaFields : '', () => {}],
    useEffect: () => {},
    InputEditor: 'InputEditor',
    React: { createElement: (type, props, ...children) => ({ type, props, children }) },
  });
  vm.runInContext(compiled, context);
  const element = context.MediationInputEditor({ node: { name: 'Mediation' }, config });
  return { element, rows: context.dataTreeRows(element.props.fields) };
}

test('Input without a target schema renders a mappable payload without descriptive prose', async () => {
  const { element, rows } = render();
  assert.equal(rows.length, 1);
  assert.equal(rows[0].path, 'payload');
  assert.equal(rows[0].explicit, true);
  assert.doesNotMatch(JSON.stringify(element.props.before), /Load a target schema in Configuration/);
  const guidance = await readFile(new URL('../src/activityGuidance.ts', import.meta.url), 'utf8');
  assert.match(guidance, /Load a target schema in Configuration/);
});

test('schema fields form nested target rows with stable mapping keys', () => {
  const mappings = { 'targetValues.order.id': '${ReadOrder.id}' };
  const { element, rows } = render({ inputMappings: mappings }, [
    { path: 'order.id', type: 'string', required: true },
    { path: 'items', type: 'array' },
  ]);
  assert.ok(rows.some(row => row.path === 'targetValues.order.id' && row.explicit));
  assert.equal(rows.find(row => row.path === 'targetValues.items').type, 'any');
  assert.equal(element.props.mappings, mappings);
});

test('recipe-only configuration works without an XSD and deduplicates schema targets', () => {
  const config = { rules: [{ target: 'order.id' }, { target: 'total' }] };
  assert.ok(render(config).rows.some(row => row.path === 'targetValues.total'));
  const { rows } = render(config, [{ path: 'order.id', type: 'string' }]);
  assert.equal(rows.filter(row => row.path === 'targetValues.order.id').length, 1);
});
