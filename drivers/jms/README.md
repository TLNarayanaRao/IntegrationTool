# EMS / JMS client libraries

Place your licensed, version-compatible JMS client JARs in this directory for
source development, then restart the MINA runtime. Do not rename driver JARs or
Java classes, and do not mix client-library versions.

Installed Windows runtimes use `C:\ProgramData\MINA Studio\drivers\jms`.
Linux runtimes use `/opt/mina/drivers/jms`. Set `FABRIC_DRIVER_HOME` to override
the driver root, or configure **Driver JAR directory** on a shared connection.

The runtime loads JARs into the connector classpath. See
[Vendor driver installation](../../docs/VENDOR_DRIVERS.md) for prerequisites.
