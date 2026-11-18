# XML and JSON activity verification — 2026-11-17

## Scope

The initial pass tested MINA against documented Parse and Render activity contracts. The installed runtime comparison covers text XML, dynamic binary XML with ASCII CDATA, and XSD-based JSON with and without a root wrapper.

## Installed 6.13 Preview V54 comparison

The isolated reference fixture runs Timer → Parse XML → Render XML → Parse JSON → Render JSON → Log. Both parsers use the same synthetic record expressed in their respective formats. The record includes an XML namespace, a boolean attribute, an integer, two ordered items, and Unicode text containing XML and JSON escape characters.

The six fixture errors came from two unresolved schema types. Moving the generated schema nodes dropped namespace declarations used by QName-valued type attributes. Keeping those schema nodes in place resolved the Parse JSON and Log binding errors. The fixture also retains each parsed or rendered result until its last consumer, so both rendered outputs reach the logger. The final design validation reported **zero errors and zero warnings**, exported a deployable EAR, and the application ran in the installed runtime.

| Case | Reference runtime | MINA Run | MINA Debug | Direct Python | Engine Python |
|---|---|---|---|---|---|
| XML text parse and render with XSD | Passed | Matched | Matched | Matched | Matched |
| JSON parse and render with XSD | Passed | Matched | Matched | Matched | Matched |
| Dynamic binary XML and ASCII CDATA | Passed with character substitution | Passed with Unicode preserved | Passed with Unicode preserved | Passed with Unicode preserved | Passed with Unicode preserved |
| XSD JSON with root wrapper | Passed | Matched | Matched | Matched | Matched |

The XML comparison checked expanded names, attributes, child order and text while ignoring indentation and prefix spelling. The JSON comparison checked decoded values, value types and array order while ignoring object member order and formatting. Text XML and unwrapped JSON passed the initial eight side-by-side comparisons.

In the supported in-app browser, Studio loaded all four activities from the temporary sample catalog and showed their Input fields. Studio Run completed the XML text and XSD JSON starter flows. Studio Debug completed the Dynamic Binary XML and XSD JSON flows. Only the isolated browser sample uses Timer starters for the Run button. The comparison and archive matrix uses the original subtasks.

The initial two cases are recorded in the [first comparison](validation/xml-json-live-comparison-2026-11-17.json).

### Extended binary XML and wrapped JSON fixture

The extended native fixture maps UTF-16 bytes and a forced encoding into Dynamic Parse XML, then maps the parsed document and `US-ASCII` into binary Render XML. The CDATA selector is `{urn:mina:format-comparison}notes`. Parse JSON and Render JSON both use the native `Json with Root` setting and the same XSD record. The fixture validated with zero errors and zero warnings, exported a deployable EAR, and produced both rendered outputs in the installed Studio runtime.

MINA imports the expanded CDATA selector and takes the encoding and document from the native XML render binding. JSON values, types and array order matched the reference in all four execution modes. Both XML outputs were valid ASCII with CDATA and the same namespace, attribute and element order. The reference serialized `é` as `?`. MINA split the CDATA around `&#233;` so an XML parser restores `é`.

The complete MINA flows passed 16 checks in Run, Debug, Direct Python and Engine Python. The four activities recovered from the actual native source passed 16 additional checks with the same modes. The native Log activity stays in the reference fixture as a diagnostic and triggers the importer's individual activity recovery. The complete MINA workflows were verified independently of that recovery. See the [extended comparison evidence](validation/xml-json-extended-comparison-2026-11-17.json).

The local fixture and EAR are under `tmp/bw613-xml-json-20261117/`. In that directory, `configure.py --extended` regenerates the fixture from the saved Studio-generated process. The checked-in regression tests exercise imported wrapped JSON and binary XML bindings from a clean checkout.

The extended backend suite passed 66 tests, including the binary XML import regression and four tests from the installed reference samples. All 35 Studio contract tests passed, the offline help checks passed, and the production Studio build completed. Vite reported a bundle-size advisory.

## Implemented corrections

| Area | Corrected behavior |
|---|---|
| XSD simple content | JSON rendering retains numeric/boolean text types through simple-content inheritance and preserves empty text with attributes. A simple-content type without attributes is a primitive value. |
| Studio schema trees | Simple-content text is mappable beside attributes, with inherited primitive types and repeating cardinality retained. Parse JSON's XSD source aliases use normal attribute keys and `$` text; XML fields use `@attribute` and `#text`. Native JSON property names are left unchanged. |
| Mapped JSON render input | Explicit mapped trees take precedence over inherited serialized XML. Formatting-only mappings do not become the payload. |
| Nulls | Empty-container substitution preserves nil primitive values and their positions in repeating fields. Schema-typed nil objects can become empty objects. |
| Namespaced XML trees | Expanded names resolve to schema fields, retaining XSD ordering and qualified attributes. |
| Binary XML | Characters outside the chosen byte encoding use numeric references. CDATA sections split around those references to preserve the actual parsed text, including literal ampersands and closing-CDATA text. |
| Imported binary XML | The render binding supplies the document and dynamic byte encoding. CDATA selection matches the expanded element name, including its namespace. |
| XML controls | Unknown input/output style values fail explicitly. XML boolean conversion accepts XSD-permitted surrounding whitespace. |

## Verification

Final affected-area suite: **60 tests passed** (`test_xml_json_conformance`, `test_format_activities`, `test_data_activity_gaps`, `test_xsd_structure_selection`, `test_api_docs`). This includes all six XML/JSON/Data activities, offline XSD imports/includes, selected structures, validation faults, Generic/Badgerfish and XSD JSON conversion, formatting and binary encoding, Data layouts and imports, and generated archive execution.

The new conformance module has **13 tests**, including six complete flow scenarios independently audited in Run, Debug, Python direct archive and Python engine archive. Every mode compares output against an explicit expected value. Scenarios cover simple-content JSON conversion, nil primitive repeats, dynamic schema-tree overrides, formatting-only inputs, namespace/Unicode XML-to-binary round-trips and escaped Badgerfish content. Three new frontend contract tests exercise the actual Studio schema-tree and field definitions with an XML DOM adapter; they do not substitute a second implementation of the schema algorithm.

The broad backend run discovered **760 tests: 748 passed, 11 skipped and one SFTP handshake error** in `test_parallel_streamed_transfers_keep_servers_and_payloads_isolated`. Three immediate isolated repetitions of that test all passed. The broad run began after the initial XML fixes; final mapped-input changes were verified afterward by the 60-test affected-area suite. The broad run is not reported as an all-green final suite. Skips require approved external services/disposable database prerequisites. This XML/JSON work does not alter SFTP code or claim to resolve that intermittent failure.

The initial automated Run/Debug tests use Studio's runtime and debug manager. The follow-up above also exercised Studio in the browser. Both generated archive formats executed on this Windows host. The broader initial suite includes existing Data streaming and header/detail/trailer coverage.

## Reproduction and deployment

With `backend` and the connector test dependencies on `PYTHONPATH`:

```text
python -m unittest backend.tests.test_xml_json_conformance backend.tests.test_format_activities backend.tests.test_data_activity_gaps backend.tests.test_xsd_structure_selection backend.tests.test_api_docs -v
node --test frontend/scripts/*.test.mjs
```

Rebuild help with `node frontend/scripts/build-documentation.mjs` using the documented PDF dependencies, then run `npm.cmd run build` in `frontend`. Rebuild/reinstall Studio or restart the backend and refresh a newly built web Studio before using the fixes. Re-export existing Python packages to include the updated conversion modules; old archives are self-contained snapshots.

See `docs/validation/xml-json-summary-2026-11-17.json` for final test/build results and `docs/XML_JSON_CHANGED_FILES_2026-11-17.md` for the change manifest. Logs are under ignored `tmp/xml-json-*20261117.log`; they are not deployment dependencies.
