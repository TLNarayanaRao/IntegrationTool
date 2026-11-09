import assert from 'node:assert/strict';
import {readFile,stat} from 'node:fs/promises';
import test from 'node:test';
const base=new URL('../public/',import.meta.url);
test('all twenty API samples are installed, portable and self-contained project templates',async()=>{
 const catalog=JSON.parse(await readFile(new URL('samples/catalog.json',base),'utf8'));
 assert.equal(new Set(catalog.map(item=>item.id)).size,catalog.length);
 const samples=catalog.filter(item=>item.family==='http-rest');assert.equal(samples.length,20);
 for(const sample of samples){
  const project=JSON.parse(await readFile(new URL(sample.file.slice(1),base),'utf8'));
  assert.ok(project.tasks.some(task=>task.id===project.active_task_id));
  assert.equal(project.properties.local.find(prop=>prop.key==='demo.directory').value,'');
  const resources=new Set(project.resources.map(item=>item.id));
  for(const task of project.tasks)for(const activity of task.activities)if(activity.config.resourceId)assert.ok(resources.has(activity.config.resourceId));
  assert.ok(!JSON.stringify(project).includes('BEGIN PRIVATE KEY'));
 }
 assert.ok((await stat(new URL('samples/http-rest/MINA-HTTP-REST-Examples.zip',base))).size>1000);
 assert.match(await readFile(new URL('samples/http-rest/README.md',base),'utf8'),/Open directly from Studio Samples/);
});
