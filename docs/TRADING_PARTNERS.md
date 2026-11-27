# Trading partners and AS2

The **Trading Partners** activity palette includes X12 and UN/EDIFACT
parsing and rendering, AS2 send and receive, synchronous and asynchronous signed
MDNs, X12 997/999 and EDIFACT CONTRL, and exchange lookup by Message-ID.

## Set up a partner

1. In Project Explorer, right-click **Resources → Connections**, then choose
   **Trading Partner**. You can also create the profile from an AS2 activity’s
   connection selector.
2. Enter the exact AS2 identifiers agreed with the partner. For outbound
   delivery, enter the partner’s HTTPS endpoint and a disposition notification
   address. HTTPS verifies the server certificate against system trust or
   the configured HTTPS CA bundle.
3. Supply the local X.509 certificate and private key and the pinned partner’s
   public certificate as runtime PEM paths. For an encrypted private key, bind
   its passphrase to a protected environment property. Mount the files
   separately when deploying and restrict access to the private key.
4. Keep outbound encryption and required inbound encryption enabled unless
   the partner has agreed to signed-only delivery. The profile test checks
   identities, certificate validity, and the local key pair without sending EDI.
5. Optionally select X12 or EDIFACT, restrict allowed transaction types, and
   enter the local and partner EDI envelope IDs. For EDIFACT, use the primary
   ID without its qualifier.

### HTTPS and compression

- For a partner that challenges AS2 Send with HTTP Basic authentication,
  configure the **Outbound HTTP Basic username** and bind the **password**
  to a protected property. MINA sends these credentials to the configured
  HTTPS data endpoint only. An inbound partner that uses HTTP Basic can
  authenticate against the HTTP Listener connection before AS2 verification.
- Set **Retries when the HTTP response is lost** to 1 or 2 if your partner
  supports duplicate delivery detection. MINA retries response read errors,
  response timeouts, and dropped connections with identical wire bytes,
  Message-ID, and Date within the same AS2 Send call. HTTP error responses,
  failed receipt verification, and restarts use the existing reconciliation
  and recovery process. The default is zero automatic retries.
- For a partner that requires mutual TLS, configure the **Mutual TLS client
  certificate chain** and **client private key** PEM paths. AS2 Send and
  AS2 Deliver Async MDN present that identity. Supply a protected property
  for an encrypted TLS key. The **HTTPS CA bundle** adds trust roots to
  system trust. MINA verifies the server certificate and hostname. Configure
  incoming mutual TLS on the HTTP Listener connection by requiring client
  certificates and trusting the partner's issuing CA. AS2 signature
  validation still uses the pinned AS2 certificate.
- Enable **Compress outbound EDI** only when agreed with the partner. MINA
  compresses the payload using CMS zlib before signing and, when enabled,
  encrypting it. Signed inbound EDI supports compression before or after
  signing, including encrypted exchanges. MINA bounds decompression and
  computes the MIC over the signed MIME entity. See [RFC 5402](https://www.rfc-editor.org/rfc/rfc5402.html).

## Validate and render EDI

Map the EDI text or original Base64 bytes to **Parse and Validate EDI**.
It checks interchange, functional group, and transaction control references
and counts before exposing the ordered segment tree. A document contains one
interchange. X12 uses ISA/IEA, GS/GE, and ST/SE envelopes. EDIFACT uses
UNB/UNZ and UNH/UNT, with optional UNA and functional groups.

Use partner-owned rules for required segments and element positions. For
example, this rule requires BEG and its first three elements in an 850.

```json
{"850":{"requiredSegments":["BEG"],"requiredElements":{"BEG":[1,2,3]}}}
```

Rules can be supplied on the partner profile for AS2 or directly on the EDI
activities. **Render EDI** accepts the parsed segment structure and validates
the rendered document. Update envelope control numbers and counts when your
mapping changes the structure. Rendering preserves elements and delimiters.
Use the original bytes when resend or signature verification requires byte identity.

## Exchange non-EDI business documents

Set **Non-EDI payload media type** on the partner profile to the wire type
agreed with the partner, such as `application/xml`, `application/json`,
`text/csv`, `application/edi-consent`, or `application/octet-stream`. Leave
the field blank to keep X12 and EDIFACT validation. For other types, map text
to **Business document text** for UTF-8 encoding, or map the original bytes
to **Original document bytes (Base64)**. AS2 Receive verifies the signed
payload and the configured media type, then exposes `binaryContent` and
`contentType`. Each business document can contain up to 8 MiB. The workflow
can parse or validate the received bytes before creating its signed receipt.

## Send, receive, and reconcile

- **Send** maps text or Base64 bytes to **AS2 Send**. MINA validates the
  interchange, signs it with SHA-256, applies encryption when enabled, and
  waits for the signed MDN in synchronous mode. A valid success receipt sets `accepted=true`.
  A signed rejection sets `accepted=false`. Transport or verification
  failures raise an activity fault. Route the signed rejection explicitly.
  A signed rejection can omit the MIC if the peer could not compute it.
  `receiptMicVerified` distinguishes that outcome from a rejection with a
  matching MIC. A success receipt always requires a matching MIC.
- **Receive** starts with a POST **HTTP Listener** on a dedicated HTTPS route.
  Leave request parsing schema and upload-to-file unset so the original body
  bytes are available. Map the listener result to **AS2 Receive**. It checks
  partner IDs, encryption, the pinned signature, and EDI envelopes before
  returning a claim and parsed interchange.
- **Reject invalid EDI with a signed MDN** by enabling **Return signed MDN
  for invalid inbound EDI**. When a signed receipt was requested and the
  partner signature verifies, invalid interchange content or a failed
  decompression inside the signed entity sets `status=rejected` and
  returns `errorCode` and `receipt`. Route this result before duplicate
  or business processing checks. Send the returned `receipt` through
  **HTTP Send Response**. For async mode, the response acknowledges the
  transport and **AS2 Deliver Async MDN** sends the stored negative receipt.
  Signature, decryption, and other failures that prevent authentication
  still raise an activity fault. Existing profiles retain their validation
  fault behavior until the setting is enabled.
- **Acknowledge** uses **AS2 Create Signed Receipt** after business processing.
  Map the Message-ID and claim token from AS2 Receive. Use the rejected
  disposition for a known failure after a delivery has been authenticated
  and claimed. Map `receipt.headers` and `receipt.binaryContent` into
  **HTTP Send Response**.
- **Handle duplicates** before running business logic. If AS2 Receive reports
  `duplicate=true`, send the cached `receipt` directly. The same Message-ID
  with different wire content is rejected. A pending delivery cannot produce
  a completed receipt until its fenced claim is settled.
- **Reconcile** through **AS2 Exchange Lookup**. Select inbound or outbound,
  then map the Message-ID. The result includes status, the interchange control
  reference and SHA-256 MIC. A signed MDN acknowledges the AS2 exchange.
  Send the EDI acknowledgement separately when required by the trading agreement.

The ledger defaults to `as2-ledger.sqlite3` under `MINA_DATA_DIR` or the
user’s `.mina` folder. Set `MINA_AS2_LEDGER_FILE` to a durable volume on
the runtime host. The default inbound processing lease is five minutes.
Records are retained for up to 90 days and capped at 100,000. Resolve uncertain
outbound delivery with the partner before resubmitting.

## Exchange asynchronous MDNs

1. On the sender profile, set **Outbound receipt mode** to **asynchronous**
   and configure **Local asynchronous MDN HTTPS URL**. Host a POST HTTP
   Listener at that path. Connect it to **AS2 Receive Async MDN**, then map
   `receipt.headers` and `receipt.binaryContent` into **HTTP Send Response**.
2. On the receiver profile, set **Partner asynchronous MDN HTTPS URL** to the
   exact address advertised by the message sender. MINA authorizes callback
   delivery against this profile address. It verifies the signed EDI before
   claiming it and compares the callback address before sending the MDN.
3. Process the original interchange, then use **AS2 Create Signed Receipt**
   to store the signed MDN and mark the receipt pending. Return the empty
   HTTP transport acknowledgement from its `receipt` fields. Deliver the
   pending MDN in a separate exchange with **AS2 Deliver Async MDN**, using
   the original Message-ID. A failed callback stays pending for retry. A
   repeated delivery of an already sent receipt returns its recorded result.
4. For early HTTP acknowledgement, durably enqueue the claimed EDI work
   before returning the transport acknowledgement exposed by **AS2 Receive**.
   Configure the processing lease to cover the consumer’s backlog and
   expected execution time. Use the consumer to create and deliver the signed MDN.
5. The original sender reports `awaiting_mdn` until a valid signed callback
   correlates to the outbound Message-ID and MIC. It then reports
   `processed` or `rejected`. An identical disposition is idempotent.
  A mismatched MIC or conflicting disposition fails verification. The sender
  records a signed rejection without a MIC as rejected, with
  `receiptMicVerified=false`.

## Generate and read functional acknowledgements

Use **Create EDI Acknowledgement** with the original interchange text or with
the parsed segment structure. Choose **997**, **999**, or **CONTRL** and
map a new interchange control number. For X12, also map the first new group
control number. MINA reverses the original sender and receiver, assigns the
new control values, and writes the acknowledgement counts. For CONTRL,
optionally map the new message reference.

Transactions default to accepted. To reject selected transactions, map
`ackDecisions` using the original transaction and functional group controls.
For an ungrouped CONTRL source, omit `groupControlNumber`. Rejected CONTRL
messages require the applicable syntax error code.

```json
[{"groupControlNumber":"1","controlNumber":"0001","accepted":false}]
```

**Read EDI Acknowledgement** returns the original X12 group and transaction
references with result codes and counts. For CONTRL it exposes the original
interchange, groups, and messages. Compare these references to your stored
outbound interchange data. The activities produce functional summaries.
Use partner-specific validation for detailed segment or element diagnostics.

## Share reconciliation between runtime instances

On each authorized peer runtime, set `MINA_AS2_LEDGER_POSTGRES_DSN` through
runtime secret injection and select **PostgreSQL** in the Trading Partner
profile. Use a dedicated database and a role that can create and own
the `mina_as2` schema. For different projects to share a profile, configure
the same **Shared reconciliation key**, local AS2 ID, and partner AS2 ID.
The profile ID is used when the key is empty. Incoming claims, callback
delivery leases, and outbound reconciliation use the database clock and
transaction locking across replicas. Existing SQLite records stay in the
original ledger when a profile changes its backend.

## Supported exchange profile

This release supports synchronous and HTTPS asynchronous signed MDNs,
SHA-256 detached CMS, CMS zlib compression, RSA/AES envelopes, and structural
EDI rules. Complete industry-specific EDI implementation guides require
separate support. Test real partner
certificates, TLS, syntax rules, and MDN interoperability before cutover.

Standards references are [AS2](https://www.rfc-editor.org/rfc/rfc4130.html),
[X12](https://ecommerce.x12.org/), and
[UN/EDIFACT syntax rules](https://unece.org/fileadmin/DAM/trade/edifact/untdid/d422_s.htm).
