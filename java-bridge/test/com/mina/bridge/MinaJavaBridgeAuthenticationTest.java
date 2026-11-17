package com.mina.bridge;

import java.lang.reflect.Method;
import java.util.Properties;

/** Tests the actual JMS bridge entry point without requiring provider JARs. */
public final class MinaJavaBridgeAuthenticationTest {
    public static final class Factory {
        static String selected, username, password;
        public Factory(String url) { }
        public Connection createConnection() {
            selected = "default"; username = password = null;
            return new Connection();
        }
        public Connection createConnection(String user, String secret) {
            selected = "explicit"; username = user; password = secret;
            return new Connection();
        }
    }
    public static final class Connection {
        public void start() { }
        public void close() { }
    }
    private static void check(String user, String secret, boolean defaults) throws Exception {
        Properties properties = new Properties();
        properties.setProperty("serverUrl", "tcp://test-only.invalid:1");
        properties.setProperty("connectionFactoryClass", Factory.class.getName());
        if (user != null) properties.setProperty("username", user);
        if (secret != null) properties.setProperty("password", secret);
        Method jms = MinaJavaBridge.class.getDeclaredMethod("jms", String.class, Properties.class);
        jms.setAccessible(true);
        jms.invoke(null, "test", properties);
        if (!(defaults ? "default" : "explicit").equals(Factory.selected))
            throw new AssertionError("Wrong connection method selected");
        if (!defaults && (!(user == null ? "" : user).equals(Factory.username)
                || !(secret == null ? "" : secret).equals(Factory.password)))
            throw new AssertionError("Explicit credentials changed");
    }
    public static void main(String[] args) throws Exception {
        check(null, null, true);
        check("", "", true);
        check("alice", "", false);
        check("alice", "test-only-secret", false);
        check("", "test-only-secret", false);
        check(" ", "", false);
    }
}
