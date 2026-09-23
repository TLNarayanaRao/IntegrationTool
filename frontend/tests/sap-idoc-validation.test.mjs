import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';
import ts from 'typescript';

// Exercise the actual Task and Project validators without mounting the Studio.
const source = await readFile(new URL('../src/main.tsx', import.meta.url), 'utf8');
const ast = ts.createSourceFile('main.tsx', source, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
const names = new Set(['isEventActivity', 'propertyReferences', 'validateTaskDefinition', 'validateProjectDefinition']);
const declarations = ast.statements.filter(statement => ts.isVariableStatement(statement)
  && statement.declarationList.declarations.some(declaration => names.has(declaration.name.getText(ast))));
assert.equal(declarations.length, names.size);
const compiled = ts.transpileModule(declarations.map(statement => statement.getText(ast)).join('\n')
  + '\nexport { validateTaskDefinition, validateProjectDefinition };',
  { compilerOptions: { module: ts.ModuleKind.ESNext } }).outputText;
const { validateTaskDefinition, validateProjectDefinition } = await import(`data:text/javascript;base64,${Buffer.from(compiled).toString('base64')}`);

function fixture(connectionConfig = {}) {
  const activity = (id, operation) => ({ id, name: id, type: 'sap', config: { operation, resourceId: 'sap', inputMappings: {} } });
  const task = { id: 'task', name: 'Receive IDoc', kind: 'starter', groups: [],
    activities: [activity('listener', 'idoc_listener'), activity('parser', 'idoc_parser'), { id: 'end', name: 'End', type: 'end', config: {} }],
    transitions: [{ source: 'listener', target: 'parser' }, { source: 'parser', target: 'end' }] };
  return { name: 'IDoc app', tasks: [task], resources: [{ id: 'sap', type: 'sap', config: connectionConfig }],
    properties: { local: [] }, packaging: { artifact_name: 'idoc', version: '1.0.0' } };
}

for (const [scope, validate] of [
  ['task', project => validateTaskDefinition(project, project.tasks[0])],
  ['project', validateProjectDefinition],
]) {
  test(`${scope}: fetched connection IDoc needs no listener/parser mappings`, () => {
    const selectedIdoc = { idocType: 'ARTMAS05', schema: { type: 'object', properties: { segment: { type: 'string' } } } };
    const project = fixture({ selectedIdoc, idocCatalog: [selectedIdoc] });
    // Empty overrides occur when the activities predate the metadata fetch.
    project.tasks[0].activities[0].config.idocType = '';
    project.tasks[0].activities[1].config.idocType = '';
    assert.deepEqual(validate(project), []);
  });
  test(`${scope}: explicit activity or inherited connection type is accepted`, () => {
    const project = fixture({ idocType: 'ORDERS05' });
    project.tasks[0].activities[1].config.idocType = 'ARTMAS05';
    assert.deepEqual(validate(project), []);
  });
  test(`${scope}: missing metadata is a configuration issue, not a mapping issue`, () => {
    const issues = validate(fixture());
    assert.equal(issues.length, 2);
    assert.ok(issues.every(issue => issue.severity === 'error' && issue.category === 'SAP IDoc configuration'));
  });
  test(`${scope}: an unrelated connection selection does not hide errors`, () => {
    const project = fixture();
    project.resources.push({ id: 'other', type: 'sap', config: { selectedIdoc: { idocType: 'ARTMAS05' } } });
    assert.equal(validate(project).filter(issue => issue.category === 'SAP IDoc configuration').length, 2);
  });
  test(`${scope}: real connection and messaging configuration errors remain`, () => {
    const project = fixture({ selectedIdoc: { idocType: 'ARTMAS05' } });
    project.tasks[0].activities[0].config.messagingSource = 'Kafka';
    project.tasks[0].activities[1].config.resourceId = 'missing';
    const issues = validate(project);
    assert.ok(issues.some(issue => issue.category === 'Connection'));
    assert.equal(issues.filter(issue => issue.category === 'SAP IDoc messaging').length, 2);
  });
}
