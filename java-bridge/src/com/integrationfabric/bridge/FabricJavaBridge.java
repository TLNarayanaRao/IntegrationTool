package com.integrationfabric.bridge;

import java.io.*;
import java.lang.reflect.*;
import java.nio.charset.StandardCharsets;
import java.sql.*;
import java.time.temporal.TemporalAccessor;
import java.util.*;
import javax.naming.Context;
import javax.naming.InitialContext;

/** Vendor-neutral process bridge for licensed JMS providers and JDBC drivers. */
public final class FabricJavaBridge {
    private FabricJavaBridge() {}

    public static void main(String[] args) {
        Map<String, Object> output = new LinkedHashMap<>();
        try {
            if (args.length != 1) throw new IllegalArgumentException("A bridge properties file is required");
            Properties p = new Properties();
            try (Reader reader = new InputStreamReader(new FileInputStream(args[0]), StandardCharsets.UTF_8)) { p.load(reader); }
            String command = required(p, "command");
            if (command.startsWith("jms.")) output = jms(command.substring(4), p);
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
