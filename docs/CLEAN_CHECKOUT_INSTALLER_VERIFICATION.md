# Clean-checkout Windows installer verification

Verified on 2026-11-12 in a separate directory containing spaces, on the same Windows x64 machine.

## Source and isolation

- Source commit: `7b78258be3c848e1e5acb3ce35fd99220d8a9e3c`.
- Verification snapshot: `a6d099bac7f168a7aef5228bc0155bb68351b6de` in an isolated temporary Git repository. This snapshot contains the build fixes listed below on top of the source commit; it does not modify the original branch or create a commit there.
- The verification checkout began with clean Git status.
- No `node_modules`, Python virtual environments, generated Java runtime, license-source cache, or prior release output was copied from the original workspace.
- Fresh installs may use normal npm/pip/download caches. This was not an offline build or a bit-for-bit reproducibility test.

## Commands and prerequisites

From a fresh clone of the source and fixes, with Node.js, Python 3.11 x64 and a complete OpenJDK 17+ installed:

```powershell
Set-Location frontend
npm.cmd ci --include=dev
npm.cmd run desktop:installer
```

Tested with Node.js 24.20.0, npm 11.19.0, Python 3.11.9, Electron 44.10.2, electron-builder 26.18.0 and OpenLogic OpenJDK 17.0.16+8. The build resolves the locally installed JDK through `MINA_JAVA_HOME`, `JAVA_HOME` or PATH; its path is not copied into Git configuration. Use `MINA_BUILD_PYTHON` when the Python 3.11 launcher is unavailable. Internet access is needed for dependencies and build/source downloads.

## Results

- Fresh `npm ci`: passed, zero audit vulnerabilities reported.
- Documentation fingerprints, production frontend build, referenced frontend assets: passed.
- Java bridge compilation and bundled runtime creation: passed.
- Fresh isolated Python environment, connector imports and compliance generation: passed.
- Both PyInstaller runtimes and NSIS installer creation: passed.
- Final payload/installer inventory: 9,157 file-hash entries verified.
- Extracted runtime inventories: 4,712 and 4,347 file hashes verified.
- Extracted installer notices, source material and recipient library replacement checks: passed.
- Both extracted Java runtimes launched successfully; Java bridge class files were present.
- Extracted runtime health endpoint, designer HTML, JavaScript/CSS and legal endpoints: passed.
- All 12 compliance/portability regression tests passed in the clean checkout's newly installed environment.

Installer: `frontend/release/clean-checkout/MINAStudio-1.0.3-Setup.exe`

Installer SHA-256: `e959490e95e1d172009f590637bd0ff53fce9a97db8b63bf5e2098b55c3dfe1b`

SBOM: `frontend/release/clean-checkout/MINAStudio-1.0.3-Payload-SBOM.cdx.json`

Detailed logs and machine-readable verification record remain under ignored `tmp/clean-installer-20261112/`.

## Portability fix found during verification

The first clean build exposed Windows' path limit after Electron staging: the legal bundle repeated long Python `.dist-info` directory names inside both runtime trees. The generator now assigns short deterministic notice filenames, preserves all notice bytes, records the original installed filename and checksum in `COMPONENTS.json`, and removes obsolete generated component notice layouts on retries. No manual deletion of license bundles is required.

Additional checks now reject a healthy backend with missing designer assets and verify the delivered Java bridge/runtime. See `scripts/build-compliance.py`, `scripts/smoke-test-packaged-runtime.py`, `scripts/verify-studio-installer.py`, `backend/tests/test_jdk_build_compliance.py` and `backend/tests/test_installer_portability.py`.

## Verification limits

This verifies a relocated clean workspace on this host, not a separate physical Windows machine. The installer was extracted and tested without installing over the existing Studio or modifying Windows registration. No code-signing certificate was configured; this installer is unsigned. Public-redistribution rights review remains a separate gate. Generated releases, caches and temporary environments remain excluded from Git.
