# HTTP and REST activity verification

The verification covers HTTP Listener, REST Receiver, HTTP Request, REST Invoke and HTTP Response in Studio, native Python listeners, Debug, Swagger/Postman generation and both Python archive formats. Live checks use local providers and generated local certificates. External enterprise services still need validation in their deployment environment.

## Activity combinations

`backend/tests/test_http_activity_e2e.py` sends real requests through these four flows. Each receives a JSON request, calls a separate local provider with a mapped body/custom header, and returns the provider response through HTTP Response.

| Inbound activity | Outbound activity | Response activity |
| --- | --- | --- |
| HTTP Listener | HTTP Request | HTTP Response |
| HTTP Listener | REST Invoke | HTTP Response |
| REST Receiver | HTTP Request | HTTP Response |
| REST Receiver | REST Invoke | HTTP Response |

## Confirmed gaps corrected

| Gap | Resulting behavior |
| --- | --- |
| Only one OpenAPI request/response representation retained | Keep all declared representations; choose the schema from actual Content-Type, with exact/type-wildcard/global-wildcard precedence |
| Text/XML bodies implicitly JSON-quoted | Infer text, XML and URL-encoded form serialization when no explicit body format is supplied |
| Numeric-looking plain text parsed as JSON numbers | Preserve text responses as strings |
| HEAD/204/304 rejected by payload schema validation | Skip response-body validation when HTTP forbids response content |
| Optional missing body rejected by an object schema | Validate supplied bodies; enforce presence independently for required bodies |
| URL-encoded numeric/boolean/array fields validated as raw strings | Decode primitive form fields using their declared schema types before validation |
| Required mapped body could be suppressed after validation | Apply Send Body Mode before validating required presence |
| Malformed JSON silently returned as text | Reject malformed nonempty JSON and non-finite JSON numbers; explicit binary mode keeps raw content |
| Non-finite OAuth introspection expiry accepted | Require a finite expiry later than the current time when exp is present |
| Preview ignored contract-derived methods | Resolve effective contract paths/methods and use the shared listener protocol handler |
| Preview did not mirror HEAD/OPTIONS/405 behavior | Use the same method dispatch as native listeners |
| HMAC preview rewrote the signed target | Verify the actual public encoded path/query sent by the client |
| HTTP preview could bypass an HTTPS connection setting | Reject plain HTTP preview for HTTPS-required connections |
| Explicit HTTPS scheme could be contradicted by a false TLS flag | HTTPS scheme always enables TLS; missing server identity fails startup instead of opening a plaintext listener |
| TRACE exposed inconsistently; CONNECT offered as an API method | Support TRACE through contracts, hosting, invocation and documentation; remove CONNECT tunneling from editor choices |
| Default HTTP Response accepted at runtime but rejected by Direct export | Allow the unambiguous default HTTP Response operation in Direct archives |

Swagger documents every declared content type. The workflow still chooses its response representation: set HTTP Response Content-Type to the representation actually returned. This does not automatically implement Accept-header negotiation or business logic.

## Capability coverage

| Capability | Evidence |
| --- | --- |
| Connection/activity/Input-tree configuration resolution | Request-tree tests and the live activity matrix |
| HTTP/HTTPS; root-folder trust; hostname verification; mutual TLS | Local TLS tests and runnable sample checks |
| Basic, Bearer/JWT, OAuth2 and HMAC | Authentication tests; local Basic/JWT/HMAC and OAuth token/introspection sample services |
| Digest, non-preemptive Basic, NTLM/LDAP integration paths | Existing transport tests; LDAP/provider calls use injected test clients |
| Path/query/header serialization and repeated values | Contract, request-tree and production HTTP tests |
| JSON, XML/XSD, plain text, form, binary and MIME | Contract, protocol, streaming and activity-level tests |
| Status/header propagation, HEAD, OPTIONS, method rejection | Listener and preview tests |
| Timeouts, connection limits, queues and cancellation cleanup | Transport/server and production tests |
| File streaming, MIME limits and upload/download cleanup | Production streaming tests |
| Retry limits, idempotency controls, circuit breaking, CORS, IP rules and throttling | Policy/production tests; distributed store calls are injected |
| HTTP/2 over TLS | Live local ALPN/HTTP2 test |
| Swagger, OpenAPI and Postman export | API documentation tests and exported live API tests |
| Live HTTP Debug pause/continue | API documentation Debug test |
| Direct/Engine archive compatibility | Fresh archive subprocesses hosting actual API routes; text contract and offline docs checks |
| Studio Samples | Installed template checks and executable sample verifier |

## Reproduce the checks

From `backend`, with its Python environment active:

```text
python -m unittest tests.test_http_activity_e2e tests.test_api_docs tests.test_api_blueprint tests.test_http_capabilities tests.test_http_request_tree tests.test_http_production tests.test_raw_python tests.test_engine_export tests.test_activity_packs tests.test_debug_testing tests.test_debug_input_capture -q
```

From the repository root, after sample certificate preparation:

```text
backend/.venv/Scripts/python.exe samples/http-rest-examples/verify_examples.py
```

On Linux use the corresponding environment's Python executable. The sample verifier opens loopback ports 9001–9003 and 9443–9449; keep these free. Fixtures are shut down afterward. From `frontend`, run the Node test suite and `npm run build` to verify editor contracts and the distributable Studio assets.

## Deployment boundaries

The checks do not certify a particular external OAuth issuer, LDAP directory, proxy, Redis service, certificate/key rotation process or production load profile. Test those with actual staging infrastructure and representative payloads, concurrency, expiry and outage cases.

This is a request/response API implementation. CONNECT tunnels, dedicated WebSocket/SSE streaming clients, complete vendor engine equivalence and full OpenAPI conformance are not claimed. OpenAPI multipart encoding-rule synthesis, callback/webhook lifecycle scaffolding and automatic inbound multipart-part extraction into a contract object remain outside the implemented subset. MIME envelope parsing and bounded binary/file transfer are implemented separately. Current certificate and authentication settings must still be provided on the execution host when exporting or deploying an application.

## Standards used for the corrections

- [OpenAPI media type matching](https://spec.openapis.org/oas/v3.1.2.html#request-body-object)
- [HTTP response content and HEAD semantics](https://www.rfc-editor.org/rfc/rfc9110.html#section-6.4.1)
