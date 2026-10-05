import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';
import ts from 'typescript';
const source = await readFile(new URL('../src/mappingTree.ts', import.meta.url), 'utf8');
const compiled = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.ESNext } }).outputText;
const { mappingTreeRows } = await import(`data:text/javascript;base64,${Buffer.from(compiled).toString('base64')}`);
const fields = [
  {path:'Orders',name:'Orders',depth:0},
  {path:'Orders.Order',name:'Order',depth:1},
  {path:'Orders.Order.ProductName',name:'ProductName',depth:2},
  {path:'Orders.Order.Price',name:'Price',depth:2},
];
test('shared activity mappings wrap target and children under a For-Each', () => {
  const rows = mappingTreeRows(fields, {'Orders.Order':{$rule:'for-each',source:'${input.orders}'},'Orders.Order.Price':'${input.orders.price}'});
  assert.deepEqual(rows.map(row=>[row.kind,row.depth]),[['field',0],['loop',1],['field',2],['field',3],['field',3]]);
  assert.equal(rows[4].rule.source,'${input.orders.price}');
  assert.ok(rows[4].ancestors.includes(rows[1].key));
});
test('For-Each-Group places an editable Grouping row before the target', () => {
  const rows = mappingTreeRows(fields, [{target:'Orders.Order',operator:'for-each-group',source:'${input.orders}',groupBy:'ProductName'}]);
  assert.deepEqual(rows.slice(1,4).map(row=>row.kind),['loop','grouping','field']);
  assert.equal(rows[2].rule.groupBy,'ProductName');
});
test('duplicate occurrences contain independent, editable child trees', () => {
  const rows = mappingTreeRows(fields, [
    {target:'Orders.Order',operator:'for-each',source:'${input.first}'},
    {target:'Orders.Order.Price',source:'${input.first.price}'},
    {target:'Orders.Order',operator:'for-each',source:'${input.second}',occurrenceId:'second'},
    {target:'Orders.Order.Price',source:'${input.second.price}',occurrenceId:'second'},
  ]);
  const duplicate = rows.filter(row=>row.occurrenceId==='second');
  assert.deepEqual(duplicate.map(row=>row.kind),['field','field','field']);
  assert.equal(duplicate[2].rule.source,'${input.second.price}');
  assert.equal(duplicate[0].duplicateRoot,true);
  assert.equal(duplicate[0].depth,rows.find(row=>row.kind==='field' && row.field.path==='Orders.Order' && !row.occurrenceId).depth);
  assert.equal(duplicate[0].loopKey,undefined);
  assert.equal(new Set(rows.map(row=>row.key)).size,rows.length);
  assert.ok(!duplicate[2].ancestors.includes('primary:Orders.Order:loop'));
});

test('large schemas use indexed lookups rather than scanning every field for each row', () => {
  let pathReads = 0;
  const largeFields = [{path:'root',name:'root',depth:0}, ...Array.from({length:3000}, (_,i) => ({
    get path() { pathReads++; return `root.field${i}`; }, name:`field${i}`, depth:1,
  }))];
  const rows = mappingTreeRows(largeFields, []);
  assert.equal(rows.length,3001);
  assert.ok(pathReads < 3000 * 12, `Expected linear field access; observed ${pathReads} reads`);
});
