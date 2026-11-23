import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';
import ts from 'typescript';

const source = await readFile(new URL('../src/canvasViewport.ts', import.meta.url), 'utf8');
const compiled = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.ESNext } }).outputText;
const { centeredCanvasScroll, fitCanvasView } = await import('data:text/javascript;base64,' + Buffer.from(compiled).toString('base64'));

test('fits a distant diagram within the tighter viewport dimension', () => {
  const viewport = { width: 1000, height: 248 };
  const boxes = [{ left: 120, top: 130, right: 224, bottom: 224 }, { left: 2300, top: 1100, right: 2404, bottom: 1194 }];
  const view = fitCanvasView(boxes, viewport, 1);
  const scroll = centeredCanvasScroll(view.center, viewport, view.zoom);
  for (const box of boxes) {
    assert.ok(box.left * view.zoom - scroll.left >= 0);
    assert.ok(box.top * view.zoom - scroll.top >= 0);
    assert.ok(box.right * view.zoom - scroll.left <= viewport.width);
    assert.ok(box.bottom * view.zoom - scroll.top <= viewport.height);
  }
  assert.ok(view.zoom < 0.6);
});

test('keeps a zoom anchor and handles compact, empty, and origin-adjacent diagrams', () => {
  const viewport = { width: 800, height: 400 };
  assert.deepEqual(centeredCanvasScroll({ x: 700, y: 550 }, viewport, 1.2), { left: 440, top: 460 });
  assert.deepEqual(centeredCanvasScroll({ x: 100, y: 50 }, viewport, 1), { left: 0, top: 0 });
  const bounds = [{ left: 0, top: 0, right: 104, bottom: 94 }];
  assert.equal(fitCanvasView(bounds, viewport, 1).zoom, 1);
  assert.equal(fitCanvasView([], viewport, 1), undefined);
  assert.equal(fitCanvasView(bounds, { width: 0, height: 400 }, 1), undefined);
});
