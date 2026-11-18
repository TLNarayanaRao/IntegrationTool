# MINA product naming

MINA-owned UI labels, samples and documentation use MINA branding and neutral
connector names such as EMS and JMS. Third-party product comparisons are not
part of the product reference.

MINA does not ship provider-specific Java factory defaults or hard-coded
legacy XML namespace hosts. Imports recognize supported XML vocabulary shapes
from declarations supplied in the input file. MINA preserves namespaces in
user-supplied XML and stylesheets because namespace identifiers are part of
the document contract. Namespace matching does not contact the named host.

For a native EMS or JMS driver, enter the provider's fully qualified
connection factory class for Direct mode or its initial context factory class
and lookup name for JNDI mode. Existing connections that previously relied
on a built-in default need the applicable class configured before use. Keep
third-party dependency notices intact.

New Linux setup defaults to `/opt/mina`. Existing installations must continue to
set `MINA_ROOT` and `MINA_AGENT_ROOT` to their actual directories and preserve
their deployed INI paths; changing an example does not migrate files on disk.

New Snowflake faults use the `MINA-SNOWFLAKE_DATABASE_JDBC-` prefix, retaining the
numeric suffix. Update external alert rules that match the complete old error
code; the common `SNOWFLAKE_DATABASE_JDBC` fault type is unchanged.

Run `python scripts/check-product-naming.py` to check maintained product sources
and bundled documentation. The checker does not allow exceptions in maintained source files. It excludes
installed dependencies and user workspaces.
Regenerate the web guide and PDF and rebuild the frontend and installer after
changing user-facing product text.
