# MINA distribution compliance

Third-party notices do not change ownership or license terms of MINA or customer
applications. This directory is not a legal-clearance certificate.

## Build outputs

- `npm run build` preserves renderer licenses under `frontend/dist/legal`.
- `scripts/build-electron-sidecar.ps1` inventories the actual Python build
  environment, copies installed license/notice files, and downloads matching
  source distributions for LGPL/MPL libraries using PyPI SHA-256 verification.
- Each standalone runtime has `legal/THIRD_PARTY_NOTICES.txt`, license texts,
  source archives, a build-environment CycloneDX SBOM, and an artifact file SBOM.
- Studio completes resource edits and any configured signing, embeds the software
  inventory, and compiles NSIS. It then generates a complete payload hash SBOM
  alongside the installer, including NSIS's added elevation helper. Verification checks file hashes
  and refuses customer-supplied vendor driver binaries in release payloads.
- Direct and Engine Python exports include `legal/SBOM.cdx.json`, dependency
  installation instructions and bundled Swagger licenses. External dependencies
  are explicitly unresolved, not incorrectly reported as installed builder versions.

Keep the complete legal directory and any corresponding-source delivery alongside
the installer/application. Regenerate records for each build and target environment.
Do not replace upstream licenses with a generic license or strip copyright notices.

## Replacing LGPL/MPL libraries in frozen runtimes

Set `MINA_LIBRARY_PATH` to an absolute directory containing compatible replacement
libraries, then restart the runtime. For example, install a modified Paramiko
package in that directory with the same Python version/architecture as the runtime.
`MINARuntime.exe --mina-library-info` and `MINAWorker.exe --mina-library-info`
report module resolution. Only Paramiko, ldap3, psycopg, psycopg_binary, certifi
and saxonche can be replaced this way; application modules cannot be overridden.
The setting is controlled by the process owner, never an integration input.
No MINA notice restricts rights granted by those libraries' licenses, including
modification/replacement and reverse engineering for debugging such modifications.

## Vendor files and artwork

Licensed SAP/EMS/JMS native clients, JARs and license keys are customer-provided
prerequisites. Keep them in the configured external driver directory; do not add
them to Git or a distributable payload without verified redistribution rights.
Ignoring a path does not remove previously published copies from Git history.
Coordinate any history rewrite separately; never rewrite shared history casually.

The SOAP artwork attribution and Java icon license are preserved under
`third_party`. Brand names/logos do not imply endorsement. Confirm the applicable
brand guidelines and any necessary permissions for externally supplied artwork.

## Release review remains required

Technical checks establish the presence and integrity of notices and inventories.
They cannot grant absent permissions or certify patent/trademark clearance.
`RELEASE_REVIEW.json` records remaining rights/provenance checks. In particular,
verify exact SaxonC native-runtime notices/source access and full corresponding
JDK native/build source access: a JDK's `lib/src.zip` alone is not the full JDK
build source. The included OpenLogic version record identifies the build used.
These checks require a distribution-specific legal/source-access review before
public release. Do not represent a passing technical build as legal approval.

## Build and verify

From the repository root in PowerShell:

```powershell
./scripts/build-studio.ps1 -Target nsis
```

This builds Studio, extracts the resulting installer into a temporary directory,
checks the installed payload hashes, checks runtime notices/source material and
library replacement resolution, and starts the extracted runtime for an HTTP
health/legal-document smoke test. It does not install over an existing Studio.
Retain `frontend/release/MINAStudio-<version>-Payload-SBOM.cdx.json` alongside
`MINAStudio-<version>-Setup.exe`; the SBOM also records the installer SHA-256.

For public distribution, copy `release-review.example.json` into a separate
review record, supply real reviewer/evidence details, and use:

```powershell
./scripts/build-studio.ps1 -Target nsis -PublicRelease -ComplianceReview C:/reviews/mina-review.json
```

The example deliberately does not approve any item. Do not mark an item approved
without retaining the corresponding permissions, notices, or source-access evidence.
