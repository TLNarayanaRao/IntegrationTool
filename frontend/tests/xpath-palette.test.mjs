import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import test from 'node:test';
import ts from 'typescript';
import vm from 'node:vm';
const awaitSource=await readFile(new URL('../src/ActivityEditor.tsx',import.meta.url),'utf8');
const inventory=await readFile(new URL('../src/xpath-catalog.ts',import.meta.url),'utf8');
const helper=await readFile(new URL('../src/xpathPalette.ts',import.meta.url),'utf8');
const code=ts.transpileModule(inventory+'\n'+helper.replace(/^import .*;$/gm,''),{compilerOptions:{module:ts.ModuleKind.ESNext,target:ts.ScriptTarget.ES2022}}).outputText;
const {bundledXPathFunctions,designerXPathFunctions,xpathFunctionExpression,xpathSuggestions}=await import(`data:text/javascript;base64,${Buffer.from(code).toString('base64')}`);

test('all activity input fields suggest versioned XPath expressions and namespaced constructors',()=>{
 assert.ok(xpathSuggestions('flo').some(item=>item.insert==='xpath2("floor()")'));
 assert.ok(xpathSuggestions('xs:da').some(item=>item.insert==='xpath2("xs:date()")'));
 assert.deepEqual(xpathSuggestions('${input.flo'),[]);
 assert.deepEqual(xpathSuggestions('"flo'),[]);
 assert.ok(xpathSuggestions('xpath2("flo').some(item=>item.insert==='floor()'));
 assert.ok(!xpathSuggestions('xpath1("mat').some(item=>item.label.includes('matches')));
});

test('the designer has the full categorized catalog without a runtime request',()=>{
 const one=bundledXPathFunctions('1.0'),two=bundledXPathFunctions('2.0');
 assert.ok(one.length>=48);assert.ok(two.length>=200);
 for(const version of ['1.0','2.0']){
  const entries=bundledXPathFunctions(version);
  assert.equal(new Set(entries.map(item=>item.name+'#'+item.args.length)).size,entries.length);
  for(const item of entries){
   assert.ok(item.description);assert.ok(item.category);assert.ok(item.args.every(label=>label));
   assert.equal(item.example.args.length,item.args.length);
   assert.ok(item.example.expression.includes(item.name+'('));
   if(!item.example.error)assert.doesNotThrow(()=>JSON.parse(item.example.result));
  }
  assert.deepEqual(designerXPathFunctions(version,[]),entries);
  assert.ok(!entries.some(item=>['doc','collection','doc-available','trace'].includes(item.name)));
 }
 for(const name of ['avg','min','max','abs','floor','round-half-to-even','distinct-values','subsequence','matches','replace','tokenize','year-from-date','xs:dateTime']){
  assert.ok(two.some(item=>item.name===name),name);
 }
 assert.ok(!one.some(item=>item.name==='matches'));
 assert.deepEqual(one.filter(item=>item.name==='sum').map(item=>item.args.length),[1]);
 assert.deepEqual(two.filter(item=>item.name==='tokenize').map(item=>item.args.length),[2,3]);
});

test('live catalogs retain descriptions, correct overloads and readable argument labels',()=>{
 const old=designerXPathFunctions('2.0',[{name:'substring',args:['argument 1','argument 2','argument 3'],category:'Strings',signature:'example'}]);
 assert.deepEqual(old[0].args,['text','start','length']);assert.match(old[0].description,/one-based/);
 assert.equal(designerXPathFunctions('2.0',[{name:'doc',args:['uri']}]).length,0);
});

test('prepared sidebar expressions preserve XPath version, quotes and XML paths',()=>{
 const expression=xpathFunctionExpression('replace',['string(/order/id)',"'[.]'","'-'"],'2.0');
 assert.equal(expression,'xpath2("replace(string(/order/id), \'[.]\', \'-\')")');
 assert.equal(xpathFunctionExpression('count',['/orders/order'],'1.0'),'xpath1("count(/orders/order)")');
});

test('XPath catalog rows and the prepared expression button can be dragged to a target',async()=>{
 const source=await readFile(new URL('../src/XPathFunctionPalette.tsx',import.meta.url),'utf8');
 const component=ts.transpileModule(source.replace(/^import .*$/gm,'').replace('export default function','function'),{
  compilerOptions:{jsx:ts.JsxEmit.React,target:ts.ScriptTarget.ES2022},
 }).outputText;
 const all=node=>node&&typeof node==='object'?[node,...node.children.flatMap(all)]:[];
 const render=(version,selected='',values=[],onHelp=()=>{})=>{
  const states=[version,selected,values,null];
  const setters=[()=>{},()=>{},()=>{},onHelp];
  const context=vm.createContext({
   React:{createElement:(type,props,...children)=>({type,props,children:children.flat(Infinity)})},
   useState:()=>[states.shift(),setters.shift()],useRef:()=>({current:null}),useMemo:fn=>fn(),useEffect:()=>{},
   window:{clearTimeout:()=>{}},
   bundledXPathFunctions,xpathFunctionExpression,
  });
  vm.runInContext(component,context);
  return all(context.XPathFunctionPalette({onSelect:()=>{}})).filter(node=>node.type==='button');
 };
 const drag=(button,expression)=>{
  assert.equal(button.props.draggable,true);
  const values=new Map();
  const dataTransfer={setData:(format,value)=>values.set(format,value)};
  button.props.onDragStart({dataTransfer});
  assert.equal(dataTransfer.effectAllowed,'copy');
  assert.equal(values.get('expression'),expression);
  assert.equal(values.get('text/plain'),expression);
  assert.equal(values.get('sourceType'),'function');
 };
 const unprepared=render('1.0');
 drag(unprepared.find(node=>node.props.key==='count#1'),'xpath1("count()")');
 drag(unprepared.find(node=>node.props.key==='true#0'),'xpath1("true()")');

 const prepared=render('2.0','round-half-to-even#2',['/order/price','2']);
 const expression='xpath2("round-half-to-even(/order/price, 2)")';
 drag(prepared.find(node=>node.props.key==='round-half-to-even#2'),expression);
 drag(prepared.find(node=>node.children.includes('Drag XPath expression to target')),expression);
 drag(prepared.find(node=>node.props.key==='round-half-to-even#1'),'xpath2("round-half-to-even()")');
 let help;
 const buttons=render('2.0','substring#3',[],entry=>{help=entry;});
 buttons.find(node=>node.props.key==='substring#2').props.onDoubleClick();
 assert.equal(help.example.expression,"substring('MINA', 2)");
 assert.equal(JSON.parse(help.example.result),'INA');
 buttons.find(node=>node.children.includes('Function help')).props.onClick();
 assert.equal(help.example.expression,"substring('MINA', 2, 2)");
 assert.equal(JSON.parse(help.example.result),'IN');
});

test('XPath builder version selection is applied to the actual saved and tested expression',()=>{
 const source=awaitSource;
 const ast=ts.createSourceFile('editor.tsx',source,ts.ScriptTarget.Latest,true,ts.ScriptKind.TSX);
 const fn=ast.statements.find(node=>node.name?.text==='MapperXPathBuilder');
 const templates=ast.statements.find(node=>node.declarationList?.declarations.some(item=>item.name.getText(ast)==='xpathTemplates'));
 const states=['floor(9.8)','<root/>','',false,'',[],'',true,undefined,'',undefined,'2.0'];
 let saved;
 const context=vm.createContext({React:{createElement:(type,props,...children)=>({type,props,children:children.flat(Infinity)})},
  useState:()=>[states.shift(),()=>{}],useMemo:()=>[],useEffect:()=>{},designerXPathFunctions});
 vm.runInContext(ts.transpileModule(templates.getText(ast)+'\n'+fn.getText(ast),{compilerOptions:{jsx:ts.JsxEmit.React,target:ts.ScriptTarget.ES2022}}).outputText,context);
 const all=node=>node&&typeof node==='object'?[node,...(node.children||[]).flatMap(all)]:[];
 const nodes=all(context.MapperXPathBuilder({config:{xpathVersion:'1.0'},target:'number',apply:value=>saved=value}));
 assert.equal(nodes.find(node=>node.props?.['aria-label']==='Expression XPath version').props.value,'2.0');
 nodes.find(node=>node.type==='button'&&node.children.includes('Apply to ')).props.onClick();
 assert.equal(saved,'xpath2("floor(9.8)")');
});
