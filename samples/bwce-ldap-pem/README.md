# BWCE LDAP lookup with PEM CA certificates

## Install

Copy BOTH source files under `src/com/hca` into the Java source folder of the same BWCE module. Replace the old `com.hca.LdapTest` class; do not retain duplicate copies in another JAR. Alternatively import `build/bwce-ldap-pem.jar` using your module's Java library configuration. Java 8-compatible source, no third-party dependencies. Tested on the local JDK 17; verify against your supported BWCE/JVM version.

In Java Invoke, select `com.hca.LdapTest` and one of these static methods:

- `userExists`: accepts the PEM certificate CONTENT as `caCertificatePem`.
- `userExistsFromPemFile`: accepts a mounted PEM FILE PATH as `caCertificatePemPath`.

Both methods have the same argument order:

```text
ldapsUrl, bindPrincipal, bindPassword, baseDn, filterTemplate, username,
caCertificatePem (or caCertificatePemPath),
connectTimeoutMs, readTimeoutMs, searchTimeoutMs
```

Example Java call using a mounted root certificate:

```java
boolean exists = com.hca.LdapTest.userExistsFromPemFile(
    "ldaps://ldap.example.com:636",
    serviceAccountDn,
    serviceAccountPassword,
    "DC=example,DC=com",
    "(&(objectClass=user)(userPrincipalName={0}))",
    "jdoe@example.com",
    "/etc/bwce/certs/root-ca.pem",
    5000, 5000, 5000
);
```

For direct content, call `userExists` with the actual multi-line PEM text instead of the path:

```text
-----BEGIN CERTIFICATE-----
...base64-encoded CA certificate...
-----END CERTIFICATE-----
```

Use real line breaks, not literal backslash-n characters. Supply your trusted CA certificate(s) as controlled deployment configuration. A root CA certificate alone is sufficient when the server sends its leaf certificate and required intermediates. Multiple PEM CA certificates are supported, but each supplied CA becomes a trust anchor. Server leaf certificates, private keys and expired CA certificates are rejected. DER-only input is not supported; export the certificate in PEM format first.

## Trust behavior

No JKS FILE or truststore password is required. A Java KeyStore object is created only in memory to initialize a per-call SSLContext. The lookup uses only the provided CA certificates as trust anchors; it does not merge JVM default trust anchors. It does not change global JVM TLS defaults or system properties, so unrelated BWCE TLS clients keep their existing configuration.

The service-account bind password is still required. The searched user's password is never required. Client private keys/mutual TLS are not implemented.

This helper does not require `javax.net.ssl.trustStore`, `javax.net.ssl.trustStoreType` or `javax.net.ssl.trustStorePassword` startup arguments. Remove them only if other components do not need them. Hostname/SAN verification is explicitly enabled on these sockets, including when a previous JNDI endpoint-identification bypass property exists. The LDAPS URL hostname must match the certificate SAN. This change does not repair a hostname mismatch.

## Behavior changes from the pasted code

- Retains stage logs and parameterized username escaping; logs omit passwords and user identifiers.
- Restores cleanup for result enumerations, LDAP contexts, per-thread TLS state and context classloader.
- Requires positive timeout values. Replace the old `0, 0, 0` with, for example, `5000, 5000, 5000`.
- Uses `Context.REFERRAL = "throw"` instead of `"follow"`. Referrals produce an error, not automatic connections to another server with service credentials. For a cross-domain search, select an approved endpoint/base with your directory administrator.
- Disables connection pooling to avoid reuse across different PEM trust configurations.

Keep your WORKING filter, username format and base DN when migrating; the example UPN filter above is illustrative. `true` means at least one visible matching entry; `false` means a completed search found none within that base/filter. It does not test enabled status or authorization. Exceptions remain errors, not false results.

The custom factory is resolved reflectively by JNDI. Both classes must be packaged in the same application/shared module and be visible to its classloader. The synchronous method installs the TLS factory for its invoking thread until the context and results are closed, then removes/restores it. Do not move individual LDAP operations into asynchronous workers or use the factory independently.

## Build and local tests

From this directory:

```text
javac --release 8 -d build/classes src/com/hca/LdapTest.java src/com/hca/PemLdapSocketFactory.java
jar cf build/bwce-ldap-pem.jar -C build/classes .
```

`test/com/hca/PemLookupTest.java` uses a local TLS server with a minimal LDAP protocol fixture. Its test PKCS12 files are generated only for that server, not required by the production helper and not included in the deployment JAR. It checks successful/empty searches, bind failure, read timeout, untrusted CA, hostname mismatch, invalid PEM, concurrent trust isolation and thread-state cleanup. These checks do not replace a real BWCE deployment test against your LDAP directory.

References:
- [Oracle JNDI custom socket factory](https://docs.oracle.com/javase/jndi/tutorial/ldap/security/ssl.html)
- [Oracle X.509 certificate parsing](https://docs.oracle.com/en/java/javase/17/docs/api/java.base/java/security/cert/CertificateFactory.html)
