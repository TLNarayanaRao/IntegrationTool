import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import test from 'node:test';
import vm from 'node:vm';
import ts from 'typescript';

const source=await readFile(new URL('../src/ActivityEditor.tsx',import.meta.url),'utf8');
const ast=ts.createSourceFile('editor.tsx',source,ts.ScriptTarget.Latest,true,ts.ScriptKind.TSX);
const hook=ast.statements.find(s=>s.name?.text==='useActivityMappingSources').getText(ast);
test('editing current Mapper mappings reuses upstream metadata; source and graph edits invalidate it',()=>{
  const ref={current:null};let builds=0;
  const context=vm.createContext({useRef:()=>ref,upstreamActivitySources:()=>{builds++;return [];},activityGroupVariables:()=>[]});
  vm.runInContext(ts.transpileModule(hook,{compilerOptions:{target:ts.ScriptTarget.ES2022}}).outputText,context);
  const source={id:'Start',config:{}};const node={id:'Mapper',config:{mappings:[]}};
  const task={id:'task',activities:[source,node],transitions:[],groups:[]};const schemas=[],resources=[];
  const first=context.useActivityMappingSources(node,task,[task],schemas,resources);
  const edited={...node,config:{mappings:[{target:'name',source:"'value'"}]}};
  const nextTask={...task,activities:[source,edited]};
  assert.equal(context.useActivityMappingSources(edited,nextTask,[nextTask],schemas,resources),first);
  assert.equal(builds,1);
  const changedTask={...nextTask,activities:[{...source,config:{schemaText:'changed'}},edited]};
  context.useActivityMappingSources(edited,changedTask,[changedTask],schemas,resources);
  assert.equal(builds,2);
  context.useActivityMappingSources(edited,{...changedTask,transitions:[{source:'Start',target:'Mapper'}]},[changedTask],schemas,resources);
  assert.equal(builds,3);
});
