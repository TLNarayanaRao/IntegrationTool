# Actual EMS throughput qualification

Status on 2026-11-16: **blocked before broker provisioning; no actual EMS test executed**.

The requested acceptance test is 100,000 fully audited records within 600 seconds
through complete flows in Run, Debug, direct Python archive and engine Python
archive modes, followed by a ten-minute lifecycle soak. Existing Artemis JMS
measurements do not establish EMS performance or EMS provider compatibility.

## Missing environment prerequisites

Read-only checks of the installed integration software, software/download folders,
JMS driver folder and Windows installed-product records found no EMS server,
EMS installer or `tibjms.jar`. The installed integration designer is not an EMS
server installation. No broker was launched, and no existing broker was changed.

Provisioning requires a supported EMS server distribution and its matching Java
provider libraries, plus activation if that release requires it. Keep activation
files and credentials outside Git. The [official download FAQ](https://www.tibco.com/downloads/faq)
describes account entitlement requirements. Current server releases document
[activation configuration](https://docs.tibco.com/pub/ems/10.5.1/doc/html/users-guide/license.htm).
No account access or downloadable server distribution was supplied for this test.

## Qualification procedure once the distribution is available

1. Install/extract the server into a temporary test location. Use a separate
   configuration, loopback listener, fresh store directory and dedicated queues;
   do not reuse production queues or edit an existing server's configuration.
2. Point a private throughput profile's `connection.driverDirectory` at the
   matching provider libraries and set its EMS connection factory class to
   `com.tibco.tibjms.TibjmsConnectionFactory`. Supply the temporary listener URL
   and test credentials. Set `dedicatedTestResources` to `true` and supply four
   distinct dedicated queue names in `destinations` for four flow workers.
3. From the repository root, use the development Python environment with
   `backend` on `PYTHONPATH` and the compiled Java bridge configured. Run
   `scripts/flow-throughput.py --family ems` separately with `--mode run`,
   `--mode debug`, `--mode python-direct` and `--mode python-engine`.
   For each invocation pass `--config <private-profile.json> --records 100000
   --deadline 600 --workers 4 --output <mode-report.json>
   --diagnostics <private-mode-diagnostics.txt>`.
4. Run `scripts/activity-throughput.py --family ems --operation publish`
   with a private profile using one dedicated `destination`, plus
   `--records 2000 --batch-size 1000 --concurrency 8 --soak-seconds 600
   --cycle-interval 10 --minimum-soak-records 100000 --output <soak-report.json>`.
5. Inspect successful send confirmations, full-payload readback, unique sequence
   audits, deadlines and process/connection cleanup. Record failures as failures;
   exclude records completed after the soak window from the throughput gate.
6. Stop only the temporary server and remove only its test resources. Retain
   sanitized reports and the server/provider versions with the qualification.

These commands describe the existing harness entry points; they have **not** been
qualified against an actual EMS provider in this environment. Studio interaction,
Run, Debug, both archive modes and the EMS soak remain unverified. No MINA code
change or EMS-specific performance fix is justified by the missing-environment
result alone.

The machine-readable status is
[`validation/ems-actual-status-2026-11-16.json`](validation/ems-actual-status-2026-11-16.json).
