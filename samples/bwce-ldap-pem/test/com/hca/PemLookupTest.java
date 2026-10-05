package com.hca;

import java.io.*;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.security.KeyStore;
import java.util.Arrays;
import java.util.concurrent.*;
import javax.naming.NamingException;
import javax.net.ssl.*;

/** Local TLS + minimal LDAP protocol fixture; no corporate directory required. */
public final class PemLookupTest {
    private static SSLContext serverTls;
    private static String trustedPem;
    private static String otherPem;

    public static void main(String[] args) throws Exception {
        Path fixtures = Paths.get(args[0]);
        KeyStore keys = KeyStore.getInstance("PKCS12");
        try (InputStream input = Files.newInputStream(fixtures.resolve("server.p12"))) {
            keys.load(input, "test-only-password".toCharArray());
        }
        KeyManagerFactory km = KeyManagerFactory.getInstance(KeyManagerFactory.getDefaultAlgorithm());
        km.init(keys, "test-only-password".toCharArray());
        serverTls = SSLContext.getInstance("TLS");
        serverTls.init(km.getKeyManagers(), null, null);
        trustedPem = new String(Files.readAllBytes(fixtures.resolve("root.pem")), StandardCharsets.US_ASCII);
        otherPem = new String(Files.readAllBytes(fixtures.resolve("other.pem")), StandardCharsets.US_ASCII);
        check(run("found", trustedPem, "localhost"), "known user");
        check(!run("absent", trustedPem, "localhost"), "absent user");
        expectFailure("bad-bind", trustedPem, "localhost");
        expectFailure("read-timeout", trustedPem, "localhost");
        expectFailure("tls-failure", otherPem, "localhost");
        expectFailure("tls-failure", trustedPem, "127.0.0.1");
        try {
            PemLdapSocketFactory.fromPem("not a certificate");
            throw new AssertionError("Invalid PEM accepted");
        } catch (IllegalArgumentException expected) { }
        ExecutorService callers = Executors.newFixedThreadPool(2);
        try {
            Future<Boolean> trusted = callers.submit(() -> run("found", trustedPem, "localhost"));
            Future<Boolean> untrusted = callers.submit(() -> {
                expectFailure("tls-failure", otherPem, "localhost"); return true;
            });
            check(trusted.get(10, TimeUnit.SECONDS), "concurrent trusted call");
            check(untrusted.get(10, TimeUnit.SECONDS), "concurrent untrusted call");
        } finally { callers.shutdownNow(); }
        System.out.println("PASS: found, absent, bad bind, read timeout, untrusted CA, hostname mismatch, invalid PEM, concurrent trust isolation");
    }

    private static void expectFailure(String mode, String pem, String host) throws Exception {
        try {
            run(mode, pem, host);
            throw new AssertionError("Expected failure: " + mode + " " + host);
        } catch (NamingException expected) {
            if ("tls-failure".equals(mode)) {
                Throwable cause = expected;
                while (cause != null && !(cause instanceof SSLHandshakeException)) cause = cause.getCause();
                check(cause != null, "TLS failure must be a handshake rejection");
            }
        }
    }

    private static boolean run(String mode, String pem, String host) throws Exception {
        SSLServerSocket server = (SSLServerSocket) serverTls.getServerSocketFactory().createServerSocket(0);
        server.setSoTimeout(5000);
        ExecutorService worker = Executors.newSingleThreadExecutor();
        Future<?> serving = worker.submit(() -> {
            try (SSLSocket socket = (SSLSocket) server.accept()) {
                socket.setSoTimeout(3000);
                socket.startHandshake();
                InputStream in = socket.getInputStream();
                OutputStream out = socket.getOutputStream();
                byte[] bind = readMessage(in);
                check(bind[3] == 0x60, "bind request");
                out.write(message(bind[2], 0x61, result("bad-bind".equals(mode) ? 49 : 0)));
                out.flush();
                if ("bad-bind".equals(mode)) return;
                byte[] search = readMessage(in);
                check(search[3] == 0x63, "search request");
                check(new String(search, StandardCharsets.ISO_8859_1).contains("jdoe"), "username in filter");
                if ("read-timeout".equals(mode)) {
                    Thread.sleep(1000);
                    return;
                }
                if ("found".equals(mode)) {
                    out.write(message(search[2], 0x64, concat(
                            tlv(4, "cn=jdoe,dc=test".getBytes(StandardCharsets.US_ASCII)), tlv(0x30, new byte[0]))));
                }
                out.write(message(search[2], 0x65, result(0)));
                out.flush();
            } catch (IOException expected) {
                if (!"tls-failure".equals(mode)) throw new RuntimeException(expected);
            } catch (Exception e) { throw new RuntimeException(e); }
        });
        ClassLoader loader = Thread.currentThread().getContextClassLoader();
        try {
            return LdapTest.userExists("ldaps://" + host + ":" + server.getLocalPort(),
                    "cn=service,dc=test", "test-password", "dc=test", "(uid={0})", "jdoe",
                    pem, 2000, 300, 2000);
        } finally {
            try {
                serving.get(6, TimeUnit.SECONDS);
                check(Thread.currentThread().getContextClassLoader() == loader, "classloader restored");
                try {
                    PemLdapSocketFactory.getDefault();
                    throw new AssertionError("Thread-local factory not cleared");
                } catch (IllegalStateException expected) { }
            } finally { server.close(); worker.shutdownNow(); }
        }
    }

    private static byte[] readMessage(InputStream in) throws IOException {
        if (in.read() != 0x30) throw new IOException("Expected LDAP sequence");
        int size = in.read();
        if ((size & 0x80) != 0) {
            int bytes = size & 0x7f;
            size = 0;
            for (int i = 0; i < bytes; i++) size = (size << 8) | in.read();
        }
        byte[] body = new byte[size];
        new DataInputStream(in).readFully(body);
        return body;
    }
    private static byte[] result(int code) { return new byte[] {10, 1, (byte) code, 4, 0, 4, 0}; }
    private static byte[] message(byte id, int tag, byte[] body) {
        return tlv(0x30, concat(new byte[] {2, 1, id}, tlv(tag, body)));
    }
    private static byte[] tlv(int tag, byte[] body) {
        if (body.length >= 128) throw new AssertionError("Fixture supports short responses only");
        return concat(new byte[] {(byte) tag, (byte) body.length}, body);
    }
    private static byte[] concat(byte[] a, byte[] b) {
        byte[] result = Arrays.copyOf(a, a.length + b.length);
        System.arraycopy(b, 0, result, a.length, b.length);
        return result;
    }
    private static void check(boolean ok, String message) {
        if (!ok) throw new AssertionError(message);
    }
}
