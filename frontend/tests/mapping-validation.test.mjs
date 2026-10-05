import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';
import ts from 'typescript';
const source = await readFile(new URL('../src/mappingValidation.ts', import.meta.url), 'utf8');
const compiled = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.ESNext } }).outputText;
const { validateMapping } = await import(`data:text/javascript;base64,${Buffer.from(compiled).toString('base64')}`);
const paths = ['input', 'last', 'Read-JSON', 'Read-JSON.customer.name', 'Read-JSON.records.value'];

test('checks numeric and boolean constants without accepting quoted numbers', () => {
  assert.equal(validateMapping('123','xs:decimal'),'');
  assert.ok(validateMapping('"123"','xs:decimal'));
  for (const value of ['123', '-4']) assert.equal(validateMapping(value, 'integer'), '');
  for (const value of ['abc', '1.5', '"123"']) assert.ok(validateMapping(value, 'integer'));
  assert.equal(validateMapping('1.25e2', 'decimal'), '');
  assert.equal(validateMapping('false', 'boolean'), '');
  assert.ok(validateMapping('yes', 'boolean'));
});
test('requires matching quotes for string constants, including numeric-looking strings', () => {
  for(const type of ['xs:string','xsd:token','normalizedString','dateTime','anyURI']) {
    assert.match(validateMapping('test',type),/quotes/);
    assert.equal(validateMapping('"test"',type),'');
  }
  for (const value of ["'hello'", '"hello"', '"hello \\"world\\""', "'123'", '"123"']) assert.equal(validateMapping(value, 'string'), '');
  for (const value of ['hello', '123', 'true']) assert.match(validateMapping(value, 'string'), /quotes/);
  assert.match(validateMapping('hello', 'any'), /quotes/);
  assert.equal(validateMapping('123', 'any'), '');
  assert.ok(validateMapping("'hello", 'string'));
  assert.equal(validateMapping('', 'integer'), '');
});
test('rejects scalar constants in array/object fields', () => {
  assert.ok(validateMapping("'gfgf'", 'array'));
  assert.ok(validateMapping('hello', 'object'));
  assert.equal(validateMapping('[1, 2]', 'array'), '');
  assert.equal(validateMapping('{"value": 1}', 'object'), '');
  assert.ok(validateMapping('hello', 'object|string|binary'));
  assert.equal(validateMapping('"hello"', 'object|string|binary'), '');
});
test('validates known source paths and nested function references', () => {
  for (const value of ['${Read-JSON.customer.name}', 'upperCase(${Read-JSON.customer.name})', '${Read-JSON.customer}', '${Read-JSON.records[0].value}', '${properties.customer}', '${vars.current}', '${last.dynamic}']) assert.equal(validateMapping(value, 'string', paths), '');
  assert.ok(validateMapping('${Unknown.value}', 'string', paths));
  assert.ok(validateMapping('${Read-JSON.customer.typo}', 'string', paths));
  assert.ok(validateMapping('upperCase(${Read-JSON.customer.typo})', 'string', paths));
  assert.ok(validateMapping('${Read-JSON.customer.name', 'string', paths));
  assert.ok(validateMapping('concat("a", "b"', 'string', paths));
  assert.equal(validateMapping('concat("literal ${Unknown.value}", "!")', 'string', paths), '');
});

test('nullable string contracts do not bypass quote validation', () => {
  assert.equal(validateMapping('null', 'string|null'), '');
  assert.equal(validateMapping('"Ada"', 'string|null'), '');
  for (const value of ['123','unquoted','true']) assert.match(validateMapping(value,'string|null'), /quotes/);
  assert.ok(validateMapping('123','null'));
});
