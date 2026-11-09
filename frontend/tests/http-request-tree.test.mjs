import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import test from 'node:test';
import vm from 'node:vm';
import ts from 'typescript';
const source=await readFile(new URL('../src/ActivityEditor.tsx',import.meta.url),'utf8');
const ast=ts.createSourceFile('editor.tsx',source,ts.ScriptTarget.Latest,true,ts.ScriptKind.TSX);
const names=['f','d','commonErrors','HTTP_METHODS','isMapperActivity','activityContract','httpRequestFields','httpRequestOccurrences','httpInputMappings','runtimeMappableInputs','resolvedActivityContract','schemaDataFields','transformSchemaFields','upstreamActivitySources'];
const selected=ast.statements.filter(statement=>names.includes(statement.name?.text)||statement.declarationList?.declarations.some(item=>names.includes(item.name.text)));
const context=vm.createContext({});
vm.runInContext(ts.transpileModule(selected.map(statement=>statement.getText(ast).replace('export ','')).join('\n'),{compilerOptions:{target:ts.ScriptTarget.ES2022}}).outputText,context);

test('HTTP method choices match API operations rather than proxy tunnels',()=>{
  const methods=Array.from(vm.runInContext('HTTP_METHODS',context));
  assert(methods.includes('TRACE'));
  assert(!methods.includes('CONNECT'));
});

test('HTTP Send Response exposes the selected endpoint response schema under body', () => {
  const response = { type: 'http_response', config: { operation: 'response' } };
  const schema = { type: 'object', properties: { result: { type: 'object', properties: { id: { type: 'integer' } } } } };
  for (const type of ['http_listener', 'rest']) {
    const endpoint = { type, config: { operation: type === 'rest' ? 'receiver' : 'listen', responseSchema: JSON.stringify(schema) } };
    const contract = context.resolvedActivityContract(response, { activities: [endpoint, response] }, [], []);
    assert.equal(contract.input.find(field => field.key === 'body.result.id').type, 'integer');
    assert(contract.input.some(field => field.key === 'headers'));
    assert(contract.input.some(field => field.key === 'body'));
  }
});

test('listeners expose request schema fields in Output and downstream Data sources', () => {
  const requestSchema = { type: 'object', properties: { order: { type: 'object', properties: { id: { type: 'integer' } } } } };
  const reply = { id: 'reply', type: 'http_response' };
  for (const type of ['http_listener', 'rest']) {
    const listener = { id: 'receive', type, config: { operation: type === 'rest' ? 'receiver' : 'listen', requestSchema } };
    const task = { activities: [listener, reply], transitions: [{ source: listener.id, target: reply.id }] };
    const outputs = context.resolvedActivityContract(listener, task, [], []).output;
    assert.equal(outputs.find(field => field.key === 'body.order.id').type, 'integer');
    assert(outputs.some(field => field.key === 'headers'));
    assert(context.upstreamActivitySources(reply, task)[0].fields.some(field => field.key === 'body.order.id'));
  }
});

test('HTTP and REST requests expose a request tree without operational configuration fields',()=>{
  for(const node of [{type:'http',config:{operation:'request'}},{type:'rest',config:{operation:'invoke'}}]){
    const contract=context.activityContract(node);
    assert.deepEqual(Array.from(contract.configuration.map(field=>field.key)).filter(key=>['method','url','bodyType','timeout','contentType','accept','openApiDocument','openApiBaseUrl','openApiReferenceDocuments','openApiAllowedRefOrigins','operationId','validateRequest','requestSchema','validateResponse','responseSchema'].includes(key)),[]);
    const input=context.runtimeMappableInputs(node,contract);
    for(const key of ['RestInputRequest.Config.host','RestInputRequest.Config.port','RestInputRequest.Config.Method','RestInputRequest.Config.requestURI','RestInputRequest.Config.RequestBody','RestInputRequest.Headers.accept','RestInputRequest.Headers.DynamicHeaders.name','RestInputRequest.mimeEnvelopeElement.mimePart.fileName'])assert(input.some(field=>field.key===key),key);
    assert.equal(input.find(field=>field.key==='RestInputRequest.Headers.DynamicHeaders').maxOccurs,'unbounded');
    assert(!input.some(field=>field.key==='openApiDocument'));
    assert(contract.output.some(field=>field.key==='RestOutputResponse.statusLine.reasonPhrase'));
  }
});

test('contract and validation defaults migrate into typed HTTP Input mappings',()=>{
 const config={operationId:'createOrder',openApiDocument:{openapi:'3.0.3'},openApiBaseUrl:'https://provider.test/spec.yaml',openApiReferenceDocuments:{},openApiAllowedRefOrigins:'https://provider.test',validateRequest:true,requestSchema:{type:'object'},validateResponse:false,responseSchema:{type:'string'}};
 const mappings=context.httpInputMappings(config);
 for(const [key,value] of Object.entries(config))assert.equal(mappings['RestInputRequest.Config.'+key],JSON.stringify(value));
 const fields=context.httpRequestFields();
 for(const key of Object.keys(config))assert(fields.some(field=>field.key==='RestInputRequest.Config.'+key));
 assert.equal(fields.find(field=>field.key==='RestInputRequest.Config.validateRequest').type,'boolean');
});

test('binary XML and rendered Data expose their actual mapping outputs',()=>{
 const xml=context.activityContract({type:'xml',config:{operation:'render',outputStyle:'Binary'}});
 assert(xml.output.some(field=>field.key==='binaryContent'));
 const data=context.activityContract({type:'flat',config:{operation:'render'}});
 assert(data.output.some(field=>field.key==='text'));
 assert(data.output.some(field=>field.key==='recordCount'));
 const json=context.activityContract({type:'json',config:{operation:'render'}});
 assert.equal(json.input.find(field=>field.key==='value').type,'any');
});

test('legacy request defaults become typed input mappings while expressions remain expressions',()=>{
  const mappings=context.httpInputMappings({method:'POST',url:'${properties.api.url}',body:{active:false},timeout:3,inputMappings:{body:'${input.body}',headers:'${input.headers}'}});
  assert.equal(mappings['RestInputRequest.Config.Method'],'"POST"');
  assert.equal(mappings['RestInputRequest.Config.requestURI'],'${properties.api.url}');
  assert.equal(mappings['RestInputRequest.Config.RequestBody'],'${input.body}');
  assert.equal(mappings['RestInputRequest.Config.timeout'],'3000');
  assert.equal(mappings['RestInputRequest.Headers'],'${input.headers}');
});

test('manual repeated header structures have independent name/value mappings',()=>{
  const mappings={'RestInputRequest.Headers.DynamicHeaders.0':'{}','RestInputRequest.Headers.DynamicHeaders.0.name':'"X-A"','RestInputRequest.Headers.DynamicHeaders.1':'{}'};
  const fields=context.httpRequestOccurrences(context.httpRequestFields(),mappings);
  assert(fields.some(field=>field.key==='RestInputRequest.Headers.DynamicHeaders.0.value'));
  assert(fields.some(field=>field.key==='RestInputRequest.Headers.DynamicHeaders.1.name'));
  assert(!fields.some(field=>field.key==='RestInputRequest.Headers.DynamicHeaders.name'));
  const refreshed=context.httpRequestOccurrences(fields,{...mappings,'RestInputRequest.Headers.DynamicHeaders.2':'{}'});
  assert(refreshed.some(field=>field.key==='RestInputRequest.Headers.DynamicHeaders.2.value'));
  assert(!refreshed.some(field=>field.key.includes('DynamicHeaders.0.0')));
});
test('old custom headers migrate into visible repeating name/value entries',()=>{
  const mappings=context.httpInputMappings({headers:{'Content-Type':'text/plain','X-Old':'before'},inputMappings:{'headers.X-Old':'${input.value}'}});
  assert.equal(mappings['RestInputRequest.Headers.content-type'],'"text/plain"');
  assert.equal(mappings['RestInputRequest.Headers.DynamicHeaders.0.name'],'"X-Old"');
  assert.equal(mappings['RestInputRequest.Headers.DynamicHeaders.0.value'],'${input.value}');
});
