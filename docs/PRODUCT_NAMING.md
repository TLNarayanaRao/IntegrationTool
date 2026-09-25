# MINA product naming

MINA-owned UI labels, samples and documentation use MINA branding and neutral
connector names such as EMS and JMS. Third-party product comparisons are not
part of the product reference.

Provider-owned Java class names, imported XML namespace identifiers and licensed
dependency notices are compatibility or legal information, not product branding.
Do not rename, encode or conceal those identifiers in executable configuration.
The runtime still needs the exact values supplied by the provider. Existing user
projects, credentials, installation directories and diagnostic logs are not
rewritten by a branding update.

New Linux setup defaults to `/opt/mina`. Existing installations must continue to
set `FABRIC_ROOT` and `FABRIC_AGENT_ROOT` to their actual directories and preserve
their deployed INI paths; changing an example does not migrate files on disk.

New Snowflake faults use the `MINA-SNOWFLAKE_DATABASE_JDBC-` prefix, retaining the
numeric suffix. Update external alert rules that match the complete old error
code; the common `SNOWFLAKE_DATABASE_JDBC` fault type is unchanged.

Run `python scripts/check-product-naming.py` to check maintained product sources
and bundled documentation. It permits only the explicit runtime compatibility
identifiers listed in the checker. Dependencies, customer data, generated build
directories, historical logs and old distributables are deliberately excluded.
Regenerate the web guide and PDF and rebuild the frontend and installer after
changing user-facing product text.
