import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';
import vm from 'node:vm';
import ts from 'typescript';

const source = await readFile(new URL('../src/ActivityEditor.tsx', import.meta.url), 'utf8');
const validationSource = await readFile(new URL('../src/mappingValidation.ts', import.meta.url), 'utf8');
const loopSource = await readFile(new URL('../src/mapperLoopMappings.ts', import.meta.url), 'utf8');
const importTs = text => import(`data:text/javascript;base64,${Buffer.from(ts.transpileModule(text,{compilerOptions:{module:ts.ModuleKind.ESNext}}).outputText).toString('base64')}`);
const {validateMapping} = await importTs(validationSource);
const {relativeLoopExpression,expandLoopExpression} = await importTs(loopSource);
const ast = ts.createSourceFile('editor.tsx', source, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
const names = ['MappingBindingContent', 'MappingContextMenu'];
const mappingSourceDeclaration = ast.statements.find(s => ts.isVariableStatement(s) && s.declarationList.declarations.some(d => d.name.getText(ast) === 'mappingSource'));
const compiled = ts.transpileModule([mappingSourceDeclaration, ...ast.statements.filter(s => names.includes(s.name?.text))].map(s => s.getText(ast)).join('\n'), {
  compilerOptions: { jsx: ts.JsxEmit.React, target: ts.ScriptTarget.ES2022 },
}).outputText;
function harness({effects = [], eventWindow = {}} = {}) {
  let cursor = 0; const state = [];
  const context = vm.createContext({
    React: { createElement: (type, props, ...children) => ({type, props: props || {}, children: children.flat(Infinity)}) },
    useState: initial => { const i = cursor++; if (!(i in state)) state[i] = typeof initial === 'function' ? initial() : initial; return [state[i], v => { state[i] = typeof v === 'function' ? v(state[i]) : v; }]; },
    useEffect: effect => effects.push(effect), useRef: () => ({current: null}),
    mappingCompletionPaths: () => ['input', 'last'], relativeLoopExpression, expandLoopExpression, validateMapping, isComplexSchemaType:()=>false,
    MappingBinding:'mapping-binding', MappingExpressionInput: 'expression-input', Braces: 'icon', DataNodeIcon: 'icon', Plus: 'icon',
    createPortal: v => v, document: {body: {}}, window: {innerWidth: 1200, innerHeight: 900, ...eventWindow},
  });
  vm.runInContext(compiled, context);
  return (name, props) => { cursor = 0; return context[name === 'MappingBinding' ? 'MappingBindingContent' : name](props); };
}
function all(node) { return node && typeof node === 'object' ? [node, ...(node.children || []).flatMap(all)] : []; }

test('schema-typed bindings report commit success and retain dark-red invalid state for bad literals',()=>{
  for(const [type,raw,valid] of [['string','sdfsf',false],['string','123',false],['string','"test"',true],['string',"'test'",true],['number','123',true],['number','"123"',false],['xs:string','bare',false],['xs:decimal','1.2',true]]) {
    const render=harness();
    const props={expression:raw,fieldType:type,sources:[],onChange() {},sourceScope:'${last.rows}'};
    const tree=render('MappingBinding',props);
    const input=all(tree).find(n=>n.type==='expression-input');
    assert.equal(tree.props.className.includes('mapping-invalid'),!valid, 'invalid saved and typed values are marked before Enter');
    assert.equal(!!input.props.error,!valid);
    assert.equal(input.props.onCommit(raw),valid,`${type}: ${raw}`);
    const committed=render('MappingBinding',props);
    assert.equal(committed.props.className.includes('mapping-invalid'),!valid);
    assert.equal(!!all(committed).find(n=>n.type==='expression-input').props.error,!valid);
  }
});

test('For Each and For Each Group apply immediately with inline editable expressions', () => {
  for (const [label,operator] of [['For Each…','for-each'],['For Each Group…','for-each-group']]) {
    for (const value of ['', '${input.rows}', {operator,source:'${input.rows}',groupBy:'product',target:'rows'}]) {
      let saved; let closed=0;
      const tree=harness()('MappingContextMenu',{menu:{label:'Rows',x:0,y:0},value,change:v=>saved=v,close:()=>closed++});
      all(tree).find(n=>n.type==='button' && n.children.includes(label)).props.onClick();
      assert.equal(saved.$rule,operator);assert.equal(saved.operator,operator);assert.equal(closed,1);
      assert.equal(saved.source, typeof value==='object' ? value.source : value);
      if (operator==='for-each-group') assert.equal(saved.groupBy,typeof value==='object' ? 'product' : '');
    }
  }
});

test('If applies directly to the field and closes the menu without a setup popup', () => {
  for (const value of ['', '${input.status}', {target:'status', constant:'ready', enabled:true}]) {
    let saved; let closed = 0;
    const tree = harness()('MappingContextMenu', {menu:{label:'Status',x:0,y:0},value,change:v=>saved=v,close:()=>closed++});
    all(tree).find(n=>n.type==='button' && n.children.includes('If…')).props.onClick();
    assert.equal(saved.$rule,'if'); assert.equal(saved.operator,'if'); assert.equal(saved.condition,'');
    assert.equal(saved.source, typeof value === 'object' ? '"ready"' : value);
    assert.equal(saved.constant,undefined); assert.equal(closed,1);
    const inline = harness()('MappingBinding', {expression:saved,sources:[],fieldLabel:'Status',onChange() {}});
    assert.equal(all(inline).filter(n=>n.type==='details').length,1);
    assert.ok(all(inline).some(n=>n.type==='span' && n.children.includes('[If]')));
  }
});

test('selecting If again preserves its existing condition and mapped value', () => {
  let saved;
  const value = {operator:'if', source:'${input.status}',condition:'${input.enabled}',target:'status'};
  const tree=harness()('MappingContextMenu',{menu:{label:'Status',x:0,y:0},value,change:v=>saved=v,close() {}});
  all(tree).find(n=>n.type==='button' && n.children.includes('If…')).props.onClick();
  assert.equal(saved.condition,value.condition);assert.equal(saved.source,value.source);assert.equal(saved.target,'status');
});

test('outside clicks dismiss the popup before configuration stops propagation; inside clicks keep it open', () => {
  const effects = []; let listener; let removed; let closed = 0;
  const eventWindow = {
    addEventListener: (...args) => listener = args,
    removeEventListener: (...args) => removed = args,
  };
  const tree = harness({effects, eventWindow})('MappingContextMenu', {menu:{label:'Status', x:0, y:0}, value:'', close:() => closed++, change() {}});
  const inside = {};
  tree.props.ref.current = {contains: target => target === inside};
  const cleanup = effects[1]();
  assert.equal(listener[0], 'pointerdown');
  assert.equal(listener[2], true, 'capture listener runs even when the configuration panel stops bubbling');
  listener[1]({target:inside}); assert.equal(closed, 0);
  listener[1]({target:{}}); assert.equal(closed, 1);
  cleanup(); assert.deepEqual(removed, listener);
});

test('deleting an individual When preserves the other mappings and renumbers branches', () => {
  const render = harness(); let saved; let prevented = false; let stopped = false;
  const expression = {$rule:'choose', whens:[{condition:'a', source:'first'}, {condition:'b', source:'second'}, {condition:'c', source:'third'}], otherwise:'fallback', target:'status'};
  const props = {expression, sources:[], onChange: v => saved = v};
  let tree = render('MappingBinding', props);
  all(tree).find(n => n.props['aria-label'] === 'Delete When 2').props.onClick({preventDefault() {prevented = true;}, stopPropagation() {stopped = true;}});
  assert.ok(prevented && stopped);
  assert.deepEqual(JSON.parse(JSON.stringify(saved.whens)), [expression.whens[0], expression.whens[2]]);
  assert.equal(saved.source, JSON.stringify(saved.whens));
  assert.equal(saved.otherwise, 'fallback'); assert.equal(saved.target, 'status');
  assert.equal(expression.whens.length, 3);
  tree = render('MappingBinding', {...props, expression:saved});
  assert.equal(all(tree).filter(n => n.props['aria-label']?.startsWith('Delete When')).length, 2);
  assert.equal(all(tree).find(n => n.props.label === 'When 2 condition').props.value, 'c');
});

test('the final When cannot be deleted, including legacy conditions', () => {
  for (const expression of [
    {$rule:'choose', whens:[{condition:'true', source:'yes'}], source:'[{"condition":"true","source":"yes"}]', otherwise:'fallback'},
    {$rule:'when-otherwise', condition:'true', source:'yes', otherwise:'fallback'},
  ]) {
    const render = harness(); let saved;
    const props = {expression, sources:[], onChange:v => saved = v};
    const tree = render('MappingBinding', props);
    const remove = all(tree).find(n => n.props['aria-label'] === 'Delete When 1');
    assert.equal(remove.props.disabled, true);
    assert.equal(remove.props.title, 'At least one When condition is required');
    remove.props.onClick({preventDefault() {}, stopPropagation() {}});
    assert.equal(saved, undefined);
    assert.equal(all(tree).filter(n => n.type === 'details').length, 2);
  }
});

test('branch count creates exactly N field-local Whens and Otherwise', () => {
  const render = harness(); let saved;
  const props = { menu: {label: 'order.status', x: 0, y: 0}, value: '${input.status}', change: v => saved = v, close() {} };
  let tree = render('MappingContextMenu', props);
  all(tree).find(n => n.type === 'button' && n.children.includes('When / Otherwise…')).props.onClick();
  tree = render('MappingContextMenu', props);
  all(tree).find(n => n.type === 'input' && n.props.type === 'number').props.onChange({target: {value: '3'}});
  tree = render('MappingContextMenu', props);
  all(tree).find(n => n.type === 'button' && n.children.includes('Create branches')).props.onClick();
  assert.equal(saved.$rule, 'choose'); assert.equal(saved.whens.length, 3);
  assert.equal(saved.otherwise, ''); assert.equal(saved.whens[0].source, '${input.status}');
});

test('field renders expandable When and Otherwise branches and edits only selected branch', () => {
  const render = harness(); let saved;
  const expression = {$rule:'choose', whens:[{condition:'false', source:'first'}, {condition:'true', source:'second'}], otherwise:'fallback'};
  const tree = render('MappingBinding', {expression, sources: [], onChange: v => saved = v});
  assert.equal(all(tree).filter(n => n.type === 'details').length, 3);
  const condition = all(tree).find(n => n.type === 'expression-input' && n.props.label === 'When 2 condition');
  condition.props.onChange('${input.enabled}');
  assert.equal(saved.whens[0].source, 'first'); assert.equal(saved.whens[1].condition, '${input.enabled}');
  assert.equal(expression.whens[1].condition, 'true'); assert.equal(saved.otherwise, 'fallback');
});

test('legacy single When/Otherwise renders inline without conversion or lost fallback', () => {
  const tree = harness()('MappingBinding', {expression: {$rule:'when-otherwise', condition:'true', source:'yes', otherwise:'no'}, onChange() {}, sources: []});
  assert.equal(all(tree).filter(n => n.type === 'details').length, 2);
});

test('compact conditions put the expression beside its branch and can collapse as a whole', () => {
  const render = harness();
  const props = { expression: {$rule:'choose', whens:[{condition:'true', source:"'yes'"}], otherwise:"'no'"}, fieldLabel:'Status', sources:[], onChange() {} };
  let tree = render('MappingBinding', props);
  assert.match(tree.props.className, /compact-condition-tree/);
  const summary = all(tree).find(n => n.type === 'summary');
  assert.ok(all(summary).some(n => n.type === 'expression-input' && n.props.label === 'When 1 condition' && n.props.multiline));
  assert.equal(all(tree).filter(n => n.props?.className === 'condition-value-row').length, 2);
  all(tree).find(n => n.props?.['aria-label'] === 'Collapse field conditions').props.onClick();
  tree = render('MappingBinding', props);
  assert.equal(all(tree).filter(n => n.type === 'details').length, 0);
  assert.equal(props.expression.whens[0].source, "'yes'");
});

test('If unwraps ordinary and previously nested mapping records without displaying metadata', () => {
  const original = {target:'Record.Name', source:'${input.rows.Name}', functions:[], enabled:true, autoGenerated:true};
  for (const value of [original, {...original,source:original}]) {
    let saved;
    const tree=harness()('MappingContextMenu',{menu:{label:'Name',x:0,y:0},value,change:v=>saved=v,close() {}});
    all(tree).find(n=>n.type==='button' && n.children.some(c=>typeof c==='string'&&c.startsWith('If'))).props.onClick();
    assert.equal(saved.source,original.source);
    const inline=harness()('MappingBinding',{expression:saved,sources:[],fieldLabel:'Name',onChange() {}});
    assert.equal(all(inline).find(n=>n.type==='mapping-binding').props.expression,original.source);
  }
});
