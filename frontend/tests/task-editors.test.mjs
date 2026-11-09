import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import test from 'node:test';
import ts from 'typescript';
const source=await readFile(new URL('../src/taskEditors.ts',import.meta.url),'utf8');
const code=ts.transpileModule(source,{compilerOptions:{module:ts.ModuleKind.ESNext}}).outputText;
const {closeTaskEditors}=await import(`data:text/javascript;base64,${Buffer.from(code).toString('base64')}`);

test('closing the only editor leaves no active editor and does not reopen a task',()=>{
 assert.deepEqual(closeTaskEditors(['a'],'a','a','one'),{openIds:[],activeTaskId:null});
 assert.deepEqual(closeTaskEditors([],'a','a','one'),{openIds:[],activeTaskId:null});
});
test('Close All empties every editor, including when the active task was already closed',()=>{
 assert.deepEqual(closeTaskEditors(['a','b','c'],'b','b','all'),{openIds:[],activeTaskId:null});
 assert.deepEqual(closeTaskEditors(['b'],'a','a','all'),{openIds:[],activeTaskId:null});
});
test('closing active and background tabs selects only an already open neighbour',()=>{
 const ids=['a','b','c'];
 assert.deepEqual(closeTaskEditors(ids,'b','b','one'),{openIds:['a','c'],activeTaskId:'c'});
 assert.deepEqual(closeTaskEditors(ids,'c','a','one'),{openIds:['b','c'],activeTaskId:'c'});
 assert.deepEqual(ids,['a','b','c']);
});
test('close left, right and others preserve their intended editors',()=>{
 const ids=['a','b','c'];
 assert.deepEqual(closeTaskEditors(ids,'a','b','left'),{openIds:['b','c'],activeTaskId:'b'});
 assert.deepEqual(closeTaskEditors(ids,'b','b','right'),{openIds:['a','b'],activeTaskId:'b'});
 assert.deepEqual(closeTaskEditors(ids,'a','b','others'),{openIds:['b'],activeTaskId:'b'});
});
