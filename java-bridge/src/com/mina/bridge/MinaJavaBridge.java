package com.mina.bridge;

import java.io.*;
import java.lang.reflect.*;
import java.nio.charset.StandardCharsets;
import java.nio.channels.FileChannel;
import java.nio.channels.FileLock;
import java.nio.channels.OverlappingFileLockException;
import java.nio.file.*;
import java.nio.file.attribute.BasicFileAttributes;
import java.sql.*;
import java.time.temporal.TemporalAccessor;
import java.util.*;
import java.util.concurrent.BlockingQueue;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.LinkedBlockingQueue;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicLong;
import javax.naming.Context;
import javax.naming.InitialContext;

/** Vendor-neutral process bridge for licensed SAP JCo, JMS providers, and JDBC drivers. */
public final class MinaJavaBridge {
    private MinaJavaBridge() {}
    private static FileChannel listenerLockChannel;
    private static FileLock listenerLock;

    public static void main(String[] args) {
        Map<String, Object> output = new LinkedHashMap<>();
        try {
            // SAP text can contain characters outside the Windows console
            // code page. The Python side consumes one UTF-8 JSON line.
            System.setOut(new PrintStream(new FileOutputStream(FileDescriptor.out), true, StandardCharsets.UTF_8));
            if (args.length != 1) throw new IllegalArgumentException("A bridge properties file is required");
            Properties p = new Properties();
            try (Reader reader = new InputStreamReader(new FileInputStream(args[0]), StandardCharsets.UTF_8)) { p.load(reader); }
            String command = required(p, "command");
            if (command.startsWith("sap.")) output = sap(command.substring(4), p);
            else if (command.startsWith("jms.")) output = jms(command.substring(4), p);
            else if (command.startsWith("jdbc.")) output = jdbc(command.substring(5), p);
            else throw new IllegalArgumentException("Unsupported bridge command: " + command);
            output.putIfAbsent("ok", true);
        } catch (Throwable error) {
            Throwable cause = error;
            while (cause instanceof InvocationTargetException && ((InvocationTargetException) cause).getCause() != null) cause = ((InvocationTargetException) cause).getCause();
            output.clear(); output.put("ok", false); output.put("errorType", cause.getClass().getName()); output.put("message", String.valueOf(cause.getMessage() == null ? cause : cause.getMessage()));
        }
        System.out.println(json(output));
    }

    /** SAP JCo is loaded reflectively because sapjco3.jar is a user-supplied, licensed driver. */
    private static Map<String, Object> sap(String operation, Properties p) throws Exception {
        Class<?> environment = Class.forName("com.sap.conn.jco.ext.Environment");
        Class<?> providerType = Class.forName("com.sap.conn.jco.ext.DestinationDataProvider");
        String destinationName = p.getProperty("destinationName", "mina-sap");
        Properties destination = new Properties();
        for (String key : p.stringPropertyNames()) if (key.startsWith("jco.client.") || key.startsWith("jco.destination.")) destination.setProperty(key, p.getProperty(key));
        Object provider = Proxy.newProxyInstance(providerType.getClassLoader(), new Class<?>[]{providerType}, (proxy, method, args) -> {
            if (method.getName().equals("getDestinationProperties")) return destination;
            if (method.getName().equals("supportsEvents")) return false;
            if (method.getName().equals("setDestinationData")) return null;
            throw new UnsupportedOperationException(method.getName());
        });
        Method isRegistered = environment.getMethod("isDestinationDataProviderRegistered");
        Method register = environment.getMethod("registerDestinationDataProvider", providerType);
        if (!(Boolean) isRegistered.invoke(null)) register.invoke(null, provider);

        // An inbound IDoc listener is an RFC server. It uses only
        // jco.server.* properties and must not initialize a client
        // destination, otherwise JCo rejects the empty client Properties.
        if (operation.equals("listen")) return listen(destinationName, p);

        Class<?> manager = Class.forName("com.sap.conn.jco.JCoDestinationManager");
        Object destinationObject = manager.getMethod("getDestination", String.class).invoke(null, destinationName);
        try {
            if (operation.equals("test")) {
                destinationObject.getClass().getMethod("ping").invoke(destinationObject);
                Object function = function(destinationObject, "STFC_CONNECTION");
                setValue(function, "REQUTEXT", p.getProperty("requestText", "MINA connection test"));
                invoke(function, "execute", destinationObject);
                Class<?> jcoType = Class.forName("com.sap.conn.jco.JCo");
                String jcoVersion = optionalStaticString(jcoType, "getVersion");
                if (jcoVersion.isBlank() && jcoType.getPackage() != null) jcoVersion = String.valueOf(jcoType.getPackage().getImplementationVersion());
                boolean jidocAvailable = false; String jidocVersion = "";
                try {
                    Class<?> jidocType = Class.forName("com.sap.conn.idoc.IDocFactory");
                    jidocAvailable = true;
                    if (jidocType.getPackage() != null) jidocVersion = String.valueOf(jidocType.getPackage().getImplementationVersion());
                } catch (ClassNotFoundException ignored) { }
                return map("message", "SAP JCo connection succeeded", "destination", destinationName, "jcoVersion", jcoVersion,
                        "jidocLibAvailable", jidocAvailable, "jidocLibVersion", jidocVersion,
                        "javaVersion", System.getProperty("java.version"), "architecture", System.getProperty("os.arch"));
            }
            if (operation.equals("call")) return executeSapFunction(destinationObject, p, false);
            if (operation.equals("idoc_validate")) return validateIdocXml(destinationObject, required(p, "idocXml"));
            if (operation.equals("worker")) return sapWorker(destinationObject);
            throw new IllegalArgumentException("Unsupported SAP JCo operation: " + operation);
        } finally { close(destinationObject); }
    }

    private static Object function(Object destination, String name) throws Exception {
        Object repository = invoke(destination, "getRepository");
        Object function = invoke(repository, "getFunction", name);
        if (function == null) throw new IllegalArgumentException("SAP function was not found: " + name);
        return function;
    }

    private static void setValue(Object function, String name, Object value) throws Exception {
        Object imports = invoke(function, "getImportParameterList");
        if (imports == null) throw new IllegalArgumentException("SAP function has no import parameter list");
        invoke(imports, "setValue", name, value);
    }

    /** Validate IDoc XML against the repository exposed by the optional,
     * separately licensed SAP Java IDoc Class Library (sapidoc3.jar). */
    private static Map<String, Object> validateIdocXml(Object destination, String xml) throws Exception {
        Class<?> jcoIdoc = Class.forName("com.sap.conn.idoc.jco.JCoIDoc");
        Method repositoryMethod = Arrays.stream(jcoIdoc.getMethods()).filter(method -> method.getName().equals("getIDocRepository") && method.getParameterCount() == 1 && method.getParameterTypes()[0].isInstance(destination)).findFirst().orElseThrow();
        Object repository = repositoryMethod.invoke(null, destination);
        Object factory = jcoIdoc.getMethod("getIDocFactory").invoke(null);
        Object processor = invoke(factory, "getIDocXMLProcessor");
        Object documents = invoke(processor, "parse", repository, xml);
        String version = optionalString(factory, "getVersion");
        return map("validated", true, "jidocLibVersion", version, "documentClass", documents.getClass().getName());
    }

    private static void jcoContext(Object destination, String action) throws Exception {
        Class<?> contextType = Class.forName("com.sap.conn.jco.JCoContext");
        Method method = Arrays.stream(contextType.getMethods())
                .filter(candidate -> candidate.getName().equals(action) && candidate.getParameterCount() == 1 && candidate.getParameterTypes()[0].isInstance(destination))
                .findFirst().orElseThrow(() -> new NoSuchMethodException("JCoContext." + action + "(JCoDestination)"));
        method.invoke(null, destination);
    }

    private static Map<String, Object> executeSapFunction(Object destination, Properties p, boolean existingContext) throws Exception {
        String functionName = required(p, "functionName");
        Object function = function(destination, functionName);
        for (String key : p.stringPropertyNames()) {
            if (key.startsWith("argument.")) setParameterPath(invoke(function, "getImportParameterList"), key.substring(9), p.getProperty(key));
            else if (key.startsWith("changing.")) setParameterPath(invoke(function, "getChangingParameterList"), key.substring(9), p.getProperty(key));
        }
        fillTables(function, p);
        if (functionName.equals("RFC_READ_TABLE")) fillReadTable(function, p);
        String protocol = p.getProperty("transactionProtocol", "sRFC").trim().toLowerCase(Locale.ROOT);
        boolean asynchronous = Set.of("trfc", "t-rfc", "qrfc", "q-rfc").contains(protocol);
        boolean localContext = !existingContext && bool(p, "transactional", false) && !asynchronous;
        String tid = null;
        if (localContext) jcoContext(destination, "begin");
        try {
            if (asynchronous) {
                tid = String.valueOf(invoke(destination, "createTID"));
                String queueName = p.getProperty("queueName", "").trim();
                if ((protocol.equals("qrfc") || protocol.equals("q-rfc")) && !queueName.isEmpty()) invoke(function, "execute", destination, tid, queueName);
                else invoke(function, "execute", destination, tid);
                invoke(destination, "confirmTID", tid);
            } else {
                invoke(function, "execute", destination);
                if (bool(p, "autoCommit", false)) {
                    Object commit = function(destination, "BAPI_TRANSACTION_COMMIT");
                    setValue(commit, "WAIT", "X");
                    invoke(commit, "execute", destination);
                }
            }
            Map<String, Object> result = functionResult(function);
            if (tid != null) { result.put("TID", tid); result.put("transactional", true); result.put("transactionProtocol", protocol); result.put("confirmed", true); }
            if (bool(p, "autoCommit", false) && !asynchronous) result.put("committed", true);
            return result;
        } catch (Exception error) {
            if (localContext) try { invoke(function(destination, "BAPI_TRANSACTION_ROLLBACK"), "execute", destination); } catch (Throwable rollback) { error.addSuppressed(rollback); }
            throw error;
        } finally {
            if (localContext) try { jcoContext(destination, "end"); } catch (Throwable error) { System.err.println("SAP JCo context cleanup failed: " + error); }
        }
    }

    /** Persistent client process. JCo's destination pool and optional stateful
     * context remain alive across calls instead of being recreated per RFC. */
    private static Map<String, Object> sapWorker(Object destination) throws Exception {
        System.out.println(json(map("event", "ready", "ok", true, "pid", ProcessHandle.current().pid()))); System.out.flush();
        boolean contextOpen = false;
        try (BufferedReader commands = new BufferedReader(new InputStreamReader(System.in, StandardCharsets.UTF_8))) {
            String line;
            while ((line = commands.readLine()) != null) {
                String[] parts = line.split("\\t", 3);
                String action = parts.length > 0 ? parts[0] : "", requestId = parts.length > 1 ? parts[1] : "";
                Map<String, Object> result = new LinkedHashMap<>();
                try {
                    if (action.equals("begin")) { if (!contextOpen) { jcoContext(destination, "begin"); contextOpen = true; } result.put("contextOpen", true); }
                    else if (action.equals("end")) { if (contextOpen) { jcoContext(destination, "end"); contextOpen = false; } result.put("contextOpen", false); }
                    else if (action.equals("commit")) {
                        if (!contextOpen) throw new IllegalStateException("No SAP JCo context is open");
                        Object commit = function(destination, "BAPI_TRANSACTION_COMMIT");
                        setValue(commit, "WAIT", "X");
                        invoke(commit, "execute", destination);
                        jcoContext(destination, "end"); contextOpen = false;
                        result.put("committed", true); result.put("contextOpen", false);
                    }
                    else if (action.equals("rollback")) {
                        if (contextOpen) {
                            invoke(function(destination, "BAPI_TRANSACTION_ROLLBACK"), "execute", destination);
                            jcoContext(destination, "end"); contextOpen = false;
                        }
                        result.put("rolledBack", true); result.put("contextOpen", false);
                    }
                    else if (action.equals("call") && parts.length == 3) {
                        Properties call = new Properties();
                        String decoded = new String(Base64.getDecoder().decode(parts[2]), StandardCharsets.UTF_8);
                        call.load(new StringReader(decoded));
                        result.putAll(executeSapFunction(destination, call, contextOpen));
                    } else if (action.equals("ping")) { invoke(destination, "ping"); result.put("healthy", true); }
                    else if (action.equals("stop")) break;
                    else throw new IllegalArgumentException("Unsupported SAP worker action: " + action);
                    result.put("ok", true);
                } catch (Throwable error) {
                    Throwable cause = error; while (cause instanceof InvocationTargetException && cause.getCause() != null) cause = cause.getCause();
                    result.clear(); result.put("ok", false); result.put("message", String.valueOf(cause.getMessage() == null ? cause : cause.getMessage())); result.put("errorType", cause.getClass().getName());
                }
                result.put("requestId", requestId); System.out.println(json(result)); System.out.flush();
            }
        } finally {
            if (contextOpen) try { jcoContext(destination, "end"); } catch (Throwable ignored) { }
        }
        return map("stopped", true);
    }

    private static void setParameterPath(Object parameters, String path, Object value) throws Exception {
        if (parameters == null) throw new IllegalArgumentException("SAP function has no parameter list for " + path);
        String[] parts = path.split("\\.");
        Object current = parameters;
        for (int index = 0; index < parts.length - 1; index++) {
            current = invoke(current, "getStructure", parts[index]);
            if (current == null) throw new IllegalArgumentException("SAP structure parameter was not found: " + String.join(".", Arrays.copyOf(parts, index + 1)));
        }
        invoke(current, "setValue", parts[parts.length - 1], value);
    }

    private static Map<String, Object> functionResult(Object function) throws Exception {
        Map<String, Object> output = new LinkedHashMap<>();
        Object exports = invoke(function, "getExportParameterList");
        if (exports != null) output.put("exports", parameterValues(exports));
        Object changing = invoke(function, "getChangingParameterList");
        if (changing != null) output.put("changing", parameterValues(changing));
        Object tables = invoke(function, "getTableParameterList");
        if (tables != null) output.put("tables", tableValues(tables));
        return output;
    }

    private static Map<String, Object> listenerFunctionResult(Object function) throws Exception {
        Map<String, Object> output = functionResult(function);
        Object imports = invoke(function, "getImportParameterList");
        if (imports != null) output.put("imports", parameterValues(imports));
        return output;
    }

    /** Split one transactional IDoc package into one workflow event per IDoc.
     * The enclosing JCo callback is committed only after every child event
     * succeeds, preserving the atomic tRFC/qRFC transaction contract. */
    @SuppressWarnings("unchecked")
    private static List<Map<String, Object>> splitIdocPackage(Map<String, Object> payload) {
        Object rawTables = payload.get("tables");
        if (!(rawTables instanceof Map<?, ?>)) return List.of(payload);
        Map<String, Object> tables = (Map<String, Object>) rawTables;
        String controlName = null, dataName = null;
        List<Object> controls = null, records = null;
        for (Map.Entry<String, Object> entry : tables.entrySet()) {
            String normalized = entry.getKey().toUpperCase(Locale.ROOT).replaceAll("[^A-Z0-9]", "");
            if (normalized.contains("IDOCCONTROLREC") && entry.getValue() instanceof List<?>) {
                controlName = entry.getKey(); controls = (List<Object>) entry.getValue();
            }
            if (normalized.contains("IDOCDATAREC") && entry.getValue() instanceof List<?>) {
                dataName = entry.getKey(); records = (List<Object>) entry.getValue();
            }
        }
        if (controls == null || controls.isEmpty()) return List.of(payload);
        Map<String, Map<String, Object>> controlsByDocument = new LinkedHashMap<>();
        for (Object rawControl : controls) {
            if (!(rawControl instanceof Map<?, ?>)) throw new IllegalArgumentException("Invalid SAP IDoc control row");
            Map<String, Object> control = (Map<String, Object>) rawControl;
            String number = String.valueOf(control.getOrDefault("DOCNUM", "")).trim();
            if ((number.isEmpty() && controls.size() > 1) || controlsByDocument.putIfAbsent(number, control) != null) {
                throw new IllegalArgumentException("Missing or duplicate DOCNUM in SAP IDoc control rows");
            }
        }
        boolean singleDocument = controls.size() == 1;
        boolean hasDocumentNumber = !controlsByDocument.containsKey("");
        Map<String, List<Object>> recordsByDocument = new HashMap<>();
        for (Object rawRecord : records == null ? List.of() : records) {
            if (!(rawRecord instanceof Map<?, ?>)) throw new IllegalArgumentException("Invalid SAP IDoc segment row");
            Map<String, Object> record = (Map<String, Object>) rawRecord;
            String number = String.valueOf(record.getOrDefault("DOCNUM", "")).trim();
            if (!controlsByDocument.containsKey(number) && !(singleDocument && (!hasDocumentNumber || number.isEmpty()))) {
                throw new IllegalArgumentException("SAP IDoc segment has no matching control row");
            }
            if (!singleDocument) recordsByDocument.computeIfAbsent(number, key -> new ArrayList<>()).add(record);
        }
        if (singleDocument) return List.of(payload);
        List<Map<String, Object>> children = new ArrayList<>(controls.size());
        for (Map.Entry<String, Map<String, Object>> document : controlsByDocument.entrySet()) {
            Map<String, Object> childTables = new LinkedHashMap<>(tables);
            childTables.put(controlName, List.of(document.getValue()));
            if (dataName != null) childTables.put(dataName, recordsByDocument.getOrDefault(document.getKey(), List.of()));
            Map<String, Object> child = new LinkedHashMap<>(payload);
            child.put("tables", childTables);
            children.add(child);
        }
        return children;
    }

    /** Populate an RFC/BAPI listener response before returning to SAP. */
    private static void applyListenerResponse(Object function, Properties response) throws Exception {
        Object exports = invoke(function, "getExportParameterList");
        Object tables = invoke(function, "getTableParameterList");
        for (String key : response.stringPropertyNames()) {
            if (key.startsWith("export.") && exports != null) {
                setParameterPath(exports, key.substring(7), response.getProperty(key));
                continue;
            }
            if (!key.startsWith("table.") || tables == null) continue;
            String[] parts = key.split("\\.", 4);
            if (parts.length != 4) continue;
            Object table = invoke(tables, "getTable", parts[1]);
            if (table == null) continue;
            int row = Integer.parseInt(parts[2]);
            while (((Number) invoke(table, "getNumRows")).intValue() <= row) invoke(table, "appendRow");
            invoke(table, "setValue", parts[3], response.getProperty(key));
        }
    }

    /** Run a real JCo RFC server and emit one UTF-8 JSON event per inbound call. */
    private static Map<String, Object> listen(String serverName, Properties p) throws Exception {
        acquireListenerLock(p.getProperty("jco.server.progid", "sap-listener"));
        System.out.println(json(map("event", "jco_log", "level", "INFO", "phase", "server_initialization", "message", "Initializing SAP JCo RFC server", "serverName", serverName, "programId", p.getProperty("jco.server.progid"), "gatewayHost", p.getProperty("jco.server.gwhost"), "gatewayService", p.getProperty("jco.server.gwserv"))));
        System.out.flush();
        Class<?> environment = Class.forName("com.sap.conn.jco.ext.Environment");
        Class<?> providerType = Class.forName("com.sap.conn.jco.ext.ServerDataProvider");
        Properties server = new Properties();
        for (String key : p.stringPropertyNames()) if (key.startsWith("jco.server.")) server.setProperty(key, p.getProperty(key));
        Object provider = Proxy.newProxyInstance(providerType.getClassLoader(), new Class<?>[]{providerType}, (proxy, method, args) -> {
            if (method.getName().equals("getServerProperties")) return server;
            if (method.getName().equals("supportsEvents")) return false;
            if (method.getName().equals("setServerData")) return null;
            throw new UnsupportedOperationException(method.getName());
        });
        Method isRegistered = environment.getMethod("isServerDataProviderRegistered");
        Method register = environment.getMethod("registerServerDataProvider", providerType);
        if (!(Boolean) isRegistered.invoke(null)) register.invoke(null, provider);
        System.out.println(json(map("event", "jco_log", "level", "INFO", "phase", "server_provider", "message", "SAP JCo server data provider registered")));
        System.out.flush();

        Class<?> factory = Class.forName("com.sap.conn.jco.server.JCoServerFactory");
        Object jcoServer = factory.getMethod("getServer", String.class).invoke(null, serverName);
        Class<?> serverType = Class.forName("com.sap.conn.jco.server.JCoServer");
        String repositoryName = p.getProperty("jco.server.repository_destination", "").trim();
        if (!repositoryName.isEmpty()) {
            Class<?> manager = Class.forName("com.sap.conn.jco.JCoDestinationManager");
            Object repositoryDestination = manager.getMethod("getDestination", String.class).invoke(null, repositoryName);
            Class<?> destinationType = Class.forName("com.sap.conn.jco.JCoDestination");
            serverType.getMethod("setRepository", destinationType).invoke(jcoServer, repositoryDestination);
            System.out.println(json(map("event", "jco_log", "level", "INFO", "phase", "repository", "message", "SAP JCo repository destination bound", "repositoryDestination", repositoryName)));
            System.out.flush();
            // IDoc RFC callbacks need the client destination to resolve the
            // function metadata and repository. Binding the destination alone
            // is lazy in JCo and can leave the server looking healthy while
            // the first SAP request fails with CPIC-CALL/ThSAPOCMINIT. Verify
            // the client channel before registering the listener as ready.
            invoke(repositoryDestination, "ping");
            System.out.println(json(map("event", "jco_log", "level", "INFO", "phase", "repository_connection", "message", "SAP JCo repository connection verified", "repositoryDestination", repositoryName)));
            System.out.flush();
        }
        boolean tidEnabled = !"disabled".equalsIgnoreCase(p.getProperty("jco.server.tid_management", "active"));
        if (tidEnabled) {
            Class<?> tidHandlerType = Class.forName("com.sap.conn.jco.server.JCoServerTIDHandler");
            Object tidHandler = tidHandler(p.getProperty("jco.server.tid_store"));
            serverType.getMethod("setTIDHandler", tidHandlerType).invoke(jcoServer, tidHandler);
            System.out.println(json(map("event", "jco_log", "level", "INFO", "phase", "tid_handler", "message", "SAP JCo TID handler installed", "tidStore", p.getProperty("jco.server.tid_store"), "mode", "active")));
        } else {
            System.out.println(json(map("event", "jco_log", "level", "INFO", "phase", "tid_handler", "message", "SAP JCo TID handler disabled by configuration", "mode", "disabled")));
        }
        System.out.flush();
        // Do not serialize/write a complete (often multi-megabyte) IDoc while
        // SAP's CPIC callback is still on the stack. A blocked stdout pipe or
        // JSON serialization pause can make SAP reset the connection after a
        // few large IDocs. Queue the extracted event and emit it from a
        // dedicated writer so callbacks return as quickly as possible.
        int connectionCount = Math.max(1, integer(p, "jco.server.connection_count", 8));
        int maxPendingEvents = Math.max(connectionCount, integer(p, "jco.server.max_pending_events", connectionCount * 2));
        BlockingQueue<Map<String, Object>> idocEvents = new LinkedBlockingQueue<>(maxPendingEvents);
        Map<String, CompletableFuture<Boolean>> pendingDeliveries = new ConcurrentHashMap<>();
        Map<String, Properties> pendingResponses = new ConcurrentHashMap<>();
        AtomicLong idocPackages = new AtomicLong();
        AtomicBoolean commandChannelClosed = new AtomicBoolean();
        long ackTimeoutNanos = TimeUnit.MILLISECONDS.toNanos(Math.max(1L, (long) (number(p, "jco.server.ack_timeout_seconds", 300) * 1000)));
        Thread commandReader = new Thread(() -> {
            try (BufferedReader commands = new BufferedReader(new InputStreamReader(System.in, StandardCharsets.UTF_8))) {
                String line;
                while ((line = commands.readLine()) != null) {
                    String[] parts = line.split("\\t", 4);
                    if (parts.length < 2) continue;
                    String action = parts[0].trim(), deliveryId = parts[1].trim();
                    if ("set".equalsIgnoreCase(action) && parts.length == 4) {
                        Properties response = pendingResponses.get(deliveryId);
                        if (response != null) response.setProperty(parts[2], new String(Base64.getDecoder().decode(parts[3]), StandardCharsets.UTF_8));
                        continue;
                    }
                    CompletableFuture<Boolean> decision = pendingDeliveries.get(deliveryId);
                    if (decision != null) decision.complete("commit".equalsIgnoreCase(action));
                }
            } catch (IOException error) {
                System.err.println("SAP JCo acknowledgement channel stopped: " + error);
            } finally {
                commandChannelClosed.set(true);
                pendingDeliveries.values().forEach(decision -> decision.complete(false));
            }
        }, "sap-idoc-ack-reader");
        commandReader.setDaemon(true);
        commandReader.start();
        Thread idocWriter = new Thread(() -> {
            try {
                while (!Thread.currentThread().isInterrupted()) {
                    Map<String, Object> event = idocEvents.take();
                    if (pendingDeliveries.containsKey(event.get("deliveryId"))) System.out.println(json(event));
                }
            } catch (InterruptedException ignored) {
                Thread.currentThread().interrupt();
            }
        }, "sap-idoc-event-writer");
        idocWriter.setDaemon(true);
        idocWriter.start();
        Class<?> handlerType = Class.forName("com.sap.conn.jco.server.JCoServerFunctionHandler");
        Object handler = Proxy.newProxyInstance(handlerType.getClassLoader(), new Class<?>[]{handlerType}, (proxy, method, args) -> {
            if (!method.getName().equals("handleRequest")) return null;
            Object function = args != null && args.length > 1 ? args[1] : null;
            if (function != null) {
                String transactionId = "";
                try {
                    String functionName = String.valueOf(invoke(function, "getName"));
                    Object serverContext = args != null && args.length > 0 ? args[0] : null;
                    transactionId = optionalString(serverContext, "getTID");
                    String connectionId = optionalString(serverContext, "getConnectionID");
                    Map<String, Object> requestPayload = listenerFunctionResult(function);
                    boolean idoc = functionName.toUpperCase(Locale.ROOT).startsWith("IDOC_INBOUND");
                    List<Map<String, Object>> requests = idoc ? splitIdocPackage(requestPayload) : List.of(requestPayload);
                    // Keep this diagnostic separate from the payload event so
                    // operations teams can distinguish SAP routing/network
                    // failures from extraction or workflow failures without
                    // logging business data.
                    if (!idoc || idocPackages.getAndIncrement() % 1000 == 0) {
                        System.out.println(json(map("event", "jco_log", "level", "INFO", "phase", "request_received", "message", "SAP JCo request callback received", "functionName", functionName, "TID", transactionId, "CPIC_ID", connectionId, "packageSize", requests.size())));
                    }
                    List<String> deliveryIds = new ArrayList<>();
                    List<CompletableFuture<Boolean>> decisions = new ArrayList<>();
                    List<Properties> responses = new ArrayList<>();
                    try {
                        long deadline = System.nanoTime() + ackTimeoutNanos;
                        for (Map<String, Object> request : requests) {
                            String deliveryId = UUID.randomUUID().toString();
                            CompletableFuture<Boolean> decision = new CompletableFuture<>();
                            Properties response = new Properties();
                            deliveryIds.add(deliveryId); decisions.add(decision); responses.add(response);
                            pendingDeliveries.put(deliveryId, decision);
                            pendingResponses.put(deliveryId, response);
                            if (commandChannelClosed.get()) throw new IOException("SAP acknowledgement channel closed");
                            if (!idocEvents.offer(map("event", "sap_request", "deliveryId", deliveryId, "functionName", functionName, "TID", transactionId, "CPIC_ID", connectionId, "packageSize", requests.size(), "payload", request),
                                    deadline - System.nanoTime(), TimeUnit.NANOSECONDS)) {
                                throw new IllegalStateException("Timed out queueing a SAP request or IDoc package");
                            }
                        }
                        for (CompletableFuture<Boolean> decision : decisions) {
                            long remaining = deadline - System.nanoTime();
                            if (remaining <= 0 || !Boolean.TRUE.equals(decision.get(remaining, TimeUnit.NANOSECONDS))) {
                                throw new IllegalStateException("MINA rolled back the SAP request or IDoc package");
                            }
                        }
                        if (responses.size() == 1 && !responses.get(0).isEmpty()) applyListenerResponse(function, responses.get(0));
                    } finally {
                        for (String deliveryId : deliveryIds) {
                            pendingDeliveries.remove(deliveryId);
                            pendingResponses.remove(deliveryId);
                        }
                    }
                } catch (Throwable error) {
                    Throwable cause = error;
                    while (cause instanceof InvocationTargetException && ((InvocationTargetException) cause).getCause() != null) cause = ((InvocationTargetException) cause).getCause();
                    System.out.println(json(map("event", "jco_log", "level", "ERROR", "phase", "request_callback", "message", "SAP JCo request callback failed", "TID", transactionId, "errorType", cause.getClass().getName(), "error", String.valueOf(cause.getMessage() == null ? cause : cause.getMessage()))));
                    System.out.flush();
                    throw new RuntimeException(cause);
                }
            }
            return null;
        });
        String functionName = p.getProperty("listenerFunction", "IDOC_INBOUND_ASYNCHRONOUS");
        // JCo 3 uses a DefaultServerHandlerFactory; JCoServer does not have
        // a setCallHandler(function, handler) method.
        Class<?> factoryType = Class.forName("com.sap.conn.jco.server.DefaultServerHandlerFactory$FunctionHandlerFactory");
        Object handlerFactory = factoryType.getConstructor().newInstance();
        Method registerHandler = Arrays.stream(factoryType.getMethods())
                .filter(method -> method.getName().equals("registerHandler") && method.getParameterCount() == 2
                        && method.getParameterTypes()[0].isAssignableFrom(String.class)
                        && method.getParameterTypes()[1].isAssignableFrom(handler.getClass()))
                .findFirst().orElseGet(() -> Arrays.stream(factoryType.getDeclaredMethods())
                        .filter(method -> method.getName().equals("registerHandler") && method.getParameterCount() == 2)
                        .findFirst().orElse(null));
        if (registerHandler == null) throw new NoSuchMethodException("JCo FunctionHandlerFactory.registerHandler");
        registerHandler.setAccessible(true);
        registerHandler.invoke(handlerFactory, functionName, handler);
        System.out.println(json(map("event", "jco_log", "level", "INFO", "phase", "function_handler", "message", "SAP JCo function handler registered", "functionName", functionName)));
        System.out.flush();
        Method setFactory = Arrays.stream(serverType.getMethods())
                .filter(method -> method.getName().equals("setCallHandlerFactory") && method.getParameterCount() == 1 && method.getParameterTypes()[0].isAssignableFrom(factoryType))
                .findFirst().orElseThrow(() -> new NoSuchMethodException("JCoServer.setCallHandlerFactory"));
        setFactory.invoke(jcoServer, handlerFactory);
        serverType.getMethod("start").invoke(jcoServer);
        System.out.println(json(map("event", "jco_log", "level", "INFO", "phase", "server_started", "message", "SAP JCo RFC server started", "programId", server.getProperty("jco.server.progid"), "gatewayHost", server.getProperty("jco.server.gwhost"), "gatewayService", server.getProperty("jco.server.gwserv"), "connectionCount", server.getProperty("jco.server.connection_count"))));
        System.out.flush();
        System.out.println(json(map("event", "listening", "serverName", serverName, "programId", server.getProperty("jco.server.progid"), "gatewayHost", server.getProperty("jco.server.gwhost"), "gatewayService", server.getProperty("jco.server.gwserv"), "repositoryDestination", repositoryName, "javaVersion", System.getProperty("java.version"), "javaVendor", System.getProperty("java.vendor"), "jcoServerClass", jcoServer.getClass().getName())));
        System.out.flush();
        synchronized (MinaJavaBridge.class) { MinaJavaBridge.class.wait(); }
        return map("message", "SAP JCo listener stopped");
    }

    /**
     * A SAP registered-server program ID must have one active owner on a
     * machine. Without a process-level guard, running the browser backend and
     * the installed Studio together can register the same TP; SAP then routes
     * IDocs to either process and the operator may watch the wrong one.
     */
    private static void acquireListenerLock(String programId) throws IOException {
        String safe = programId.replaceAll("[^A-Za-z0-9_.-]", "_");
        Path path = Paths.get(System.getProperty("java.io.tmpdir"), "mina-sap-" + safe + ".lock");
        listenerLockChannel = FileChannel.open(path, StandardOpenOption.CREATE, StandardOpenOption.WRITE);
        try {
            listenerLock = listenerLockChannel.tryLock();
        } catch (OverlappingFileLockException error) {
            listenerLock = null;
        }
        if (listenerLock == null) {
            try { listenerLockChannel.close(); } catch (IOException ignored) { }
            listenerLockChannel = null;
            throw new IOException("SAP JCo program ID '" + programId + "' is already owned by another MINA listener on this machine");
        }
    }

    /** Durable tRFC TID state prevents duplicate IDoc delivery after retries. */
    private static Object tidHandler(String fileName) throws Exception {
        Class<?> type = Class.forName("com.sap.conn.jco.server.JCoServerTIDHandler");
        SapTidStore store = new SapTidStore(Path.of(fileName == null || fileName.isBlank() ? "sap-tids.properties" : fileName));
        return Proxy.newProxyInstance(type.getClassLoader(), new Class<?>[]{type}, (proxy, method, args) -> {
            String operation = method.getName();
            if (method.getDeclaringClass() == Object.class) {
                return switch (operation) {
                    case "hashCode" -> System.identityHashCode(proxy);
                    case "equals" -> proxy == args[0];
                    default -> "MINA SAP TID handler";
                };
            }
            String tid = null;
            for (Object argument : args == null ? new Object[0] : args) {
                if (argument instanceof String) { tid = (String) argument; break; }
            }
            if (tid == null || tid.isBlank()) return operation.equals("checkTID") ? Boolean.FALSE : null;
            try {
                switch (operation) {
                    case "checkTID": return store.check(tid);
                    case "commit": store.commit(tid); break;
                    case "rollback": store.rollback(tid); break;
                    case "confirmTID": store.confirm(tid); break;
                }
            } catch (IOException error) {
                throw new UncheckedIOException("SAP JCo TID store failed during " + operation, error);
            }
            return null;
        });
    }

    /** A committed TID has one marker until SAP confirms it. In-flight and rolled back TIDs need no disk state. */
    static final class SapTidStore {
        private final Path legacyFile;
        private final Path committedDirectory;
        private final Properties legacy = new Properties();
        private final Set<String> active = new HashSet<>();

        SapTidStore(Path file) throws IOException {
            legacyFile = file.toAbsolutePath();
            committedDirectory = Files.createDirectories(legacyFile.resolveSibling(legacyFile.getFileName() + ".committed"));
            try (InputStream input = Files.newInputStream(legacyFile)) { legacy.load(input); }
            catch (NoSuchFileException absent) { /* Fresh installation. */ }
        }

        private Path marker(String tid) {
            // Hex uses a single case so two TIDs cannot alias on Windows filesystems.
            return committedDirectory.resolve(HexFormat.of().formatHex(tid.getBytes(StandardCharsets.UTF_8)));
        }

        synchronized boolean check(String tid) throws IOException {
            String oldState = legacy.getProperty(tid);
            if (active.contains(tid) || "COMMITTED".equals(oldState) || "CONFIRMED".equals(oldState)) return false;
            try {
                Files.readAttributes(marker(tid), BasicFileAttributes.class);
                return false;
            } catch (NoSuchFileException absent) {
                // A missing marker is expected, a missing store is an I/O fault.
                Files.readAttributes(committedDirectory, BasicFileAttributes.class);
                return active.add(tid);
            }
        }

        synchronized void commit(String tid) throws IOException {
            try { Files.createFile(marker(tid)); }
            catch (FileAlreadyExistsException committed) { /* Commit can be retried. */ }
            if (System.getProperty("os.name", "").equals("Linux")) {
                // Persist the directory entry before acknowledging commit on Linux.
                try (FileChannel directory = FileChannel.open(committedDirectory, StandardOpenOption.READ)) {
                    directory.force(true);
                }
            }
            active.remove(tid);
        }

        synchronized void rollback(String tid) { active.remove(tid); }

        synchronized void confirm(String tid) throws IOException {
            if (legacy.containsKey(tid)) {
                Path temp = Files.createTempFile(legacyFile.getParent(), "sap-tids-", ".tmp");
                Properties remaining = new Properties();
                remaining.putAll(legacy);
                remaining.remove(tid);
                try {
                    try (OutputStream output = Files.newOutputStream(temp)) { remaining.store(output, "MINA SAP JCo tRFC transaction state"); }
                    try { Files.move(temp, legacyFile, StandardCopyOption.ATOMIC_MOVE, StandardCopyOption.REPLACE_EXISTING); }
                    catch (AtomicMoveNotSupportedException unsupported) { Files.move(temp, legacyFile, StandardCopyOption.REPLACE_EXISTING); }
                    legacy.remove(tid);
                } finally {
                    Files.deleteIfExists(temp);
                }
            }
            Files.deleteIfExists(marker(tid));
            active.remove(tid);
        }
    }

    private static Map<String, Object> parameterValues(Object list) throws Exception {
        Map<String, Object> values = new LinkedHashMap<>();
        Object metadata = invoke(list, "getMetaData");
        int count = ((Number) invoke(metadata, "getFieldCount")).intValue();
        for (int index = 0; index < count; index++) {
            String name = String.valueOf(invoke(metadata, "getName", index));
            values.put(name, jsonValue(invoke(list, "getValue", name)));
        }
        return values;
    }

    private static Map<String, Object> tableValues(Object list) throws Exception {
        Map<String, Object> values = new LinkedHashMap<>();
        Object metadata = invoke(list, "getMetaData");
        int count = ((Number) invoke(metadata, "getFieldCount")).intValue();
        for (int index = 0; index < count; index++) {
            String name = String.valueOf(invoke(metadata, "getName", index));
            Object table = invoke(list, "getTable", name);
            values.put(name, tableRows(table));
        }
        return values;
    }

    private static List<Object> tableRows(Object table) throws Exception {
        int count = ((Number) invoke(table, "getNumRows")).intValue();
        List<Object> rows = new ArrayList<>(count);
        Object metadata = invoke(table, "getMetaData");
        int fields = ((Number) invoke(metadata, "getFieldCount")).intValue();
        String[] names = new String[fields];
        for (int field = 0; field < fields; field++) names[field] = String.valueOf(invoke(metadata, "getName", field));
        for (int row = 0; row < count; row++) {
            invoke(table, "setRow", row);
            Map<String, Object> item = new LinkedHashMap<>();
            for (String name : names) item.put(name, jsonValue(invoke(table, "getValue", name)));
            rows.add(item);
        }
        return rows;
    }

    private static void fillTables(Object function, Properties p) throws Exception {
        // In JCo, RFC table parameters (for example RFC_READ_TABLE's FIELDS
        // and OPTIONS) live in the function table-parameter list, not in the
        // scalar import record.
        Object tables = invoke(function, "getTableParameterList");
        for (String key : p.stringPropertyNames()) {
            if (!key.startsWith("tableArg.")) continue;
            String[] parts = key.split("\\.", 4);
            if (parts.length != 4) continue;
            Object table = invoke(tables, "getTable", parts[1]);
            if (table == null) continue;
            int row = Integer.parseInt(parts[2]);
            while (((Number) invoke(table, "getNumRows")).intValue() <= row) invoke(table, "appendRow");
            invoke(table, "setValue", parts[3], p.getProperty(key));
        }
    }

    private static void fillReadTable(Object function, Properties p) throws Exception {
        Object tables = invoke(function, "getTableParameterList");
        for (String key : p.stringPropertyNames()) {
            if (!key.startsWith("readTable.")) continue;
            String[] parts = key.split("\\.", 4);
            if (parts.length != 4) continue;
            Object table = invoke(tables, "getTable", parts[1]);
            int row = Integer.parseInt(parts[2]);
            while (((Number) invoke(table, "getNumRows")).intValue() <= row) invoke(table, "appendRow");
            invoke(table, "setValue", parts[3], p.getProperty(key));
        }
    }

    private static Object jsonValue(Object value) {
        if (value == null || value instanceof String || value instanceof Number || value instanceof Boolean) return value;
        try {
            // JCo import/export structures expose metadata and getValue but
            // do not expose getNumRows like a JCoTable does.
            Object metadata = value.getClass().getMethod("getMetaData").invoke(value);
            int fields = ((Number) metadata.getClass().getMethod("getFieldCount").invoke(metadata)).intValue();
            Map<String, Object> structure = new LinkedHashMap<>();
            for (int field = 0; field < fields; field++) {
                String name = String.valueOf(metadata.getClass().getMethod("getName", int.class).invoke(metadata, field));
                structure.put(name, jsonValue(value.getClass().getMethod("getValue", String.class).invoke(value, name)));
            }
            return structure;
        } catch (Exception ignored) { }
        try {
            int rows = ((Number) value.getClass().getMethod("getNumRows").invoke(value)).intValue();
            List<Object> result = new ArrayList<>();
            if (rows > 0) {
                Object metadata = value.getClass().getMethod("getMetaData").invoke(value);
                int fields = ((Number) metadata.getClass().getMethod("getFieldCount").invoke(metadata)).intValue();
                for (int row = 0; row < rows; row++) {
                    value.getClass().getMethod("setRow", int.class).invoke(value, row);
                    Map<String, Object> item = new LinkedHashMap<>();
                    for (int field = 0; field < fields; field++) {
                        String name = String.valueOf(metadata.getClass().getMethod("getName", int.class).invoke(metadata, field));
                        item.put(name, value.getClass().getMethod("getValue", String.class).invoke(value, name));
                    }
                    result.add(item);
                }
            }
            return result;
        } catch (Exception ignored) { return String.valueOf(value); }
    }

    private static Map<String, Object> jms(String operation, Properties p) throws Exception {
        Object factory;
        InitialContext context = null;
        if (bool(p, "jndiEnabled", false)) {
            Hashtable<String, String> environment = new Hashtable<>();
            put(environment, Context.INITIAL_CONTEXT_FACTORY, required(p, "jndiContextFactory"));
            put(environment, Context.PROVIDER_URL, p.getProperty("jndiProviderUrl"));
            put(environment, Context.SECURITY_PRINCIPAL, p.getProperty("jndiUsername"));
            put(environment, Context.SECURITY_CREDENTIALS, p.getProperty("jndiPassword"));
            context = new InitialContext(environment);
            factory = context.lookup(required(p, "connectionFactory"));
        } else {
            String factoryClass = required(p, "connectionFactoryClass");
            Class<?> type = Class.forName(factoryClass);
            try { factory = type.getConstructor(String.class).newInstance(required(p, "serverUrl")); }
            catch (NoSuchMethodException ignored) {
                factory = type.getConstructor().newInstance();
                invoke(factory, "setServerUrl", required(p, "serverUrl"));
            }
        }
        Object connection = null, session = null;
        try {
            String username = p.getProperty("username", ""), password = p.getProperty("password", "");
            // Empty credentials mean provider defaults/anonymous authentication.
            // Passing two empty strings can override factory/JNDI credentials
            // and is rejected by providers whose anonymous login needs nulls.
            connection = username.isEmpty() && password.isEmpty()
                ? invoke(factory, "createConnection")
                : invoke(factory, "createConnection", username, password);
            if (!p.getProperty("clientId", "").isBlank()) invoke(connection, "setClientID", p.getProperty("clientId"));
            invoke(connection, "start");
            if (operation.equals("test")) return map("message", "Native JMS connection succeeded");
            session = invoke(connection, "createSession", false, operation.equals("listen") ? 2 : 1);
            if (operation.equals("sender_worker")) return jmsSenderWorker(session, context);
            String destinationName = required(p, "destination");
            Object destination;
            if (context != null && bool(p, "jndiDestination", false)) destination = context.lookup(destinationName);
            else destination = invoke(session, bool(p, "topic", false) ? "createTopic" : "createQueue", destinationName);
            if (operation.equals("listen")) {
                Object consumer = p.getProperty("selector", "").isBlank() ? invoke(session, "createConsumer", destination) : invoke(session, "createConsumer", destination, p.getProperty("selector"));
                try (BufferedReader commands = new BufferedReader(new InputStreamReader(System.in, StandardCharsets.UTF_8))) {
                    System.out.println(json(map("event", "listening", "received", false, "destination", destinationName, "ok", true)));
                    System.out.flush();
                    while (true) {
                        Object message = invoke(consumer, "receive", 1000L);
                        if (message == null) continue;
                        String deliveryId = UUID.randomUUID().toString();
                        Object body;
                        try { body = invoke(message, "getText"); } catch (Exception ignored) { body = String.valueOf(message); }
                        Map<String, Object> headers = new LinkedHashMap<>();
                        copyHeader(headers, message, "JMSMessageID", "getJMSMessageID");
                        copyHeader(headers, message, "JMSCorrelationID", "getJMSCorrelationID");
                        copyHeader(headers, message, "JMSReplyTo", "getJMSReplyTo");
                        copyHeader(headers, message, "JMSType", "getJMSType");
                        Map<String, Object> properties = new LinkedHashMap<>();
                        Enumeration<?> names = (Enumeration<?>) invoke(message, "getPropertyNames");
                        while (names.hasMoreElements()) { String name = String.valueOf(names.nextElement()); properties.put(name, invoke(message, "getObjectProperty", name)); }
                        System.out.println(json(map("event", "message", "received", true, "deliveryId", deliveryId, "body", body, "headers", headers, "properties", properties, "destination", destinationName, "ok", true)));
                        System.out.flush();
                        String decision;
                        do { decision = commands.readLine(); if (decision == null) throw new EOFException("JMS acknowledgement channel closed"); }
                        while (!decision.equals("commit\t" + deliveryId) && !decision.equals("rollback\t" + deliveryId) && !decision.startsWith("reply\t" + deliveryId + "\t"));
                        if (decision.startsWith("reply\t")) {
                            String[] parts = decision.split("\t", 3);
                            Object replyDestination = invoke(message, "getJMSReplyTo");
                            if (replyDestination == null) throw new IllegalStateException("JMS request does not contain JMSReplyTo");
                            Object producer = invoke(session, "createProducer", replyDestination);
                            try {
                                String replyBody = new String(Base64.getDecoder().decode(parts[2]), StandardCharsets.UTF_8);
                                Object reply = invoke(session, "createTextMessage", replyBody);
                                Object correlation = invoke(message, "getJMSCorrelationID");
                                if (correlation == null || String.valueOf(correlation).isBlank()) correlation = invoke(message, "getJMSMessageID");
                                invoke(reply, "setJMSCorrelationID", correlation);
                                invoke(producer, "send", reply);
                                invoke(message, "acknowledge");
                            } finally { close(producer); }
                        } else if (decision.startsWith("commit\t")) invoke(message, "acknowledge");
                        else invoke(session, "recover");
                    }
                } finally { close(consumer); }
            }
            if (operation.equals("send")) {
                Object producer = invoke(session, "createProducer", destination);
                try {
                    return jmsSend(session, producer, destinationName, p);
                } finally { close(producer); }
            }
            if (operation.equals("request")) {
                Object producer = invoke(session, "createProducer", destination);
                Object replyDestination = p.getProperty("replyTo", "").isBlank()
                    ? invoke(session, "createTemporaryQueue")
                    : invoke(session, bool(p, "replyTopic", false) ? "createTopic" : "createQueue", p.getProperty("replyTo"));
                Object consumer = invoke(session, "createConsumer", replyDestination);
                try {
                    Object request = invoke(session, "createTextMessage", p.getProperty("body", ""));
                    invoke(request, "setJMSReplyTo", replyDestination);
                    setIfPresent(request, "setJMSCorrelationID", p, "correlationId");
                    setIfPresent(request, "setJMSType", p, "messageType");
                    for (String name : p.stringPropertyNames()) if (name.startsWith("messageProperty.")) invoke(request, "setStringProperty", name.substring(16), p.getProperty(name));
                    invoke(producer, "setDeliveryMode", bool(p, "persistent", true) ? 2 : 1);
                    invoke(producer, "setPriority", integer(p, "priority", 4));
                    invoke(producer, "setTimeToLive", number(p, "expiration", 0));
                    invoke(producer, "send", request);
                    Object response = invoke(consumer, "receive", number(p, "timeoutMs", 30000));
                    if (response == null) return map("received", false, "body", null, "requestMessageId", invoke(request, "getJMSMessageID"));
                    Object body;
                    try { body = invoke(response, "getText"); } catch (Exception ignored) { body = String.valueOf(response); }
                    Map<String, Object> headers = new LinkedHashMap<>();
                    copyHeader(headers, response, "JMSMessageID", "getJMSMessageID");
                    copyHeader(headers, response, "JMSCorrelationID", "getJMSCorrelationID");
                    return map("received", true, "body", body, "headers", headers, "requestMessageId", invoke(request, "getJMSMessageID"));
                } finally { close(consumer); close(producer); }
            }
            if (operation.equals("receive")) return jmsReceive(session, context, p, destination);
            throw new IllegalArgumentException("Unsupported JMS operation: " + operation);
        } finally {
            close(session); close(connection); if (context != null) context.close();
        }
    }

    private static Map<String, Object> jmsReceive(Object session, InitialContext context, Properties p, Object suppliedDestination) throws Exception {
        String name = required(p, "destination");
        Object destination = suppliedDestination != null ? suppliedDestination : context != null && bool(p, "jndiDestination", false) ? context.lookup(name) : invoke(session, bool(p, "topic", false) ? "createTopic" : "createQueue", name);
        Object consumer = p.getProperty("selector", "").isBlank() ? invoke(session, "createConsumer", destination) : invoke(session, "createConsumer", destination, p.getProperty("selector"));
        try {
            int maximum = Math.max(1, Math.min(10000, integer(p, "maxMessages", 1)));
            long timeoutMs = number(p, "timeoutMs", 30000);
            long deadline = System.nanoTime() + Math.max(0L, timeoutMs) * 1000000L;
            Object message = invoke(consumer, "receive", timeoutMs);
            List<Map<String, Object>> messages = new ArrayList<>();
            while (message != null) {
                messages.add(jmsReceived(message));
                if (bool(p, "clientAcknowledge", false)) invoke(message, "acknowledge");
                if (messages.size() >= maximum) break;
                // A single batch deadline includes all delivery waits.
                // Zero retains the legacy first-message indefinite wait,
                // then drains only immediately available messages.
                if (timeoutMs <= 0) message = invoke(consumer, "receiveNoWait");
                else {
                    long remaining = deadline - System.nanoTime();
                    if (remaining <= 0) break;
                    message = invoke(consumer, "receive", Math.max(1L, (remaining + 999999L) / 1000000L));
                }
            }
            if (messages.isEmpty()) return map("received", false, "body", null, "headers", Map.of(), "properties", Map.of(), "count", 0);
            Map<String, Object> result = new LinkedHashMap<>(messages.get(0));
            result.put("count", messages.size());
            if (maximum > 1) result.put("messages", messages);
            return result;
        } finally { close(consumer); }
    }

    private static Map<String, Object> jmsReceived(Object message) throws Exception {
        Object body;
        try { body = invoke(message, "getText"); } catch (Exception ignored) { body = String.valueOf(message); }
        Map<String, Object> headers = new LinkedHashMap<>();
        copyHeader(headers, message, "JMSMessageID", "getJMSMessageID"); copyHeader(headers, message, "JMSCorrelationID", "getJMSCorrelationID"); copyHeader(headers, message, "JMSReplyTo", "getJMSReplyTo");
        copyHeader(headers, message, "JMSType", "getJMSType"); copyHeader(headers, message, "JMSTimestamp", "getJMSTimestamp");
        copyHeader(headers, message, "JMSPriority", "getJMSPriority"); copyHeader(headers, message, "JMSRedelivered", "getJMSRedelivered");
        Map<String, Object> properties = new LinkedHashMap<>();
        Enumeration<?> names = (Enumeration<?>) invoke(message, "getPropertyNames");
        while (names.hasMoreElements()) { String name = String.valueOf(names.nextElement()); properties.put(name, invoke(message, "getObjectProperty", name)); }
        return map("received", true, "body", body, "headers", headers, "properties", properties, "count", 1);
    }

    private static Map<String, Object> jdbc(String operation, Properties p) throws Exception {
        Class.forName(required(p, "driverClass"));
        Properties credentials = new Properties();
        put(credentials, "user", p.getProperty("username")); put(credentials, "password", p.getProperty("password"));
        for (String name : p.stringPropertyNames()) if (name.startsWith("jdbcProperty.")) credentials.setProperty(name.substring(13), p.getProperty(name));
        DriverManager.setLoginTimeout(integer(p, "timeoutSeconds", 30));
        try (Connection connection = DriverManager.getConnection(required(p, "jdbcUrl"), credentials)) {
            if (operation.equals("test")) {
                boolean valid = connection.isValid(integer(p, "timeoutSeconds", 30));
                return map("ok", valid, "message", valid ? "JDBC connection succeeded" : "JDBC driver reported an invalid connection", "databaseProduct", connection.getMetaData().getDatabaseProductName(), "databaseVersion", connection.getMetaData().getDatabaseProductVersion());
            }
            if (operation.equals("metadata")) return jdbcMetadata(connection, p);
            if (operation.equals("execute")) {
                connection.setAutoCommit(false);
                try {
                    Map<String, Object> result = jdbcExecute(connection, p);
                    connection.commit();
                    return result;
                } catch (Exception error) {
                    try { connection.rollback(); } catch (SQLException rollback) { error.addSuppressed(rollback); }
                    throw error;
                }
            }
            if (operation.equals("worker")) return jdbcWorker(connection);
            throw new IllegalArgumentException("Unsupported JDBC operation: " + operation);
        }
    }

    /** Send through a serialized JMS session while retaining provider completion. */
    private static Map<String, Object> jmsSend(Object session, Object producer, String destinationName, Properties p) throws Exception {
        Object message = invoke(session, "createTextMessage", p.getProperty("body", ""));
        setIfPresent(message, "setJMSCorrelationID", p, "correlationId");
        setIfPresent(message, "setJMSType", p, "messageType");
        if (!p.getProperty("replyTo", "").isBlank()) {
            Object replyDestination = invoke(session, bool(p, "replyTopic", false) ? "createTopic" : "createQueue", p.getProperty("replyTo"));
            invoke(message, "setJMSReplyTo", replyDestination);
        }
        for (String name : p.stringPropertyNames()) if (name.startsWith("messageProperty.")) invoke(message, "setStringProperty", name.substring(16), p.getProperty(name));
        invoke(producer, "setDeliveryMode", bool(p, "persistent", true) ? 2 : 1);
        invoke(producer, "setPriority", integer(p, "priority", 4));
        invoke(producer, "setTimeToLive", number(p, "expiration", 0));
        long started = System.nanoTime();
        invoke(producer, "send", message);
        return map("messageId", invoke(message, "getJMSMessageID"), "destination", destinationName, "published", true,
                   "providerSendMs", (System.nanoTime() - started) / 1000000.0);
    }

    private static Map<String, Object> jmsSenderWorker(Object session, InitialContext context) throws Exception {
        Map<String, Object> producers = new LinkedHashMap<>();
        try (BufferedReader commands = new BufferedReader(new InputStreamReader(System.in, StandardCharsets.UTF_8))) {
            System.out.println(json(map("event", "ready", "ok", true))); System.out.flush();
            String line;
            while ((line = commands.readLine()) != null) {
                String[] parts = line.split("\t", 3);
                if (parts[0].equals("stop")) break;
                Map<String, Object> result;
                boolean failed = false;
                try {
                    if ((!parts[0].equals("send") && !parts[0].equals("receive")) || parts.length < 3) throw new IllegalArgumentException("Invalid JMS sender command");
                    Properties call = new Properties();
                    call.load(new StringReader(new String(Base64.getDecoder().decode(parts[2]), StandardCharsets.UTF_8)));
                    String destinationName = required(call, "destination");
                    if (parts[0].equals("receive")) result = jmsReceive(session, context, call, null);
                    else {
                    String cacheKey = bool(call, "topic", false) + ":" + bool(call, "jndiDestination", false) + ":" + destinationName;
                    Object producer = producers.get(cacheKey);
                    if (producer == null) {
                        Object destination = context != null && bool(call, "jndiDestination", false)
                            ? context.lookup(destinationName)
                            : invoke(session, bool(call, "topic", false) ? "createTopic" : "createQueue", destinationName);
                        if (producers.size() >= 32) {
                            String oldest = producers.keySet().iterator().next();
                            close(producers.remove(oldest));
                        }
                        producer = invoke(session, "createProducer", destination);
                        producers.put(cacheKey, producer);
                    }
                    result = jmsSend(session, producer, destinationName, call);
                    }
                    result.put("ok", true);
                } catch (Throwable error) {
                    result = map("ok", false, "message", String.valueOf(error.getMessage() == null ? error : error.getMessage()));
                    failed = true;
                }
                result.put("requestId", parts.length > 1 ? parts[1] : "");
                System.out.println(json(result)); System.out.flush();
                // Never replay an uncertain send. A later caller may establish a new connection.
                if (failed) break;
            }
        } finally { for (Object producer : producers.values()) close(producer); }
        return map("stopped", true);
    }

    private static Map<String, Object> jdbcWorker(Connection connection) throws Exception {
        connection.setAutoCommit(false);
        System.out.println(json(map("event", "ready", "ok", true, "pid", ProcessHandle.current().pid(), "autoCommit", false))); System.out.flush();
        boolean active = true;
        try (BufferedReader commands = new BufferedReader(new InputStreamReader(System.in, StandardCharsets.UTF_8))) {
            String line;
            while ((line = commands.readLine()) != null) {
                String[] parts = line.split("\\t", 3);
                String action = parts.length > 0 ? parts[0] : "", requestId = parts.length > 1 ? parts[1] : "";
                Map<String, Object> result = new LinkedHashMap<>();
                try {
                    if (action.equals("begin")) {
                        if (!active) { connection.setAutoCommit(false); active = true; }
                        result.put("transactionOpen", true);
                    } else if (action.equals("execute") && parts.length == 3) {
                        if (!active) throw new IllegalStateException("No JDBC transaction is open");
                        Properties call = new Properties();
                        call.load(new StringReader(new String(Base64.getDecoder().decode(parts[2]), StandardCharsets.UTF_8)));
                        result.putAll(jdbcExecute(connection, call));
                        result.put("transactionOpen", true);
                    } else if (action.equals("commit")) {
                        if (!active) throw new IllegalStateException("No JDBC transaction is open");
                        connection.commit(); active = false;
                        result.put("committed", true); result.put("transactionOpen", false);
                    } else if (action.equals("rollback")) {
                        if (active) connection.rollback(); active = false;
                        result.put("rolledBack", true); result.put("transactionOpen", false);
                    } else if (action.equals("ping")) {
                        result.put("healthy", connection.isValid(5)); result.put("transactionOpen", active);
                    } else if (action.equals("stop")) break;
                    else throw new IllegalArgumentException("Unsupported JDBC worker action: " + action);
                    result.put("ok", true);
                } catch (Throwable error) {
                    result.clear(); result.put("ok", false); result.put("message", String.valueOf(error.getMessage() == null ? error : error.getMessage())); result.put("errorType", error.getClass().getName());
                }
                result.put("requestId", requestId); System.out.println(json(result)); System.out.flush();
            }
        } finally {
            if (active) try { connection.rollback(); } catch (Throwable ignored) { }
            try { connection.setAutoCommit(true); } catch (Throwable ignored) { }
        }
        return map("stopped", true);
    }

    private static Map<String, Object> jdbcMetadata(Connection connection, Properties p) throws SQLException {
        String catalog = emptyToNull(p.getProperty("catalog")), schema = emptyToNull(p.getProperty("schema"));
        List<Object> tables = new ArrayList<>(); DatabaseMetaData metadata = connection.getMetaData();
        try (ResultSet result = metadata.getTables(catalog, schema, "%", new String[]{"TABLE", "VIEW"})) {
            while (result.next()) {
                String tableCatalog = result.getString("TABLE_CAT"), tableSchema = result.getString("TABLE_SCHEM"), tableName = result.getString("TABLE_NAME");
                List<Object> columns = new ArrayList<>();
                try (ResultSet columnResult = metadata.getColumns(tableCatalog, tableSchema, tableName, "%")) {
                    while (columnResult.next()) columns.add(map("name", columnResult.getString("COLUMN_NAME"), "dataType", columnResult.getString("TYPE_NAME"), "notNull", columnResult.getInt("NULLABLE") == DatabaseMetaData.columnNoNulls, "ordinal", columnResult.getInt("ORDINAL_POSITION")));
                }
                tables.add(map("catalog", tableCatalog, "schema", tableSchema, "name", tableName, "type", result.getString("TABLE_TYPE"), "columns", columns));
            }
        }
        return map("driver", p.getProperty("databaseDriver"), "tables", tables);
    }

    private static Map<String, Object> jdbcExecute(Connection connection, Properties p) throws SQLException {
        String sql = required(p, "sql");
        if ("call".equals(p.getProperty("operation"))) return jdbcCall(connection, p, sql);
        try (PreparedStatement statement = connection.prepareStatement(sql)) {
            int timeout = integer(p, "queryTimeoutSeconds", 0);
            if (timeout > 0) statement.setQueryTimeout(timeout);
            int batch = integer(p, "batchCount", 0);
            String fallbackSql = p.getProperty("fallback.sql");
            if (fallbackSql != null) {
                try (PreparedStatement fallback = connection.prepareStatement(fallbackSql)) {
                    if (timeout > 0) fallback.setQueryTimeout(timeout);
                    long updated = 0;
                    for (int row = 0; row < Math.max(1, batch); row++) {
                        String rowPrefix = batch > 0 ? "batch." + row + "." : "";
                        bindJdbcParameters(statement, p, "", rowPrefix);
                        int count = statement.executeUpdate();
                        if (count == 0) {
                            bindJdbcParameters(fallback, p, "fallback.", rowPrefix);
                            count = fallback.executeUpdate();
                        }
                        updated = addJdbcCount(updated, count);
                    }
                    return map("noOfUpdates", updated, "rowCount", updated);
                }
            }
            if (batch > 0) {
                for (int row = 0; row < batch; row++) {
                    bindJdbcParameters(statement, p, "", "batch." + row + ".");
                    statement.addBatch();
                }
                long updated = 0;
                for (int count : statement.executeBatch()) updated = addJdbcCount(updated, count);
                return map("noOfUpdates", updated, "rowCount", updated);
            }
            bindJdbcParameters(statement, p, "", "");
            boolean hasResult = statement.execute();
            if (!hasResult) { int updates = statement.getUpdateCount(); return map("noOfUpdates", updates, "rowCount", updates); }
            try (ResultSet result = statement.getResultSet()) {
                ResultSetMetaData metadata = result.getMetaData(); int columns = metadata.getColumnCount();
                int maximum = integer(p, "maxRows", 0), offset = integer(p, "rowOffset", 0);
                int subset = integer(p, "subsetSize", 0);
                int remaining = maximum == 0 ? Integer.MAX_VALUE : Math.max(0, maximum - offset);
                int limit = subset == 0 ? remaining : Math.min(remaining, subset);
                List<Object> rows = new ArrayList<>(), columnOutput = new ArrayList<>();
                for (int index = 1; index <= columns; index++) columnOutput.add(map("name", metadata.getColumnLabel(index), "dataType", metadata.getColumnTypeName(index)));
                if (limit > 0) {
                    for (int index = 0; index < offset && result.next(); index++) { /* advance to requested page */ }
                }
                while (rows.size() < limit && result.next()) {
                    Map<String, Object> row = new LinkedHashMap<>();
                    for (int index = 1; index <= columns; index++) row.put(metadata.getColumnLabel(index), sqlValue(result.getObject(index)));
                    rows.add(row);
                }
                boolean hasNext = subset > 0 && rows.size() == limit && limit < remaining && result.next();
                return map("resultSet", map("Record", rows), "rows", rows, "rowCount", rows.size(), "columns", columnOutput,
                        "lastSubset", !hasNext, "nextRowOffset", hasNext ? (long) offset + rows.size() : null);
            }
        }
    }

    private static int jdbcOutType(String type) throws SQLException {
        switch (type.toLowerCase(Locale.ROOT)) {
            case "integer": return Types.INTEGER;
            case "long": return Types.BIGINT;
            case "number": case "double": case "float": return Types.DOUBLE;
            case "decimal": return Types.DECIMAL;
            case "boolean": return Types.BOOLEAN;
            case "binary": return Types.VARBINARY;
            case "date": return Types.DATE;
            case "time": return Types.TIME;
            case "timestamp": case "datetime": return Types.TIMESTAMP;
            case "string": case "json": return Types.VARCHAR;
            default: throw new SQLException("Unsupported JDBC OUT parameter type: " + type);
        }
    }

    private static Map<String, Object> jdbcCall(Connection connection, Properties p, String sql) throws SQLException {
        try (CallableStatement statement = connection.prepareCall(sql)) {
            int count = integer(p, "parameterCount", 0), timeout = integer(p, "queryTimeoutSeconds", 0);
            if (timeout > 0) statement.setQueryTimeout(timeout);
            int maximum = integer(p, "maxRows", 0);
            if (maximum > 0) statement.setMaxRows(maximum);
            for (int index = 0; index < count; index++) {
                String key = "parameter." + index, direction = p.getProperty(key + ".direction", "IN");
                if (!direction.equals("IN")) statement.registerOutParameter(index + 1, jdbcOutType(p.getProperty(key + ".declaredType", "string")));
                if (!direction.equals("OUT")) setParameter(statement, index + 1, p.getProperty(key + ".type", "string"), p.getProperty(key + ".value"));
            }
            List<Object> sets = new ArrayList<>();
            boolean hasResult = statement.execute();
            while (true) {
                if (hasResult) {
                    try (ResultSet result = statement.getResultSet()) {
                        List<Object> rows = new ArrayList<>(); ResultSetMetaData metadata = result.getMetaData();
                        while ((maximum == 0 || rows.size() < maximum) && result.next()) {
                            Map<String,Object> row = new LinkedHashMap<>();
                            for (int col = 1; col <= metadata.getColumnCount(); col++) row.put(metadata.getColumnLabel(col), sqlValue(result.getObject(col)));
                            rows.add(row);
                        }
                        sets.add(rows);
                    }
                } else if (statement.getUpdateCount() == -1) break;
                hasResult = statement.getMoreResults();
            }
            Map<String,Object> output = new LinkedHashMap<>();
            for (int index = 0; index < count; index++) {
                String key = "parameter." + index;
                if (!p.getProperty(key + ".direction", "IN").equals("IN")) output.put(p.getProperty(key + ".name", "Parameter" + (index + 1)), sqlValue(statement.getObject(index + 1)));
            }
            return map("resultSets", sets, "outParameters", output, "UnresolvedResultSets", new ArrayList<>());
        }
    }

    private static void bindJdbcParameters(PreparedStatement statement, Properties p, String prefix, String rowPrefix) throws SQLException {
        int count = integer(p, prefix + "parameterCount", 0);
        for (int index = 0; index < count; index++) {
            String key = prefix + rowPrefix + "parameter." + index;
            setParameter(statement, index + 1, p.getProperty(key + ".type", "string"), p.getProperty(key + ".value"));
        }
    }

    private static long addJdbcCount(long total, int count) throws SQLException {
        if (count == Statement.EXECUTE_FAILED) throw new SQLException("JDBC batch statement failed");
        return total < 0 || count < 0 ? Statement.SUCCESS_NO_INFO : total + count;
    }

    private static void setParameter(PreparedStatement statement, int index, String type, String value) throws SQLException {
        if ("null".equals(type)) statement.setObject(index, null);
        else if ("boolean".equals(type)) statement.setBoolean(index, Boolean.parseBoolean(value));
        else if ("integer".equals(type) || "long".equals(type)) statement.setLong(index, Long.parseLong(value));
        else if (Set.of("number", "decimal", "double", "float").contains(type)) statement.setBigDecimal(index, new java.math.BigDecimal(value));
        else if ("date".equals(type)) statement.setDate(index, java.sql.Date.valueOf(value));
        else if ("time".equals(type)) statement.setTime(index, java.sql.Time.valueOf(value));
        else if ("timestamp".equals(type) || "datetime".equals(type)) statement.setTimestamp(index, java.sql.Timestamp.valueOf(value.replace('T', ' ')));
        else if ("binary".equals(type)) statement.setBytes(index, Base64.getDecoder().decode(value));
        else statement.setString(index, value == null ? "" : value);
    }

    private static Object sqlValue(Object value) {
        if (value == null || value instanceof Number || value instanceof Boolean || value instanceof String) return value;
        if (value instanceof byte[]) return Base64.getEncoder().encodeToString((byte[]) value);
        if (value instanceof java.util.Date || value instanceof TemporalAccessor) return value.toString();
        if (value instanceof Clob) try { Clob clob = (Clob) value; return clob.getSubString(1, Math.toIntExact(clob.length())); } catch (SQLException ignored) {}
        return String.valueOf(value);
    }

    private static Object invoke(Object target, String name, Object... args) throws Exception {
        Method selected = null;
        for (Method method : target.getClass().getMethods()) {
            if (!compatible(method, name, args)) continue;
            selected = method;
            break;
        }
        if (selected == null) throw new NoSuchMethodException(target.getClass().getName() + "." + name + "/" + args.length);
        // Several JMS providers, including EMS, return package-private
        // implementation classes such as TibjmsxSessionImp. A public method on
        // that class is still inaccessible to callers in another package. Use
        // the equivalent method declared by its public JMS interface instead.
        Method callable = publicContractMethod(target.getClass(), name, args);
        if (callable != null) return callable.invoke(target, args);
        if (!selected.canAccess(target) && !selected.trySetAccessible()) {
            throw new IllegalAccessException("Cannot access " + selected + " through " + target.getClass().getName());
        }
        return selected.invoke(target, args);
    }

    private static String optionalString(Object target, String method) {
        if (target == null) return "";
        try {
            Object value = invoke(target, method);
            return value == null ? "" : String.valueOf(value);
        } catch (Exception ignored) {
            return "";
        }
    }

    private static String optionalStaticString(Class<?> target, String method) {
        try {
            Object value = target.getMethod(method).invoke(null);
            return value == null ? "" : String.valueOf(value);
        } catch (Exception ignored) {
            return "";
        }
    }

    private static Method publicContractMethod(Class<?> type, String name, Object[] args) {
        Set<Class<?>> visited = new HashSet<>();
        Deque<Class<?>> contracts = new ArrayDeque<>();
        Class<?> current = type;
        while (current != null) {
            contracts.addAll(Arrays.asList(current.getInterfaces()));
            current = current.getSuperclass();
        }
        while (!contracts.isEmpty()) {
            Class<?> contract = contracts.removeFirst();
            if (!visited.add(contract)) continue;
            contracts.addAll(Arrays.asList(contract.getInterfaces()));
            if (!Modifier.isPublic(contract.getModifiers())) continue;
            for (Method method : contract.getMethods()) if (compatible(method, name, args)) return method;
        }
        return null;
    }

    private static boolean compatible(Method method, String name, Object[] args) {
        if (!method.getName().equals(name) || method.getParameterCount() != args.length) return false;
        Class<?>[] types = method.getParameterTypes();
        for (int index = 0; index < args.length; index++) {
            if (args[index] != null && !wrap(types[index]).isAssignableFrom(wrap(args[index].getClass()))) return false;
        }
        return true;
    }

    private static Class<?> wrap(Class<?> type) {
        if (!type.isPrimitive()) return type;
        if (type == int.class) return Integer.class; if (type == long.class) return Long.class; if (type == boolean.class) return Boolean.class;
        if (type == double.class) return Double.class; if (type == float.class) return Float.class; if (type == short.class) return Short.class;
        if (type == byte.class) return Byte.class; if (type == char.class) return Character.class; return type;
    }

    private static void close(Object target) { if (target != null) try { invoke(target, "close"); } catch (Exception ignored) {} }
    private static void copyHeader(Map<String,Object> out, Object message, String key, String getter) { try { out.put(key, invoke(message, getter)); } catch (Exception ignored) {} }
    private static void setIfPresent(Object target, String method, Properties p, String key) throws Exception { if (!p.getProperty(key, "").isBlank()) invoke(target, method, p.getProperty(key)); }
    private static String required(Properties p, String key) { String value = p.getProperty(key, "").trim(); if (value.isEmpty()) throw new IllegalArgumentException(key + " is required"); return value; }
    private static boolean bool(Properties p, String key, boolean fallback) { String value = p.getProperty(key); return value == null || value.isBlank() ? fallback : Set.of("true", "1", "yes", "on").contains(value.toLowerCase(Locale.ROOT)); }
    private static int integer(Properties p, String key, int fallback) { try { return Integer.parseInt(p.getProperty(key, String.valueOf(fallback))); } catch (NumberFormatException ignored) { return fallback; } }
    private static long number(Properties p, String key, long fallback) { try { return Long.parseLong(p.getProperty(key, String.valueOf(fallback))); } catch (NumberFormatException ignored) { return fallback; } }
    private static String emptyToNull(String value) { return value == null || value.isBlank() ? null : value; }
    private static void put(Map<String,String> target, String key, String value) { if (value != null && !value.isBlank()) target.put(key, value); }
    private static void put(Properties target, String key, String value) { if (value != null && !value.isBlank()) target.setProperty(key, value); }
    private static Map<String,Object> map(Object... values) { Map<String,Object> result = new LinkedHashMap<>(); for (int i=0; i<values.length; i+=2) result.put(String.valueOf(values[i]), values[i+1]); return result; }

    private static String json(Object value) {
        if (value == null) return "null";
        if (value instanceof Boolean || value instanceof Number) return String.valueOf(value);
        if (value instanceof Map<?,?>) { StringJoiner join = new StringJoiner(",", "{", "}"); for (Map.Entry<?,?> entry : ((Map<?,?>) value).entrySet()) join.add(json(String.valueOf(entry.getKey())) + ":" + json(entry.getValue())); return join.toString(); }
        if (value instanceof Iterable<?>) { StringJoiner join = new StringJoiner(",", "[", "]"); for (Object item : (Iterable<?>) value) join.add(json(item)); return join.toString(); }
        String text = String.valueOf(value); StringBuilder out = new StringBuilder("\"");
        for (char ch : text.toCharArray()) { if (ch == '\\' || ch == '"') out.append('\\').append(ch); else if (ch == '\n') out.append("\\n"); else if (ch == '\r') out.append("\\r"); else if (ch == '\t') out.append("\\t"); else if (ch < 32) out.append(String.format("\\u%04x", (int) ch)); else out.append(ch); }
        return out.append('"').toString();
    }
}
