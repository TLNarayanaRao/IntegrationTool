import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';
import vm from 'node:vm';
import ts from 'typescript';

const source = await readFile(new URL('../src/ActivityEditor.tsx', import.meta.url), 'utf8');
const ast = ts.createSourceFile('editor.tsx', source, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
const names = ['MappingBinding', 'MappingContextMenu'];
const compiled = ts.transpileModule(ast.statements.filter(s => names.includes(s.name?.text)).map(s => s.getText(ast)).join('\n'), {
  compilerOptions: { jsx: ts.JsxEmit.React, target: ts.ScriptTarget.ES2022 },
}).outputText;
function harness() {
  let cursor = 0; const state = [];
  const context = vm.createContext({
    React: { createElement: (type, props, ...children) => ({type, props: props || {}, children: children.flat(Infinity)}) },
    useState: initial => { const i = cursor++; if (!(i in state)) state[i] = typeof initial === 'function' ? initial() : initial; return [state[i], v => { state[i] = typeof v === 'function' ? v(state[i]) : v; }]; },
    useEffect: () => {}, useRef: () => ({current: null}),
    mappingSource: v => v && typeof v === 'object' ? v.source : v,
    MappingExpressionInput: 'expression-input', Braces: 'icon', DataNodeIcon: 'icon', Plus: 'icon',
    createPortal: v => v, document: {body: {}}, window: {innerWidth: 1200, innerHeight: 900},
  });
  vm.runInContext(compiled, context);
  return (name, props) => { cursor = 0; return context[name](props); };
}
function all(node) { return node && typeof node === 'object' ? [node, ...(node.children || []).flatMap(all)] : []; }

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
