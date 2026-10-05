import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import test from 'node:test';
import ts from 'typescript';
const source=await readFile(new URL('../src/mapperLoopMappings.ts',import.meta.url),'utf8');
const {autoMapLoopChildren,relativeLoopExpression,expandLoopExpression}=await import(`data:text/javascript;base64,${Buffer.from(ts.transpileModule(source,{compilerOptions:{module:ts.ModuleKind.ESNext}}).outputText).toString('base64')}`);
const fields=[{path:'Record',type:'object[]',repeating:true},{path:'Record.Name',type:'string'},{path:'Record.Address',type:'object'},{path:'Record.Address.City',type:'string'},{path:'Record.Marks',type:'number'}];
const sources=[{activity:{id:'s',type:'start',name:'Read'},reference:'Read',distance:1,fields:[{key:'rows.name'},{key:'rows.address.city'},{key:'rows.MARKS'}]}];

test('loop-relative names expand only for real schema fields; plain string literals remain subject to quote validation',()=>{
  const paths=['activities.s.output.rows.name','Read.rows.name'];
  for(const scope of ['${activities.s.output.rows}','${Read.rows}']) {
    assert.equal(expandLoopExpression('name',scope,paths),scope.slice(0,-1)+'.name}');
    assert.equal(expandLoopExpression('sdfsf',scope,paths),'sdfsf');
    assert.equal(expandLoopExpression('123',scope,paths),'123');
    assert.equal(expandLoopExpression('"name"',scope,paths),'"name"');
  }
});

test('dragged collections map matching children without regard to case for every reference format',()=>{
  for(const expression of ['${Read.rows}','${activities.s.output.rows}','${input.rows}','${last.rows}']) {
    const rules=autoMapLoopChildren(fields,[{target:'Record',operator:'for-each',source:expression}],'Record',expression,sources);
    assert.deepEqual(rules.slice(1).map(r=>r.target),['Record.Name','Record.Address.City','Record.Marks']);
    assert.equal(rules[1].source,expression.slice(0,-1)+'.name}');
    assert.equal(rules[2].source,expression.slice(0,-1)+'.address.city}');
  }
});
test('automatic mapping preserves explicit mappings and keeps duplicate occurrences independent',()=>{
  const manual={target:'Record.Name',constant:'manual'};
  const other={target:'Record.Marks',constant:42,occurrenceId:'copy'};
  const rules=autoMapLoopChildren(fields,[manual,other],'Record','${Read.rows}',sources);
  assert.equal(rules.find(r=>r.target==='Record.Name'),manual);
  assert.equal(rules.find(r=>r.occurrenceId==='copy'),other);
  assert.equal(rules.find(r=>r.target==='Record.Marks'&&!r.occurrenceId).source,'${Read.rows.MARKS}');
});
test('ambiguous case matches are skipped and unmatched child fields stay unmapped',()=>{
  const rules=autoMapLoopChildren(fields,[],'Record','${Read.rows}',[{...sources[0],fields:[{key:'rows.name'},{key:'rows.NAME'}]}]);
  assert.deepEqual(rules,[]);
});
test('short paths are display-only and expand back to the correct collection scope',()=>{
  const scope='${Read.rows}';
  assert.equal(relativeLoopExpression('${Read.rows.address.city}',scope),'address.city');
  assert.equal(expandLoopExpression('address.city',scope),'${Read.rows.address.city}');
  for(const value of ["'literal'",'123','true','upperCase(name)','${Other.name}','']) assert.equal(expandLoopExpression(value,scope),value);
  assert.equal(relativeLoopExpression('${Other.name}',scope),'${Other.name}');
});

test('changing a loop source refreshes generated children but retains manual values',()=>{
  const manual={target:'Record.Name',constant:'custom'};
  const first=autoMapLoopChildren(fields,[manual],'Record','${Read.rows}',sources);
  const newSources=[...sources,{activity:{id:'other',name:'Other'},reference:'Other',fields:[{key:'records.name'},{key:'records.Address.City'},{key:'records.marks'}]}];
  const updated=autoMapLoopChildren(fields,first,'Record','${Other.records}',newSources);
  assert.equal(updated.find(r=>r.target==='Record.Name'),manual);
  assert.equal(updated.find(r=>r.target==='Record.Marks').source,'${Other.records.marks}');
  assert.equal(updated.filter(r=>r.target==='Record.Marks').length,1);
});
