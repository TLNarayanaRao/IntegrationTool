from __future__ import annotations

import re
import sqlite3
from pathlib import Path
from typing import Any


class JdbcAdapterError(RuntimeError):
    def __init__(self, message: str, fault_type: str = "JDBCSQLException"):
        super().__init__(message)
        self.fault_type = fault_type


def _sqlite_path(url: str) -> str:
    value = str(url or "integration.db")
    for prefix in ("jdbc:sqlite:", "sqlite:///"):
        if value.startswith(prefix):
            return value[len(prefix):]
    return value


def connect(config: dict):
    driver = str(config.get("driver") or "sqlite").lower()
    try:
        if driver == "sqlite":
            connection = sqlite3.connect(_sqlite_path(config.get("url")), timeout=float(config.get("timeoutSeconds") or 30))
            connection.row_factory = sqlite3.Row
            return connection
        if driver in ("postgresql", "postgres"):
            import psycopg
            return psycopg.connect(config.get("url") or "", user=config.get("username") or None, password=config.get("password") or None, connect_timeout=int(config.get("timeoutSeconds") or 30))
        if driver in ("mysql", "mariadb"):
            import pymysql
            return pymysql.connect(host=config.get("host") or "localhost", port=int(config.get("port") or 3306), user=config.get("username") or "", password=config.get("password") or "", database=config.get("database") or None, connect_timeout=int(config.get("timeoutSeconds") or 30))
        if driver in ("sqlserver", "mssql"):
            import pyodbc
            return pyodbc.connect(config.get("url") or config.get("connectionString") or "", timeout=int(config.get("timeoutSeconds") or 30))
        if driver == "oracle":
            import oracledb
            return oracledb.connect(user=config.get("username"), password=config.get("password"), dsn=config.get("url") or config.get("dsn"))
        if driver == "db2":
            import ibm_db_dbi
            return ibm_db_dbi.connect(config.get("url") or "", config.get("username") or "", config.get("password") or "")
        if driver == "snowflake":
            from .snowflake import connect as snowflake_connect
            return snowflake_connect(config)
    except ImportError as exc:
        raise JdbcAdapterError(f"The optional Python adapter for {driver} is not installed", "JDBCConnectionNotFoundException") from exc
    except Exception as exc:
        raise JdbcAdapterError(f"Unable to connect using {driver}: {exc}", "JDBCConnectionNotFoundException") from exc
    raise JdbcAdapterError(f"Unsupported JDBC driver {driver}", "JDBCConnectionNotFoundException")


def test_connection(config: dict) -> dict:
    connection = connect(config)
    try:
        cursor = connection.cursor()
        cursor.execute("SELECT 1")
        cursor.fetchone()
        return {"ok": True, "message": f"{str(config.get('driver') or 'sqlite').upper()} connection succeeded"}
    finally:
        connection.close()


def metadata(config: dict) -> dict:
    connection = connect(config)
    driver = str(config.get("driver") or "sqlite").lower()
    try:
        cursor = connection.cursor()
        tables: list[dict] = []
        if driver == "sqlite":
            cursor.execute("SELECT name, type FROM sqlite_master WHERE type IN ('table','view') AND name NOT LIKE 'sqlite_%' ORDER BY name")
            for name, kind in cursor.fetchall():
                escaped = str(name).replace(chr(34), chr(34) * 2)
                columns = []
                for row in connection.execute(f'PRAGMA table_info("{escaped}")').fetchall():
                    columns.append({"name": row[1], "dataType": row[2] or "TEXT", "notNull": bool(row[3]), "default": row[4], "primaryKey": bool(row[5])})
                tables.append({"schema": "main", "name": name, "type": kind.upper(), "columns": columns})
        else:
            schema = config.get("schema") or ("PUBLIC" if driver == "snowflake" else "public")
            cursor.execute("SELECT table_schema, table_name, table_type FROM information_schema.tables WHERE table_schema = %s ORDER BY table_name", (schema,))
            for table_schema, name, kind in cursor.fetchall():
                cursor.execute("SELECT column_name, data_type, is_nullable, ordinal_position FROM information_schema.columns WHERE table_schema=%s AND table_name=%s ORDER BY ordinal_position", (table_schema, name))
                columns = [{"name": row[0], "dataType": row[1], "notNull": str(row[2]).upper() == "NO", "ordinal": row[3]} for row in cursor.fetchall()]
                tables.append({"schema": table_schema, "name": name, "type": kind, "columns": columns})
        return {"driver": driver, "tables": tables}
    finally:
        connection.close()


def _parameters(config: dict) -> Any:
    value = config.get("parameters") or config.get("preparedParameters") or {}
    if isinstance(value, list):
        return [item.get("value") if isinstance(item, dict) else item for item in value]
    return value


def _normalize_sql(sql: str, parameters: Any, driver: str):
    if isinstance(parameters, dict):
        if driver == "sqlite":
            return sql, parameters
        names = re.findall(r":([A-Za-z_][A-Za-z0-9_]*)", sql)
        if names:
            return re.sub(r":[A-Za-z_][A-Za-z0-9_]*", "%s", sql), [parameters.get(name) for name in names]
        return sql.replace("?", "%s"), list(parameters.values())
    if driver != "sqlite":
        sql = sql.replace("?", "%s")
    return sql, parameters


def execute(connection_config: dict, config: dict) -> dict:
    operation = str(config.get("operation") or "query")
    sql = str(config.get("SqlStatement") or config.get("SqlUpdateStatement") or config.get("statement") or config.get("sql") or "").strip()
    if operation == "truncate" and sql.lower().startswith("truncate ") and str(connection_config.get("driver") or "sqlite").lower() == "sqlite":
        sql = "DELETE FROM " + sql.split()[-1]
    connection = connect(connection_config)
    driver = str(connection_config.get("driver") or "sqlite").lower()
    try:
        cursor = connection.cursor()
        timeout = int(config.get("timeout") or 0)
        if driver == "sqlite" and timeout > 0:
            connection.execute(f"PRAGMA busy_timeout={timeout * 1000}")
        if operation == "call":
            procedure = str(config.get("procedure") or "").strip()
            if not procedure:
                raise JdbcAdapterError("A stored procedure or function is required", "InvalidInputException")
            if not hasattr(cursor, "callproc"):
                raise JdbcAdapterError("The selected database adapter does not support stored procedures", "JDBCSQLException")
            result = cursor.callproc(procedure, list(_parameters(config) or []))
            result_sets = []
            while cursor.description:
                names = [item[0] for item in cursor.description]
                result_sets.append([dict(zip(names, row)) for row in cursor.fetchall()])
                if not getattr(cursor, "nextset", lambda: False)():
                    break
            if not config.get("overrideTransactionBehavior"):
                connection.commit()
            return {"resultSets": result_sets, "outParameters": result, "UnresolvedResultSets": []}
        if not sql:
            raise JdbcAdapterError("An SQL statement is required", "InvalidInputException")
        parameters = _parameters(config)
        sql, parameters = _normalize_sql(sql, parameters, driver)
        if config.get("interpretEmptyStringAsNull"):
            if isinstance(parameters, dict): parameters = {key: None if value == "" else value for key, value in parameters.items()}
            elif isinstance(parameters, list): parameters = [None if value == "" else value for value in parameters]
        records = config.get("records") if isinstance(config.get("records"), list) else None
        if operation in ("insert", "update", "delete") and config.get("batchUpdate") and records:
            cursor.executemany(sql, [list(row.values()) if isinstance(row, dict) else row for row in records])
        else:
            cursor.execute(sql, parameters or ())
        if cursor.description:
            names = [item[0] for item in cursor.description]
            maximum = int(config.get("maxRows") if config.get("maxRows") is not None else config.get("maximumRows") or 0)
            if maximum < 0: raise JdbcAdapterError("Maximum rows cannot be negative", "InvalidInputException")
            subset = int(config.get("subsetSize") or 0) if config.get("processInSubsets") else 0
            limit = subset or maximum
            rows = cursor.fetchall() if limit == 0 else cursor.fetchmany(limit)
            output = [dict(zip(names, row)) for row in rows]
            return {"resultSet": {"Record": output}, "rows": output, "rowCount": len(output), "lastSubset": not subset or len(rows) < subset, "columns": [{"name": item[0], "dataType": str(item[1] or "unknown")} for item in cursor.description]}
        connection.commit()
        count = int(cursor.rowcount or 0)
        return {"noOfUpdates": count, "rowCount": count, "lastInsertId": getattr(cursor, "lastrowid", None)}
    except JdbcAdapterError:
        raise
    except Exception as exc:
        try: connection.rollback()
        except Exception: pass
        raise JdbcAdapterError(str(exc), "JDBCSQLException") from exc
    finally:
        connection.close()


jdbc_adapter = type("JdbcAdapter", (), {"test": staticmethod(test_connection), "metadata": staticmethod(metadata), "execute": staticmethod(execute)})()
