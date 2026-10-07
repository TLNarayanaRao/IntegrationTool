import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import test from 'node:test';
import vm from 'node:vm';
import ts from 'typescript';
const source=await readFile(new URL('../src/executionMetrics.ts',import.meta.url),'utf8');
const context=vm.createContext({exports:{}});
vm.runInContext(ts.transpileModule(source,{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2021}}).outputText,context);
const {timingRecords,timingSummary,analyticsCsv,escapeReport}=context.exports;
test('timings count repeats, zero duration and failures without mixing tasks',()=>{
  const logs=[0,10,20].map(durationMs=>({kind:'activity',activityId:'a',taskId:'one',durationMs,level:durationMs===20?'ERROR':'INFO',payload:'secret'}));
  logs.push({kind:'activity',runtimeActivityId:'a',taskId:'two',durationMs:2},{kind:'activity',activityId:'a',durationMs:NaN},{kind:'lifecycle',durationMs:100});
  const records=timingRecords(logs),rows=timingSummary(records);
  assert.equal(records.length,4);assert.equal(rows.length,2);
  assert.equal(rows[0].total,30);assert.equal(rows[0].count,3);assert.equal(rows[0].failures,1);assert.equal(rows[0].mean,10);assert.equal(rows[0].p95,20);
  assert.equal(rows[0].min,0);assert.ok(!JSON.stringify(records).includes('secret'));
  assert.equal(timingSummary([]).length,0);
});
test('report exports escape HTML and spreadsheet formulas',()=>{
  assert.equal(escapeReport('<script>"&'), '&lt;script&gt;&quot;&amp;');
  const csv=analyticsCsv(timingSummary([{activityId:'a',taskId:'one',name:'=HYPERLINK("bad")',type:'mapper',durationMs:1,status:'completed',endedAt:''}]));
  assert.ok(csv.includes('"\'=HYPERLINK(""bad"")"'));
  const padded=analyticsCsv(timingSummary([{activityId:'a',taskId:'one',name:'  =1+1',type:'mapper',durationMs:1,status:'completed',endedAt:''}]));
  assert.ok(padded.includes('"\'  =1+1"'));
});
