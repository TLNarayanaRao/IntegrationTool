# REST APIs and shared HTTP connections

Use **HTTP Client Connection** for HTTP Request / REST Invoke and **HTTP Server Connection** for HTTP Listener / REST Receiver. These presets create reusable HTTP resources with explicit client/server roles. Existing HTTP resources continue to work; choose a role when editing them. A server resource cannot be used for an outbound request, and a client resource cannot host a listener.

## MINA API Blueprint: load YAML and host an API

Open **API Blueprint** on the Studio ribbon. Load a `.raml` RAML 1.0 API, or a `.yaml`, `.yml` or `.json` OpenAPI contract, or paste its contents. **Load example** supplies a small two-operation API. Choose **Validate YAML** to check syntax, contract structure, unique routes/operation IDs, path parameters, schemas and any declared response examples. Missing operation IDs receive stable generated IDs. YAML duplicate keys and aliases are rejected; ordinary YAML strings such as `on`/`off` remain strings. Numeric response keys are normalized to status-code strings.

For a multi-file contract, choose **Load API folder**, then select **Entry API document**. The folder's relative paths are preserved, so references such as `models/order.yaml` and local JSON Pointers can be bundled without fetching URLs or reading files outside the selected folder. Import accepts up to 16 supplied source files, each at most 8 MiB, with a 32 MiB upload total and an 8 MiB bundled-contract limit. RAML folders can include RAML/YAML/JSON, XML/XSD examples, text and Markdown. Change remote references to matching local relative paths before importing; the wizard does not download URLs. Switching entry documents invalidates the previous validation and operation selection while retaining edits to previously selected files.

Validation checks every declared request/response media schema, response codes, parameter locations and duplicates, route placeholders, callback structure, and mock examples against their corresponding media schemas. Named/referenced examples, explicit JSON null examples, and schema-level examples are supported. Example response headers use declared examples or schema defaults. Declared 204/205 responses can be mocked without a body. Generated names remain unique even when routes differ only in case or callbacks share a display name. Contracts are bounded to 256 paths, 512 operations, and 1024 generated operation/callback tasks.

Generated mock responses preserve JSON strings and null as JSON values in Studio, Run, Debug, and exported Python applications. Hyphenated URI parameter names, such as `{order-id}`, are routed correctly. Hosted Swagger resolves named examples from imported documents and retains response header declarations; Postman exports preserve explicit null request examples.

Use **Find operations**, **Select all**, and **Clear selection** for larger contracts. Filtering does not deselect hidden operations. Each operation indicates its available mock status, or that it will return 501 until implemented. Creating an API remains separate from implementing its business logic; loading a contract never generates that logic automatically.

Select the operations to implement, then choose a saved HTTP server connection or enter a new bind host, port and protocol. HTTPS hosting requires the server's own certificate/private key or a saved connection with an identity store. The selected connection settings are copied into a dedicated API server resource, preserving property bindings and authentication settings. The contract is stored once on that resource and remains editable there.

Choose initial response behavior explicitly. **501 placeholders** is the default: importing an interface does not implement business logic. **Declared response examples** hosts schema-validated mock examples for testing; operations without examples still return 501. Each selected operation becomes an editable Starter Task containing REST Receiver → HTTP Response. Replace the placeholder/example response with your integration logic and enable response validation when implementing the operation.

Select **API package** to choose an existing task package. **New package** creates a root folder; **New subpackage** creates a child of the selected package. Names use the same validation as Project Explorer, and spaces become hyphens. Generated operation tasks, contract callback helpers when present, and the API-specific server connection are saved in the selected package. New folders are only saved when the API is created; closing the wizard leaves the project unchanged.

**Create & host API** saves and starts all selected routes together, showing their actual endpoint URLs. There is no separate **Create API tasks** button in this wizard. If hosting fails, the saved tasks remain available and **Host API** retries without duplicating them. **Run** on any task in that Blueprint hosts its sibling API tasks; **Stop** releases the listener ports. Unrelated starter tasks do not join the Blueprint. Both Python archive formats host the same generated routes when running the application.

The wizard imports RAML 1.0, OpenAPI 3 and Swagger 2 contracts. The activity contract editor separately supports explicit external-reference configuration. **Create new API** creates a separate design; **Update existing API** changes a selected Blueprint in place through review. When retaining multiple API versions, give them distinct routes/base paths or ports so an application-wide Python deployment can host them together. The popup stays within the viewport and scrolls its content independently of its action controls.

### RAML traits, libraries and resource types

Choose the API root beginning with `#%RAML 1.0`, rather than a Library/Trait/ResourceType fragment. **Load API folder** supplies local `!include` documents and `uses` libraries, including nested namespaces. The importer expands parameterized traits (`is`) and resource types (`type`), inheritance, optional methods such as `post?`, reserved `resourcePath`, `resourcePathName` and `methodName` parameters, and standard naming transformations such as `!singularize`, `!pluralize` and case conversions. Explicit declarations override inherited values; inherited collections are merged. An optional method is expanded only when that method exists on the resource or through nonoptional inheritance.

Supported types include objects, arrays, inherited/namespaced types, unions, nullable values, primitive constraints, date/time formats, XML metadata and included JSON schemas. Nested routes, URI/query/header parameters, media types, responses, examples, Basic/OAuth2 security and single-credential Pass Through security convert into the shared runtime contract. Explicit `protocols: [HTTPS]` requires a TLS connection. Configure the actual credentials and TLS identity on the server shared connection; importing security declarations does not generate secrets.

The saved resource contains normalized OpenAPI, so Swagger, Postman, Run, Debug and both Python archive formats use the same expanded contract without a RAML parser at deployment. Keep the original source folder under version control and reload it to update the API; the wizard does not regenerate RAML source from edited OpenAPI. The Studio backend additionally installs the pinned `inflection` dependency from `backend/requirements.txt` for template transformations.

This is a bounded offline RAML importer, not a claim of complete RAML specification certification. Overlays/extensions, whole-object `queryString`, unsupported security mechanisms, custom validation facets and unsupported type facets must be converted before import. Missing files, cyclic expansion, unknown types/templates, YAML aliases/duplicate keys and unsupported declarations produce validation errors. No import reads arbitrary disk paths, fetches URLs or executes custom YAML tags.

### Safely update an existing API

1. Stop Run/Debug. Open **API Blueprint**, choose **Update existing API** and select its API-specific server connection.
2. Load the revised contract or source folder, validate it, and select the operations to retain or add. Keep `(operationId)` stable in RAML when renaming a route; otherwise matching falls back to the existing method/path.
3. Choose **Preview update**. The first preview saves pending Studio edits. Inspect added, changed, unchanged and removed operations, conflicts and warnings. Response behavior controls only newly generated operations.
4. Acknowledge the review and choose **Apply reviewed update**. **Host API** then starts the updated implementation.

Matched tasks retain their IDs, names, packages, activities, transitions, groups, input/output schemas, business logic and mappings. Existing response mappings are preserved rather than replaced with examples. The dedicated connection retains its ID, transport, authentication and property bindings; its normalized contract changes. New operations receive new editable flows. Callback helpers retain stable IDs and custom mappings; obsolete callback helpers are retained with a warning so existing Call Sub Task references remain valid.

Removal of an implemented operation blocks apply instead of silently deleting its flow. Resolve removals explicitly or retain the operation in the contract. Ambiguous matches and object-name collisions also block apply. Schema changes require review and may require manual business-mapping changes; preserving a mapping does not guarantee that it satisfies a changed schema.

Apply is rejected while that project's Run/Debug session is active. A preview token binds the exact contract and selection to the saved project revision. If another editor changes the saved project, apply returns a conflict; **Refresh preview** reads the latest saved revision without writing an old Studio snapshot over it, and requires review again. A temporary project-directory snapshot restores the prior saved project if saving the update fails. If restoration itself fails, the server reports the retained recovery directory; keep that directory for recovery. This protects ordinary save failures, rather than guaranteeing recovery from every machine/storage failure.

## Default confidentiality

On an HTTP client/shared connection, enable **Default confidentiality / system trust** to require HTTPS with server-certificate and hostname verification. System root trust remains available; a configured trusted-certificate folder augments it. No client identity certificate is needed unless the provider requires mutual TLS. An HTTP URL or disabled certificate verification conflicts with default confidentiality and fails configuration. When no port is configured, HTTPS uses 443; explicit ports are respected. The setting is also available as the boolean environment property `connections.http.defaultConfidentiality`.

This is MINA's Python equivalent of default TLS confidentiality, using the runtime host's system trust rather than a Java `cacerts` file. Certificate-folder trust applies to HTTP Request, REST Invoke and SOAP Request/Reply, in Studio and both Python exports.

## Design and run a REST API

### HTTP Send Response input headers

Every HTTP Send Response activity exposes these optional fields by default in **Input**, for both HTTP Listener and REST Receiver flows:

- **HTTPHeaders** → **Content-Type**, complex **StatusLine**, and **Cookies**. Content-Type accepts common media types or a custom value. Cookies accepts one complete Set-Cookie string or an array of strings; map an array in Studio, for example `["session=abc; Path=/; HttpOnly", "locale=en; Path=/"]`. Each cookie is emitted separately.
- **DynamicHTTPHeaders** → **Headers*** → **headerName**, **headerValue**. Choose **Add header** for independent entries, duplicate the repeating Headers structure, map a collection, or use For Each. Each populated entry needs a name and a value; an empty string is a valid value. Completely empty entries are ignored. Header names are case-insensitive. Repeated names produce separate header lines; Content-Type must have a single value.

Legacy `headers`, `contentType` and `statusCode` mappings remain supported. HTTPHeaders overrides matching legacy settings. DynamicHTTPHeaders overrides matching standard/legacy headers, except Set-Cookie values append to Cookies. Unmapped optional fields keep the existing defaults. Response media types must still satisfy the endpoint contract and the caller's Accept header. Header names and values are validated; newline/control-character injection and malformed status lines fail the activity. The transport retains control of Content-Length, Transfer-Encoding and Connection. These mappings run identically in Studio Run/Debug and Direct/Engine Python archives.

Expand **HTTPHeaders → StatusLine** in Input to map each optional child independently:

| Field | Type | Example Input expression | Behavior |
| --- | --- | --- | --- |
| `httpVersion` | string | `"HTTP/1.0"` or `${input.version}` | Selects the actual response version on a native HTTP/1 listener (1.0 or 1.1). On HTTP/2 or HTTP/3 it must match the negotiated protocol. The `HTTP/` prefix is optional. |
| `statusCode` | integer | `201` or `${Receive.query.status}` | Overrides the legacy statusCode when supplied. Leave unmapped to retain the legacy value or default 200. Numeric literals have no quotes. |
| `reasonPhrase` | string | `"Stored by integration"` or `${input.description}` | Sends a custom reason phrase on native HTTP/1 listeners, including an explicitly empty string. Omit to use the standard status description. Newlines, control characters and non-Latin-1 text are rejected. |

Map the whole StatusLine object when an upstream activity already supplies these fields. An empty object or omitted children keeps the existing numeric status. Legacy full status-line string mappings, such as `"HTTP/1.0 201 Stored by integration"`, also apply their version and reason rather than discarding them. Mapped settings remain visible in **Output → statusLine** and execution/debug data. Hosted final responses require status codes 200–599; 1xx informational responses are not sent by this activity.

`statusCode` controls the actual response status. Native HTTP/1 listeners now apply the mapped version and reason to the wire response. For example, version `"1.0"`, status `201` and reason `"Stored by integration"` send `HTTP/1.0 201 Stored by integration`. This works over HTTP and HTTPS. HTTP/1.0 responses use length-delimited bodies and `Connection: close`; header-only responses retain their normal bodyless semantics. File responses retain their known content length. Each connection/request has independent settings, so custom phrases cannot leak to another response or modify global status tables.

| Listener/connection | Version override | Reason override |
| --- | --- | --- |
| Native HTTP/1 listener (server connection version 1.1), HTTP or HTTPS | HTTP/1.0 or HTTP/1.1 | Custom Latin-1 text or explicitly empty string |
| Negotiated HTTP/2 | Must be HTTP/2 (2.0 alias accepted) | Omit or use empty string; nonempty phrases are rejected |
| Negotiated HTTP/3 | Must be HTTP/3 (3.0 alias accepted) | Omit or use empty string; nonempty phrases are rejected |
| HTTP/1 fallback on a connection configured for HTTP/2 or HTTP/3, or an HTTP/1 ASGI preview/host without MINA's extension | Matching HTTP/1.1 only | Unsupported; omit the field |

HTTP/2 and HTTP/3 carry a numeric `:status`, not a textual reason phrase ([HTTP/2](https://www.rfc-editor.org/rfc/rfc9113.html#section-8.3.2), [HTTP/3](https://www.rfc-editor.org/rfc/rfc9114.html#section-4.3.2)). A response mapping cannot upgrade or downgrade an established HTTP/2/3 connection: configure the server shared connection and client for that protocol instead. Unsupported settings produce an HTTP_RESPONSE 500 before response headers are committed, and the server log records the rejected setting. The workflow may already have run before its response is checked. Protocol-error responses use the transport's normal status line. Studio Run, Debug and both Python archive formats share these rules; ASGI-based previews cannot claim native status-line support unless their host advertises it.

### Request and listener setup

For HTTP Request and REST Invoke, map the contract, operation ID, reference documents/origins and request/response validation settings under **Input → RestInputRequest.Config**. Existing configuration values are shown as typed mappings. Configuration keeps the display name and shared connection selector. JSON/XSD validation and contract selection can use properties or upstream values; XSD validation uses offline lxml validation with self-contained schemas. Generated archives include the required dependencies. Listener routing stays in startup configuration.

Create a **Starter Task** and choose **HTTP Listener** or **REST API Receiver**. In endpoint setup, select the HTTP server shared connection, methods, route, supported request and response content types, and any request or response schema. Use **Create new connection** in the shared connection picker if needed. Studio creates the listener or receiver and an **HTTP Send Response** activity. Schema controls display the selected schema name. Selecting a project schema copies its current definition, so reselect it after editing that definition when the endpoint needs the update.

The receiver starts a task when its configured method and path match a request. Run starts a real listener on the shared connection's host and port, and Stop releases the port. Multiple exported receiver tasks can share a port when their transport settings agree and their routes do not conflict.

Use **HTTP Response** on the same workflow path to reply to a REST Receiver's caller. Studio may name the generated node **HTTP-Send-Response**. Set the status code and map the response body and any headers there.

Select every method you want the receiver to accept. In **Request parameters**, use **URI path** to type a placeholder already in the route, such as `{id}` in `/orders/{id}`. Add **Query** entries for values such as `?details=true` and **Custom header** entries for values such as `X-Tenant`. Set the type and mark any required entries. The receiver returns HTTP 400 if a required value is missing or a declared value has the wrong type. The workflow receives the values in `pathParameters`, `query`, and `headers`, with header names normalized to lowercase. OpenAPI and Postman include these declarations.

Run and Debug show the live listener address. If the connection has a public API base URL, Studio shows that separately as the deployment address. Selecting HTTP on the shared server connection disables TLS and switches HTTP/2 back to HTTP/1.1.

REST Invoke and HTTP Request support URI parameters, default and activity headers/query parameters, JSON, text/XML, form, binary and file bodies, buffered/chunked transfer, response status validation, and optional request/response schema validation. XML requires a text body and the appropriate media type. REST invocation returns `statusCode`, `headers`, `body`, `elapsedMs`, and `httpVersion`; Untouched legacy HTTP Request activities retain their payload response; new requests and requests edited through the Input tree return the response envelope.

Optionally paste an **OpenAPI 3 or Swagger 2 JSON/YAML contract** and select its exact **operation ID**. The operation defines the HTTP method/path, required parameters, media types and request/response schemas. Invocation uses the connection's base URL when supplied, otherwise the contract server URL. A receiver combines its base path with the operation path; without a configured base path it uses the contract server's path. Body validation defaults to enabled. Parameter validation includes required values, arrays, objects, cookies, numeric/string constraints and formats. Operation-level parameters override path-level definitions. Response schemas select exact status, status class (for example `4XX`), then `default`, including error responses before status faults are raised.

Local references work offline. Supply external documents in **Supplied external reference documents** as a JSON object mapping document URI to document object or YAML text. For network references, configure **Contract base URL** for relative paths and explicitly list exact HTTPS origins in **Allowed external reference HTTPS origins**. No origins means no remote retrieval; redirects, URL credentials and implicit file access are forbidden. Retrieval uses the shared client's TLS trust, with document/count/size bounds; schema validation itself never fetches URLs. YAML aliases are rejected. The contract limit is 8 MiB, with at most 16 referenced documents and 32 MiB downloaded references. Mapping expressions do not execute YAML code. MIME bodies continue to use the explicit Input tree; OpenAPI does not automatically manufacture MIME mapping rules or perform browser authorization/consent.

The Studio preview URL uses the same validation and authentication as the real listener. It cannot establish mutual TLS for an individual project; use the configured HTTPS endpoint to test client certificates. Preview signatures use the project-relative listener path. The real endpoint's HTTP/TLS transport settings apply when Run hosts the dedicated listener or an exported application runs.


## Request and response trees

Configuration holds the shared HTTP client connection and optional API contract and schema validation settings. Request values belong in Input, under `RestInputRequest`:

- `Config`: host, port, scheme, requestURI, Method, RequestBody, bodyFormat, query and URI parameters, QueryString, FilePath, timeout in milliseconds, and request policy overrides. Unmapped connection settings supply defaults.
- `Headers`: accept, content-type, Accept-Charset, Accept-Encoding, Cookie and pragma.
- `CustomHeaders`: choose **Add header** to create a row with separate **name** and **value** mappings. Add or remove rows independently, or map a source collection with **For Each**. Repeated custom headers retain all values. Duplicate entries for a nonrepeating standard header fail validation. Header names and values must be ASCII and cannot contain line breaks.
- `mimeEnvelopeElement`: repeating `mimePart` entries containing `mimeHeaders` and exactly one of binaryContent (base64), textContent or fileName. MIME headers include content-type, content-transfer-encoding, content-id and content-disposition. File names refer to files available on the runtime host. Multipart messages are buffered by default; `Config.streamRequest` enables bounded streaming within the configured size limit.

Legacy request configuration values appear as Input mappings when opened; editing saves them into the new structure. String constants require quotes; numbers and booleans use native literals, while expressions supply runtime values. Output exposes `RestOutputResponse` with statusLine (httpVersion, statusCode, reasonPhrase), body, asciiContent, binaryContent, Headers, repeating DynamicHeaders and parsed MIME parts. The runtime also retains the envelope's statusCode, headers, body, elapsedMs and httpVersion fields. Input and Output trees show optional and repeating cardinalities.

The request input uses the `RestInputRequest` root. Studio, Direct Python and Engine Python exports use the same request and MIME implementation.

For a request to `/orders/{id}`, map `Config.URIParameters` to an object such as `{"id":"A/B"}` and `Config.QueryParameters` to an object such as `{"tag":["open","priority"]}`. The slash in the ID is encoded as part of the path value, and both tags are sent. To send `X-Tenant: west`, open **CustomHeaders**, choose **Add header**, and map the name to `"X-Tenant"` and the value to `"west"`. A mapped query value overrides the same key from the connection or request URI.

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

Set **Requests per client/window** above zero to enable fixed-window throttling. The key uses the effective client IP and route. Exceeding the limit returns 429 and `Retry-After`. Redis storage shares counts across replicas. Memory storage applies within one runtime. Set **Trusted proxy IPs / CIDRs** if a trusted proxy supplies client addresses.

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

Use the activity's **Documentation** tab for its own Configuration, Input, Output, and Errors reference. In **Help → MINA Documentation**, search for **HTTP and REST activity verification** for the supported test matrix and remaining standards gaps.

### OpenAPI security and multipart forms

Select a server connection that can enforce the imported operation's security. MINA uses operation-level OpenAPI security, or inherits the top-level declaration if omitted. Configure **OpenAPI API key secrets** as a protected JSON property keyed by security scheme name. API keys can be read from headers, query parameters or cookies. MINA requires all keys named in a selected alternative, together with its configured Basic/LDAP, Bearer/JWT/OAuth2 or mutual TLS requirements where applicable. The listener refuses startup if it cannot enforce any alternative. A shared connection supports one HTTP Authorization scheme at a time.

For a contract with `multipart/form-data`, map **RequestBody** by form property name. Arrays generate repeated parts, nested objects are JSON, and `format: binary` fields take base64. OpenAPI `encoding.contentType` controls the part type. Map **multipartPartHeaders** as an object keyed by form property when the contract declares extra headers. Declared defaults fill omitted outbound headers. MINA validates required headers and their schemas on both sides. Reserved framing and content headers remain controlled by the serializer. The receiving workflow gets typed `body` and `mimeEnvelopeElement`. Contract-driven forms are buffered and bounded.

Outbound query parameters with OpenAPI `allowReserved: true` preserve URI-safe reserved characters and valid percent escapes. Delimiters that could create another query parameter or a URL fragment remain escaped.

### Shared HTTP policies

- Set **Listener error response format** to **problem** for RFC 9457 `application/problem+json` errors produced by the listener. Existing connections default to the original JSON error shape. Workflow responses still use the body and content type mapped in HTTP Send Response.
- Set **Trusted proxy IPs / CIDRs** only for proxies you control that maintain the `X-Forwarded-For` chain. MINA checks the immediate peer and walks the chain from right to left. The effective address appears in `clientIp` and applies to IP allowlists and rate limits. The original peer remains in `remote`.
- Enable **Propagate HTTP trace context** on the inbound and outbound connections to link version 00 `traceparent` headers across a workflow. The listener exposes `traceId`. This propagates identifiers and does not export trace spans.
- Enable **Conditional GET and HEAD** and map `ETag` or `Last-Modified` response headers to return 304 when the request validators match. The workflow still runs. The option does not cache responses or enforce write preconditions.
- **HTTP Write Preconditions** checks inbound headers against mapped datastore validators and returns `allowed` and `statusCode` (200, 412, or 428). Branch before any mutation. Use a version predicate or transaction lock in the actual write to prevent a concurrent change between the check and mutation.
- **Shared public response cache** reuses fresh public HTTP 200 GET responses in the runtime process. It partitions entries by destination and request headers, honors explicit freshness and skips authenticated, conditional, range and file requests. A successful mutation through a cache-enabled connection invalidates that origin's entries. Replicas each have their own cache.
- For OAuth client assertions, select **private_key_jwt** and set the registered PEM key path, asymmetric algorithm, and optional key ID. The runtime signs a short-lived assertion for the configured HTTPS token or introspection URL. Provide the signing key separately on the runtime host.

### HTTP/3, event streams, and callbacks

Select protocol **3** for native HTTP/3. Hosting binds UDP and TCP on the configured port and needs an HTTPS PEM certificate plus unencrypted PEM private key. TCP also serves HTTP/2 and HTTP/1.1. Native outbound HTTP/3 requires direct, verified HTTPS and supports buffered requests and replies. Proxies, file streaming, mutual TLS, custom CRLs and custom cipher suites are outside the HTTP/3 implementation.

Use **Read Server-Sent Events** to read a bounded batch with an optional Last-Event-ID. Use **WebSocket Exchange** with a `ws://` or `wss://` URL to send an optional message and collect bounded replies. Binary replies are base64. These activities close their connection when finished. They do not publish SSE streams, host WebSocket endpoints, or reconnect automatically.

API Blueprint imports OpenAPI webhooks as selectable listeners under `/_webhooks/<name>`. Configure authentication on the server connection before hosting them. Callbacks on selected operations generate reusable Sub Tasks. Call one explicitly with `callbackUrl` and `body` and set the `connections.http.callbackAllowedOrigins` property to the approved HTTPS origins. Use the contract expression shown in the task description to map the URL. MINA validates the callback contract, verifies TLS, and disables redirects. The generated task performs one workflow-managed delivery rather than creating an automatic subscription or durable delivery queue.

## Deployment qualification

The activity-level suite `tests.test_http_activity_e2e` exercises HTTP Listener and REST Receiver through both HTTP Request and REST Invoke, returning through HTTP Response on real local listeners. It also covers Studio contract preview, HMAC encoded request targets, HTTPS preview enforcement, multiple content types, strict JSON, bodyless responses and fresh Direct/Engine archives.

REST contracts retain all declared request/response content types and validate against the actual Content-Type, using exact media types before type wildcards and `*/*`. Swagger exposes all declared formats. Set HTTP Response's content type explicitly when returning a representation other than the configured default; the workflow chooses the response representation. Explicit request-schema overrides remain effective. Optional absent request bodies are accepted; required bodies cannot be bypassed with Send Body Mode = NEVER/AUTO.

In HTTP Listener and REST Receiver setup or Configuration, check one or more **Request content types** and **Response content types**. You can add custom types alongside the common ones. No selection keeps automatic behavior. With multiple response types, MINA uses the caller's `Accept` header and its quality values; the first checked format is the default. An explicitly mapped HTTP Send Response content type must be one of the offered types and acceptable to the client. For XML output, map an XML document or an object with one root element. With mixed media types, a standalone XSD applies to XML and a standalone JSON Schema applies to JSON; use an OpenAPI contract for separate schemas by media type. Swagger lists each selected format, and the Postman export includes a request for each selected request format.

URL-encoded form fields use declared primitive schema types before validation, including repeated primitive arrays. Direct archives also accept the default HTTP Response operation, matching runtime behavior.

When body format is omitted, outbound text/XML content is sent as text and URL-encoded form content is encoded as form data. Explicit body format settings retain precedence. Text responses such as `42` remain strings. Malformed nonempty JSON and NaN/Infinity are rejected; binary response mode retains raw content. HEAD, 204, 205 and 304 responses skip body schema validation because they have no response content. TRACE is supported as an optional API operation; CONNECT proxy tunneling is not offered as an API method.

Studio preview resolves methods and paths from the selected API contract, including HEAD, OPTIONS and 405 behavior. Signed previews use the actual encoded public request target. A connection requiring HTTPS must use an HTTPS endpoint; plain HTTP preview cannot bypass confidentiality.

An explicit HTTPS server scheme always enables TLS, even if a legacy TLS checkbox value is false. A missing server certificate/key then fails startup instead of silently opening a plaintext listener.

Run `python -m unittest tests.test_http_capabilities tests.test_http_request_tree tests.test_http_production` from `backend` with its virtual environment active. The suite covers local TLS/mTLS, HTTP/2 negotiation, HTTP contracts, binary/repeating values, streaming/file cleanup, policy behavior and Python exports. Redis protocol calls are tested with an injected store; provision and exercise the actual Redis service, issuer/LDAP, certificates, proxy and upstream API in staging.

Export Direct or Engine Python and install the archive's generated dependencies. HTTP contract support requires `jsonschema`, `PyYAML` and `regex`; HTTP/2 hosting adds `hypercorn`/`h2`; distributed policies add `redis`. Keep certificate files and secrets external. Supply the Redis URL through the generated secret binding, never an unprotected source literal.

Use the Direct archive's `--qualify-task <task-id>` runner against the staging API with representative payloads, concurrency, latency/error thresholds and memory limits. Test the Engine archive with the same fixtures and deployment load harness. Repeat under upstream outages, token/key rotation, Redis failure and deployment restart. Record the report with the release. Automated regression success is evidence for the implemented behavior, not a guarantee about an untested production environment or third-party service.
