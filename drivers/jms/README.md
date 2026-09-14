# TIBCO EMS client libraries

Place the licensed TIBCO EMS/JMS client JARs in this directory, then restart the
Integration Studio local runtime.

The runtime loads every `*.jar` file in this directory into the shared TIBCO EMS
connector classpath. Do not rename the JARs and do not add their IDs to project
connections.

The default absolute directory is:

`C:\Users\ltangirala\OneDrive - PetSmart\Documents\PetSmart-Integration-Tool\java-runtime\lib\tibco-ems`

For a different machine-wide directory, set `TIBCO_EMS_JAR_PATH` before starting
the Java runtime. This is a platform setting and is not stored in projects.
