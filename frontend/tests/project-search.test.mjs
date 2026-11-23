import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';
import ts from 'typescript';

const scriptUrl = source => 'data:text/javascript;base64,' + Buffer.from(
  ts.transpileModule(source, {compilerOptions: {module: ts.ModuleKind.ESNext}}).outputText,
).toString('base64');
const names = scriptUrl(await readFile(new URL('../src/studioObjectName.ts', import.meta.url), 'utf8'));
const source = await readFile(new URL('../src/projectSearch.ts', import.meta.url), 'utf8');
const {projectSearchIndex, searchProject, projectReferences} = await import(scriptUrl(source.replace('"./studioObjectName"', JSON.stringify(names))));

const fixture = {
  active_environment: 'local',
  tasks: [
    {id:'main', name:'Orders', kind:'starter', package_path:'Inbound', activities:[
      {id:'publish', name:'Publish Order', type:'kafka', config:{operation:'publish', resourceId:'bus', inputMappings:{topic:'${properties.orders.topic}'}}},
      {id:'call', name:'Dispatch', type:'call_task', config:{taskId:'Fulfillment/Validate', dynamicTaskId:'${properties.route.task}'}},
      {id:'parse', name:'Parse CSV', type:'flat', config:{operation:'parse', dataFormatId:'format'}},
    ], groups:[{name:'Transaction',config:{resourceId:'database'}}], transitions:[{id:'filter',source:'publish',condition:'${properties.orders.topic}'}]},
    {id:'validate',name:'Validate',kind:'subtask',package_path:'Fulfillment',activities:[]},
    {id:'alternate',name:'Alternate',kind:'subtask',activities:[]},
    {id:'sealed',name:'Shared API',kind:'subtask',library_origin:{alias:'ops',public:true},activities:[{id:'internal',name:'Hidden Implementation',type:'kafka',config:{resourceId:'bus'}}]},
    {id:'private',name:'Private Asset',kind:'subtask',library_origin:{alias:'ops',public:false},activities:[]},
  ],
  resources:[{id:'bus',name:'Order Broker',type:'kafka',config:{password:'hidden-password'}},{id:'database',name:'Orders DB',type:'jdbc'}],
  schemas:[{id:'format',name:'Records.json',content:'{"dataFormat":{"schemaId":"document"}}'},{id:'document',name:'Order.xsd'}],
  properties:{local:[{key:'orders.topic',value:'unpublished-value'},{key:'route.task',value:'alternate'}],qa:[{key:'route.task',value:'validate'}]},
};

test('project search filters by metadata without indexing protected internals or property values', () => {
  const index = projectSearchIndex(fixture,{tasks:['Inbound','Fulfillment']});
  assert.deepEqual(searchProject(index,'inbound kafka','Activity').map(row=>row.name),['Publish Order']);
  assert.deepEqual(searchProject(index,'inbound','Folder').map(row=>row.name),['Inbound']);
  assert.equal(searchProject(index,'shared api','Task')[0].location.kind,'library');
  for (const query of ['hidden implementation','private asset','hidden-password','unpublished-value']) {
    assert.deepEqual(searchProject(index,query,''),[]);
  }
});

test('find references resolves calls by qualified name and indicates property-driven environments', () => {
  const validate = projectReferences(fixture,{kind:'task',id:'validate'});
  assert.deepEqual(validate.map(row=>row.name),['Dispatch']);
  assert.match(validate[0].detail,/taskId.*dynamicTaskId \(qa\)/);
  const alternate = projectReferences(fixture,{kind:'task',id:'alternate'});
  assert.match(alternate[0].detail,/dynamicTaskId \(local\)/);
});

test('find references includes configured groups, Data Formats and property expressions', () => {
  const db = projectReferences(fixture,{kind:'resource',id:'database'});
  assert.equal(db[0].kind,'Group');
  assert.deepEqual(projectReferences(fixture,{kind:'resource',id:'bus'}).map(row=>row.name),['Publish Order']);
  assert.deepEqual(projectReferences(fixture,{kind:'schema',id:'format'}).map(row=>row.name),['Parse CSV']);
  assert.deepEqual(projectReferences(fixture,{kind:'schema',id:'document'}).map(row=>row.name),['Records.json']);
  assert.deepEqual(projectReferences(fixture,{kind:'property',id:'orders.topic'}).map(row=>row.name),['Publish Order','Transition condition']);
});
