import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import test from 'node:test';
import vm from 'node:vm';
import ts from 'typescript';

test('completion uses the displayed short expression and current caret rather than a stale full path',async()=>{
  const source=await readFile(new URL('../src/MappingExpressionInput.tsx',import.meta.url),'utf8');
  const ast=ts.createSourceFile('input.tsx',source,ts.ScriptTarget.Latest,true,ts.ScriptKind.TSX);
  let choose;
  function visit(node) {if(ts.isVariableDeclaration(node)&&node.name.getText(ast)==='choose') choose=node;ts.forEachChild(node,visit);}
  visit(ast);
  const completionSource=await readFile(new URL('../src/mappingCompletion.ts',import.meta.url),'utf8');
  const {completeMapping}=await import(`data:text/javascript;base64,${Buffer.from(ts.transpileModule(completionSource,{compilerOptions:{module:ts.ModuleKind.ESNext}}).outputText).toString('base64')}`);
  let saved;
  const context=vm.createContext({input:{current:{value:'CHAR_VAL',selectionStart:8}},text:'${Mapper.Record.CHAR_VAL}CHAR_VAL}',prefix:'${Mapper.Record.CHAR_VAL}',suffix:'CHAR_VAL}',completeMapping,onChange:v=>saved=v,setCaret() {},setOpen() {},setIndex() {}});
  const code=ts.transpileModule(`const ${choose.getText(ast)}; choose({insert:'\u0024{Mapper.Record.CHAR_VAL_FLOAT_TO_DV_UOM}'});`,{compilerOptions:{target:ts.ScriptTarget.ES2022}}).outputText;
  vm.runInContext(code,context);
  assert.equal(saved,'${Mapper.Record.CHAR_VAL_FLOAT_TO_DV_UOM}');
});
