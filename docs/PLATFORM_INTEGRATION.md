# Shared recovery, event contracts, and cloud activities

## Shared message recovery

Select **PostgreSQL** as the **State backend** on Deduplicate Message,
Message Receipt, Replay Messages, and Aggregate Messages. Set
`MINA_MESSAGE_STATE_POSTGRES_DSN` on every replica that shares state. Put the
DSN in runtime secret injection. Use a dedicated database and allow the runtime
role to create and own the `mina_message_state` schema on first use.
Activities that cooperate must use the same **Message namespace**. Existing
activities continue using their SQLite files unless you change their backend.

Claims use the database clock and a transaction lock across replicas. Complete
the claim after downstream work succeeds, then acknowledge the broker.
Use stable idempotency keys for downstream writes that may be retried.

Run `python scripts/message-recovery.py list --backend postgresql --namespace orders`
to inspect failed and expired claims. Run the command with `requeue --key ORDER-123`
to make a specific key available again. The command returns metadata by default.
Use `--include-payload` when an authorized operator needs the stored payload.
Resubmit through the normal flow to obtain a fresh claim token.

## OpenTelemetry

Set `OTEL_SERVICE_NAME` and `OTEL_EXPORTER_OTLP_ENDPOINT` on the runtime to
send task and activity traces and duration metrics to an OTLP HTTP collector.
Use the signal-specific `OTEL_EXPORTER_OTLP_TRACES_ENDPOINT` and
`OTEL_EXPORTER_OTLP_METRICS_ENDPOINT` to override the paths.
`OTEL_TRACES_EXPORTER=console` writes local traces to stderr.

Runtime logs emitted within a span include its trace and span IDs. Kafka,
Pub/Sub, JMS/EMS, and AMQP adapters that expose message properties can pass
W3C trace headers. Explicit application headers take precedence. A batch
starts its own trace because its messages can have different parents.
Install the OpenTelemetry SDK and OTLP HTTP exporter in standalone Python
deployments where you enable telemetry.

## Event contracts

Open **Project → Event Contracts** in the ribbon. Load or paste an AsyncAPI
3.0 or 3.1 JSON/YAML document, select **Validate contract**, and review
send/receive operations, channel addresses, and message names.
**Export AsyncAPI** saves the reviewed document as JSON. Review covers MINA’s
supported operation and message model with local channel and message references.

Add **Validate AsyncAPI Message** before sending or after receiving a message.
Select the activity, then choose **Apply to selected activity** from the
reviewed contract, or set the contract and operation ID in Configuration. Specify the message name
if the operation declares several. The activity validates mapped payloads
against the selected JSON Schema and passes valid data through.
**Create CloudEvent** and **Parse CloudEvent** support structured CloudEvents
1.0 JSON. Map `source`, `type`, and optional metadata into the context
attributes, then map regular event data or binary data as Base64.

## AWS S3 and SQS

The **Cloud and Events** palette includes S3 list, read, and write operations.
They use the AWS SDK credential chain. To override the region, set **AWS region**.
Read and write default to 1 MiB and allow up to 16 MiB per object. Map the
continuation token to fetch the next list page. Use the Base64 fields for binary
objects and the conditional write option to create a key only if it is absent.

**SQS Receive Message** can start a task. **S3 Event Receiver** starts a task
from direct S3 bucket notifications delivered to SQS. Configure the bucket
notification and queue permissions in AWS. Attach **SQS Acknowledge Message**
on the successful path, with the same queue URL and the received receipt handle.
Set a visibility timeout longer than the expected job and use the queue’s
dead-letter policy for repeated failures.

## PostgreSQL change capture

Run [the database setup script](../scripts/postgres-cdc.sql) as the source
database owner and attach the trigger to authorized tables. It writes inserts,
updates, and deletes to a durable queue in the same transaction as the source
change. A rolled-back source transaction leaves no delivered change. The
trigger captures whole before/after rows. Use a distinct channel for each
consumer group.

Set `MINA_POSTGRES_CDC_DSN`. Start a task with **PostgreSQL Change Receiver**
for the channel. After downstream success, map its change ID and lease token
into **PostgreSQL Change Receipt**. Expired leases become available to other
workers. For strict ordering, use one consumer and handle retries on the
original change. This capture mode starts after trigger installation.
Initial snapshots and WAL-based capture are separate workflows.

## Saved flow tests and CI

Save a JSON suite alongside the Studio project in Git. Each case contains a
task ID, an input object, and an expected JSON output.

```text
python scripts/ci/test-project.py scripts/ci/fixtures/platform-flow.json scripts/ci/fixtures/platform-flow.mina-tests.json --environment qa
```

The runner executes each case against the Studio runtime and both generated
Python formats. Mismatches and failed executions return a nonzero exit code.
Set the EAR workflow’s `test_suite` and `test_environment` inputs to gate
packaging. Use synthetic data and isolated dependencies for tests that
perform writes or send messages.
