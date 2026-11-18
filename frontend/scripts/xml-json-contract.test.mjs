import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import ts from 'typescript';
import {DOMParser as XmlParser} from '@xmldom/xmldom';

// Supply browser DOM traversal properties to the actual schema-tree function.
// Conversion and schema logic remain the production implementation.
const sample = new XmlParser().parseFromString('<root/>','application/xml');
const prototype = Object.getPrototypeOf(sample.documentElement);
Object.defineProperty(prototype,'children',{configurable:true,get(){return Array.from(this.childNodes).filter(node=>node.nodeType===1);}});
Object.defineProperty(prototype,'parentElement',{configurable:true,get(){return this.parentNode?.nodeType===1?this.parentNode:null;}});
globalThis.DOMParser = class {
  parseFromString(text,type){
    const doc = new XmlParser().parseFromString(text,type);
    doc.querySelector = name=>doc.getElementsByTagName(name)[0]||null;
    return doc;
  }
};
const text = fs.readFileSync(new URL('../src/ActivityEditor.tsx',import.meta.url),'utf8');
const source = ts.createSourceFile('ActivityEditor.tsx',text,ts.ScriptTarget.Latest,true,ts.ScriptKind.TSX);
const wanted = ['activityContract','transformSchemaFields','formatSchemaOutputFields'];
const definitions = [];
for(const node of source.statements){
  if(ts.isFunctionDeclaration(node)&&wanted.includes(node.name?.text))definitions.push(node.getText(source));
  if(ts.isVariableStatement(node))for(const item of node.declarationList.declarations){
    if(ts.isIdentifier(item.name)&&['f','d'].includes(item.name.text))definitions.push('const '+item.getText(source)+';');
  }
}
const code = ts.transpileModule(definitions.join('\n')+'\nexport {transformSchemaFields};',
  {compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.ESNext}}).outputText;
const {activityContract,transformSchemaFields,formatSchemaOutputFields} = await import('data:text/javascript;base64,'+Buffer.from(code).toString('base64'));
const xsd = `<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema">
<xs:simpleType name="Price"><xs:restriction base="xs:decimal"/></xs:simpleType>
<xs:complexType name="Money"><xs:simpleContent><xs:extension base="Price"><xs:attribute name="currency" type="xs:string"/></xs:extension></xs:simpleContent></xs:complexType>
<xs:complexType name="Taxed"><xs:simpleContent><xs:extension base="Money"><xs:attribute name="tax" type="xs:boolean"/></xs:extension></xs:simpleContent></xs:complexType>
<xs:element name="invoice"><xs:complexType><xs:sequence><xs:element name="amount" type="Taxed" maxOccurs="unbounded"/>
<xs:element name="flag"><xs:complexType><xs:simpleContent><xs:extension base="xs:boolean"/></xs:simpleContent></xs:complexType></xs:element>
</xs:sequence></xs:complexType></xs:element></xs:schema>`;

test('Studio exposes inherited simple-content text beside attributes and retains repetition',()=>{
  const fields = transformSchemaFields({targetSchemaText:xsd});
  assert.equal(fields.find(f=>f.path==='invoice.amount').repeating,true);
  assert.equal(fields.find(f=>f.path==='invoice.amount.#text').type,'decimal');
  assert.equal(fields.find(f=>f.path==='invoice.amount.@currency').type,'string');
  assert.equal(fields.find(f=>f.path==='invoice.amount.@tax').type,'boolean');
  assert.equal(fields.find(f=>f.path==='invoice.flag').type,'boolean');
});

test('Parse JSON source paths match runtime aliases without mutating XML/render fields',()=>{
  const fields = [{key:'invoice.amount.@currency',label:'@currency',type:'string'}, {key:'invoice.amount.#text',label:'#text',type:'decimal'}];
  const converted = formatSchemaOutputFields({type:'json',config:{operation:'parse',schemaType:'XSD'}},fields);
  assert.deepEqual(converted.map(f=>f.key),['invoice.amount.currency','invoice.amount.$']);
  assert.deepEqual(fields.map(f=>f.key),['invoice.amount.@currency','invoice.amount.#text']);
  for(const node of [{type:'xml',config:{operation:'parse'}},{type:'json',config:{operation:'render',schemaType:'XSD'}},{type:'json',config:{operation:'parse',schemaType:'Native JSON'}}])assert.equal(formatSchemaOutputFields(node,fields),fields);
});

test('XML/JSON activity controls retain dynamic format options in Input',()=>{
  const binary = activityContract({type:'xml',config:{operation:'parse',inputStyle:'Dynamic'}});
  for(const key of ['xmlString','xmlBinary.bytes','xmlBinary.forceEncoding','xmlBinary.byteCount'])assert.ok(binary.input.some(f=>f.key===key),key);
  const render = activityContract({type:'xml',config:{operation:'render',outputStyle:'Binary'}});
  for(const key of ['byteEncoding','formatOptions.cdataElements','formatOptions.validateInput'])assert.ok(render.input.some(f=>f.key===key),key);
  for(const operation of ['parse','render']){
    const contract = activityContract({type:'json',config:{operation,schemaType:'XSD'}});
    assert.ok(contract.input.some(f=>f.key==='formatOptions.jsonStyle'));
    assert.ok(contract.input.some(f=>f.key==='formatOptions.'+(operation==='parse'?'validateOutput':'validateInput')));
    assert.ok(contract.configuration.every(f=>f.type==='boolean'||['schemaType'].includes(f.key)));
  }
});
