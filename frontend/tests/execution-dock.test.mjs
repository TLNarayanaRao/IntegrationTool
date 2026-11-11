import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import test from 'node:test';
import vm from 'node:vm';
import ts from 'typescript';

const source = await readFile(new URL('../src/ExecutionDock.tsx',import.meta.url),'utf8');
const code = ts.transpileModule(source,{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2020,
  jsx:ts.JsxEmit.React,jsxFactory:'create',jsxFragmentFactory:'Fragment'}}).outputText;

function render(mode) {
  const effects=[],frames=new Map(); let changed,scroll,focused=false;
  const log={scrollHeight:500,clientHeight:100,scrollTop:0,
    addEventListener(_event,fn){scroll=fn;},removeEventListener(){}};
  const element={focus(){focused=true;},querySelector(){return log;}};
  const context=vm.createContext({exports:{},Fragment:'fragment',
    create:(type,props,...children)=>({type,props:props||{},children:children.flat(Infinity)}),
    require:name=>name==='react' ? {useRef:()=>({current:element}),useEffect:fn=>effects.push(fn)} : {__esModule:true,default:'ModalLayer'},
    requestAnimationFrame:fn=>{const id=Symbol();frames.set(id,fn);return id;},cancelAnimationFrame:id=>frames.delete(id),
    MutationObserver:class {constructor(fn){changed=fn;} observe(){} disconnect(){}},
  });
  vm.runInContext(code,context);
  const tree=context.exports.default({mode,children:'execution logs'});
  const cleanup=effects.map(effect=>effect());
  const flush=()=>{for(const [key,fn] of [...frames]){frames.delete(key);fn();}};
  return {tree,log,flush,changed:()=>changed(),scrolled:()=>scroll(),focused:()=>focused,cleanup:()=>cleanup.forEach(fn=>fn?.())};
}

test('execution logs follow new entries until the user scrolls away from the bottom',()=>{
  const app=render('normal');app.flush();
  assert(app.focused());assert.equal(app.log.scrollTop,500);
  app.log.scrollTop=400;app.scrolled();app.log.scrollHeight=700;app.changed();app.flush();
  assert.equal(app.log.scrollTop,700);
  app.log.scrollTop=100;app.scrolled();app.log.scrollHeight=900;app.changed();app.flush();
  assert.equal(app.log.scrollTop,100);
  app.cleanup();
});

test('expanded execution views use the viewport modal layer; normal execution stays in the lower pane',()=>{
  const normal=render('normal');assert.equal(normal.tree.type,'section');normal.cleanup();
  for(const mode of ['expanded','fullscreen']) {
    const app=render(mode);assert.equal(app.tree.type,'ModalLayer');
    assert.equal(app.tree.children[0].props.role,'dialog');assert.equal(app.tree.children[0].props['aria-modal'],true);
    app.cleanup();
  }
});

test('a finished debugger releases Run and Debug even when its initial runtime snapshot was paused',async()=>{
  const app=await readFile(new URL('../src/main.tsx',import.meta.url),'utf8');
  const expression=app.match(/const executionActive = ([\s\S]*?);/)[1];
  const active=status=>vm.runInNewContext(expression,{busy:false,debugState:{status},endpoints:[],runtimeState:{status:'paused'}});
  assert.equal(active('paused'),true);
  assert.equal(active('running'),true);
  for(const status of ['completed','failed','stopped']) assert.equal(active(status),false);
});

test('inspecting an activity restores its configuration without changing the debug session',async()=>{
  const source=await readFile(new URL('../src/main.tsx',import.meta.url),'utf8');
  const declaration=source.match(/const inspectActivity = [\s\S]*?\n  };/)[0];
  const code=ts.transpileModule(declaration+'\nexports.inspect=inspectActivity;',{compilerOptions:{target:ts.ScriptTarget.ES2020}}).outputText;
  const view={};
  const context=vm.createContext({exports:{},
    ...Object.fromEntries(['Selected','SelectedIds','SelectedEdge','SelectedResource','ExecutionPanelOpen','MonitorMode','ActiveTab']
      .map(key=>['set'+key,value=>{view[key]=value;}]))});
  vm.runInContext(code,context);
  context.exports.inspect('Mapper');
  assert.equal(view.Selected,'Mapper');assert.deepEqual([...view.SelectedIds],['Mapper']);
  assert.equal(view.ExecutionPanelOpen,false);assert.equal(view.MonitorMode,'normal');
  assert.equal(view.ActiveTab,'configuration');assert.equal(view.SelectedEdge,null);assert.equal(view.SelectedResource,null);
  context.exports.inspect('End',['Mapper','End']);
  assert.deepEqual([...view.SelectedIds],['Mapper','End']);
});
