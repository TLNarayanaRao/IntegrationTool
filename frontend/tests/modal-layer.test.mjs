import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import test from 'node:test';
import vm from 'node:vm';
import ts from 'typescript';
const source=await readFile(new URL('../src/ModalLayer.tsx',import.meta.url),'utf8');
const ast=ts.createSourceFile('modal.tsx',source,ts.ScriptTarget.Latest,true,ts.ScriptKind.TSX);
const declaration=ast.statements.find(statement=>statement.name?.text==='ModalLayer');
const script=ts.transpileModule(declaration.getText(ast).replace('export default ','').replace('export ',''),{compilerOptions:{jsx:ts.JsxEmit.React}}).outputText;
test('full-screen dialogs render outside panel clipping and preserve interaction props',()=>{
 const body={},handler=()=>{},context=vm.createContext({document:{body},React:{createElement:(type,props)=>({type,props})},createPortal:(content,target)=>({content,target})});
 vm.runInContext(script,context);
 const result=context.ModalLayer({className:'modal-backdrop mapper-backdrop',children:'dialog',onMouseDown:handler});
 assert.equal(result.target,body);
 assert.equal(result.content.props.className,'modal-backdrop mapper-backdrop viewport-modal-layer');
 assert.equal(result.content.props.onMouseDown,handler);
 assert.equal(result.content.props.children,'dialog');
});
test('all full-screen modal backdrops use the common viewport layer',async()=>{
 for(const name of ['main.tsx','MapperStudio.tsx','ActivityEditor.tsx','DebugJobData.tsx','SchemaStudio.tsx']){
  const text=await readFile(new URL('../src/'+name,import.meta.url),'utf8');
  const file=ts.createSourceFile(name,text,ts.ScriptTarget.Latest,true,ts.ScriptKind.TSX);
  function check(node){if(ts.isJsxOpeningElement(node)&&node.attributes.properties.some(attr=>ts.isJsxAttribute(attr)&&attr.name.text==='className'&&attr.initializer&&ts.isStringLiteral(attr.initializer)&&['modal-backdrop','schema-backdrop','sap-idoc-picker'].some(cls=>attr.initializer.text.split(' ').includes(cls))))assert.equal(node.tagName.getText(file),'ModalLayer',name);ts.forEachChild(node,check);}
  check(file);
 }
});
