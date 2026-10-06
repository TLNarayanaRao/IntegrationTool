# REST APIs and shared HTTP connections

Use **HTTP Client Connection** for HTTP Request / REST Invoke and **HTTP Server Connection** for HTTP Listener / REST Receiver. These presets create reusable HTTP resources with explicit client/server roles. Existing HTTP resources continue to work; choose a role when editing them. A server resource cannot be used for an outbound request, and a client resource cannot host a listener.

## Design and run a REST API

REST Receiver starts a task when its configured method and path match a request. Add an HTTP response activity to control status, headers and body. Run starts a real listener on the shared connection's host and port, and Stop releases the port. Multiple exported receiver tasks can share a port when their transport settings agree and their routes do not conflict.

REST Invoke and HTTP Request support URI parameters, default and activity headers/query parameters, JSON, text/XML, form, binary and file bodies, buffered/chunked transfer, response status validation, and optional request/response schema validation. XML requires a text body and the appropriate media type. REST invocation returns `statusCode`, `headers`, `body`, `elapsedMs`, and `httpVersion`; Untouched legacy HTTP Request activities retain their payload response; new requests and requests edited through the Input tree return the response envelope.

Optionally paste an **OpenAPI 3 or Swagger 2 JSON contract** and select its exact **operation ID**. The operation defines the HTTP method and path, required parameters, media types, and request/response schemas. Invocation uses the connection's base URL when supplied, otherwise the contract's server URL. A receiver uses its configured bind address and combines its base path with the operation path; without a configured base path it uses the contract server's path. Contract validation defaults to enabled; the validation switches can disable body schema checks. Required parameters and primitive wire types still validate. Only local references are followed. YAML, remote references, externally referenced documents, browser authorization flows and OpenAPI multipart schema synthesis are not implemented. MIME multipart bodies use the Input tree.

The Studio preview URL uses the same validation and authentication as the real listener. It cannot establish mutual TLS for an individual project; use the configured HTTPS endpoint to test client certificates. Preview signatures use the project-relative listener path. The real endpoint's HTTP/TLS transport settings apply when Run hosts the dedicated listener or an exported application runs.


## Request and response trees

Configuration holds the shared HTTP client connection and optional API contract and schema validation settings. Request values belong in Input, under `RestInputRequest`:

- `Config`: host, port, scheme, requestURI, Method, RequestBody, bodyFormat, query and URI parameters, QueryString, FilePath, timeout in milliseconds, and request policy overrides. Unmapped connection settings supply defaults.
- `Headers`: accept, content-type, Accept-Charset, Accept-Encoding, Cookie and pragma. Repeating `DynamicHeaders` entries contain name/value pairs. Add or remove entries independently, or map a source collection with For Each. Repeated custom headers retain all values; duplicate dynamic entries for a nonrepeating standard header fail validation. Header names and values must be ASCII and cannot contain line breaks.
- `mimeEnvelopeElement`: repeating `mimePart` entries containing `mimeHeaders` and exactly one of binaryContent (base64), textContent or fileName. MIME headers include content-type, content-transfer-encoding, content-id and content-disposition. File names refer to files available on the runtime host. Multipart messages are buffered within the configured size limit.

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

Zero client phase timeout means no independent phase deadline, subject to the activity timeout budget. The default activity budget is 180 seconds; synchronous client phase waits and response consumption are bounded, but this is not a hard wall-clock cancellation of a Python thread. Retries apply only to connection failures, preventing automatic replays after an uncertain response. Host/port settings must refer to an address the runtime can actually bind or reach.

QTP is a Jetty concept. MINA implements its minimum/maximum settings with Python authentication workers and an asynchronous request concurrency gate. It does not embed Jetty or duplicate its scheduling semantics. Outbound HTTP/2 is supported; inbound listeners currently serve HTTP/1.1. Use an HTTP/2 gateway when needed. TLS 1.3 cipher selection follows the Python/OpenSSL defaults. Certificate revocation uses configured CRLs; OCSP fetching and Java security-provider configuration are not implemented.

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

HMAC uses MINA's explicit signing format, not AWS SigV4 or a vendor-specific HMAC policy. Send `X-MINA-Key-Id`, `X-MINA-Timestamp`, `X-MINA-Nonce`, and `Authorization: HMAC <base64 signature>`. The signed text is five newline-separated values: uppercase method, exact encoded path/query, Unix timestamp, nonce, and hexadecimal SHA256 body digest. Select SHA256/384/512 for the keyed signature. Signed requests cannot follow redirects. Nonce replay protection is process-local; put a shared replay policy at the gateway when scaling across replicas.

## Python deployment

Studio, Direct Python archives and Engine Python archives use the same HTTP transport, authentication and listener implementation. Generated dependency checks include HTTPX, Uvicorn and the security libraries required by the configured connections. Provision external certificate/key/store files on the execution host, and supply exported secrets through the deployment environment/property bindings. Export retains endpoint URLs and key-file locations while removing secret values.

Direct archives can run with `python run.py` after extraction or as a Python zip application. Engine archives run with `python -m application.main`. Existing Administrator deployment commands continue to apply. Optional modules include PyJWT/cryptography, ldap3, httpx-ntlm and h2. Test against your own directory, identity provider, certificate chain and proxy before deployment; local automated tests exercise protocol behavior and failures, not access to external enterprise services.

## Reference documentation and scope

The design was compared against the [TIBCO BusinessWorks 6.12 REST Reference](https://docs.tibco.com/pub/activematrix_businessworks/6.12.0/doc/pdf/TIB_BW_6.12.0_rest_reference.pdf), [MuleSoft HTTP connector reference](https://docs.mulesoft.com/http-connector/latest/http-documentation), [HTTP authentication](https://docs.mulesoft.com/http-connector/latest/http-authentication), and [LDAP Basic authentication policy](https://docs.mulesoft.com/mule-gateway/policies-included-basic-auth-ldap). Detailed HTTP client settings were available in the [BW 6.11 HTTP Client reference](https://docs.tibco.com/pub/activematrix_businessworks/6.11.0/doc/html/binding-palette/http-client.htm); the corresponding 6.12 HTML reference was unavailable during review.

This implementation provides Python equivalents for the documented capabilities listed above. It does not claim full TIBCO/Mule engine compatibility. Java client implementations, Jetty QTP internals, Mule policy deployment, full OpenAPI compliance, WADL generation, streaming multipart bodies, provider-specific OAuth browser integrations and vendor-specific security modules remain outside the implementation.
