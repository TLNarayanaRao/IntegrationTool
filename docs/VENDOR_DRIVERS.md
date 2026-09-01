# Vendor driver installation

Integration Fabric Studio bundles its own minimal Java runtime and connector bridge. Vendor-licensed JARs are intentionally not distributed in the installer.

The default machine-wide driver root on Windows is:

```text
C:\ProgramData\Integration Fabric Studio\drivers
```

Set `FABRIC_DRIVER_HOME` to override the complete root, or enter a **Driver JAR directory** in an individual shared connection. Source checkouts also search `D:\Integration-tool\IntegrationFabric\drivers` as a development fallback.

## TIBCO EMS / JMS

Place the EMS client files in:

```text
C:\ProgramData\Integration Fabric Studio\drivers\jms\tibjms.jar
C:\ProgramData\Integration Fabric Studio\drivers\jms\jakarta.jms-api-2.0.3.jar
```

For older EMS releases, use the matching `jms-2.0.jar` supplied with that EMS installation. Add `tibjmsufo.jar` for unshared-state failover. Do not mix JARs from different EMS releases.

The default direct factory class is:

```text
com.tibco.tibjms.TibjmsConnectionFactory
```

Direct mode uses the EMS URL, username, and password. JNDI mode additionally uses the configured initial-context factory, provider URL, credentials, and connection-factory JNDI name.

## Microsoft SQL Server

Download the Microsoft JDBC Driver for SQL Server and place the Java 11-compatible JAR in:

```text
C:\ProgramData\Integration Fabric Studio\drivers\jdbc\sqlserver\mssql-jdbc-<version>.jre11.jar
```

The driver class is `com.microsoft.sqlserver.jdbc.SQLServerDriver`. SQL Server Authentication is fully Java-based and does not need ODBC. Windows Integrated Authentication additionally requires Microsoft's architecture-matched authentication DLL; username/password authentication is the portable default.

## Oracle Database

Place the Oracle JDBC driver in:

```text
C:\ProgramData\Integration Fabric Studio\drivers\jdbc\oracle\ojdbc11.jar
```

Optional Oracle companion JARs such as `orai18n.jar`, `ucp.jar`, or Oracle PKI libraries can be put in the same directory when the selected Oracle features require them. The driver class is `oracle.jdbc.OracleDriver`. Thin JDBC mode does not require Oracle Instant Client.

## Build prerequisite

The installer build machine needs JDK 17 or newer because `desktop:installer` compiles the bridge and creates the bundled Java runtime. End-user machines do not need Java installed.

Build the bridge alone with:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\build-java-bridge.ps1
```

The connection-test response reports `loadedJars`, making it possible to verify exactly which vendor files were loaded.
