import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import Module from 'node:module';
import ts from 'typescript';
import React from 'react';
import {renderToStaticMarkup} from 'react-dom/server';

function load(name) {
  const file=fileURLToPath(new URL('../src/'+name,import.meta.url));
  const module=new Module(file); module.paths=Module._nodeModulePaths(path.dirname(file));
  const code=ts.transpileModule(fs.readFileSync(file,'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022,jsx:ts.JsxEmit.ReactJSX,esModuleInterop:true}}).outputText;
  module._compile(code,file); return module.exports;
}
const {schemaFromActivityFields}=load('mapper-assistant-ui.ts');
const Review=load('MappingPlanReview.tsx').default;
const {mappingSchemaDefinition}=load('mapperSchemaSample.ts');
const {mapperFunctionCatalog}=load('mapper-functions.ts');

test('record mediation functions are available in the shared draggable function catalog',()=>{
  for(const name of ['aggregateRecords','reconcileRecords']) {
    const entries=mapperFunctionCatalog.filter(fn=>fn.name===name);
    assert.equal(entries.length,1);assert.equal(entries[0].category,'Collection');
    assert.match(entries[0].template,/\$value/);assert.match(entries[0].pipeline,new RegExp('^'+name+'\\('));
    assert.ok(entries[0].description.length>80);
  }
});

test('JSON samples expose nested repeats, sibling fields and scalar array items',()=>{
  const sample={orders:[{id:1,lines:[{sku:'A',qty:2}]},{id:2,optional:true,lines:[{sku:'B',qty:2.5}]}],tags:['fast','safe']};
  const before=JSON.stringify(sample),schema=mappingSchemaDefinition(sample);
  assert.equal(schema.properties.orders.items.properties.lines.items.properties.sku.type,'string');
  assert.equal(schema.properties.orders.items.properties.lines.items.properties.qty.type,'number');
  assert.equal(schema.properties.orders.items.properties.optional.type,'boolean');
  assert.equal(schema.properties.tags.items.type,'string');
  assert.equal(JSON.stringify(sample),before);
});

test('schema definitions remain intact and sample limits are enforced safely',()=>{
  for(const schema of [{type:'object',properties:{id:{type:'integer'}}},{$ref:'#/$defs/Record'},{name:{type:'string'}}]) {
    const result=mappingSchemaDefinition(schema);
    if(schema.name)assert.equal(result.properties.name.type,'string');else assert.equal(result,schema);
  }
  const result=mappingSchemaDefinition(JSON.parse('{"__proto__":{"polluted":true},"safe":1}'));
  assert.equal({}.polluted,undefined);assert.equal(result.properties.safe.type,'integer');
  let deep=1;for(let i=0;i<66;i++)deep={nested:deep};
  assert.throws(()=>mappingSchemaDefinition(deep),/64 levels/);
});

test('upstream metadata preserves nested repeating levels without making every leaf an array',()=>{
  const fields=[{key:'orders',type:'object',repeating:true,maxOccurs:'unbounded'},
    {key:'orders.id',type:'integer',repeating:true,maxOccurs:'1'},
    {key:'orders.lines',type:'object',repeating:true,maxOccurs:'unbounded'},
    {key:'orders.lines.qty',type:'integer',repeating:true,maxOccurs:'1'}];
  const original=JSON.stringify(fields), schema=schemaFromActivityFields(fields);
  assert.equal(schema.properties.orders.type,'array');
  assert.equal(schema.properties.orders.items.properties.id.type,'integer');
  assert.equal(schema.properties.orders.items.properties.lines.type,'array');
  assert.equal(schema.properties.orders.items.properties.lines.items.properties.qty.type,'integer');
  assert.equal(JSON.stringify(fields),original);
});

test('metadata conversion does not populate object prototypes',()=>{
  const schema=schemaFromActivityFields([null,{key:5},{key:'__proto__.polluted',type:'string'},{key:'safe',type:'string'}]);
  assert.equal({}.polluted,undefined); assert.equal(schema.properties.safe.type,'string');
  assert.deepEqual(Object.keys(schema.properties),['safe']);
});

const base={summary:{suggested:1,loops:2,protected:3,ambiguous:1,unmatched:1,requiredUnmapped:1},engine:'Local matching',
  recommendations:[{target:'customer.id',status:'ambiguous',required:true,confidence:85,alternatives:[{source:'billing.id',score:85,reasons:['Compatible data types']}]}]};
test('review explains ambiguous fields, exposes a source choice and required-field warning',()=>{
  const html=renderToStaticMarkup(React.createElement(Review,{plan:base,onApply(){},onDiscard(){},onChoose(){}}));
  assert.match(html,/Choose this source/);assert.match(html,/Compatible data types/);
  assert.match(html,/required fields still need/);assert.match(html,/Apply reviewed suggestions/);
});
test('large reviews render a bounded first page and escape field names',()=>{
  const plan={...base,recommendations:Array.from({length:180},(_,i)=>({target:i===0?'<script>':`field${i}`,status:'unmatched',alternatives:[]}))};
  const html=renderToStaticMarkup(React.createElement(Review,{plan,onApply(){},onDiscard(){},onChoose(){}}));
  assert.equal((html.match(/<article/g)||[]).length,100);assert.match(html,/80 remaining/);
  assert.match(html,/&lt;script&gt;/);assert.doesNotMatch(html,/<script>/);
});
test('review search narrows visible suggestions and empty plans cannot be applied',()=>{
  const plan={...base,summary:{...base.summary,suggested:0}};
  const html=renderToStaticMarkup(React.createElement(Review,{plan,query:'not-found',onApply(){},onDiscard(){},onChoose(){}}));
  assert.doesNotMatch(html,/<article/);assert.match(html,/disabled=""/);
});
test('a manual stylesheet cannot silently override newly reviewed visual mappings',()=>{
  const html=renderToStaticMarkup(React.createElement(Review,{plan:base,manualBinding:true,onApply(){},onDiscard(){},onChoose(){}}));
  assert.match(html,/manual XSLT stylesheet supplies runtime output/);assert.match(html,/disabled=""/);
});
