import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import test from 'node:test';
import vm from 'node:vm';
import ts from 'typescript';
const source=await readFile(new URL('../src/ActivityEditor.tsx',import.meta.url),'utf8');
const ast=ts.createSourceFile('editor.tsx',source,ts.ScriptTarget.Latest,true,ts.ScriptKind.TSX);
const validation=await readFile(new URL('../src/mappingValidation.ts',import.meta.url),'utf8');
const {validateMapping}=await import(`data:text/javascript;base64,${Buffer.from(ts.transpileModule(validation,{compilerOptions:{module:ts.ModuleKind.ESNext}}).outputText).toString('base64')}`);
const names=['activityMappingIssues','activityInputMappingTypes'];
const code=ts.transpileModule(ast.statements.filter(s=>names.includes(s.name?.text)).map(s=>s.getText(ast).replace('export ','')).join('\n'),{compilerOptions:{target:ts.ScriptTarget.ES2022}}).outputText;
const context=vm.createContext({validateMapping,isMapperActivity:type=>type==='mapper',transformSchemaFields:config=>config.fields,
  runtimeMappableInputs:(node,contract)=>contract.input,resolvedActivityContract:node=>({input:node.fields||[]}),dataTreeRows:fields=>fields,
  mappingCompletionPaths:()=>['input','last'],upstreamActivitySources:()=>[]});
vm.runInContext(code,context);

test('packaging checks Mapper literals and conditional branches against schema types',()=>{
  const node={type:'mapper',config:{fields:[{path:'name',type:'string'},{path:'amount',type:'number'}],mappings:[
    {target:'name',source:'bare',targetType:'number'}, {target:'amount',source:'"123"'},
    {target:'name',operator:'choose',whens:[{condition:'true',source:'bad'}],otherwise:'"good"'}]}};
  assert.equal(context.activityMappingIssues(node,{},[],[],[]).length,3);
  node.config.mappings=[{target:'name',constant:'good'},{target:'amount',source:'123'}];
  assert.equal(context.activityMappingIssues(node,{},[],[],[]).length,0);
});

test('all-activity Input mappings use current schema types, not stale stored metadata',()=>{
  const node={type:'end',fields:[{path:'result.name',type:'string'},{path:'result.count',type:'integer'}],config:{inputMappingTypes:{'result.name':'number'},inputMappings:{'result.name':'bare','result.count':'"123"'}}};
  assert.equal(context.activityInputMappingTypes(node,{},[],[],[])['result.name'],'string');
  assert.equal(context.activityMappingIssues(node,{},[],[],[]).length,2);
  node.config.inputMappings={'result.name':"'correct'",'result.count':123};
  assert.equal(context.activityMappingIssues(node,{},[],[],[]).length,0);
});
