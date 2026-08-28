package io.integrationfabric.sdk;
import java.util.Map;
public interface FabricActivity { Map<String, Object> execute(Map<String, Object> payload) throws Exception; }
