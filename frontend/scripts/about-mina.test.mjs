import {test} from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import {createRequire} from 'node:module';
import ts from 'typescript';
import React from 'react';
import {renderToStaticMarkup} from 'react-dom/server';
const require=createRequire(import.meta.url);
function render(desktop) {
  const source=fs.readFileSync(new URL('../src/AboutMina.tsx',import.meta.url),'utf8').replaceAll('import.meta.env.VITE_APP_VERSION',JSON.stringify('9.8.7-rc.1'));
  const compiled=ts.transpileModule(source,{compilerOptions:{module:ts.ModuleKind.CommonJS,jsx:ts.JsxEmit.ReactJSX,esModuleInterop:true}}).outputText;
  const exports={};vm.runInNewContext(compiled,{exports,require:name=>name.endsWith('.css')?{}:require(name),window:{minaDesktop:desktop?{}:undefined}});
  return renderToStaticMarkup(React.createElement(exports.default));
}
test('browser About shows build version, identity and documentation',()=>{
  const html=render(false);
  for(const value of ['9.8.7-rc.1','Web browser','MINA Studio','Mediation, Integration','/help/index.html','Control Plane'])assert.ok(html.includes(value),value);
});
test('desktop About remains usable with an older host without app-info API',()=>{
  const html=render(true);assert.ok(html.includes('Desktop application'));assert.ok(html.includes('9.8.7-rc.1'));
});
test('installed desktop version overrides the browser build version',async()=>{
  const updates=[];
  const source=fs.readFileSync(new URL('../src/AboutMina.tsx',import.meta.url),'utf8').replaceAll('import.meta.env.VITE_APP_VERSION',JSON.stringify('1.0.0'));
  const compiled=ts.transpileModule(source,{compilerOptions:{module:ts.ModuleKind.CommonJS,jsx:ts.JsxEmit.ReactJSX}}).outputText;
  const exports={};
  const hooks={useState:value=>[value,next=>updates.push(next)],useEffect:fn=>fn()};
  vm.runInNewContext(compiled,{exports,require:name=>name==='react'?hooks:name.endsWith('.css')?{}:require(name),window:{minaDesktop:{getAppInfo:async()=>({version:'3.7.0',packaged:true,platform:'win32'})}}});
  exports.default();await new Promise(resolve=>setImmediate(resolve));
  assert.deepEqual(updates,['3.7.0','Installed application']);
});
