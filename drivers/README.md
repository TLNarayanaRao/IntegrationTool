# Local vendor drivers

This directory is the source-development fallback for licensed connector libraries. JAR files are ignored by Git and are not included automatically in desktop installers.

Place files as follows:

```text
drivers/jms/tibjms.jar
drivers/jms/jakarta.jms-api-2.0.3.jar
drivers/jdbc/sqlserver/mssql-jdbc-<version>.jre11.jar
drivers/jdbc/oracle/ojdbc11.jar
```

Installed desktop applications use `C:\ProgramData\Integration Fabric Studio\drivers` by default. See `docs/VENDOR_DRIVERS.md`.
