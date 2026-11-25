import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import ts from "typescript";

const source = await readFile(new URL("../src/ResponsiveRibbon.tsx", import.meta.url), "utf8");
const ast = ts.createSourceFile("ResponsiveRibbon.tsx", source, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
const fit = ast.statements.find(node => node.name?.text === "expandedRibbonSections");
const javascript = ts.transpileModule(fit.getText(ast), {compilerOptions:{module:ts.ModuleKind.ESNext}}).outputText;
const {expandedRibbonSections} = await import(`data:text/javascript;base64,${Buffer.from(javascript).toString("base64")}`);

test("reserves a dropdown for each section and expands the sections that fit", () => {
  const expanded = [360, 220, 740, 180, 200];
  const dropdowns = [76, 76, 76, 76, 76];
  assert.deepEqual(expandedRibbonSections(320, expanded, dropdowns), [false, false, false, false, false]);
  assert.deepEqual(expandedRibbonSections(820, expanded, dropdowns), [true, true, false, false, false]);
  assert.deepEqual(expandedRibbonSections(680, expanded, dropdowns), [true, false, false, false, false]);
  assert.deepEqual(expandedRibbonSections(1700, expanded, dropdowns), [true, true, true, true, true]);
});
