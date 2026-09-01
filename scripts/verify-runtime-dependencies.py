"""Fail a desktop build before PyInstaller when a connector is incomplete."""
from __future__ import annotations

import importlib
import sys


REQUIRED_MODULES = {
    "FastAPI": "fastapi",
    "HTTP client": "httpx",
    "SFTP": "paramiko",
    "Kafka": "confluent_kafka",
    "Kafka Avro": "fastavro",
    "GCP Pub/Sub": "google.cloud.pubsub_v1",
    "Snowflake": "snowflake.connector",
    "RabbitMQ AMQP 0.9.1": "pika",
    "AMQP 1.0": "proton",
    "Azure Service Bus": "azure.servicebus",
    "Azure identity": "azure.identity",
    "Excel XLSX": "openpyxl",
    "Excel XLS": "xlrd",
    "PostgreSQL": "psycopg",
    "MySQL/MariaDB": "pymysql",
    "Oracle": "oracledb",
    "ODBC/SQL Server": "pyodbc",
    "IBM Db2": "ibm_db_dbi",
    "Databricks SQL": "databricks.sql",
    "Databricks OAuth": "databricks.sdk",
}


failures: list[str] = []
for feature, module in REQUIRED_MODULES.items():
    try:
        importlib.import_module(module)
    except Exception as exc:  # native DLL loading errors matter too
        failures.append(f"{feature} ({module}): {type(exc).__name__}: {exc}")

if failures:
    print("Runtime dependency verification failed:", file=sys.stderr)
    for failure in failures:
        print(f"  - {failure}", file=sys.stderr)
    raise SystemExit(1)

print(f"Runtime dependency verification passed: {len(REQUIRED_MODULES)} connector modules")
