import test from 'node:test';
import assert from 'node:assert/strict';
import {fieldDescription, missingFieldDescriptions} from './field-documentation.mjs';

test('field documentation preserves authored editor help', () => {
 assert.equal(fieldDescription({key:'custom',help:'Exact authored guidance.'}), 'Exact authored guidance.');
});
test('provider timeout descriptions preserve their units', () => {
 assert.match(fieldDescription({key:'timeout'}, {type:'kafka'}), /seconds/);
 assert.match(fieldDescription({key:'timeout'}, {type:'http'}), /milliseconds/);
 assert.match(fieldDescription({key:'heartbeatIncomingMs'}, {type:'ems'}), /STOMP incoming.*milliseconds/);
});
test('nested dynamic header fields describe the pair rather than generic names', () => {
 assert.match(fieldDescription({key:'RestInputRequest.Headers.DynamicHeaders.name'}), /Custom HTTP header name/);
 assert.match(fieldDescription({key:'RestInputRequest.Headers.DynamicHeaders.value'}), /custom HTTP header/);
});
test('unknown fields are recorded for the build coverage gate', () => {
 const key='undocumentedRegressionField';
 assert.equal(fieldDescription({key},{type:'example'}), '');
 assert.ok(missingFieldDescriptions.has(`example: ${key}`));
 missingFieldDescriptions.delete(`example: ${key}`);
});
