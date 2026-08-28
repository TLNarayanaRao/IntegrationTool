package io.integrationfabric.sdk;
import java.util.HashMap; import java.util.Map;
public final class EchoActivity implements FabricActivity { public Map<String,Object> execute(Map<String,Object> payload) { var result = new HashMap<>(payload); result.put("processedBy", "Java EchoActivity"); return result; } }
