import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import ts from 'typescript';

// Load the actual pure Studio contract, without importing the React editor or
// replacing its field logic with a test-only implementation.
const text=fs.readFileSync(new URL('../src/ActivityEditor.tsx',import.meta.url),'utf8');
const source=ts.createSourceFile('ActivityEditor.tsx',text,ts.ScriptTarget.Latest,true,ts.ScriptKind.TSX);
const declarations=[];
for(const node of source.statements){
  if(ts.isFunctionDeclaration(node)&&node.name?.text==='activityContract')declarations.push(node.getText(source));
  if(ts.isVariableStatement(node))for(const item of node.declarationList.declarations){
    if(ts.isIdentifier(item.name)&&['f','d'].includes(item.name.text))declarations.push('const '+item.getText(source)+';');
  }
}
const code=ts.transpileModule(declarations.join('\n'),{compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.ESNext}}).outputText;
const {activityContract}=await import('data:text/javascript;base64,'+Buffer.from(code).toString('base64'));

test('Parse Data streaming exposes paths and metadata instead of a materialized document',()=>{
  const contract=activityContract({type:'flat',config:{operation:'parse',streaming:true,nestedRecords:true}});
  for(const key of ['fileName','streamOutputFile','streamErrorFile','formatOptions.fieldPaths','formatOptions.streamMaxBatchBytes','formatOptions.quoteRecovery'])assert.ok(contract.input.some(field=>field.key===key),key);
  assert.equal(contract.input.find(field=>field.key==='formatOptions.fieldPaths').type,'object');
  assert.ok(contract.output.some(field=>field.key==='filePath'));
  assert.ok(!contract.output.some(field=>['records','xmlString','text'].includes(field.key)));
  for(const key of ['nestedRecords','streaming'])assert.equal(contract.configuration.find(field=>field.key===key).type,'boolean');
});

test('Render Data file streaming and legacy record inputs remain distinct',()=>{
  const stream=activityContract({type:'flat',config:{operation:'render',streaming:true}});
  assert.ok(stream.input.some(field=>field.key==='streamInputFile'&&field.required));
  assert.ok(stream.input.some(field=>field.key==='formatOptions.fileEncoding'));
  assert.ok(!stream.input.some(field=>field.key==='records'));
  const legacy=activityContract({type:'flat',config:{operation:'render'}});
  assert.ok(legacy.input.some(field=>field.key==='records'));
  assert.ok(legacy.output.some(field=>field.key==='text'));
});

test('HDT and whole-file rules are dynamically mappable and expose validation summaries',()=>{
  const contract=activityContract({type:'flat',config:{operation:'parse',streaming:true,groupRecords:true}});
  for(const key of ['recordLayouts','wholeFileRules'])assert.equal(contract.input.find(field=>field.key==='formatOptions.'+key).type,'object');
  for(const key of ['groupRecords','wholeFileValidation','wholeFileXsd'])assert.equal(contract.configuration.find(field=>field.key===key).type,'boolean');
  for(const key of ['validation','validation.valid','validation.xsdValidated','validation.totals','groupCount','detailCount'])assert.ok(contract.output.some(field=>field.key===key));
});
