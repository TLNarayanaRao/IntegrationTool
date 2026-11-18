import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
import test from 'node:test';
import picomatch from 'picomatch';

const require = createRequire(import.meta.url);

test('Studio build tools use the checked-in picomatch backport', () => {
  const local = require('../vendor/picomatch/package.json');
  for (const consumer of ['vite', 'tinyglobby', 'fdir']) {
    const resolve = createRequire(require.resolve(consumer));
    const installed = resolve('picomatch/package.json');
    assert.equal(installed.name, local.name, consumer);
    assert.equal(installed.version, local.version, consumer);
  }
});

test('the parser literalizes complex repeated groups and preserves common file globs', () => {
  for (const options of [{}, {maxExtglobRecursion: false}]) {
    const pattern = '+(report*)';
    const guarded = picomatch(pattern, options);
    assert.equal(guarded(pattern), true);
    assert.equal(guarded('report'), false);
  }
  assert.equal(picomatch('+(app|lib)')('applib'), true);
  assert.equal(picomatch('+(src)')('srcsrc'), true);
  assert.equal(picomatch('+(draft\\s)')('draft '), false);
  assert.equal(picomatch('+(App|app)', {nocase: true})('APP'), false);
  assert.equal(picomatch('src/**/*.{ts,tsx}')('src/panels/Main.tsx'), true);
});
