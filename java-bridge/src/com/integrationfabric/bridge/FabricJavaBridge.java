package com.integrationfabric.bridge;

import java.io.*;
import java.lang.reflect.*;
import java.nio.charset.StandardCharsets;
import java.sql.*;
import java.time.temporal.TemporalAccessor;
import java.util.*;
import javax.naming.Context;
import javax.naming.InitialContext;

/** Vendor-neutral process bridge for licensed SAP JCo, JMS providers, and JDBC drivers. */
public final class FabricJavaBridge {
    private FabricJavaBridge() {}

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
        String destinationName = p.getProperty("destinationName", "integration-fabric-sap");
        Properties destination = new Properties();
        for (String key : p.stringPropertyNames()) if (key.startsWith("jco.client.")) destination.setProperty(key, p.getProperty(key));
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
                setValue(function, "REQUTEXT", p.getProperty("requestText", "Integration Fabric connection test"));
                invoke(function, "execute", destinationObject);
                return map("message", "SAP JCo connection succeeded", "destination", destinationName);
            }
            if (operation.equals("call")) {
                String functionName = required(p, "functionName");
                Object function = function(destinationObject, functionName);
                for (String key : p.stringPropertyNames()) if (key.startsWith("argument.")) setValue(function, key.substring(9), p.getProperty(key));
                fillTables(function, p);
                if (functionName.equals("RFC_READ_TABLE")) fillReadTable(function, p);
                invoke(function, "execute", destinationObject);
                return functionResult(function);
            }
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

    private static Map<String, Object> functionResult(Object function) throws Exception {
        Map<String, Object> output = new LinkedHashMap<>();
        Object exports = invoke(function, "getExportParameterList");
        if (exports != null) output.put("exports", parameterValues(exports));
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

    /** Run a real JCo RFC server and emit one UTF-8 JSON event per inbound call. */
    private static Map<String, Object> listen(String serverName, Properties p) throws Exception {
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
        }
        Class<?> tidHandlerType = Class.forName("com.sap.conn.jco.server.JCoServerTIDHandler");
        Object tidHandler = tidHandler(p.getProperty("jco.server.tid_store"));
        serverType.getMethod("setTIDHandler", tidHandlerType).invoke(jcoServer, tidHandler);
        System.out.println(json(map("event", "jco_log", "level", "INFO", "phase", "tid_handler", "message", "SAP JCo TID handler installed", "tidStore", p.getProperty("jco.server.tid_store"))));
        System.out.flush();
        Class<?> handlerType = Class.forName("com.sap.conn.jco.server.JCoServerFunctionHandler");
        Object handler = Proxy.newProxyInstance(handlerType.getClassLoader(), new Class<?>[]{handlerType}, (proxy, method, args) -> {
            if (!method.getName().equals("handleRequest")) return null;
            Object function = args != null && args.length > 1 ? args[1] : null;
            if (function != null) {
                try {
                    String functionName = String.valueOf(invoke(function, "getName"));
                    Map<String, Object> event = map("event", "idoc", "functionName", functionName, "payload", listenerFunctionResult(function));
                    System.out.println(json(event));
                    System.out.flush();
                } catch (Throwable error) {
                    Throwable cause = error;
                    while (cause instanceof InvocationTargetException && ((InvocationTargetException) cause).getCause() != null) cause = ((InvocationTargetException) cause).getCause();
                    System.out.println(json(map("event", "jco_log", "level", "ERROR", "phase", "idoc_callback", "message", "SAP JCo IDoc callback could not be serialized", "errorType", cause.getClass().getName(), "error", String.valueOf(cause.getMessage() == null ? cause : cause.getMessage()))));
                    System.out.flush();
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
        synchronized (FabricJavaBridge.class) { FabricJavaBridge.class.wait(); }
        return map("message", "SAP JCo listener stopped");
    }

    /** Durable tRFC TID state prevents duplicate IDoc delivery after retries. */
    private static Object tidHandler(String fileName) throws Exception {
        Class<?> type = Class.forName("com.sap.conn.jco.server.JCoServerTIDHandler");
        File store = new File(fileName == null || fileName.isBlank() ? "sap-tids.properties" : fileName);
        File parent = store.getAbsoluteFile().getParentFile();
        if (parent != null) parent.mkdirs();
        Properties states = new Properties();
        if (store.isFile()) {
            try (InputStream input = new FileInputStream(store)) { states.load(input); }
            catch (IOException error) { System.err.println("SAP JCo TID store could not be loaded: " + error); }
        }
        Object lock = new Object();
        return Proxy.newProxyInstance(type.getClassLoader(), new Class<?>[]{type}, (proxy, method, args) -> {
            try {
                String tid = null;
                if (args != null) {
                    for (Object argument : args) {
                        if (argument instanceof String) { tid = (String) argument; break; }
                    }
                }
                if (tid == null || tid.isBlank()) return null;
                synchronized (lock) {
                    if (method.getName().equals("checkTID")) {
                        String state = states.getProperty(tid, "");
                        if ("COMMITTED".equals(state) || "CONFIRMED".equals(state)) return false;
                        states.setProperty(tid, "RECEIVED");
                        persistTidState(store, states);
                        return true;
                    }
                    if (method.getName().equals("commit")) states.setProperty(tid, "COMMITTED");
                    else if (method.getName().equals("rollback")) states.setProperty(tid, "ROLLED_BACK");
                    else if (method.getName().equals("confirmTID")) states.remove(tid);
                    else return null;
                    persistTidState(store, states);
                }
                return null;
            } catch (Throwable error) {
                Throwable cause = error;
                while (cause instanceof InvocationTargetException && cause.getCause() != null) cause = cause.getCause();
                // JCo calls this interface through a Java Proxy. Never throw from
                // the callback: a checked exception becomes UndeclaredThrowableException
                // and SAP records the inbound IDoc as a TID fault. Keep delivery alive
                // and log the real cause for diagnostics.
                System.err.println("SAP JCo TID handler failed in " + method.getName() + ": " + cause);
                if (method.getName().equals("checkTID")) return true;
                return null;
            }
        });
    }

    private static void persistTidState(File store, Properties states) {
        File temporary = new File(store.getPath() + ".tmp");
        try (OutputStream output = new FileOutputStream(temporary)) {
            states.store(output, "Integration Fabric SAP JCo tRFC transaction state");
            if (store.exists() && !store.delete()) throw new IOException("Unable to replace SAP TID store " + store);
            if (!temporary.renameTo(store)) throw new IOException("Unable to commit SAP TID store " + store);
        } catch (IOException error) {
            // Persistence failure must not escape the JCo callback. The callback
            // logs the problem and keeps the SAP transaction callable.
            System.err.println("Unable to persist SAP TID state at " + store + ": " + error);
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
        List<Object> rows = new ArrayList<>();
        int count = ((Number) invoke(table, "getNumRows")).intValue();
        Object metadata = invoke(table, "getMetaData");
        int fields = ((Number) invoke(metadata, "getFieldCount")).intValue();
        for (int row = 0; row < count; row++) {
            invoke(table, "setRow", row);
            Map<String, Object> item = new LinkedHashMap<>();
            for (int field = 0; field < fields; field++) {
                String name = String.valueOf(invoke(metadata, "getName", field));
                item.put(name, jsonValue(invoke(table, "getValue", name)));
            }
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
            put(environment, Context.INITIAL_CONTEXT_FACTORY, p.getProperty("jndiContextFactory"));
            put(environment, Context.PROVIDER_URL, p.getProperty("jndiProviderUrl"));
            put(environment, Context.SECURITY_PRINCIPAL, p.getProperty("jndiUsername"));
            put(environment, Context.SECURITY_CREDENTIALS, p.getProperty("jndiPassword"));
            context = new InitialContext(environment);
            factory = context.lookup(required(p, "connectionFactory"));
        } else {
            String factoryClass = p.getProperty("connectionFactoryClass", "com.tibco.tibjms.TibjmsConnectionFactory");
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
            connection = invoke(factory, "createConnection", username, password);
            if (!p.getProperty("clientId", "").isBlank()) invoke(connection, "setClientID", p.getProperty("clientId"));
            invoke(connection, "start");
            if (operation.equals("test")) return map("message", "Native JMS connection succeeded");
            session = invoke(connection, "createSession", false, 1); // Session.AUTO_ACKNOWLEDGE
            String destinationName = required(p, "destination");
            Object destination;
            if (context != null && bool(p, "jndiDestination", false)) destination = context.lookup(destinationName);
            else destination = invoke(session, bool(p, "topic", false) ? "createTopic" : "createQueue", destinationName);
            if (operation.equals("send")) {
                Object producer = invoke(session, "createProducer", destination);
                try {
                    Object message = invoke(session, "createTextMessage", p.getProperty("body", ""));
                    setIfPresent(message, "setJMSCorrelationID", p, "correlationId");
                    setIfPresent(message, "setJMSType", p, "messageType");
                    for (String name : p.stringPropertyNames()) if (name.startsWith("messageProperty.")) invoke(message, "setStringProperty", name.substring(16), p.getProperty(name));
                    invoke(producer, "setDeliveryMode", bool(p, "persistent", true) ? 2 : 1);
                    invoke(producer, "setPriority", integer(p, "priority", 4));
                    invoke(producer, "setTimeToLive", number(p, "expiration", 0));
                    invoke(producer, "send", message);
                    return map("messageId", invoke(message, "getJMSMessageID"), "destination", destinationName, "published", true);
                } finally { close(producer); }
            }
            if (operation.equals("receive")) {
                Object consumer = p.getProperty("selector", "").isBlank() ? invoke(session, "createConsumer", destination) : invoke(session, "createConsumer", destination, p.getProperty("selector"));
                try {
                    Object message = invoke(consumer, "receive", number(p, "timeoutMs", 30000));
                    if (message == null) return map("received", false, "body", null, "headers", Map.of(), "properties", Map.of());
                    Object body;
                    try { body = invoke(message, "getText"); } catch (Exception ignored) { body = String.valueOf(message); }
                    Map<String, Object> headers = new LinkedHashMap<>();
                    copyHeader(headers, message, "JMSMessageID", "getJMSMessageID"); copyHeader(headers, message, "JMSCorrelationID", "getJMSCorrelationID");
                    copyHeader(headers, message, "JMSType", "getJMSType"); copyHeader(headers, message, "JMSTimestamp", "getJMSTimestamp");
                    copyHeader(headers, message, "JMSPriority", "getJMSPriority"); copyHeader(headers, message, "JMSRedelivered", "getJMSRedelivered");
                    Map<String, Object> properties = new LinkedHashMap<>();
                    Enumeration<?> names = (Enumeration<?>) invoke(message, "getPropertyNames");
                    while (names.hasMoreElements()) { String name = String.valueOf(names.nextElement()); properties.put(name, invoke(message, "getObjectProperty", name)); }
                    if (bool(p, "clientAcknowledge", false)) invoke(message, "acknowledge");
                    return map("received", true, "body", body, "headers", headers, "properties", properties, "count", 1);
                } finally { close(consumer); }
            }
            throw new IllegalArgumentException("Unsupported JMS operation: " + operation);
        } finally {
            close(session); close(connection); if (context != null) context.close();
        }
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
            if (operation.equals("execute")) return jdbcExecute(connection, p);
            throw new IllegalArgumentException("Unsupported JDBC operation: " + operation);
        }
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
        try (PreparedStatement statement = connection.prepareStatement(sql)) {
            int timeout = integer(p, "queryTimeoutSeconds", 0); if (timeout > 0) statement.setQueryTimeout(timeout);
            int count = integer(p, "parameterCount", 0);
            for (int index = 0; index < count; index++) setParameter(statement, index + 1, p.getProperty("parameter." + index + ".type", "string"), p.getProperty("parameter." + index + ".value"));
            boolean hasResult = statement.execute();
            if (!hasResult) { int updates = statement.getUpdateCount(); return map("noOfUpdates", updates, "rowCount", updates); }
            try (ResultSet result = statement.getResultSet()) {
                ResultSetMetaData metadata = result.getMetaData(); int columns = metadata.getColumnCount();
                int maximum = integer(p, "maxRows", 0), seen = 0; List<Object> rows = new ArrayList<>(), columnOutput = new ArrayList<>();
                for (int index = 1; index <= columns; index++) columnOutput.add(map("name", metadata.getColumnLabel(index), "dataType", metadata.getColumnTypeName(index)));
                while (result.next() && (maximum <= 0 || seen < maximum)) {
                    Map<String, Object> row = new LinkedHashMap<>();
                    for (int index = 1; index <= columns; index++) row.put(metadata.getColumnLabel(index), sqlValue(result.getObject(index)));
                    rows.add(row); seen++;
                }
                return map("resultSet", map("Record", rows), "rows", rows, "rowCount", rows.size(), "columns", columnOutput, "lastSubset", true);
            }
        }
    }

    private static void setParameter(PreparedStatement statement, int index, String type, String value) throws SQLException {
        if ("null".equals(type)) statement.setObject(index, null);
        else if ("boolean".equals(type)) statement.setBoolean(index, Boolean.parseBoolean(value));
        else if ("integer".equals(type)) statement.setLong(index, Long.parseLong(value));
        else if ("number".equals(type) || "decimal".equals(type)) statement.setBigDecimal(index, new java.math.BigDecimal(value));
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
        // Several JMS providers, including TIBCO EMS, return package-private
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
