# Product audit — 5 October 2026

This report records the earlier audit baseline. The subsequent capability pass
extends its schema support and adds reusable tests, templates, streaming tools
and durable message activities. See [Transformation capabilities](TRANSFORMATION_CAPABILITIES.md)
for current behavior and limits; the baseline limitations below are historical.

This pass covered Studio mapping and schema handling, transformation execution,
Python Direct and Engine archives, project persistence/import, SFTP configuration,
and Control Plane authentication/package inspection. Mapper remains the
transformation activity; the removed Mediation activity was not restored.

## Fixes and added capabilities

- Local JSON Schema references, nullable types and bounded recursive schema trees.
  XSD trees include inherited fields, attributes and nested anonymous types.
- Runtime JSON contract checks for required fields, types, enum/const, local
  references, composition, additional properties, array bounds/uniqueness/tuple
  items, string length and numeric bounds/multiples. JSON activities use these
  checks when validation is requested.
- Current selected project schemas take precedence over stale cached schema
  content in the editor, runtime and archive compiler.
- Export validation derives literal types through referenced schemas. Nullable
  string fields still require quotes for string constants.
- Generic Input literals retain numeric, boolean, object and array types. Quoted
  strings containing reference syntax remain literal in exported Python.
- JSON Parse and Render use consistent result shapes, duplicate-key policies,
  mapped root fields, null removal and serialization in Studio and archives.
- Start and End evaluate input mappings once. Nested loops reuse their mapping
  plans; mapping recommendations reuse name tokens and similarity calculations.
- SFTP shares host-key verification, known hosts, private-key/passphrase, agent
  and timeout settings across Studio and archives; failed connections are closed.
- Concurrent project reads/writes are serialized within the Studio process;
  temporary filenames are unique and identifiers are checked before saving.
- Project imports limit uploaded and expanded payload size and reject duplicate
  payload entries. Control Plane packages reject unsafe portable paths,
  case-insensitive duplicate entries and ZIP symbolic links.
- Credential-free Control Plane Owner access is limited to direct localhost
  requests with matching browser origins. Remote/proxied access requires an API
  key or scoped token. Invalid token expiration values fail closed.

## Verification and limits

Final verification passed: 240 backend tests, 84 frontend/desktop tests,
30 Control Plane Python tests and seven Control Plane UI tests (361 total).
TypeScript compilation, the Vite production build, documentation fingerprints
and Git whitespace checks passed. The regenerated help covers 96 activities,
11 groups, 98 functions and 12 shared connection types. The production build
still reports a large JavaScript bundle warning; this pass did not add code
splitting or claim to eliminate every performance bottleneck.

Regression suites exercise frontend mapping behavior, backend activities,
generated Python applications and Control Plane security/package handling.
Archive parity tests execute both Python formats in separate processes; Direct
archives are also executed as ZIP applications. A browser check exercised the
actual XSD tree function with inheritance, attributes and recursive types.

A synthetic nested-loop benchmark (300 parent records, eight child records,
eight child mappings and 400 unrelated mappings) preserved identical output.
The median of three runs was 201 ms without cached loop planning and 178 ms with
it. This is a fixture measurement, not a guarantee for other workloads or UI
interaction times.

This is a concrete audit pass, not a claim that every possible issue is fixed.
The JSON Schema validator supports a documented subset: remote references,
patternProperties, pattern and format constraints are not supported. XSD is
also a subset, not a complete standards validator. Store locking is local to
one process, not a distributed or crash-atomic transaction. Live SAP, brokers,
databases and SFTP providers still require qualification with deployment
credentials and representative production payloads. Connector authentication
was tested with mocks, not a live SFTP server.
