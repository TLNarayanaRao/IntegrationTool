from __future__ import annotations

import csv
import json
import re
import tempfile
import uuid
from pathlib import Path
from typing import Any


class SnowflakeAdapterError(RuntimeError):
    def __init__(self, message: str, code: str = "TIBCO-BW-PALETTE-SNOWFLAKE_DATABASE_JDBC-500009"):
        super().__init__(message)
        self.code = code


SNOWFLAKE_TO_XSD = {
    "NUMBER": "decimal", "DECIMAL": "decimal", "NUMERIC": "decimal",
    "INT": "integer", "INTEGER": "integer", "BIGINT": "integer", "SMALLINT": "integer",
    "DOUBLE": "double", "FLOAT": "double", "REAL": "double",
    "VARCHAR": "string", "CHAR": "string", "CHARACTER": "string", "STRING": "string", "TEXT": "string",
    "BINARY": "base64Binary", "VARBINARY": "base64Binary", "BOOLEAN": "boolean",
    "DATE": "date", "TIME": "time", "TIMESTAMP": "dateTime", "TIMESTAMP_LTZ": "dateTime",
    "TIMESTAMP_NTZ": "dateTime", "TIMESTAMP_TZ": "dateTime", "VARIANT": "anyType",
    "OBJECT": "anyType", "ARRAY": "anyType",
}


def _bool(value: Any) -> bool:
    return value is True or str(value).lower() in ("true", "1", "yes", "on")


def _identifier(value: str) -> str:
    parts = [part.strip() for part in str(value or "").split(".") if part.strip()]
    if not parts:
        raise SnowflakeAdapterError("A Snowflake table/entity is required")
    return ".".join(f'"{part.strip(chr(34)).replace(chr(34), chr(34) * 2)}"' for part in parts)


def _columns(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return [item.strip() for item in str(value or "").split(",") if item.strip()]


def _records(cfg: dict, payload: Any) -> list[dict]:
    value = cfg.get("values", cfg.get("records", cfg.get("data", payload)))
    if isinstance(value, dict) and "records" in value:
        value = value["records"]
    if value in (None, ""):
        return []
    if isinstance(value, list):
        return [item if isinstance(item, dict) else {"value": item} for item in value]
    return [value if isinstance(value, dict) else {"value": value}]


def _qualified_table(connection: dict, cfg: dict) -> str:
    table = cfg.get("tableName") or cfg.get("entity")
    database = cfg.get("overrideDatabaseName") or connection.get("database")
    schema = cfg.get("overrideSchemaName") or connection.get("schema")
    if table and "." in str(table):
        return _identifier(str(table))
    prefix = [item for item in (database, schema, table) if item]
    return _identifier(".".join(str(item) for item in prefix))


def _other_properties(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    result = {}
    for entry in str(value or "").split(";"):
        if "=" in entry:
            key, item = entry.split("=", 1)
            if key.strip():
                result[key.strip()] = item.strip()
    return result


def _private_key(config: dict):
    path = config.get("privateKeyFile")
    if not path:
        return None
    try:
        from cryptography.hazmat.primitives import serialization
    except ImportError as exc:
        raise SnowflakeAdapterError("Key Pair Authentication requires the optional cryptography package") from exc
    password = config.get("privateKeyPassphrase")
    key = serialization.load_pem_private_key(Path(path).read_bytes(), password=str(password).encode() if password else None)
    return key.private_bytes(serialization.Encoding.DER, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())


def _validate_connection(config: dict) -> None:
    if config.get("mode") == "mock":
        return
    account = str(config.get("account") or "").strip()
    if not account:
        raise SnowflakeAdapterError("Snowflake Account is required")
    if "_" in account:
        raise SnowflakeAdapterError("Snowflake Account must use hyphens, not underscores")
    minimum = int(config.get("minimumConnections") or 2)
    maximum = int(config.get("maximumConnections") or 8)
    if minimum < 0 or maximum < 1 or minimum > maximum:
        raise SnowflakeAdapterError("Connection pool requires 0 <= minimum connections <= maximum connections")
    if int(config.get("serviceThreads") or 8) < 1:
        raise SnowflakeAdapterError("Service Threads must be at least 1")


def connect(config: dict):
    _validate_connection(config)
    try:
        import snowflake.connector
    except ImportError as exc:
        raise SnowflakeAdapterError("External Snowflake connections require snowflake-connector-python", "TIBCO-BW-PALETTE-SNOWFLAKE_DATABASE_JDBC-500017") from exc
    authentication = str(config.get("authenticationType") or "Username/Password").lower()
    provider = str(config.get("provider") or "Snowflake")
    options: dict[str, Any] = {
        "account": config.get("account"), "user": config.get("username"),
        "warehouse": config.get("warehouse") or None, "database": config.get("database") or None,
        "schema": config.get("schema") or None, "role": config.get("role") or None,
        "login_timeout": int(config.get("loginTimeoutSeconds") or 60),
    }
    if authentication == "username/password":
        options["password"] = config.get("password")
    elif authentication.startswith("federated"):
        options["authenticator"] = config.get("oktaEndpointUrl") if provider.lower() == "okta" else "externalbrowser"
        options["password"] = config.get("oktaPassword") or config.get("password")
        options["user"] = config.get("oktaUsername") or config.get("username")
    elif authentication == "oauth":
        options["authenticator"] = "oauth"
        options["token"] = config.get("accessToken") or config.get("oauthToken")
        if not options["token"]:
            raise SnowflakeAdapterError("OAuth requires an access token; authorization-code exchange is performed outside the runtime")
    elif authentication.startswith("key pair"):
        options["private_key"] = _private_key(config)
    options.update(_other_properties(config.get("otherProperties")))
    options = {key: value for key, value in options.items() if value not in (None, "")}
    return snowflake.connector.connect(**options)


def test_connection(config: dict) -> dict:
    if config.get("mode") == "mock":
        return {"ok": True, "message": "Snowflake design-time mock connection is ready"}
    connection = connect(config)
    try:
        cursor = connection.cursor()
        cursor.execute("SELECT CURRENT_ACCOUNT(), CURRENT_WAREHOUSE(), CURRENT_DATABASE(), CURRENT_SCHEMA()")
        account, warehouse, database, schema = cursor.fetchone()
        return {"ok": True, "message": f"Snowflake connection succeeded: {account} · {warehouse or 'no warehouse'} · {database or 'no database'}.{schema or ''}"}
    finally:
        connection.close()


def list_entities(config: dict, database: str = "", schema: str = "", pattern: str = "") -> list[dict]:
    if config.get("mode") == "mock":
        items = config.get("mockEntities") or []
        return [item for item in items if not pattern or pattern.lower().replace("%", "") in str(item.get("name", "")).lower()]
    connection = connect(config)
    try:
        database = database or config.get("database")
        schema = schema or config.get("schema") or "PUBLIC"
        if not database:
            raise SnowflakeAdapterError("Entity retrieval requires a database")
        cursor = connection.cursor()
        cursor.execute(
            f'SELECT TABLE_CATALOG,TABLE_SCHEMA,TABLE_NAME,TABLE_TYPE FROM {_identifier(database)}.INFORMATION_SCHEMA.TABLES WHERE TABLE_SCHEMA=%s AND TABLE_NAME ILIKE %s ORDER BY TABLE_NAME',
            (schema, pattern or "%"),
        )
        return [{"database": row[0], "schema": row[1], "name": row[2], "entityType": row[3]} for row in cursor.fetchall()]
    finally:
        connection.close()


def entity_metadata(config: dict, database: str, schema: str, entity: str) -> dict:
    if config.get("mode") == "mock":
        found = next((item for item in config.get("mockEntities", []) if item.get("name") == entity), None)
        if not found:
            raise SnowflakeAdapterError(f"Mock Snowflake entity {entity!r} was not found")
        return found
    connection = connect(config)
    try:
        cursor = connection.cursor()
        cursor.execute(
            f'SELECT COLUMN_NAME,DATA_TYPE,IS_NULLABLE,NUMERIC_PRECISION,NUMERIC_SCALE,CHARACTER_MAXIMUM_LENGTH,ORDINAL_POSITION FROM {_identifier(database)}.INFORMATION_SCHEMA.COLUMNS WHERE TABLE_SCHEMA=%s AND TABLE_NAME=%s ORDER BY ORDINAL_POSITION',
            (schema, entity),
        )
        columns = []
        for name, data_type, nullable, precision, scale, length, position in cursor.fetchall():
            normalized = str(data_type).upper().split("(", 1)[0]
            xsd = "integer" if normalized in ("NUMBER", "DECIMAL", "NUMERIC") and scale in (None, 0) else SNOWFLAKE_TO_XSD.get(normalized, "string")
            columns.append({"name": name, "dataType": data_type, "xsdType": xsd, "notNull": nullable == "NO", "precision": precision, "scale": scale, "dimension": length, "ordinal": position, "primaryKey": False})
        try:
            cursor.execute(f"SHOW PRIMARY KEYS IN TABLE {_identifier(f'{database}.{schema}.{entity}')}")
            primary = {row[4] for row in cursor.fetchall()}
            for column in columns:
                column["primaryKey"] = column["name"] in primary
        except Exception:
            pass
        return {"database": database, "schema": schema, "name": entity, "entityType": "TABLE_OR_VIEW", "columns": columns}
    finally:
        connection.close()


def _mock_execute(operation: str, cfg: dict, records: list[dict]) -> dict:
    if operation == "query":
        rows = list(cfg.get("mockRows") or [])
        maximum = int(cfg.get("maximumRows") or 100)
        return {"rows": rows if maximum == 0 else rows[:maximum], "rowCount": len(rows if maximum == 0 else rows[:maximum])}
    if operation == "insert":
        failed = int(cfg.get("mockFailedRows") or 0)
        return {"rowsAttempted": len(records), "rowsAffected": max(0, len(records) - failed), "batchFailures": [] if not failed else [{"batch": 1, "reason": "Configured mock failure", "failedRows": failed}]}
    if operation in ("update", "delete"):
        return {"rowsAffected": int(cfg.get("mockRowsAffected", len(records) or 1))}
    if operation == "bulk_load":
        return {"loadResults": cfg.get("mockLoadResults") or [{"FILE": cfg.get("filePath") or "mock.csv", "STATUS": "LOADED", "ROWS_PARSED": len(records), "ROWS_LOADED": len(records), "ERROR_LIMIT": 0, "ERRORS_SEEN": 0, "FIRST_ERROR": None, "FIRST_ERROR_LINE": None, "FIRST_ERROR_CHARACTER": None, "FIRST_ERROR_COLUMN_NAME": None}]}
    raise SnowflakeAdapterError(f"Unsupported Snowflake operation {operation}")


def _create_table(cursor, table: str, cfg: dict):
    metadata = cfg.get("columns") or cfg.get("entityMetadata", {}).get("columns") or []
    if not metadata:
        raise SnowflakeAdapterError("Create Table from XSD requires resolved column metadata", "TIBCO-BW-PALETTE-SNOWFLAKE_DATABASE_JDBC-500022")
    fields = []
    xsd_to_snowflake = {"integer": "NUMBER", "decimal": "NUMBER", "double": "DOUBLE", "boolean": "BOOLEAN", "date": "DATE", "time": "TIME", "dateTime": "TIMESTAMP_TZ", "base64Binary": "BINARY", "anyType": "VARIANT", "string": "VARCHAR"}
    for column in metadata:
        data_type = column.get("dataType") or xsd_to_snowflake.get(column.get("xsdType"), "VARCHAR")
        fields.append(f'{_identifier(column["name"])} {data_type}{" NOT NULL" if column.get("notNull") else ""}')
    cursor.execute(f"CREATE TABLE IF NOT EXISTS {table} ({', '.join(fields)})")


def execute(connection_config: dict, cfg: dict, payload: Any) -> dict:
    operation = str(cfg.get("operation") or "query")
    records = _records(cfg, payload)
    if connection_config.get("mode") == "mock":
        return _mock_execute(operation, cfg, records)
    connection = connect(connection_config)
    try:
        cursor = connection.cursor()
        timeout = int(cfg.get("timeout") or cfg.get("queryTimeoutSeconds") or 0)
        if timeout > 0:
            cursor.execute(f"ALTER SESSION SET STATEMENT_TIMEOUT_IN_SECONDS={timeout}")
        table = _qualified_table(connection_config, cfg) if operation != "query" or cfg.get("entity") or cfg.get("tableName") else ""
        if _bool(cfg.get("createTableFromXsd")) or _bool(cfg.get("createTableIfNoneExists")):
            _create_table(cursor, table, cfg)
        if operation == "query":
            statement = str(cfg.get("statement") or cfg.get("sql") or (f"SELECT * FROM {table}" if table else ""))
            parameters = cfg.get("parameters") or []
            cursor.execute(statement.replace("?", "%s"), parameters)
            names = [item[0] for item in cursor.description or []]
            maximum = int(cfg.get("maximumRows") or 100)
            if maximum < 0:
                raise SnowflakeAdapterError("Maximum Rows cannot be negative", "TIBCO-BW-PALETTE-SNOWFLAKE_DATABASE_JDBC-500014")
            rows = cursor.fetchall() if maximum == 0 else cursor.fetchmany(maximum)
            return {"rows": [dict(zip(names, row)) for row in rows], "rowCount": len(rows)}
        if operation == "insert":
            if not records:
                return {"rowsAttempted": 0, "rowsAffected": 0, "batchFailures": []}
            columns = _columns(cfg.get("valueColumns")) or list(records[0])
            merge_columns = _columns(cfg.get("mergeOnColumns"))
            affected, failures, size = 0, [], max(1, int(cfg.get("batchSize") or 100))
            if _bool(cfg.get("merge")) and (size != 1 or not merge_columns):
                raise SnowflakeAdapterError("Insert Merge requires Batch Size 1 and Merge On Columns")
            for offset in range(0, len(records), size):
                batch = records[offset:offset + size]
                try:
                    if _bool(cfg.get("merge")):
                        source = batch[0]
                        on_clause = " AND ".join(f't.{_identifier(key)}=s.{_identifier(key)}' for key in merge_columns)
                        select = ",".join(f'%s AS {_identifier(key)}' for key in columns)
                        update = ",".join(f't.{_identifier(key)}=s.{_identifier(key)}' for key in columns if key not in merge_columns)
                        insert_names = ",".join(_identifier(key) for key in columns)
                        insert_values = ",".join(f's.{_identifier(key)}' for key in columns)
                        cursor.execute(f"MERGE INTO {table} t USING (SELECT {select}) s ON {on_clause} WHEN MATCHED THEN UPDATE SET {update} WHEN NOT MATCHED THEN INSERT ({insert_names}) VALUES ({insert_values})", [source.get(key) for key in columns])
                        affected += max(cursor.rowcount, 0)
                    else:
                        statement = f"INSERT INTO {table} ({','.join(_identifier(key) for key in columns)}) VALUES ({','.join(['%s'] * len(columns))})"
                        cursor.executemany(statement, [[None if _bool(cfg.get("interpretEmptyStringAsNull")) and row.get(key) == "" else row.get(key) for key in columns] for row in batch])
                        affected += max(cursor.rowcount, 0)
                except Exception as exc:
                    failures.append({"batch": offset // size + 1, "reason": str(exc), "failedRows": len(batch)})
                    if _bool(cfg.get("faultOnBatchFailure")):
                        raise
            connection.commit()
            return {"rowsAttempted": len(records), "rowsAffected": affected, "batchFailures": failures}
        if operation in ("update", "delete"):
            value_columns = _columns(cfg.get("valueColumns"))
            parameter_columns = _columns(cfg.get("parameterColumns"))
            inputs = records or [{}]
            affected = 0
            for record in inputs:
                if _bool(cfg.get("interpretEmptyStringAsNull")):
                    record = {key: None if value == "" else value for key, value in record.items()}
                where = " AND ".join(f'{_identifier(key)}=%s' for key in parameter_columns)
                if _bool(cfg.get("merge")):
                    merge_columns = _columns(cfg.get("mergeOnColumns")) or parameter_columns
                    if not merge_columns:
                        raise SnowflakeAdapterError("Merge requires Merge On Columns")
                    columns = list(dict.fromkeys(value_columns + parameter_columns)) or list(record)
                    select = ",".join(f'%s AS {_identifier(key)}' for key in columns)
                    on_clause = " AND ".join(f't.{_identifier(key)}=s.{_identifier(key)}' for key in merge_columns)
                    if operation == "update":
                        update_columns = [key for key in columns if key not in merge_columns]
                        if not update_columns:
                            raise SnowflakeAdapterError("Update Merge requires at least one value column")
                        update_clause = ",".join(f't.{_identifier(key)}=s.{_identifier(key)}' for key in update_columns)
                        insert_names = ",".join(_identifier(key) for key in columns)
                        insert_values = ",".join(f's.{_identifier(key)}' for key in columns)
                        statement = f"MERGE INTO {table} t USING (SELECT {select}) s ON {on_clause} WHEN MATCHED THEN UPDATE SET {update_clause} WHEN NOT MATCHED THEN INSERT ({insert_names}) VALUES ({insert_values})"
                    else:
                        statement = f"MERGE INTO {table} t USING (SELECT {select}) s ON {on_clause} WHEN MATCHED THEN DELETE"
                    values = [record.get(key) for key in columns]
                elif operation == "update":
                    if not value_columns:
                        value_columns = [key for key in record if key not in parameter_columns]
                    statement = f"UPDATE {table} SET {','.join(f'{_identifier(key)}=%s' for key in value_columns)}" + (f" WHERE {where}" if where else "")
                    values = [record.get(key) for key in value_columns + parameter_columns]
                else:
                    statement = f"DELETE FROM {table}" + (f" WHERE {where}" if where else "")
                    values = [record.get(key) for key in parameter_columns]
                cursor.execute(statement, values)
                affected += max(cursor.rowcount, 0)
            connection.commit()
            return {"rowsAffected": affected}
        if operation == "bulk_load":
            stage_type = str(cfg.get("stageType") or "UserStage")
            stage = "@~" if stage_type == "UserStage" else f"@%{table}" if stage_type == "TableStage" else f'@{cfg.get("namedStage")}'
            file_path = cfg.get("filePath")
            temporary = None
            if stage_type != "AmazonS3":
                if not file_path:
                    temporary = tempfile.NamedTemporaryFile("w", suffix=".csv", newline="", delete=False, encoding="utf-8")
                    columns = _columns(cfg.get("valueColumns")) or list(records[0] if records else {})
                    writer = csv.DictWriter(temporary, fieldnames=columns); writer.writeheader(); writer.writerows(records); temporary.close(); file_path = temporary.name
                cursor.execute(f"PUT 'file://{Path(file_path).resolve().as_posix()}' {stage} AUTO_COMPRESS={'TRUE' if _bool(cfg.get('compressData', True)) else 'FALSE'} OVERWRITE=TRUE")
            format_name = str(cfg.get("fileFormat") or "DelimitedFiles")
            format_sql = "TYPE=CSV SKIP_HEADER=1" if format_name == "DelimitedFiles" else f"TYPE={format_name}"
            on_error = str(cfg.get("onError") or "ABORT_STATEMENT")
            if on_error == "SKIP_FILE_<num>": on_error = f"SKIP_FILE_{int(cfg.get('skipFileErrorCount') or 1)}"
            if on_error == "SKIP_FILE_<num>%": on_error = f"SKIP_FILE_{float(cfg.get('skipFileErrorPercentage') or 1)}%"
            validation = " VALIDATION_MODE=RETURN_ERRORS" if _bool(cfg.get("validationMode")) else ""
            copy_target = table
            temporary_table = ""
            if _bool(cfg.get("merge")) and not validation:
                merge_columns = _columns(cfg.get("mergeOnColumns"))
                columns = _columns(cfg.get("valueColumns")) or [str(item.get("name")) for item in (cfg.get("entityMetadata", {}).get("columns") or []) if item.get("name")]
                if not merge_columns or not columns:
                    raise SnowflakeAdapterError("Bulk Load Merge requires Merge On Columns and resolved entity columns")
                temporary_table = _identifier(f"IF_BULK_{uuid.uuid4().hex[:12]}")
                cursor.execute(f"CREATE TEMP TABLE {temporary_table} LIKE {table}")
                copy_target = temporary_table
            cursor.execute(f"COPY INTO {copy_target} FROM {stage} FILE_FORMAT=({format_sql}) ON_ERROR='{on_error}' PURGE={'TRUE' if _bool(cfg.get('purgeStageFiles')) else 'FALSE'}{validation}")
            names = [item[0] for item in cursor.description or []]
            rows = [dict(zip(names, row)) for row in cursor.fetchall()] if cursor.description else []
            if temporary_table:
                on_clause = " AND ".join(f't.{_identifier(key)}=s.{_identifier(key)}' for key in merge_columns)
                update_columns = [key for key in columns if key not in merge_columns]
                if not update_columns:
                    raise SnowflakeAdapterError("Bulk Load Merge requires at least one non-key column")
                update_clause = ",".join(f't.{_identifier(key)}=s.{_identifier(key)}' for key in update_columns)
                insert_names = ",".join(_identifier(key) for key in columns)
                insert_values = ",".join(f's.{_identifier(key)}' for key in columns)
                cursor.execute(f"MERGE INTO {table} t USING {temporary_table} s ON {on_clause} WHEN MATCHED THEN UPDATE SET {update_clause} WHEN NOT MATCHED THEN INSERT ({insert_names}) VALUES ({insert_values})")
                cursor.execute(f"DROP TABLE {temporary_table}")
            connection.commit()
            if temporary:
                Path(temporary.name).unlink(missing_ok=True)
            return {"loadResults": rows}
        raise SnowflakeAdapterError(f"Unsupported Snowflake operation {operation}")
    except SnowflakeAdapterError:
        raise
    except Exception as exc:
        raise SnowflakeAdapterError(f"Snowflake {operation} failed: {exc}") from exc
    finally:
        connection.close()


snowflake_adapter = type("SnowflakeAdapter", (), {
    "test": staticmethod(test_connection), "list_entities": staticmethod(list_entities),
    "entity_metadata": staticmethod(entity_metadata), "execute": staticmethod(execute),
})()
