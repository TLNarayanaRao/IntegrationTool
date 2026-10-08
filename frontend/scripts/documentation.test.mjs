import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
const base = new URL('../public/help/', import.meta.url);
const read = name => fs.readFileSync(new URL(name, base), 'utf8');
const model = JSON.parse(read('documentation-data.json'));
test('all topics have unique, linkable IDs and populated sections', () => {
 assert.equal(new Set(model.pages.map(p => p.id)).size, model.pages.length);
 assert.equal(model.counts.pages, model.pages.length);
 for (const p of model.pages) {
  assert.match(p.id, /^[a-z0-9-]+$/);
  assert.ok(p.title && p.category && p.sections.length);
  for (const s of p.sections) assert.ok(s.title && s.blocks.length);
 }
});
test('every activity has all six reference tabs', () => {
 const activities = model.pages.filter(p => p.id.startsWith('activity-'));
 assert.equal(activities.length, model.counts.activities);
 for (const p of activities) assert.deepEqual(p.sections.map(s=>s.title), ['Overview','Configuration','Input','Output','Advanced','Errors']);
});

test('every activity bundles its Studio icon for web and PDF documentation', () => {
 for (const page of model.pages.filter(p=>p.id.startsWith('activity-'))) {
  assert.match(page.icon, /^activity-icons\/[a-zA-Z0-9_.-]+$/);
  assert.match(page.iconPdf, /^activity-icons\/[a-zA-Z0-9_.-]+$/);
  assert.ok(fs.statSync(new URL(page.icon,base)).size>0,page.id);
  assert.ok(fs.statSync(new URL(page.iconPdf,base)).size>0,page.id);
 }
});

test('field reference tables contain authored guidance rather than missing-help notices', () => {
 assert.doesNotMatch(JSON.stringify(model), /No additional field description is supplied|Requiredness can also depend/i);
 for (const page of model.pages.filter(p=>p.id.startsWith('activity-')||p.id.startsWith('connection-'))) {
  for (const section of page.sections) for (const block of section.blocks.filter(b=>b.kind==='table'&&b.columns.at(-1)==='Details')) {
   for (const row of block.rows) {
    assert.ok(row[2].trim(),`${page.id}: ${row[0]}`);
    assert.doesNotMatch(row[2], /^See the .*procedure/,`${page.id}: ${row[0]}`);
   }
  }
 }
});

test('Mapper configuration documents its custom schema and policy controls', () => {
 const mapper=model.pages.find(p=>p.type==='mapper');
 const rows=mapper.sections.find(s=>s.title==='Configuration').blocks.find(b=>b.kind==='table').rows;
 for (const key of ['targetSchemaId','targetSchemaText','nullPolicy','typeCoercion','onMappingError','maxOutputSizeKb','validateOutput','trimStrings','removeEmptyStructures','copyNil']) {
  assert.ok(rows.some(row=>row[0].endsWith(`\n${key}`)),key);
 }
});
test('function, connection and group coverage matches generated counts', () => {
 for (const [prefix,key] of [['group-','groups'],['function-','functions'],['connection-','connections']]) {
  assert.equal(model.pages.filter(p=>p.id.startsWith(prefix)).length,model.counts[key]);
 }
 const picker=fs.readFileSync(new URL('../src/ActivityPicker.tsx',import.meta.url),'utf8');
 const groupSource=picker.slice(picker.indexOf('const groupEntries'),picker.indexOf('].map'));
 for(const match of groupSource.matchAll(/\["[^"]+", "([^"]+)"\]/g)) {
  assert.ok(model.pages.some(p=>p.id===`group-${match[1].replaceAll('_','-')}`));
 }
});
test('offline data script and JSON contain identical documentation', () => {
 const context={window:{}};vm.runInNewContext(read('documentation-data.js'), context);
 assert.equal(JSON.stringify(context.window.MINA_DOCUMENTATION),JSON.stringify(model));
 assert.equal(fs.readFileSync(new URL('MINA-Documentation.pdf',base)).subarray(0,5).toString(),'%PDF-');
});
test('Kafka, EMS and SAP each have activity-specific operational documentation', () => {
 const covered=model.pages.filter(p=>['kafka','ems','sap'].includes(p.type));
 assert.equal(covered.length,22);
 for(const p of covered){
  assert.equal(p.detailLevel,'operational',p.id);
  assert.ok(p.sections.find(s=>s.title==='Input').blocks.some(b=>b.kind==='code'),p.id);
  assert.ok(p.sections.find(s=>s.title==='Output').blocks.some(b=>b.kind==='code'),p.id);
  assert.ok(p.sections.find(s=>s.title==='Errors').blocks.some(b=>b.text==='Acceptance test'),p.id);
  assert.ok(p.sections.find(s=>s.title==='Advanced').blocks.some(b=>b.text==='Implemented behavior and limitations'),p.id);
  assert.doesNotMatch(JSON.stringify(p),/No additional field description is supplied/);
 }
});
test('viewer assets are bundled and text is not injected as HTML', () => {
 for(const name of ['documentation.css','documentation.js','documentation-data.js','MINA-Documentation.pdf']) assert.ok(fs.existsSync(new URL(name,base)));
 assert.doesNotMatch(read('documentation.js'), /\.innerHTML\s*=|\beval\(/);
 assert.match(read('documentation.js'), /textContent/);
});
test('developer source map covers every activity and group with verified locations', () => {
 for(const p of model.pages.filter(p=>p.type||p.id.startsWith('group-'))){
  const guide=model.pages.find(d=>d.id===`developer-${p.id}`);
  assert.ok(guide?.developer,p.id);
  assert.ok(guide.sourceRefs.length>0,p.id);
 }
 for(const page of model.pages.filter(p=>p.developer)) for(const ref of page.sourceRefs||[]){
  const source=fs.readFileSync(new URL(`../../${ref.file}`,import.meta.url),'utf8');
  assert.ok(ref.line>0);
  if(ref.symbol!=='(module)') assert.ok(source.split(/\r?\n/)[ref.line-1].includes(ref.symbol),`${ref.file}:${ref.line}`);
 }
 for(const key of ['tasks','run','debug','mapping','functions','drag-drop','groups','export','logging','function-index']) assert.ok(model.pages.some(p=>p.id===`developer-${key}`));
});
test('separate developer PDF model contains only developer topics', () => {
 const dev=JSON.parse(read('developer-data.json'));
 assert.equal(dev.manual,'developer');
 assert.ok(dev.pages.length>100);
 assert.ok(dev.pages.every(p=>p.developer));
 assert.equal(fs.readFileSync(new URL('MINA-Developer-Guide.pdf',base)).subarray(0,5).toString(),'%PDF-');
});
