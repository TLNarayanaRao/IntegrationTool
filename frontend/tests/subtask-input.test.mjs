import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import ts from "typescript";

const source = await readFile(new URL("../src/subtaskInput.ts", import.meta.url), "utf8");
const js = ts.transpileModule(source, {compilerOptions:{module:ts.ModuleKind.ESNext}}).outputText;
const { decodeSubtaskXmlFile, guidedInputFields, newSubtaskInputDraft, readSubtaskInput, subtaskInputFormat } =
  await import(`data:text/javascript;base64,${Buffer.from(js).toString("base64")}`);

test("Start fields build nested input and preserve numbers, booleans, and repeated values", () => {
  const report = {format:"xsd", example:{order:{id:1,active:true,tags:["sample"],memo:"sample"}}, fields:[
    {path:"order.id", type:"integer", required:true}, {path:"order.tags", type:"string", repeating:true},
  ]};
  const fields = guidedInputFields(report);
  const [id, active, tags, memo] = fields;
  assert.equal(id.required, true);
  assert.equal(tags.type, "array");
  const draft = newSubtaskInputDraft(report);
  assert.equal(draft.method, "form");
  assert.deepEqual(readSubtaskInput(draft, fields), {});
  draft.values = {[id.key]:"0", [active.key]:"false", [tags.key]:'["one","two"]', [memo.key]:""};
  assert.deepEqual(readSubtaskInput(draft, fields), {order:{id:0,active:false,tags:["one","two"],memo:""}});
  draft.values[id.key] = '"text"';
  assert.throws(() => readSubtaskInput(draft, fields), /order.id must be a number/);
});

test("the selected source controls the payload and preserves literal JSON keys", () => {
  const fields = guidedInputFields({format:"json", example:JSON.parse('{"a.b":"example","__proto__":{"safe":true}}')});
  const draft = {method:"form", json:"null", file:{name:"fixture.json",text:"[1,2]"},
    values:{[fields[0].key]:"chosen", [fields[1].key]:"false"}};
  const guided = readSubtaskInput(draft, fields);
  assert.equal(Object.getPrototypeOf(guided), Object.prototype);
  assert.deepEqual(guided, JSON.parse('{"a.b":"chosen","__proto__":{"safe":false}}'));
  assert.equal(readSubtaskInput({...draft, method:"json"}, fields), null);
  assert.deepEqual(readSubtaskInput({...draft, method:"file"}, fields), [1,2]);
  assert.deepEqual(readSubtaskInput({...draft, method:"empty"}, fields), {});
  assert.throws(() => readSubtaskInput({...draft, method:"file", file:undefined}, fields), /Choose a JSON file/);
  assert.throws(() => readSubtaskInput({...draft, method:"file", file:{name:"bad.json",text:""}}, fields), /bad.json must contain valid JSON/);
});

test("XML input keeps the original document and decodes XML file encodings", () => {
  const text = '<?xml version="1.0" encoding="UTF-16"?><n:order xmlns:n="urn:orders">café</n:order>';
  for (const encoding of ["utf-16le", "utf-16be"]) {
    const bytes = new Uint8Array(2 + text.length * 2);
    const little = encoding.endsWith("le");
    const view = new DataView(bytes.buffer);
    view.setUint16(0, 0xfeff, little);
    for (let index = 0; index < text.length; index++) view.setUint16(2 + index * 2, text.charCodeAt(index), little);
    assert.equal(decodeSubtaskXmlFile(bytes.buffer), text);
  }
  const draft = {...newSubtaskInputDraft(), method:"xml-file", "xml-file":{name:"order.xml",text}, xml:"<other/>"};
  assert.equal(readSubtaskInput(draft, []), text);
  assert.equal(readSubtaskInput({...draft, method:"xml"}, []), "<other/>");
  assert.equal(subtaskInputFormat(draft.method), "xml");
  assert.equal(subtaskInputFormat("file"), "json");
  assert.throws(() => readSubtaskInput({...draft, method:"xml", xml:" "}, []), /Paste XML/);
  assert.throws(() => readSubtaskInput({...draft, "xml-file":undefined}, []), /Choose an XML file/);
});
