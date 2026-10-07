import assert from 'node:assert/strict';
import {readFile, readdir} from 'node:fs/promises';
import test from 'node:test';
import vm from 'node:vm';
import ts from 'typescript';

test('activity SVG artwork has no small embedded activity captions', async () => {
  const directory = new URL('../src/assets/activity-icons/', import.meta.url);
  for (const name of await readdir(directory)) {
    if (!name.endsWith('.svg')) continue;
    const svg = await readFile(new URL(name, directory), 'utf8');
    if (name === 'end-stop.svg') {
      const labels = svg.match(/<text\b[^>]*>[\s\S]*?<\/text>/g) || [];
      assert.equal(labels.length, 1, 'End retains exactly one central stop-sign label');
      assert.match(labels[0], /x="128"/);
      assert.match(labels[0], /text-anchor="middle"/);
      assert.match(labels[0], /font-size="57"/);
      assert.match(labels[0], />End<\/text>/);
    } else assert.doesNotMatch(svg, /<text\b/i, name);
  }
});

test('shared icon loader chooses bundled artwork and preserves legacy PNGs', async () => {
  const source = await readFile(new URL('../src/activityIconUrl.ts', import.meta.url), 'utf8');
  const ast = ts.createSourceFile('icons.ts', source, ts.ScriptTarget.Latest, true);
  const declaration = ast.statements.find(statement => statement.name?.text === 'activityIconUrl');
  const context = vm.createContext({bundledIcons: {
    './assets/activity-icons/dataweave-transform.svg': '/assets/transform-content-hash.svg',
    './assets/activity-icons/mapper-symbol.svg': 'data:image/svg+xml,caption-free',
  }});
  vm.runInContext(ts.transpileModule(declaration.getText(ast).replace('export ', ''), {}).outputText, context);
  assert.equal(context.activityIconUrl('dataweave-transform.svg'), '/assets/transform-content-hash.svg');
  assert.equal(context.activityIconUrl('mapper-symbol.svg'), 'data:image/svg+xml,caption-free');
  assert.equal(context.activityIconUrl('FileRead'), '/activity-icons/FileRead.png');
});

test('canvas, palette and picker use the same icon loader', async () => {
  for (const name of ['main.tsx', 'ActivityPicker.tsx']) {
    const source = await readFile(new URL('../src/' + name, import.meta.url), 'utf8');
    assert.match(source, /src=\{activityIconUrl\(asset\)\}/, name);
  }
});
