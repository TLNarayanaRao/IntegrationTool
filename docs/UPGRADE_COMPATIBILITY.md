# MINA upgrade compatibility

New installations use MINA branding. The following legacy identifiers remain
supported as compatibility contracts; do not replace them in bulk renames.

- Control Plane and Python-agent settings accept `MINA_*` and previous `FABRIC_*`
  environment names. A nonblank MINA value wins; blank MINA values do not override
  an existing legacy credential. This includes the Control Plane data directory,
  API key, encryption key and runtime command. Keep the same encryption key and
  data directory when upgrading an existing installation.
- Studio imports and Control Plane uploads accept old archive manifest formats
  as well as MINA formats. New exports still use MINA names.
- Agents emit both names for managed application settings, including environment,
  enabled starters and the mounted secret file. Previously exported Python apps
  can therefore continue reading the original launch contract. Re-exporting is
  still necessary to receive fixes inside generated application code.
- Native connector lookup checks previous Windows/Linux driver locations as well
  as new locations. Existing Java/driver environment overrides remain accepted.
  Rebuild and deploy the matching Java bridge with a runtime upgrade; path
  compatibility does not make old compiled bridge classes interchangeable.

Before upgrading Linux, back up the Control Plane data directory and preserve its
encryption key securely. Deploy the updated Administrator and agent together.
Verify unauthenticated API requests receive 401 when a key is configured, then
check team access, package import, secret resolution and starter stop/start.
Never paste real credentials into diagnostic output.

Pick First remains explicitly rejected in the engine as documented in GROUPS.md.
It must not silently select a branch and claim event-race/cancellation support.

Regenerate bundled help after source changes with `npm run docs:build`; then
`npm run docs:check` verifies source fingerprints and both PDF outputs.
