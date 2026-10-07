import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import test from 'node:test';
import vm from 'node:vm';
import ts from 'typescript';
const source = await readFile(new URL('../src/CanvasMagnifier.tsx', import.meta.url), 'utf8');
const ast = ts.createSourceFile('magnifier.tsx', source, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
const declaration = ast.statements.find(statement => statement.name?.text === 'magnifierPosition');
const context = vm.createContext({});
vm.runInContext(ts.transpileModule(declaration.getText(ast).replace('export ', ''), {}).outputText, context);
test('magnifier flips at screen edges and stays inside short viewports', () => {
  for (const [width, height] of [[1440,900], [640,360], [320,240]]) {
    const lensWidth = Math.min(300,width-16), lensHeight = Math.min(220,height-16);
    for (const [x,y] of [[0,0],[width/2,height/2],[width-1,height-1]]) {
      const position = context.magnifierPosition(x,y,lensWidth,lensHeight,width,height);
      assert.ok(position.left >= 8 && position.top >= 8);
      assert.ok(position.left + lensWidth <= width - 8);
      assert.ok(position.top + lensHeight <= height - 8);
    }
  }
});
