import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import test from 'node:test';
import vm from 'node:vm';
import ts from 'typescript';
const source=await readFile(new URL('../src/ActivityEditor.tsx',import.meta.url),'utf8');
const ast=ts.createSourceFile('editor.tsx',source,ts.ScriptTarget.Latest,true,ts.ScriptKind.TSX);
const names=['f','d','commonErrors','HTTP_METHODS','isMapperActivity','activityContract','httpRequestFields','httpRequestOccurrences','httpInputMappings','runtimeMappableInputs'];
const selected=ast.statements.filter(statement=>names.includes(statement.name?.text)||statement.declarationList?.declarations.some(item=>names.includes(item.name.text)));
const context=vm.createContext({});
vm.runInContext(ts.transpileModule(selected.map(statement=>statement.getText(ast).replace('export ','')).join('\n'),{compilerOptions:{target:ts.ScriptTarget.ES2022}}).outputText,context);

test('HTTP and REST requests expose a request tree without operational configuration fields',()=>{
  for(const node of [{type:'http',config:{operation:'request'}},{type:'rest',config:{operation:'invoke'}}]){
    const contract=context.activityContract(node);
    assert.deepEqual(Array.from(contract.configuration.map(field=>field.key)).filter(key=>['method','url','bodyType','timeout','contentType','accept'].includes(key)),[]);
    const input=context.runtimeMappableInputs(node,contract);
    for(const key of ['RestInputRequest.Config.host','RestInputRequest.Config.port','RestInputRequest.Config.Method','RestInputRequest.Config.requestURI','RestInputRequest.Config.RequestBody','RestInputRequest.Headers.accept','RestInputRequest.Headers.DynamicHeaders.name','RestInputRequest.mimeEnvelopeElement.mimePart.fileName'])assert(input.some(field=>field.key===key),key);
    assert.equal(input.find(field=>field.key==='RestInputRequest.Headers.DynamicHeaders').maxOccurs,'unbounded');
    assert(!input.some(field=>field.key==='openApiDocument'));
    assert(contract.output.some(field=>field.key==='RestOutputResponse.statusLine.reasonPhrase'));
  }
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
