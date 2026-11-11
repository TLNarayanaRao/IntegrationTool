import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import test from 'node:test';
import ts from 'typescript';
const source=await readFile(new URL('../src/mapperLoopMappings.ts',import.meta.url),'utf8');
const {activityMappingRules,activityMappingsFromRules,autoMapLoopChildren,emptyRepeatOccurrence,mapActivityRepeatingDrop,mapRepeatingDrop,relativeLoopExpression,expandLoopExpression,removeRepeatOccurrence}=await import(`data:text/javascript;base64,${Buffer.from(ts.transpileModule(source,{compilerOptions:{module:ts.ModuleKind.ESNext}}).outputText).toString('base64')}`);
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

test('Copy-Of replaces descendants in its occurrence but preserves the separate copy of the same collection',()=>{
  const rules = [{target:'Record.Name', source:'old'}, {target:'Record.Address.Lines', operator:'for-each', occurrenceId:'child',duplicateOf:'primary'},
    {target:'Record.Address.Lines.Value', occurrenceId:'child', source:'old'},
    {target:'Record',operator:'for-each',occurrenceId:'other',duplicateOf:'primary'}, {target:'Record.Name',occurrenceId:'other',source:'independent'}];
  const copied=mapRepeatingDrop(fields,rules,'Record','${Read.rows}',sources,'copy-of');
  assert.deepEqual(copied.slice(0,-1),rules.slice(-2));
  assert.equal(copied.at(-1).operator,'copy-of');
  assert.equal(copied.at(-1).source,'${Read.rows}');
});

test('SmartMap matches normalized paths within the dropped collection and skips ambiguous matches',()=>{
  const target=[...fields,{path:'Record.FirstName',type:'string'},{path:'Record.LastName',type:'string'}];
  const source=[{prefix:'coerced.orders',fields:[{key:'rows.name'},{key:'rows.first_name'},{key:'rows.last_name'},{key:'rows.last-name'}]}];
  const map = (mode) => mapRepeatingDrop(target,[],'Record','${coerced.orders.rows}',source,mode);
  assert.deepEqual(map('for-each').map(r=>r.target),['Record','Record.Name']);
  assert.deepEqual(map('smart-map').map(r=>r.target),['Record','Record.Name','Record.FirstName']);
  assert.equal(map('smart-map').at(-1).source,'${coerced.orders.rows.first_name}');
});

test('duplicating a copy or loop starts empty and replacing it keeps its identity and the primary bindings',()=>{
  const source = [...sources,{prefix:'coerced.other',fields:[{key:'rows.Name'}]}];
  for (const operator of ['copy-of','for-each']) {
    const primary = {target:'Record',operator,source:'${Read.rows}'};
    const originals = operator === 'for-each' ? [primary,{target:'Record.Name',source:'${Read.rows.name}'}] : [primary];
    const blank = emptyRepeatOccurrence('Record','object[]','second',undefined,primary);
    assert.equal(blank.source,'');
    assert.equal(blank.duplicateOf,'primary');
    const rules = [...originals, blank, emptyRepeatOccurrence('Record','object[]','third')];
    for (const mode of ['copy-of','for-each']) {
      const updated = mapRepeatingDrop(fields,rules,'Record','${coerced.other.rows}',source,mode,'second');
      assert.deepEqual(updated.slice(0,originals.length),originals);
      assert.equal(updated[originals.length].duplicateOf,'primary');
      assert.equal(updated[originals.length].source,'${coerced.other.rows}');
      assert.equal(updated.find(r=>r.target==='Record.Name' && r.occurrenceId==='second')?.source,
        mode === 'for-each' ? '${coerced.other.rows.Name}' : undefined);
      assert.deepEqual(removeRepeatOccurrence(updated,'second'),[...originals,rules.at(-1)]);
    }
  }
});

test('activity drop rules preserve unrelated mappings and replace fixed rows with dynamic bindings',()=>{
  const initial={status:'"ok"','Record.0.Name':'"old"'};
  const target=[...fields,{path:'Record.FirstName',type:'string'}];
  const upstream=[{prefix:'vars.orders',fields:[{key:'Name'},{key:'first_name'}]}];
  const map=(mode,mappings=initial,source='${vars.orders}')=>mapActivityRepeatingDrop(target,mappings,'Record',source,upstream,mode);
  const copied=map('copy-of');
  assert.deepEqual(copied,{status:'"ok"',Record:{$rule:'copy-of',source:'${vars.orders}'}});
  const loop=map('for-each',copied);
  assert.equal(loop['Record.Name'].source,'${vars.orders.Name}');
  assert.equal(loop['Record.FirstName'],undefined);
  const smart=map('smart-map',loop);
  assert.equal(smart['Record.FirstName'].source,'${vars.orders.first_name}');
  assert.equal(smart.Record.mapChildren,true);
  assert.equal(map('smart-map',smart,'')['Record.FirstName'],undefined);
});

test('activity duplicate scopes survive reload, remapping and deletion without touching the original',()=>{
  const original={Record:{$rule:'copy-of',source:'${input.first}'},'Record.0.Name':'"fixed"'};
  const blank=activityMappingsFromRules([...activityMappingRules(original),emptyRepeatOccurrence('Record','object[]','second')]);
  const loaded=JSON.parse(JSON.stringify(blank));
  assert.equal(loaded.$occurrences[0].source,'');
  const mapped=mapActivityRepeatingDrop(fields,loaded,'Record','${Read.rows}',sources,'for-each','second');
  assert.deepEqual(mapped.Record,original.Record);
  assert.equal(mapped['Record.0.Name'],original['Record.0.Name']);
  assert.equal(mapped.$occurrences.find(rule=>rule.target==='Record.Name').source,'${Read.rows.name}');
  assert.deepEqual(activityMappingsFromRules(removeRepeatOccurrence(activityMappingRules(mapped),'second')),original);
});
