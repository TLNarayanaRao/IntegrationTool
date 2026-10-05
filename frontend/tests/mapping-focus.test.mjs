import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import test from 'node:test';
import ts from 'typescript';
const source=await readFile(new URL('../src/mappingFocus.ts',import.meta.url),'utf8');
const {focusNextMapping}=await import(`data:text/javascript;base64,${Buffer.from(ts.transpileModule(source,{compilerOptions:{module:ts.ModuleKind.ESNext}}).outputText).toString('base64')}`);

test('Enter advances only to visible editable mappings in the active editor and blurs at the end',()=>{
  const fields=[];
  const scope={querySelectorAll:()=>fields};
  const field=(extra={})=>({disabled:false,readOnly:false,getClientRects:()=>[{}],closest:()=>scope,focus(){this.focused=true;},select(){this.selected=true;},blur(){this.blurred=true;},...extra});
  const current=field(),hidden=field({getClientRects:()=>[]}),disabled=field({disabled:true}),readonly=field({readOnly:true}),next=field();
  fields.push(current,hidden,disabled,readonly,next);
  focusNextMapping(current);
  assert.equal(next.focused,true);assert.equal(next.selected,true);
  for(const unavailable of [hidden,disabled,readonly]) assert.equal(unavailable.focused,undefined);
  focusNextMapping(next);assert.equal(next.blurred,true);
});
