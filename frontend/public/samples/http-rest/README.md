# MINA HTTP and REST sample projects

Import these projects into Studio to learn API hosting, outbound requests, HTTPS trust, authentication, Swagger testing and Postman downloads. Twenty projects cover the cases below. Each host and caller is a separate project, so you can keep the provider listening while running its caller. These are local learning fixtures, with public demo credentials and example business responses.

## Prepare and import

### Open directly from Studio Samples

In Studio choose **Samples → HTTP & REST examples**, then select **Open editable sample** on the desired host or caller card. Each opening creates a new project, preserving any edited copy you already have. You do not need to browse for or import a package. The cards identify the matching host, port and required setup.

HTTP host samples run immediately. For HTTPS/authentication examples, use **Download API helper kit** in the Samples window, extract it and run `prepare.py` as described below. In each opened secure sample set **Properties → local → demo.directory** to the full path of the helper kit's generated `local` folder. This one property supplies the trusted-root folder and certificate/key paths. Start the OAuth fixture from that same helper kit before using samples 06/15. **API setup guide** downloads this guide from the Samples window.

### Import the standalone packages

1. Extract the complete sample bundle to a writable folder. Keep `projects`, `specs`, `postman` and the Python helpers together. The `projects/*.mpackage` files are the files to import into Studio; the outer ZIP is a distribution bundle.
2. Prepare certificate files and update package paths **before importing**. From the repository root on this Windows machine, run:

   ```powershell
   & .\backend\.venv\Scripts\python.exe .\samples\http-rest-examples\prepare.py
   ```

   In an extracted standalone bundle on Windows or Linux, use Python 3.10+ with `cryptography` installed:

   ```text
   python -m pip install -r requirements.txt
   python prepare.py
   ```

   Preparation generates local certificates and rewrites `demo.directory` in all packages to the actual folder. It does not install certificates into your operating system or change system trust. HTTP-only samples can be imported without this step.
3. In Studio select **Import**, choose the required `.mpackage`, then select **local** as the environment. Import the corresponding caller as a separate project. Do not import the fixture scripts as projects.
4. Open the host project, select its API task and click **Run**. Keep that project running. Select the caller project and click **Run**. The caller's output has `statusCode: 200` and the response under `body`.
5. Use **Stop** in the host project when finished. All hosts bind to loopback only. Their ports must be free; change both host and caller connection settings if you change a port.

Certificates are valid for 30 days. To renew, stop the samples, move the generated `local` folder aside and rerun `prepare.py`. Reimport the packages or update the imported projects' `demo.directory` property. Running preparation again with complete existing files preserves the certificates. Never use these fixture keys or credentials for real services.

## Importable projects

| File in projects | Purpose | Provider and expected result |
| --- | --- | --- |
| 01-host-one-http.mpackage | One REST API operation | Port 9001, GET `/hello` returns `{"message":"Hello from MINA"}` |
| 02-host-multiple-http.mpackage | Three operations hosted together | Port 9002, GET `/hello`, GET `/orders/{id}`, POST `/echo` |
| 03-host-generic-http.mpackage | Plain HTTP Listener and HTTP Response | Port 9003, GET `/hello`; generated Swagger without a REST contract |
| 04-host-https.mpackage | HTTPS server identity | Port 9443, GET `/hello`; server sends leaf plus intermediate |
| 05-host-basic.mpackage | Basic authentication over HTTPS | Port 9445, valid credentials give 200; missing/wrong credentials give 401 |
| 06-host-oauth2.mpackage | OAuth 2.0 resource server using introspection | Port 9446; start the token fixture on 9444 first |
| 07-host-jwt.mpackage | Signed JWT validation | Port 9447, verifies signature, expiry, issuer and audience |
| 08-host-hmac.mpackage | HMAC authentication | Port 9448, signs method, path/query, body digest, timestamp and nonce |
| 09-host-mtls.mpackage | Mutual TLS client certificates | Port 9449, requires a trusted client certificate |
| 10-call-http.mpackage | HTTP Request over HTTP | Call host 01 on 9001 |
| 11-invoke-rest.mpackage | REST Invoke with a path parameter | Call host 02 `/orders/42`; example order response has id `42` |
| 12-call-https.mpackage | HTTP Request over verified HTTPS | Call host 04 using only the root in the trusted folder |
| 13-default-confidentiality.mpackage | REST Invoke with default confidentiality | Call host 04; HTTPS and hostname/certificate verification remain required |
| 14-call-basic.mpackage | REST Invoke with Basic credentials | Call host 05 |
| 15-call-oauth2.mpackage | OAuth client credentials token exchange and API call | Call host 06, obtaining a token from the HTTPS fixture |
| 16-call-jwt.mpackage | Generate and send a signed JWT | Call host 07 |
| 17-call-hmac.mpackage | Generate fresh HMAC headers | Call host 08 |
| 18-call-mtls.mpackage | Send a client certificate over HTTPS | Call host 09 |
| 19-post-json.mpackage | JSON request body and Content-Type header | Call host 02 POST `/echo`; returns the validated request body |
| 20-path-query-headers.mpackage | Path, query and repeating custom headers | Call host 02 `/orders/42?detail=true`, with X-Correlation-ID and X-Channel |

The multiple-operation project uses one MINA API Blueprint group. Running any of its generated API tasks hosts all three operations. The order endpoint deliberately returns a fixed example order; it is not a database lookup. `/echo` validates and returns the actual posted JSON. Host and caller examples use shared HTTP connections; outbound request values are mapped in the activity's **Input → RestInputRequest** tree.

Matching OpenAPI documents are in `specs`. To practice authoring instead of importing the ready project, create a new Studio project, open **API Blueprint**, load the desired `.openapi.json` (JSON is valid YAML), validate, select operations, select example responses, and create/host the API. Set HTTPS and authentication on its shared HTTP server connection as shown in the corresponding ready project.

## Start with one HTTP API

1. Import `01-host-one-http.mpackage` and `10-call-http.mpackage`.
2. Run the host's GET `/hello` task.
3. The live endpoints panel shows `http://127.0.0.1:9001/hello` and an **Open Swagger** link. Open `http://localhost:9001/_mina/docs` if testing from the same computer.
4. Expand GET `/hello`, select **Try it out**, then **Execute**. Expect 200 and the greeting JSON.
5. Run the caller project. Inspect the Call output to see the same response.

For multiple APIs, run project 02 instead and use its Swagger on port 9002. Its POST `/echo` accepts `{"name":"Sample item","quantity":2}`. Missing `name`, an empty name, non-integer quantity or quantity below 1 produces 400. An unknown route gives 404; DELETE `/hello` gives 405.

To host independent APIs at the same time, run host 01 in its project and host 02 in its separate project. Both listeners stay available, on 9001 and 9002 respectively, with separate Swagger URLs and collections. Studio Run owns the selected host or Blueprint group; for independent hosts keep separate projects rather than repeatedly starting different host groups within one project.

## HTTPS and root certificate trust

Run host 04 and caller 12 or 13. `local/trusted-roots` contains **only root.pem**. The server presents `server-chain.pem`, containing its leaf and intermediate certificates. The caller verifies that chain to the root and validates the localhost/127.0.0.1 certificate name. The caller does not need the intermediate or server leaf in its trusted folder.

The shared client connection's **Trusted certificate folder** is `${properties.demo.directory}/trusted-roots`. Host identity fields point to `server-chain.pem` and `server-key.pem`. Caller 13 enables **Default confidentiality** and retains certificate verification. Its custom root supplements system trust; default confidentiality does not mean accepting a self-signed or untrusted server.

For browser Swagger testing, trust the generated demo root in a dedicated test browser/profile using your normal certificate-management process. For Postman, add `local/trusted-roots/root.pem` as a CA certificate in certificate settings and keep SSL verification enabled. MINA's trusted-folder setting does not configure browser or Postman trust. Never bypass a certificate warning as the setup method. For another computer, these loopback samples must be adapted deliberately: listener binding, public URL, firewall and certificate SAN must all match that deployment.

For mutual TLS, run host 09 and caller 18. In Postman also add a client certificate for `localhost`, port `9449`, with `client-chain.pem` as the CRT and `client-key.pem` as the KEY. Browser client-certificate enrollment depends on the browser/OS; use the included MINA caller or Postman PEM settings for this example. A trusted root alone does not supply client identity.

## Basic authentication

Run host 05 and caller 14. The local properties are `demo.username = mina-demo` and `demo.password = mina-demo-password`. In Swagger's documentation access panel select **Basic / LDAP**, enter those values, then **Load API docs**. Swagger's request interceptor uses those credentials for testing. A request without credentials, or with a wrong password, returns 401. Basic credentials are used only over HTTPS in these examples.

## OAuth 2.0 client credentials

This example exercises a real HTTPS token exchange, token caching and protected-API introspection using a small local fixture. The fixture supports **client_credentials only**; it is not a production authorization server or a browser login service.

1. In a separate terminal start the fixture and leave it running:

   ```powershell
   & .\backend\.venv\Scripts\python.exe .\samples\http-rest-examples\oauth_fixture.py
   ```

   From an extracted bundle, run `python oauth_fixture.py`.
2. Import and run host 06. Its shared server connection uses **OAuth2**, the HTTPS introspection URL `https://localhost:9444/introspect`, client ID `mina-demo-client`, client secret `mina-demo-client-secret`, required scope `orders.read`, and the generated trusted-root folder.
3. Import and run caller 15. Its shared client connection uses token URL `https://localhost:9444/token`, grant `client_credentials`, client authentication `basic`, scope `orders.read`, the same client ID/secret and root folder. The activity obtains a short-lived opaque access token and sends it as Bearer authorization to the API. The API introspects that token and checks scope/expiry.
4. To obtain a token for Swagger/Postman, run:

   ```powershell
   & .\backend\.venv\Scripts\python.exe .\samples\http-rest-examples\tokens.py oauth2
   ```

   In a standalone bundle use `python tokens.py oauth2`. Copy the printed token, select Bearer/token access in Swagger, paste it and load the docs. Tokens expire after five minutes; request another when needed.
5. For negative tests use an invented token (401), wrong client secret (token exchange fails), or request a token with only `profile` scope (the API rejects it with 401 because `orders.read` is required). Stopping the fixture makes new token exchanges/introspection fail. Stop the host and fixture when finished.

For Postman's OAuth 2.0 authorization helper use **Client Credentials**, the access-token URL above, client authentication **Send as Basic Auth header**, and the same client ID, secret and scope. Alternatively use `tokens.py oauth2` and the collection's `accessToken` variable. The generated collection intentionally uses an empty Bearer-token variable; it does not export an OAuth client secret. Configure the CA certificate before requesting a token.

For a real issuer replace token/introspection URLs, credentials, scopes and trust configuration. Authorization Code with PKCE and Refresh Token grants require provider-issued codes/tokens and redirect registration; no reusable code/token is bundled. Configure `oauthGrantType`, `oauthAuthorizationCode`, `oauthRedirectUri`, `oauthCodeVerifier`, or `oauthRefreshToken` as appropriate to that provider. These provider-dependent grants are recipes, not additional runnable local-fixture examples.

## JWT and HMAC

Run host 07 with caller 16 for JWT. Both use the demo HS256 secret, issuer `mina-demo`, audience `mina-sample-api`, and a five-minute lifetime. To test in Swagger/Postman run `tokens.py jwt`, choose Bearer/token access, and paste the result. An invalid signature, expired token, wrong issuer or audience must be rejected. Use managed asymmetric keys and your actual issuer policies for a real deployment.

Run host 08 with caller 17 for HMAC. The local key ID is `default`; the demo secret is the `demo.hmacSecret` property. In Swagger choose **MINA HMAC**, use that key ID/secret and load the docs. It signs each raw request afresh. In the Postman collection set `hmacKeyId` and `hmacSecret`; its pre-request script computes a fresh signature. Reusing a captured signature/nonce is rejected. Multipart/file-body signing needs a signing client; the supplied collection signer covers raw bodies.

## Download and import Postman collections

1. Run the desired **host** project in Studio. Open its live endpoints panel.
2. Click **Download Postman collection**. Save `MINA-API.postman_collection.json`; no separate copy step is required.
3. Alternatively click **Open Swagger**, supply documentation credentials if required, and click **Download Postman collection** in that page.
4. In Postman choose **Import**, select the downloaded JSON, and open the imported collection. Review `baseUrl` and the request paths.
5. Configure HTTPS CA/client certificates before testing TLS endpoints. Set only the variables relevant to the example: `username`/`password`, `accessToken`, or `hmacKeyId`/`hmacSecret`. Saved MINA credentials are not included in downloads.
6. Send a request. Expect 200 for a valid example. The multiple-operation collection contains three requests; `/echo` includes an editable example JSON body.

Ready-made collections for all nine hosts are also in `postman`. They target localhost and remain usable after Studio import/preparation. These are convenient starter files; download again from Studio after changing hosted routes. The mutual-TLS collection needs client certificate settings outside the JSON.

## Debug and failure checks

Open a host, set a breakpoint on HTTP Response, then choose **Debug**. The live endpoints panel shows the actual server and Swagger URL. Send a request from Swagger/Postman. It remains pending while Studio is paused. Continue or Step to finish it and return the response. One HTTP request can be debugged at a time; additional simultaneous requests return 503. Respect the activity/client timeout and stop the debug host when finished. Documentation requests themselves do not execute the flow.

| Check | Expected result |
| --- | --- |
| Run a caller before its host | Connection failure; start the matching host |
| Invalid `/echo` JSON against its schema | 400 |
| Unknown path / unsupported method | 404 / 405 |
| Missing or incorrect credentials | 401; mTLS may fail during the TLS handshake |
| OAuth token missing required scope or expired | 401 |
| Client missing the trusted demo root | TLS verification failure |
| Hostname absent from the server certificate | TLS hostname verification failure |
| Occupied host port | Startup failure; free/change the sample port |
| Moved sample folder after importing | Update `demo.directory` in the imported local environment |
| Expired demo certificates | Renew locally and update/reimport the projects |

To rerun the complete executable check from the repository root:

```powershell
& .\backend\.venv\Scripts\python.exe .\samples\http-rest-examples\verify_examples.py
```

The verifier uses real packaged projects, native listeners and the runtime, tests all 20 projects plus selected negative cases, and stops its fixtures afterward. It needs the repository backend dependencies and sample ports 9001–9003 and 9443–9449 free. `verification-report.json` is a local test result, not an importable project. `build_examples.py` is a maintainer generator; ordinary users only need preparation, import and the fixture/token helpers.

## References

- [OAuth 2.0 client credentials and TLS requirements](https://www.rfc-editor.org/rfc/rfc6749.html#section-4.4)
- [Postman collection import](https://learning.postman.com/docs/getting-started/importing-and-exporting/importing-data/)
- [Postman CA and client certificate setup](https://learning.postman.com/docs/use/send-requests/authorization/certificates/)
