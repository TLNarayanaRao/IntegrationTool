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

This is a request/response API implementation. The table below identifies the remaining protocol and contract boundaries. Certificate and authentication settings must be available on the execution host when deploying an exported application.

## Standards coverage and deployment limits

The activities cover ordinary HTTP/REST request and response integrations. This table separates protocol defects from capabilities needed by particular API contracts or deployment environments.

| Priority | Gap | Current behavior and impact |
| --- | --- | --- |
| Security scope | Imported OpenAPI security | Hosting rejects unenforceable requirements. A supported alternative can combine multiple OpenAPI API keys with the connection's Authorization scheme and mutual TLS. The connection supports one Authorization scheme at a time. |
| Corrected | HTTP 205 Reset Content | Listeners suppress response content, and clients skip body processing and validation. Generated OpenAPI omits content for 205. |
| Supported for buffered forms | OpenAPI serialization and multipart | Outbound query values honor `allowReserved` for safe wire characters. Contract-driven forms apply and validate declared non-reserved part headers and content types. |
| Implemented as a setting | Problem Details | Opt in to RFC 9457 responses for listener-generated errors. Existing connections retain their legacy JSON format. |
| Implemented as settings | Trace context and proxy trust | Version 00 W3C trace context can follow inbound and outbound activities. Explicit proxy CIDRs enable trusted X-Forwarded-For client attribution. Span export and other forwarded-header formats are outside this feature. |
| Implemented as a setting | OAuth client authentication | The runtime can sign a private-key JWT assertion for the configured HTTPS endpoint. Real provider registration, credential rotation and interoperation remain staging checks. |
| Opt-in | Conditional requests and caching | Conditional GET/HEAD uses mapped validators. A dedicated activity evaluates write preconditions before a datastore write. The bounded process cache serves fresh public GETs and does not perform stale serving or distributed invalidation. |
| Supported with limits | Callbacks and webhooks | Named webhooks become hosted endpoints. Callback Sub Tasks require explicit workflow calls and an HTTPS allowlist. Durable subscriptions and automatic callback delivery remain outside the scaffold. |
| Bounded clients | SSE and WebSocket | Activities read SSE events or exchange WebSocket messages and close after their configured limits. Inbound SSE publishing and WebSocket hosting are outside these activities. |
| Native transport | HTTP/3 | QUIC hosting and direct buffered clients use TLS 1.3. Mutual TLS, custom CRLs or cipher suites, proxies, and outbound file or event streaming are outside HTTP/3 support. |

## Standards references

- [OpenAPI media type matching](https://spec.openapis.org/oas/v3.1.2.html#request-body-object)
- [OpenAPI parameter serialization and security requirements](https://spec.openapis.org/oas/v3.1.2.html)
- [HTTP 205 Reset Content and conditional requests](https://www.rfc-editor.org/rfc/rfc9110.html#section-15.3.6)
- [HTTP caching](https://www.rfc-editor.org/rfc/rfc9111.html)
- [HTTP/3](https://www.rfc-editor.org/rfc/rfc9114.html)
- [Problem Details for HTTP APIs](https://www.rfc-editor.org/rfc/rfc9457.html)
- [OAuth JWT client authentication](https://www.rfc-editor.org/rfc/rfc7523.html#section-2.2)
- [W3C Trace Context](https://www.w3.org/TR/trace-context/)
