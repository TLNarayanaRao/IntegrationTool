package com.hca;

import java.io.ByteArrayInputStream;
import java.io.IOException;
import java.net.InetAddress;
import java.net.Socket;
import java.nio.charset.StandardCharsets;
import java.security.GeneralSecurityException;
import java.security.KeyStore;
import java.security.cert.Certificate;
import java.security.cert.CertificateFactory;
import java.security.cert.X509Certificate;
import java.util.Collection;
import javax.net.SocketFactory;
import javax.net.ssl.SSLContext;
import javax.net.ssl.SSLParameters;
import javax.net.ssl.SSLSocket;
import javax.net.ssl.SSLSocketFactory;
import javax.net.ssl.TrustManagerFactory;

/** JNDI adapter. Each synchronous lookup installs its own factory on its thread. */
public final class PemLdapSocketFactory extends SSLSocketFactory {
    private static final ThreadLocal<PemLdapSocketFactory> CURRENT =
            new ThreadLocal<PemLdapSocketFactory>();
    private final SSLSocketFactory delegate;

    private PemLdapSocketFactory(SSLSocketFactory delegate) {
        this.delegate = delegate;
    }

    static PemLdapSocketFactory fromPem(String pem)
            throws GeneralSecurityException, IOException {
        if (pem == null || !pem.contains("-----BEGIN CERTIFICATE-----")
                || pem.contains("PRIVATE KEY")) {
            throw new IllegalArgumentException("Supply PEM CA certificate text, not a private key or path");
        }
        Collection<? extends Certificate> certificates = CertificateFactory.getInstance("X.509")
                .generateCertificates(new ByteArrayInputStream(pem.getBytes(StandardCharsets.US_ASCII)));
        if (certificates.isEmpty()) {
            throw new IllegalArgumentException("PEM contains no certificates");
        }
        // Memory only: no keystore file and no keystore password.
        KeyStore trust = KeyStore.getInstance("JKS");
        trust.load(null, null);
        int index = 0;
        for (Certificate certificate : certificates) {
            X509Certificate ca = (X509Certificate) certificate;
            ca.checkValidity();
            if (ca.getBasicConstraints() < 0) {
                throw new IllegalArgumentException("PEM must contain CA certificates, not server leaf certificates");
            }
            trust.setCertificateEntry("ca-" + index++, ca);
        }
        TrustManagerFactory managers = TrustManagerFactory.getInstance(
                TrustManagerFactory.getDefaultAlgorithm());
        managers.init(trust);
        SSLContext tls = SSLContext.getInstance("TLS");
        tls.init(null, managers.getTrustManagers(), null);
        return new PemLdapSocketFactory(tls.getSocketFactory());
    }

    static PemLdapSocketFactory install(PemLdapSocketFactory factory) {
        PemLdapSocketFactory previous = CURRENT.get();
        CURRENT.set(factory);
        return previous;
    }

    static void restore(PemLdapSocketFactory previous) {
        if (previous == null) CURRENT.remove();
        else CURRENT.set(previous);
    }

    /** Called reflectively by the JDK LDAP provider. */
    public static SocketFactory getDefault() {
        PemLdapSocketFactory factory = CURRENT.get();
        if (factory == null) {
            throw new IllegalStateException("Use this factory through LdapTest.userExists");
        }
        return factory;
    }

    private Socket configure(Socket socket) {
        SSLSocket ssl = (SSLSocket) socket;
        SSLParameters parameters = ssl.getSSLParameters();
        parameters.setEndpointIdentificationAlgorithm("LDAPS");
        ssl.setSSLParameters(parameters);
        return ssl;
    }

    @Override public String[] getDefaultCipherSuites() { return delegate.getDefaultCipherSuites(); }
    @Override public String[] getSupportedCipherSuites() { return delegate.getSupportedCipherSuites(); }
    // Unconnected sockets preserve JNDI's configured connect timeout.
    @Override public Socket createSocket() throws IOException {
        return configure(delegate.createSocket());
    }
    @Override public Socket createSocket(String host, int port) throws IOException {
        return configure(delegate.createSocket(host, port));
    }
    @Override public Socket createSocket(String host, int port, InetAddress local, int localPort)
            throws IOException {
        return configure(delegate.createSocket(host, port, local, localPort));
    }
    @Override public Socket createSocket(InetAddress host, int port) throws IOException {
        return configure(delegate.createSocket(host, port));
    }
    @Override public Socket createSocket(InetAddress host, int port, InetAddress local, int localPort)
            throws IOException {
        return configure(delegate.createSocket(host, port, local, localPort));
    }
    @Override public Socket createSocket(Socket socket, String host, int port, boolean autoClose)
            throws IOException {
        return configure(delegate.createSocket(socket, host, port, autoClose));
    }
}
