package com.integrationfabric.bridge;

import java.lang.reflect.Method;

/** Regression test for providers that return package-private JMS implementations. */
public final class FabricJavaBridgeReflectionTest {
    public interface PublicSessionContract {
        String createConsumer(String destination);
    }

    private static final class ProviderSessionImplementation implements PublicSessionContract {
        @Override public String createConsumer(String destination) { return "consumer:" + destination; }
    }

    public static void main(String[] args) throws Exception {
        Method invoke = FabricJavaBridge.class.getDeclaredMethod("invoke", Object.class, String.class, Object[].class);
        invoke.setAccessible(true);
        Object result = invoke.invoke(null, new Object[]{new ProviderSessionImplementation(), "createConsumer", new Object[]{"orders"}});
        if (!"consumer:orders".equals(result)) throw new AssertionError("Public interface invocation failed: " + result);
    }
}
