import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import test from 'node:test';
import vm from 'node:vm';
import ts from 'typescript';

const source = await readFile(new URL('../src/ActivityEditor.tsx', import.meta.url), 'utf8');
const ast = ts.createSourceFile('editor.tsx', source, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
const names = ['cardinalitySymbol', 'transformSchemaFields', 'schemaDataFields', 'dataTreeRows'];
const code = ts.transpileModule(ast.statements.filter(s => names.includes(s.name?.text)).map(s => s.getText(ast)).join('\n'), {compilerOptions:{target:ts.ScriptTarget.ES2022}}).outputText;
const context = vm.createContext({d:(key,label,type) => ({key,label,type})});
vm.runInContext(code, context);

test('occurrence symbols distinguish optional, required and repeating elements', () => {
  for (const [field, symbol] of [
    [{minOccurs:'0', maxOccurs:'1'}, '?'],
    [{minOccurs:'1', maxOccurs:'1'}, ''],
    [{minOccurs:'0', maxOccurs:'unbounded'}, '*'],
    [{minOccurs:'1', maxOccurs:'unbounded'}, '+'],
    [{minOccurs:'2', maxOccurs:'5'}, '+'],
    [{type:'string', required:true}, ''],
    [{type:'string'}, '?'],
    [{type:'object[]'}, '*'],
  ]) assert.equal(context.cardinalitySymbol(field), symbol);
});

test('JSON schema cardinality survives conversion into shared activity input trees', () => {
  const schema = {type:'object', required:['id'], properties:{id:{type:'string'}, note:{type:'string'}, rows:{type:'array', items:{type:'object', required:['name'], properties:{name:{type:'string'}, comment:{type:'string'}}}}, tags:{type:'array', minItems:1, items:{type:'string'}}}};
  const fields = context.transformSchemaFields({targetSchema:schema});
  assert.deepEqual(Array.from(fields, f => context.cardinalitySymbol(f)), ['', '?', '*', '', '?', '+']);
  const rows = context.dataTreeRows(context.schemaDataFields(schema));
  assert.deepEqual(Array.from(rows, f => context.cardinalitySymbol(f)), ['', '?', '*', '', '?', '+']);
});
