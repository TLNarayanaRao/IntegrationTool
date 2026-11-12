import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import test from 'node:test';
import vm from 'node:vm';
import ts from 'typescript';

const editor=await readFile(new URL('../src/ActivityEditor.tsx',import.meta.url),'utf8');
const ast=ts.createSourceFile('editor.tsx',editor,ts.ScriptTarget.Latest,true,ts.ScriptKind.TSX);
const main=ts.createSourceFile('main.tsx',await readFile(new URL('../src/main.tsx',import.meta.url),'utf8'),ts.ScriptTarget.Latest,true,ts.ScriptKind.TSX);
const compile=text=>ts.transpileModule(text,{compilerOptions:{module:ts.ModuleKind.ESNext,jsx:ts.JsxEmit.React,target:ts.ScriptTarget.ES2022}}).outputText;
const helpers=await readFile(new URL('../src/mapperLoopMappings.ts',import.meta.url),'utf8');
const mappings=await import(`data:text/javascript;base64,${Buffer.from(compile(helpers)).toString('base64')}`);
function find(node,predicate){let result;function visit(n){if(predicate(n))result=n;else ts.forEachChild(n,visit);}visit(node);return result;}
const packs=find(main,n=>ts.isVariableDeclaration(n)&&n.name.getText(main)==='packs');
const icons={};function iconNames(node){if(ts.isPropertyAssignment(node)&&node.name.getText(main)==='icon')icons[node.initializer.getText(main)]='icon';ts.forEachChild(node,iconNames);}iconNames(packs);
const catalog=vm.createContext({...icons});vm.runInContext(compile(`globalThis.packs=${packs.initializer.getText(main)}`),catalog);
const definitions=catalog.packs.flatMap(pack=>pack.items);

test('every palette activity clears a complex root through its actual editor action and saves the new config',()=>{
 const input=ast.statements.find(n=>n.name?.text==='InputEditor');
 const deleteRule=find(input,n=>ts.isVariableDeclaration(n)&&n.name.getText(ast)==='deleteRule');
 const transform=ast.statements.find(n=>n.name?.text==='TransformInputEditor');
 const mapperMenu=find(transform,n=>ts.isJsxSelfClosingElement(n)&&n.tagName.getText(ast)==='MappingContextMenu');
 const mapperRemove=mapperMenu.attributes.properties.find(n=>n.name?.getText(ast)==='remove').initializer.expression;
 const inputElement=find(ast,n=>ts.isJsxSelfClosingElement(n)&&n.tagName.getText(ast)==='InputEditor'&&n.attributes.properties.some(p=>p.name?.getText(ast)==='set'&&p.initializer?.expression?.getText(ast).includes('inputMappingTypes')));
 const save=inputElement.attributes.properties.find(n=>n.name?.getText(ast)==='set').initializer.expression;
 const covered=new Set();
 assert.ok(definitions.length>=100);
 for(const def of [...definitions,{type:'transform'},{type:'ai_transform'}]){
  const rules=[{target:'root.clear.value',source:'"stale"'},
   {target:'root.keep.value',source:'"keep"'},{target:'rootSibling.value',source:'"sibling"'}];
  const cfg={operation:def.operation,inputMappings:mappings.activityMappingsFromRules(rules),mappings:rules};
  let saved;
  const context=vm.createContext({...mappings,cfg,node:{type:def.type},task:{},tasks:[],schemas:[],resources:[],
   contract:{input:[],configuration:[]},isParseRender:node=>['xml','json','flat'].includes(node.type),
   formatInputMappings:()=>({legacy:new Map()}),activityInputMappingTypes:()=>({}),update:patch=>saved=patch.config,
   contextMenu:{path:'root.clear'},rules,mappings:rules,setMappings:value=>saved={...cfg,mappings:value}});
  vm.runInContext(compile(`const save=${save.getText(ast)};globalThis.set=save;const ${deleteRule.getText(ast)};globalThis.deleteRule=deleteRule;globalThis.removeMapper=${mapperRemove.getText(ast)};`),context);
  if(['mapper','transform','ai_transform'].includes(def.type)){
   context.removeMapper();assert.deepEqual(JSON.parse(JSON.stringify(saved.mappings)),rules.slice(1),def.label);
  }else{
   context.deleteRule('root.clear');
   assert.deepEqual(JSON.parse(JSON.stringify(saved.inputMappings)),{'root.keep.value':'"keep"','rootSibling.value':'"sibling"'},def.label);
  }
  assert.equal(cfg.inputMappings['root.clear.value'],'"stale"','saved config must not mutate original snapshot');
  covered.add(def.type);
 }
 assert.ok(covered.has('call_task'));assert.ok(covered.has('end'));assert.ok(covered.has('http_response'));
});
