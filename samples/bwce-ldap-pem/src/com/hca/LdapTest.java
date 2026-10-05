package com.hca;

import java.io.IOException;
import java.net.URI;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Paths;
import java.security.GeneralSecurityException;
import java.util.Hashtable;
import java.util.UUID;
import javax.naming.Context;
import javax.naming.NamingEnumeration;
import javax.naming.NamingException;
import javax.naming.directory.DirContext;
import javax.naming.directory.InitialDirContext;
import javax.naming.directory.SearchControls;
import javax.naming.directory.SearchResult;

public final class LdapTest {
    /** Supply actual PEM text (including BEGIN/END CERTIFICATE), not a filename. */
    public static boolean userExists(String ldapsUrl, String bindPrincipal,
            String bindPassword, String baseDn, String filterTemplate, String username,
            String caCertificatePem, int connectTimeoutMs, int readTimeoutMs,
            int searchTimeoutMs) throws NamingException, GeneralSecurityException, IOException {
        requireText(ldapsUrl, "ldapsUrl");
        URI uri = URI.create(ldapsUrl);
        if (!"ldaps".equalsIgnoreCase(uri.getScheme()) || uri.getHost() == null
                || uri.getUserInfo() != null || uri.getQuery() != null || uri.getFragment() != null
                || (uri.getRawPath() != null && !uri.getRawPath().isEmpty()
                    && !"/".equals(uri.getRawPath()))
                || uri.getPort() == 0 || uri.getPort() > 65535) {
            throw new IllegalArgumentException("Use ldaps://hostname:port without a DN, credentials or query");
        }
        requireText(bindPrincipal, "bindPrincipal");
        if (bindPassword == null || bindPassword.isEmpty()) {
            throw new IllegalArgumentException("bindPassword must not be empty");
        }
        requireText(baseDn, "baseDn");
        requireText(filterTemplate, "filterTemplate");
        requireText(username, "username");
        if (!filterTemplate.contains("{0}")) {
            throw new IllegalArgumentException("filterTemplate must contain {0}");
        }
        if (connectTimeoutMs <= 0 || readTimeoutMs <= 0 || searchTimeoutMs <= 0) {
            throw new IllegalArgumentException("All timeouts must be positive milliseconds");
        }

        String id = UUID.randomUUID().toString();
        log(id, "LOAD_PEM START");
        PemLdapSocketFactory factory = PemLdapSocketFactory.fromPem(caCertificatePem);
        log(id, "LOAD_PEM SUCCESS");
        Hashtable<String, Object> env = new Hashtable<String, Object>();
        env.put(Context.INITIAL_CONTEXT_FACTORY, "com.sun.jndi.ldap.LdapCtxFactory");
        env.put(Context.PROVIDER_URL, ldapsUrl);
        env.put(Context.SECURITY_AUTHENTICATION, "simple");
        env.put(Context.SECURITY_PRINCIPAL, bindPrincipal);
        env.put(Context.SECURITY_CREDENTIALS, bindPassword);
        env.put(Context.REFERRAL, "throw");
        env.put("java.naming.ldap.factory.socket", PemLdapSocketFactory.class.getName());
        env.put("com.sun.jndi.ldap.connect.pool", "false");
        env.put("com.sun.jndi.ldap.connect.timeout", Integer.toString(connectTimeoutMs));
        env.put("com.sun.jndi.ldap.read.timeout", Integer.toString(readTimeoutMs));
        env.put("java.naming.ldap.derefAliases", "never");
        SearchControls controls = new SearchControls();
        controls.setSearchScope(SearchControls.SUBTREE_SCOPE);
        controls.setTimeLimit(searchTimeoutMs);
        controls.setCountLimit(1);
        controls.setReturningAttributes(new String[0]);
        controls.setReturningObjFlag(false);

        DirContext context = null;
        NamingEnumeration<SearchResult> results = null;
        Thread thread = Thread.currentThread();
        ClassLoader previousLoader = thread.getContextClassLoader();
        PemLdapSocketFactory previousFactory = PemLdapSocketFactory.install(factory);
        String stage = "CONNECT_TLS_BIND";
        long started = System.nanoTime();
        try {
            // Make the custom factory visible from the BWCE application module.
            thread.setContextClassLoader(LdapTest.class.getClassLoader());
            log(id, stage + " START");
            context = new InitialDirContext(env);
            log(id, "BIND SUCCESS");
            stage = "SEARCH";
            log(id, stage + " START");
            results = context.search(baseDn, filterTemplate, new Object[] {username}, controls);
            stage = "READ_SEARCH_RESULTS";
            log(id, stage + " START");
            boolean exists = results.hasMore();
            log(id, "SEARCH COMPLETE exists=" + exists);
            return exists;
        } catch (NamingException e) {
            log(id, "FAILED stage=" + stage + " totalElapsedMs="
                    + (System.nanoTime() - started) / 1_000_000
                    + " exception=" + e.getClass().getSimpleName());
            throw e;
        } finally {
            try {
                if (results != null) {
                    try { results.close(); } catch (NamingException ignored) { }
                }
                if (context != null) {
                    try { context.close(); } catch (NamingException ignored) { }
                }
            } finally {
                env.clear();
                PemLdapSocketFactory.restore(previousFactory);
                thread.setContextClassLoader(previousLoader);
            }
        }
    }

    /** Alternative Java Invoke entry point: read a mounted PEM file. */
    public static boolean userExistsFromPemFile(String ldapsUrl, String bindPrincipal,
            String bindPassword, String baseDn, String filterTemplate, String username,
            String caCertificatePemPath, int connectTimeoutMs, int readTimeoutMs,
            int searchTimeoutMs) throws NamingException, GeneralSecurityException, IOException {
        requireText(caCertificatePemPath, "caCertificatePemPath");
        String pem = new String(Files.readAllBytes(Paths.get(caCertificatePemPath)),
                StandardCharsets.US_ASCII);
        return userExists(ldapsUrl, bindPrincipal, bindPassword, baseDn, filterTemplate,
                username, pem, connectTimeoutMs, readTimeoutMs, searchTimeoutMs);
    }

    private static void requireText(String value, String name) {
        if (value == null || value.trim().isEmpty()) {
            throw new IllegalArgumentException(name + " must not be blank");
        }
    }
    private static void log(String id, String message) {
        System.out.println("LDAP [" + id + "] " + message);
    }
}
