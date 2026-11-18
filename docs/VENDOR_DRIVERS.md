# Vendor driver installation

MINA Studio bundles its own minimal Java runtime and connector bridge. Vendor-licensed JARs are intentionally not distributed in the installer.

Vendor native client libraries (`.lib`, `.dll`, `.so`, `.dylib`) and license keys
are also external prerequisites. They are ignored by Git under `drivers/`, and
artifact verification rejects known SAP/EMS/JMS binaries in release payloads.
Keep local drivers in the configured driver folder; source cleanup must not
delete customer-owned local copies. See [distribution compliance](../compliance/README.md)
for release SBOMs, notices and remaining permission/source-access review.

The default machine-wide driver root on Windows is:

```text
C:\ProgramData\MINA Studio\drivers
```

Set `MINA_DRIVER_HOME` to override the complete root, or enter a **Driver JAR directory** in an individual shared connection. Source checkouts also search `D:\Integration-tool\MINA\drivers` as a development fallback.

## EMS / JMS

Place the provider's EMS client and the matching JMS API JAR in the
`jms` directory under the driver root. If the provider requires a separate
library for failover, install the matching version from the same distribution.

In Direct mode, set the server URL and the provider's fully qualified
connection factory class. In JNDI mode, set the provider URL, the initial
context factory class, and the connection factory lookup name. Supply
credentials if your provider requires them.

## Microsoft SQL Server

Download the Microsoft JDBC Driver for SQL Server and place the Java 11-compatible JAR in:

```text
C:\ProgramData\MINA Studio\drivers\jdbc\sqlserver\mssql-jdbc-<version>.jre11.jar
```

The driver class is `com.microsoft.sqlserver.jdbc.SQLServerDriver`. SQL Server Authentication is fully Java-based and does not need ODBC. Windows Integrated Authentication additionally requires Microsoft's architecture-matched authentication DLL; username/password authentication is the portable default.

## Oracle Database

Place the Oracle JDBC driver in:

```text
C:\ProgramData\MINA Studio\drivers\jdbc\oracle\ojdbc11.jar
```

Optional Oracle companion JARs such as `orai18n.jar`, `ucp.jar`, or Oracle PKI libraries can be put in the same directory when the selected Oracle features require them. The driver class is `oracle.jdbc.OracleDriver`. Thin JDBC mode does not require Oracle Instant Client.

## Build prerequisite

The installer build machine needs JDK 17 or newer because `desktop:installer` compiles the bridge and creates the bundled Java runtime. End-user machines do not need Java installed.

Build the bridge alone with:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\build-java-bridge.ps1
```

The connection-test response reports `loadedJars`, making it possible to verify exactly which vendor files were loaded.
