# REST APIs and shared HTTP connections

Use **HTTP Client Connection** for HTTP Request / REST Invoke and **HTTP Server Connection** for HTTP Listener / REST Receiver. These presets create reusable HTTP resources with explicit client/server roles. Existing HTTP resources continue to work; choose a role when editing them. A server resource cannot be used for an outbound request, and a client resource cannot host a listener.

## MINA API Blueprint: load YAML and host an API

Open **API Blueprint** on the Studio ribbon. Load a `.yaml`, `.yml` or `.json` OpenAPI contract, or paste its contents. **Load example** supplies a small two-operation API. Choose **Validate YAML** to check syntax, contract structure, unique routes/operation IDs, path parameters, schemas and any declared response examples. Missing operation IDs receive stable generated IDs. YAML duplicate keys and aliases are rejected; ordinary YAML strings such as `on`/`off` remain strings. Numeric response keys are normalized to status-code strings.

Select the operations to implement, then choose a saved HTTP server connection or enter a new bind host, port and protocol. HTTPS hosting requires the server's own certificate/private key or a saved connection with an identity store. The selected connection settings are copied into a dedicated API server resource, preserving property bindings and authentication settings. The contract is stored once on that resource and remains editable there.

Choose initial response behavior explicitly. **501 placeholders** is the default: importing an interface does not implement business logic. **Declared response examples** hosts schema-validated mock examples for testing; operations without examples still return 501. Each selected operation becomes an editable Starter Task containing REST Receiver → HTTP Response. Replace the placeholder/example response with your integration logic and enable response validation when implementing the operation.

**Create API tasks** saves the design without opening a port. **Create & host API** saves and starts all selected routes together, showing their actual endpoint URLs. If hosting fails, the saved tasks remain available and **Host API** retries without duplicating them. **Run** on any task in that Blueprint hosts its sibling API tasks; **Stop** releases the listener ports. Unrelated starter tasks do not join the Blueprint. Both Python archive formats host the same generated routes when running the application.

Import currently accepts self-contained contracts/local JSON Pointer references; inline external documents before using the Blueprint wizard. The activity contract editor separately supports explicit external-reference configuration. Re-importing creates a separate API design; it does not overwrite existing business mappings. When retaining multiple API versions, give them distinct routes/base paths or ports so an application-wide Python deployment can host them together. The popup stays within the viewport and scrolls its content independently of its action controls.

## Default confidentiality

On an HTTP client/shared connection, enable **Default confidentiality / system trust** to require HTTPS with server-certificate and hostname verification. System root trust remains available; a configured trusted-certificate folder augments it. No client identity certificate is needed unless the provider requires mutual TLS. An HTTP URL or disabled certificate verification conflicts with default confidentiality and fails configuration. When no port is configured, HTTPS uses 443; explicit ports are respected. The setting is also available as the boolean environment property `connections.http.defaultConfidentiality`.

This is MINA's Python equivalent of default TLS confidentiality, using the runtime host's system trust rather than a Java `cacerts` file. Certificate-folder trust applies to HTTP Request, REST Invoke and SOAP Request/Reply, in Studio and both Python exports.

## Design and run a REST API

For HTTP Request and REST Invoke, map the contract, operation ID, reference documents/origins and request/response validation settings under **Input → RestInputRequest.Config**. Existing configuration values are shown as typed mappings. Configuration keeps the display name and shared connection selector. JSON/XSD validation and contract selection can use properties or upstream values; XSD validation uses offline lxml validation with self-contained schemas. Generated archives include the required dependencies. Listener routing stays in startup configuration.

REST Receiver starts a task when its configured method and path match a request. Add an HTTP response activity to control status, headers and body. Run starts a real listener on the shared connection's host and port, and Stop releases the port. Multiple exported receiver tasks can share a port when their transport settings agree and their routes do not conflict.

REST Invoke and HTTP Request support URI parameters, default and activity headers/query parameters, JSON, text/XML, form, binary and file bodies, buffered/chunked transfer, response status validation, and optional request/response schema validation. XML requires a text body and the appropriate media type. REST invocation returns `statusCode`, `headers`, `body`, `elapsedMs`, and `httpVersion`; Untouched legacy HTTP Request activities retain their payload response; new requests and requests edited through the Input tree return the response envelope.

Optionally paste an **OpenAPI 3 or Swagger 2 JSON/YAML contract** and select its exact **operation ID**. The operation defines the HTTP method/path, required parameters, media types and request/response schemas. Invocation uses the connection's base URL when supplied, otherwise the contract server URL. A receiver combines its base path with the operation path; without a configured base path it uses the contract server's path. Body validation defaults to enabled. Parameter validation includes required values, arrays, objects, cookies, numeric/string constraints and formats. Operation-level parameters override path-level definitions. Response schemas select exact status, status class (for example `4XX`), then `default`, including error responses before status faults are raised.

Local references work offline. Supply external documents in **Supplied external reference documents** as a JSON object mapping document URI to document object or YAML text. For network references, configure **Contract base URL** for relative paths and explicitly list exact HTTPS origins in **Allowed external reference HTTPS origins**. No origins means no remote retrieval; redirects, URL credentials and implicit file access are forbidden. Retrieval uses the shared client's TLS trust, with document/count/size bounds; schema validation itself never fetches URLs. YAML aliases are rejected. The contract limit is 8 MiB, with at most 16 referenced documents and 32 MiB downloaded references. Mapping expressions do not execute YAML code. MIME bodies continue to use the explicit Input tree; OpenAPI does not automatically manufacture MIME mapping rules or perform browser authorization/consent.

The Studio preview URL uses the same validation and authentication as the real listener. It cannot establish mutual TLS for an individual project; use the configured HTTPS endpoint to test client certificates. Preview signatures use the project-relative listener path. The real endpoint's HTTP/TLS transport settings apply when Run hosts the dedicated listener or an exported application runs.


## Request and response trees

Configuration holds the shared HTTP client connection and optional API contract and schema validation settings. Request values belong in Input, under `RestInputRequest`:

- `Config`: host, port, scheme, requestURI, Method, RequestBody, bodyFormat, query and URI parameters, QueryString, FilePath, timeout in milliseconds, and request policy overrides. Unmapped connection settings supply defaults.
- `Headers`: accept, content-type, Accept-Charset, Accept-Encoding, Cookie and pragma. Repeating `DynamicHeaders` entries contain name/value pairs. Add or remove entries independently, or map a source collection with For Each. Repeated custom headers retain all values; duplicate dynamic entries for a nonrepeating standard header fail validation. Header names and values must be ASCII and cannot contain line breaks.
- `mimeEnvelopeElement`: repeating `mimePart` entries containing `mimeHeaders` and exactly one of binaryContent (base64), textContent or fileName. MIME headers include content-type, content-transfer-encoding, content-id and content-disposition. File names refer to files available on the runtime host. Multipart messages are buffered by default; `Config.streamRequest` enables bounded streaming within the configured size limit.

Legacy request configuration values appear as Input mappings when opened; editing saves them into the new structure. String constants require quotes; numbers and booleans use native literals, while expressions supply runtime values. Output exposes `RestOutputResponse` with statusLine (httpVersion, statusCode, reasonPhrase), body, asciiContent, binaryContent, Headers, repeating DynamicHeaders and parsed MIME parts. The runtime also retains the envelope's statusCode, headers, body, elapsedMs and httpVersion fields. Input and Output trees show optional and repeating cardinalities.

This organization follows the [BWCE Send HTTP Request input, header and MIME documentation](https://docs.tibco.com/pub/bwce/2.5.3/doc/html/GUID-3E3F3D02-EE74-46C3-935B-ECF1C3D3B618.html), using the requested `RestInputRequest` root. Studio, Direct Python and Engine Python exports use the same request and MIME implementation.

## Connection configuration

| Area | Implemented configuration |
| --- | --- |
| Addressing | Client/server role, protocol, host, port, base URL and base path; activity path and methods |
| Confidentiality | System trust with default confidentiality, custom trust with a configured store, HTTPS enforcement, hostname verification, TLS 1.2/1.3 bounds, TLS 1.2 cipher list |
| Certificates | PEM trust certificates, PEM certificate chain/private key and key password, PKCS12 identity/trust store passwords, JKS store password and identity alias, CRL, optional/required inbound client certificates |
| Client timeouts | Separate connection, socket/read, write and pool wait timeouts in milliseconds; legacy second-based values remain accepted |
| Pooling | Total and per-host limits, persistent connections, idle expiry, disabled pooling, cookie persistence and response buffer size |
| Delivery | Redirect switch, bounded connection retries and retry delay, request/response size limits, expected content/accept types and success status codes |
| Proxy | Proxy URL or host/port and optional credentials |
| Server limits | Minimum/maximum QTP worker settings, concurrency and queue limits, queue timeout, accept backlog, persistent connection idle timeout, body read timeout, header/body size limits and IP/CIDR allowlist |
| Execution | Request execution timeout and contract validation |

Zero client phase timeout means no independent phase deadline, subject to the activity timeout budget. The default activity budget is 180 seconds; synchronous client phase waits and response consumption are bounded, but this is not a hard wall-clock cancellation of a Python thread. Connection failures are retryable; configured status retries additionally require idempotency safeguards. Read failures are not automatically replayed. Host/port settings must refer to an address the runtime can actually bind or reach.

QTP is a Jetty concept. MINA implements its minimum/maximum settings with Python authentication workers, a bounded admission queue and an asynchronous execution gate. It does not embed Jetty or duplicate its scheduling semantics. HTTP/1.1 listeners use Uvicorn. Selecting HTTP version `2` on a server connection enables Hypercorn with HTTPS ALPN negotiation for HTTP/2 and HTTP/1.1. HTTP/2 listeners require HTTPS and use the same trust, identity and mutual-TLS configuration. TLS 1.3 cipher selection follows Python/OpenSSL defaults. Certificate revocation uses configured CRLs; OCSP fetching and Java security-provider configuration are not implemented.

PEM and PKCS12 work in Python. JKS conversion requires Java `keytool` on PATH or under JAVA_HOME. A selected JKS identity key must use the store password; convert stores with a distinct key password to PKCS12 first. Certificate/key paths are external deployment requirements; MINA does not bundle private keys or certificate stores into source archives.

### Trust certificates from a property-bound folder

Set the string property `connections.http.trustedCertificateFolder` to your certificate folder, for example `D:\MINA\certificates\trusted` on Windows or `/etc/mina/certificates/trusted` on Linux. In the HTTP shared connection, bind **Trusted root / chain certificate folder** to `${properties.connections.http.trustedCertificateFolder}` using the property picker. Select that HTTP connection for HTTP Request, REST Invoke or SOAP Request/Reply. Enable HTTPS and keep certificate verification enabled.

Place trusted root certificates directly in the folder. Intermediate chain certificates are optional: normally the HTTPS server supplies them, but you can add them to the same folder if needed. A complete path to a trusted root is still required; an intermediate alone does not bypass root verification. Server/client identity certificates and private keys remain separate settings for hosting HTTPS or mutual TLS.

The folder accepts `.pem`, `.crt`, `.cer` and `.der` files, including PEM bundles and binary DER certificates. It requires no OpenSSL rehash operation. Subfolders are not scanned; unrelated file extensions are ignored. Empty, missing, unreadable or invalid certificate folders produce a configuration error. Keep private keys out of the trust folder. Limits are 256 certificate files, 8 MiB per file and 32 MiB total. Folder trust is added to system trust and any explicitly configured trust store.

New outbound calls detect certificate file additions, removals and file modification times and create a fresh TLS client when needed. Existing requests finish with their original TLS context. Inbound servers load folder trust at startup; restart them after changing client CA certificates. Configure an environment-specific property value and provision the folder on each deployment host. Studio and both Python archive formats resolve the same property and use the same folder-loading implementation; the folder itself remains an external deployment requirement.

## Authentication

| Scheme | Client | Server |
| --- | --- | --- |
| Basic | Preemptive or challenge-based username/password | Constant-time credential comparison; empty credentials rejected |
| Digest / NTLM | HTTP challenge authentication | Not implemented |
| Bearer | Supplied access token | Supplied token comparison |
| OAuth2 | Client credentials, supplied authorization code with optional PKCE verifier, refresh token; cached token exchange | HTTPS token introspection; active/expiry checks and required scopes |
| JWT | Supplied JWT, or generate a signed token with claims, issuer, audience and lifetime | Verify configured algorithm/key, expiration, issuer/audience when configured, clock skew |
| HMAC | Sign method, exact request path/query, timestamp, nonce and SHA256 body digest | Signature, timestamp and nonce replay checks |
| LDAP | Not an outbound REST authentication scheme | Basic credentials authenticated by verified LDAPS or StartTLS, service search/user DN template, optional required group |
| Certificate | TLS client identity | Required and verified mutual TLS |

JWT algorithms are explicitly limited to HS256/384/512, RS256/384/512 and ES256/384. Asymmetric signing uses a PEM private key; verification uses a PEM public key. Configure strong shared secrets and the expected issuer/audience for your application.

OAuth token and introspection endpoints require HTTPS. Authorization-code acquisition/consent is performed outside MINA; provide the returned code, redirect URI and verifier when applicable. Token refresh is automatic when the provider supplies a refresh token. LDAP search escapes usernames, rejects anonymous binds and always verifies its TLS connection. LDAP group checking uses `memberOf` and depends on directory support.

HMAC uses MINA's explicit signing format, not AWS SigV4 or a vendor-specific HMAC policy. Send `X-MINA-Key-Id`, `X-MINA-Timestamp`, `X-MINA-Nonce`, and `Authorization: HMAC <base64 signature>`. The signed text is five newline-separated values: uppercase method, exact encoded path/query, Unix timestamp, nonce, and hexadecimal SHA256 body digest. Select SHA256/384/512 for the keyed signature. Signed requests cannot follow redirects. Select policy storage `redis` and bind **Redis policy connection URL** to a protected property for atomic nonce claims across replicas; `memory` is local to one runtime. Redis failures reject protected requests with 503 rather than silently disabling replay protection. Use `rediss://` for encrypted Redis connections.

### Browser access, key rotation and throttling

Configure exact **Allowed browser origins** on a server connection to enable CORS. Credentialed CORS rejects wildcard origins. Preflight checks the requested method and headers before authentication; actual requests still authenticate normally, and allowed-origin authentication failures include CORS headers. CORS is a browser policy, not an alternative to authentication. Configure required browser headers and exposed response headers explicitly.

For JWT issuer key rotation, set an explicit HTTPS **JWT verification JWKS URL**, asymmetric signature algorithm, expected issuer and audience. The endpoint comes from configuration, never from token headers. Keys are cached for 300 seconds by default; an unknown `kid` can refresh after a default 10-second cooldown. Discovery is bounded to 1 MiB/128 keys and uses configured TLS trust. Symmetric JWKS algorithms, mismatched algorithms and unsuitable keys are rejected. Missing keys or discovery failures never bypass signature checks.

Set **Requests per client/window** above zero to enable fixed-window throttling. The key uses the actual remote IP and route. Exceeding the limit returns 429 and `Retry-After`. Redis storage shares counts across replicas; memory storage applies within one runtime. Behind a proxy, the actual peer is the proxy: terminate per-user/IP policies there when required. Forwarded headers are not trusted automatically.

### Retries and circuit breakers

`retryCount` bounds retries. **Retry response status codes** is empty by default; explicitly select statuses such as `429,502,503,504` when appropriate. Response retries require an idempotent method, a mapped `Idempotency-Key`, or the explicit non-idempotent retry override. An idempotency header only helps when the destination enforces it. Backoff grows exponentially with optional jitter; `Retry-After` seconds/HTTP dates are honored within the configured maximum delay and remaining activity budget. Read failures are not automatically replayed. All retry attempts share one activity budget.

Set **Circuit breaker failures** above zero to open a runtime-local circuit after consecutive connectivity/server failures. **Circuit recovery delay** controls when one half-open probe may run; success closes the circuit and failure reopens it. Configuration/client validation errors do not count as server failures. Circuit state is local, while optional Redis throttling/replay state is shared.

### Binary bodies and large files

Listeners preserve binary request bytes and expose base64 `binaryContent`, complete repeated `headerPairs`, and scalar-or-list query/header values. `?tag=a&tag=b` preserves both tags. Ambiguous duplicate Authorization/Host/Content-Type/Content-Length/Origin headers are rejected. Existing routes return 405 with `Allow` for unsupported methods; GET routes support HEAD and listeners answer OPTIONS automatically.

File request bodies (`Config.FilePath`) stream from disk. Set `Config.streamRequest = true` to stream MIME attachments; streaming MIME supports base64/binary/7bit/8bit transfer encoding and bounded nested envelopes. Streamed uploads require authentication that does not internally buffer the body: preemptive Basic, Bearer, OAuth2, JWT, HMAC or certificates. Challenge-authentication modes that require buffering reject streaming requests explicitly.

For downloads, map `Config.responseFile` to a runtime filename. Data streams into a sibling temporary file; successful completion publishes it atomically. Existing destinations are protected unless `Config.overwriteResponseFile = true`. Failures and size-limit errors remove the partial file. Output body contains `fileName` and `size`. Use buffered mode when response-schema validation is required; file mode cannot bypass that validation. Set `Config.responseBodyMode = "binary"` for a buffered byte body; structured output retains base64 `binaryContent`.

For large inbound bodies, select **Inbound body storage = file** and an existing writable **Temporary upload directory** on the server connection. The flow receives `fileName`/`size`; consume or move the file during that request. Temporary uploads are deleted on success, failure, cancellation or disconnect. This mode spools the complete wire entity, including a multipart entity, without buffering it or incrementally extracting its parts. Use memory mode for JSON/XSD body validation or automatic MIME-part decoding.

HTTP Response can map either `body`, base64 `binaryContent`, or `fileName` for streamed output. Repeating response-header values such as `Set-Cookie` remain separate headers. Size bounds still apply in all storage modes.

## Swagger documentation and Postman

Studio's **Samples → HTTP & REST examples** opens twenty editable host/caller projects directly. Each opening creates a new copy. Cards show provider dependencies and setup requirements. The Samples footer downloads the API setup guide and helper kit, including certificate preparation and local OAuth fixtures. For secure examples, prepare the helper kit and set the opened project's local `demo.directory` property to its generated `local` folder. No machine-specific certificate paths or generated private keys are bundled in the gallery.

Hosted HTTP and REST listeners automatically serve **MINA API Explorer**, with bundled Swagger UI and **Try it out**, at `http(s)://host:port/_mina/docs`. Run and Debug show the actual listener endpoint, an **Open Swagger** link and a **Download Postman collection** button. The download is a Postman v2.1 collection JSON; import it into Postman and supply any credential variables locally. The API Explorer also has a collection download button. No CDN is needed.

The OpenAPI document is at `/_mina/openapi.json` and the collection at `/_mina/postman.json`. These describe the currently hosted routes, including the selected API Blueprint operations, effective base path, parameters, request/response schemas, examples and authentication. Generic HTTP listeners receive generated operation descriptions. Swagger testing invokes the actual integration. In Debug it pauses at configured breakpoints; use Continue/Step in Studio to finish the request. One request can be debugged at a time; additional requests return 503. HTTP activity timeouts still apply; a timed-out debug request stops that debug session so a stale paused job cannot affect another request.

On the HTTP shared connection, **Host Swagger documentation** disables/enables documentation (enabled by default). `/_mina` is reserved when enabled. **API documentation access** defaults to authenticated: the specification and collection use the connection's authentication, while the HTML/assets are available to display the access panel. Public documentation access must be selected explicitly and does not bypass API authentication. **Public API base URL** optionally supplies an externally reachable origin and gateway prefix for generated links and collections. Configure your gateway to forward the documentation paths as well as the API routes.

Basic/LDAP credentials, access tokens and HMAC secrets entered in the API Explorer stay in that tab and are not saved in generated collections. Postman collections use empty credential variables. HMAC signing is supplied for raw JSON/text requests; multipart/file signing requires your own signing client. Browser HMAC signing needs HTTPS or localhost. Configure mutual-TLS client certificates separately in your browser/Postman, and trust the hosting server's TLS certificate. Browser security and CORS policies still apply. Outbound HTTP Request and REST Invoke activities call providers; they do not themselves host Swagger routes.

Swagger UI assets and their Apache-2.0 license/notices are included in both Direct and Engine Python archives. To update bundled assets after upgrading the pinned npm dependency, run `npm run swagger:assets` from `frontend` and rerun the API documentation/export tests.

## Python deployment details

Studio, Direct Python archives and Engine Python archives use the same HTTP transport, authentication and listener implementation. Generated dependency checks include HTTPX, Uvicorn and the security libraries required by the configured connections. Provision external certificate/key/store files on the execution host, and supply exported secrets through the deployment environment/property bindings. Export retains endpoint URLs and key-file locations while removing secret values.

Direct archives can run with `python run.py` after extraction or as a Python zip application. Engine archives run with `python -m application.main`. Existing Administrator deployment commands continue to apply. Optional modules include PyJWT/cryptography, ldap3, httpx-ntlm and h2. Test against your own directory, identity provider, certificate chain and proxy before deployment; local automated tests exercise protocol behavior and failures, not access to external enterprise services.

## Reference documentation and scope

The design was compared against the [TIBCO BusinessWorks 6.12 REST Reference](https://docs.tibco.com/pub/activematrix_businessworks/6.12.0/doc/pdf/TIB_BW_6.12.0_rest_reference.pdf), [MuleSoft HTTP connector reference](https://docs.mulesoft.com/http-connector/latest/http-documentation), [HTTP authentication](https://docs.mulesoft.com/http-connector/latest/http-authentication), and [LDAP Basic authentication policy](https://docs.mulesoft.com/mule-gateway/policies-included-basic-auth-ldap). Detailed HTTP client settings were available in the [BW 6.11 HTTP Client reference](https://docs.tibco.com/pub/activematrix_businessworks/6.11.0/doc/html/binding-palette/http-client.htm); the corresponding 6.12 HTML reference was unavailable during review.

This implementation provides the Python capabilities listed above. It does not claim full TIBCO/Mule engine or complete OpenAPI conformance. Java client implementations, Jetty QTP internals, Mule policy deployment, WADL generation, automatic OpenAPI multipart-rule synthesis, incremental inbound multipart-part extraction, provider-specific OAuth browser integrations and vendor-specific security modules remain outside the implementation.

## Deployment qualification

The activity-level suite `tests.test_http_activity_e2e` exercises HTTP Listener and REST Receiver through both HTTP Request and REST Invoke, returning through HTTP Response on real local listeners. It also covers Studio contract preview, HMAC encoded request targets, HTTPS preview enforcement, multiple content types, strict JSON, bodyless responses and fresh Direct/Engine archives.

REST contracts retain all declared request/response content types and validate against the actual Content-Type, using exact media types before type wildcards and `*/*`. Swagger exposes all declared formats. Set HTTP Response's content type explicitly when returning a representation other than the configured default; the workflow chooses the response representation. Explicit request-schema overrides remain effective. Optional absent request bodies are accepted; required bodies cannot be bypassed with Send Body Mode = NEVER/AUTO.

In HTTP Listener and REST Receiver setup or Configuration, check one or more **Request content types** and **Response content types**. You can add custom types alongside the common ones. No selection keeps automatic behavior. With multiple response types, MINA uses the caller's `Accept` header and its quality values; the first checked format is the default. An explicitly mapped HTTP Send Response content type must be one of the offered types and acceptable to the client. For XML output, map an XML document or an object with one root element. With mixed media types, a standalone XSD applies to XML and a standalone JSON Schema applies to JSON; use an OpenAPI contract for separate schemas by media type. Swagger lists each selected format, and the Postman export includes a request for each selected request format.

URL-encoded form fields use declared primitive schema types before validation, including repeated primitive arrays. Direct archives also accept the default HTTP Response operation, matching runtime behavior.

When body format is omitted, outbound text/XML content is sent as text and URL-encoded form content is encoded as form data. Explicit body format settings retain precedence. Text responses such as `42` remain strings. Malformed nonempty JSON and NaN/Infinity are rejected; binary response mode retains raw content. HEAD, 204 and 304 responses skip body schema validation because they have no response content. TRACE is supported as an optional API operation; CONNECT proxy tunneling is not offered as an API method.

Studio preview resolves methods and paths from the selected API contract, including HEAD, OPTIONS and 405 behavior. Signed previews use the actual encoded public request target. A connection requiring HTTPS must use an HTTPS endpoint; plain HTTP preview cannot bypass confidentiality.

An explicit HTTPS server scheme always enables TLS, even if a legacy TLS checkbox value is false. A missing server certificate/key then fails startup instead of silently opening a plaintext listener.

Run `python -m unittest tests.test_http_capabilities tests.test_http_request_tree tests.test_http_production` from `backend` with its virtual environment active. The suite covers local TLS/mTLS, HTTP/2 negotiation, HTTP contracts, binary/repeating values, streaming/file cleanup, policy behavior and Python exports. Redis protocol calls are tested with an injected store; provision and exercise the actual Redis service, issuer/LDAP, certificates, proxy and upstream API in staging.

Export Direct or Engine Python and install the archive's generated dependencies. HTTP contract support requires `jsonschema`, `PyYAML` and `regex`; HTTP/2 hosting adds `hypercorn`/`h2`; distributed policies add `redis`. Keep certificate files and secrets external. Supply the Redis URL through the generated secret binding, never an unprotected source literal.

Use the Direct archive's `--qualify-task <task-id>` runner against the staging API with representative payloads, concurrency, latency/error thresholds and memory limits. Test the Engine archive with the same fixtures and deployment load harness. Repeat under upstream outages, token/key rotation, Redis failure and deployment restart. Record the report with the release. Automated regression success is evidence for the implemented behavior, not a guarantee about an untested production environment or third-party service.
