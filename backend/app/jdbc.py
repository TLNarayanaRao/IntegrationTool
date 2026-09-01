from __future__ import annotations

import re
import sqlite3
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

from .java_bridge import JavaBridgeError, invoke as invoke_java


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


def _connection_url(config: dict, *prefixes: str) -> str:
    value = str(config.get("connectionString") or config.get("url") or "").strip()
    for prefix in prefixes:
        if value.lower().startswith(prefix.lower()):
            return value[len(prefix):]
    return value


def _parsed_url(config: dict, *jdbc_prefixes: str):
    return urlparse(_connection_url(config, *jdbc_prefixes))


def _connect_postgresql(config: dict):
    import psycopg
    value = _connection_url(config, "jdbc:")
    timeout = int(config.get("timeoutSeconds") or 30)
    if value.startswith(("postgresql://", "postgres://")):
        options = {"connect_timeout": timeout}
        if config.get("username"): options["user"] = config["username"]
        if config.get("password"): options["password"] = config["password"]
        return psycopg.connect(value, **options)
    return psycopg.connect(
        host=config.get("host") or "localhost", port=int(config.get("port") or 5432),
        dbname=config.get("database") or None, user=config.get("username") or None,
        password=config.get("password") or None, connect_timeout=timeout,
    )


def _connect_mysql(config: dict):
    import pymysql
    parsed = _parsed_url(config, "jdbc:")
    query = parse_qs(parsed.query)
    return pymysql.connect(
        host=config.get("host") or parsed.hostname or "localhost",
        port=int(config.get("port") or parsed.port or 3306),
        user=config.get("username") or (unquote(parsed.username) if parsed.username else ""),
        password=config.get("password") or (unquote(parsed.password) if parsed.password else ""),
        database=config.get("database") or parsed.path.lstrip("/") or None,
        charset=str(config.get("charset") or (query.get("characterEncoding") or ["utf8mb4"])[0]),
        connect_timeout=int(config.get("timeoutSeconds") or 30),
        ssl={"ca": config.get("sslCaFile")} if config.get("sslCaFile") else None,
    )


def _oracle_dsn(config: dict, oracle_module) -> str:
    raw = _connection_url(config).strip()
    if raw.lower().startswith("jdbc:oracle:thin:@"):
        raw = raw[len("jdbc:oracle:thin:@"):]
    if raw.startswith("//"):
        parsed = urlparse("oracle:" + raw)
        return oracle_module.makedsn(parsed.hostname, parsed.port or int(config.get("port") or 1521), service_name=parsed.path.lstrip("/") or config.get("serviceName") or config.get("database"))
    if raw and not raw.lower().startswith("jdbc:"):
        return raw
    host = config.get("host") or "localhost"
    port = int(config.get("port") or 1521)
    if config.get("sid"):
        return oracle_module.makedsn(host, port, sid=config["sid"])
    return oracle_module.makedsn(host, port, service_name=config.get("serviceName") or config.get("database"))


def _db2_connection_string(config: dict) -> str:
    raw = _connection_url(config).strip()
    if raw.lower().startswith("jdbc:db2://"):
        parsed = urlparse(raw[len("jdbc:"):])
        return ";".join((
            f"DATABASE={config.get('database') or parsed.path.lstrip('/')}",
            f"HOSTNAME={config.get('host') or parsed.hostname or 'localhost'}",
            f"PORT={int(config.get('port') or parsed.port or 50000)}", "PROTOCOL=TCPIP",
            f"UID={config.get('username') or ''}", f"PWD={config.get('password') or ''}",
        )) + ";"
    if "=" in raw:
        return raw
    return ";".join((
        f"DATABASE={config.get('database') or raw}", f"HOSTNAME={config.get('host') or 'localhost'}",
        f"PORT={int(config.get('port') or 50000)}", "PROTOCOL=TCPIP",
        f"UID={config.get('username') or ''}", f"PWD={config.get('password') or ''}",
    )) + ";"


def _databricks_settings(config: dict) -> dict[str, Any]:
    raw = str(config.get("url") or "").strip()
    properties: dict[str, str] = {}
    hostname = str(config.get("serverHostname") or config.get("host") or "").strip()
    if raw.lower().startswith("jdbc:databricks://"):
        address, _, attributes = raw[len("jdbc:databricks://"):].partition(";")
        parsed = urlparse("https://" + address)
        hostname = hostname or parsed.hostname or ""
        for item in attributes.split(";"):
            key, separator, value = item.partition("=")
            if separator: properties[key.strip().lower()] = value.strip()
    http_path = str(config.get("httpPath") or properties.get("httppath") or "").strip()
    if not hostname or not http_path:
        raise JdbcAdapterError("Databricks requires Server Hostname and HTTP Path from the SQL warehouse connection details", "JDBCConnectionNotFoundException")
    settings: dict[str, Any] = {
        "server_hostname": hostname.removeprefix("https://").rstrip("/"), "http_path": http_path,
        "catalog": config.get("catalog") or None, "schema": config.get("schema") or None,
        "use_cloud_fetch": _as_bool(config.get("useCloudFetch"), True),
        "user_agent_entry": "IntegrationFabricStudio",
    }
    auth = str(config.get("authentication") or "Personal Access Token")
    token = config.get("accessToken") or config.get("password") or properties.get("auth_accesstoken") or properties.get("pwd")
    if auth == "OAuth M2M":
        from databricks.sdk.core import Config, oauth_service_principal
        client_id, client_secret = config.get("clientId"), config.get("clientSecret")
        if not client_id or not client_secret:
            raise JdbcAdapterError("Databricks OAuth M2M requires Client ID and Client Secret", "JDBCConnectionNotFoundException")
        settings["credentials_provider"] = lambda: oauth_service_principal(Config(host=f"https://{settings['server_hostname']}", client_id=client_id, client_secret=client_secret))
    elif auth == "OAuth U2M":
        settings["auth_type"] = "databricks-oauth"
    elif token:
        settings["access_token"] = token
    else:
        raise JdbcAdapterError("Databricks Personal Access Token is required", "JDBCConnectionNotFoundException")
    return settings


def _as_bool(value: Any, default: bool = False) -> bool:
    if value is None or value == "":
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ("1", "true", "yes", "on")


def _uses_java(config: dict) -> bool:
    driver = str(config.get("driver") or "").lower()
    mode = str(config.get("connectionMode") or "jdbc" if driver in ("sqlserver", "mssql", "oracle") else "python").lower()
    return driver in ("sqlserver", "mssql", "oracle") and mode in ("jdbc", "java", "java bridge", "jdbc (java bridge)")


def _java_jdbc_url(config: dict) -> str:
    driver = str(config.get("driver") or "").lower()
    raw = str(config.get("url") or config.get("connectionString") or "").strip()
    if raw.lower().startswith("jdbc:"):
        return raw
    host = str(config.get("host") or "localhost").strip()
    if driver in ("sqlserver", "mssql"):
        port = int(config.get("port") or 1433)
        database = str(config.get("database") or "").strip()
        values = [f"jdbc:sqlserver://{host}:{port}"]
        if database: values.append(f"databaseName={database}")
        values.extend((f"encrypt={str(_as_bool(config.get('encrypt'), True)).lower()}", f"trustServerCertificate={str(_as_bool(config.get('trustServerCertificate'))).lower()}"))
        return ";".join(values)
    if driver == "oracle":
        port = int(config.get("port") or 1521)
        if config.get("sid") and not config.get("serviceName"):
            return f"jdbc:oracle:thin:@{host}:{port}:{config['sid']}"
        service = str(config.get("serviceName") or config.get("database") or "").strip()
        if not service:
            raise JdbcAdapterError("Oracle requires a JDBC URL, service name, or SID", "JDBCConnectionNotFoundException")
        return f"jdbc:oracle:thin:@//{host}:{port}/{service}"
    raise JdbcAdapterError(f"Java JDBC is not configured for {driver}", "JDBCConnectionNotFoundException")


def _java_driver_class(config: dict) -> str:
    if config.get("driverClass"):
        return str(config["driverClass"])
    return "com.microsoft.sqlserver.jdbc.SQLServerDriver" if str(config.get("driver") or "").lower() in ("sqlserver", "mssql") else "oracle.jdbc.OracleDriver"


def _java_family(config: dict) -> str:
    return "jdbc/sqlserver" if str(config.get("driver") or "").lower() in ("sqlserver", "mssql") else "jdbc/oracle"


def _java_connection_values(config: dict) -> dict[str, Any]:
    values: dict[str, Any] = {
        "databaseDriver": str(config.get("driver") or ""), "driverClass": _java_driver_class(config),
        "jdbcUrl": _java_jdbc_url(config), "username": config.get("username"), "password": config.get("password"),
        "timeoutSeconds": config.get("timeoutSeconds", 30), "catalog": config.get("catalog"), "schema": config.get("schema"),
    }
    properties = config.get("jdbcProperties")
    if isinstance(properties, str) and properties.strip():
        try: properties = __import__("json").loads(properties)
        except ValueError as exc: raise JdbcAdapterError("Advanced JDBC properties must be a JSON object", "InvalidInputException") from exc
    if isinstance(properties, dict):
        for key, value in properties.items(): values[f"jdbcProperty.{key}"] = value
    return values


def _java_parameters(sql: str, parameters: Any) -> tuple[str, list[Any]]:
    if isinstance(parameters, dict):
        names = re.findall(r":([A-Za-z_][A-Za-z0-9_]*)", sql)
        if names:
            return re.sub(r":[A-Za-z_][A-Za-z0-9_]*", "?", sql), [parameters.get(name) for name in names]
        return sql, list(parameters.values())
    return sql, list(parameters or [])


def _java_parameter_type(value: Any) -> str:
    if value is None: return "null"
    if isinstance(value, bool): return "boolean"
    if isinstance(value, int): return "integer"
    if isinstance(value, float): return "number"
    return "string"


def _java_test(config: dict) -> dict:
    try:
        output = invoke_java("jdbc.test", config, _java_connection_values(config), family=_java_family(config))
        output["message"] = f"{str(config.get('driver')).upper()} native JDBC connection succeeded"
        return output
    except JavaBridgeError as exc:
        raise JdbcAdapterError(str(exc), "JDBCConnectionNotFoundException") from exc


def _java_metadata(config: dict) -> dict:
    try: return invoke_java("jdbc.metadata", config, _java_connection_values(config), family=_java_family(config))
    except JavaBridgeError as exc: raise JdbcAdapterError(str(exc), "JDBCSQLException") from exc


def _java_execute(connection_config: dict, config: dict) -> dict:
    operation = str(config.get("operation") or "query")
    sql = str(config.get("SqlStatement") or config.get("SqlUpdateStatement") or config.get("statement") or config.get("sql") or "").strip()
    parameters = _parameters(config)
    if operation == "call" and not sql:
        procedure = str(config.get("procedure") or "").strip()
        if not procedure: raise JdbcAdapterError("A stored procedure or function is required", "InvalidInputException")
        values = list(parameters.values()) if isinstance(parameters, dict) else list(parameters or [])
        sql, parameters = "{call " + procedure + "(" + ",".join("?" for _ in values) + ")}", values
    if not sql: raise JdbcAdapterError("An SQL statement is required", "InvalidInputException")
    sql, parameters = _java_parameters(sql, parameters)
    values = {**_java_connection_values(connection_config), "sql": sql, "parameterCount": len(parameters), "queryTimeoutSeconds": config.get("timeout", 0), "maxRows": config.get("maxRows") if config.get("maxRows") is not None else config.get("maximumRows", 0)}
    for index, value in enumerate(parameters):
        values[f"parameter.{index}.type"] = _java_parameter_type(value)
        values[f"parameter.{index}.value"] = "" if value is None else value
    try: return invoke_java("jdbc.execute", connection_config, values, family=_java_family(connection_config), timeout=float(config.get("timeout") or connection_config.get("timeoutSeconds") or 30) + 5)
    except JavaBridgeError as exc: raise JdbcAdapterError(str(exc), "JDBCSQLException") from exc


def _odbc_value(value: Any) -> str:
    """Quote an ODBC value without allowing semicolons to become attributes."""
    return "{" + str(value or "").replace("}", "}}") + "}"


def _sqlserver_driver(config: dict, installed: list[str]) -> str:
    requested = str(config.get("odbcDriver") or config.get("driverName") or "").strip().strip("{}")
    by_name = {name.lower(): name for name in installed}
    if requested:
        if requested.lower() not in by_name:
            available = ", ".join(installed) or "none"
            raise JdbcAdapterError(
                f"SQL Server ODBC driver '{requested}' is not installed. Installed ODBC drivers: {available}. "
                "Install Microsoft ODBC Driver 18 for SQL Server or select an installed driver.",
                "JDBCConnectionNotFoundException",
            )
        return by_name[requested.lower()]
    preferred = (
        "ODBC Driver 18 for SQL Server",
        "ODBC Driver 17 for SQL Server",
        "SQL Server Native Client 11.0",
        "SQL Server",
        "FreeTDS",
    )
    for candidate in preferred:
        if candidate.lower() in by_name:
            return by_name[candidate.lower()]
    available = ", ".join(installed) or "none"
    raise JdbcAdapterError(
        "No Microsoft SQL Server ODBC driver is installed. Install Microsoft ODBC Driver 18 for SQL Server. "
        f"Installed ODBC drivers: {available}.",
        "JDBCConnectionNotFoundException",
    )


def _jdbc_sqlserver_parts(url: str) -> tuple[str, dict[str, str]]:
    value = str(url or "").strip()
    if not value.lower().startswith("jdbc:sqlserver://"):
        return "", {}
    address, _, properties = value[len("jdbc:sqlserver://"):].partition(";")
    settings: dict[str, str] = {}
    for item in properties.split(";"):
        key, separator, item_value = item.partition("=")
        if separator:
            settings[key.strip().lower()] = item_value.strip()
    return address.strip(), settings


def _sqlserver_connection_string(config: dict, installed_drivers: list[str]) -> str:
    raw = str(config.get("connectionString") or config.get("url") or "").strip()
    if raw.lower().startswith("odbc:"):
        raw = raw[5:].lstrip("/")
    # A configured DSN is complete by itself. A full ODBC string with DRIVER
    # must also remain untouched so advanced vendor attributes are preserved.
    if not raw.lower().startswith("jdbc:") and re.search(r"(^|;)\s*(driver|dsn)\s*=", raw, re.IGNORECASE):
        return raw

    driver = _sqlserver_driver(config, installed_drivers)
    if not raw.lower().startswith("jdbc:") and re.search(r"(^|;)\s*(server|data source)\s*=", raw, re.IGNORECASE):
        return f"DRIVER={_odbc_value(driver)};{raw.lstrip(';')}"
    jdbc_address, jdbc = _jdbc_sqlserver_parts(raw)
    host = str(config.get("host") or "").strip()
    port = str(config.get("port") or "").strip()
    if jdbc_address:
        host = jdbc_address
        # JDBC uses host:port while SQL Server ODBC convention is host,port.
        if host.count(":") == 1 and "," not in host and "\\" not in host:
            host, jdbc_port = host.rsplit(":", 1)
            port = port or jdbc_port
    server = host or "localhost"
    if port and "," not in server and "\\" not in server:
        server = f"{server},{port}"
    database = str(config.get("database") or jdbc.get("databasename") or jdbc.get("database") or "").strip()
    username = str(config.get("username") or jdbc.get("user") or "").strip()
    password = str(config.get("password") or jdbc.get("password") or "")
    integrated = _as_bool(config.get("trustedConnection"), False) or _as_bool(jdbc.get("integratedsecurity"), False) or str(config.get("authentication") or "").lower().startswith("windows")
    encrypt = config.get("encrypt", jdbc.get("encrypt", True))
    trust_certificate = config.get("trustServerCertificate", jdbc.get("trustservercertificate", False))

    parts = [f"DRIVER={_odbc_value(driver)}", f"SERVER={_odbc_value(server)}"]
    if database:
        parts.append(f"DATABASE={_odbc_value(database)}")
    if integrated:
        parts.append("Trusted_Connection=yes")
    else:
        if username:
            parts.append(f"UID={_odbc_value(username)}")
        if password:
            parts.append(f"PWD={_odbc_value(password)}")
    parts.extend((f"Encrypt={'yes' if _as_bool(encrypt, True) else 'no'}", f"TrustServerCertificate={'yes' if _as_bool(trust_certificate) else 'no'}"))
    return ";".join(parts) + ";"


def connect(config: dict):
    driver = str(config.get("driver") or "sqlite").lower()
    try:
        if driver == "sqlite":
            connection = sqlite3.connect(_sqlite_path(config.get("url")), timeout=float(config.get("timeoutSeconds") or 30))
            connection.row_factory = sqlite3.Row
            return connection
        if driver in ("postgresql", "postgres"):
            return _connect_postgresql(config)
        if driver in ("mysql", "mariadb"):
            return _connect_mysql(config)
        if driver in ("sqlserver", "mssql"):
            import pyodbc
            connection_string = _sqlserver_connection_string(config, list(pyodbc.drivers()))
            return pyodbc.connect(connection_string, timeout=int(config.get("timeoutSeconds") or 30))
        if driver == "oracle":
            import oracledb
            return oracledb.connect(user=config.get("username"), password=config.get("password"), dsn=config.get("dsn") or _oracle_dsn(config, oracledb))
        if driver == "db2":
            import ibm_db_dbi
            return ibm_db_dbi.connect(_db2_connection_string(config), "", "")
        if driver == "databricks":
            from databricks import sql as databricks_sql
            return databricks_sql.connect(**_databricks_settings(config))
        if driver == "snowflake":
            from .snowflake import connect as snowflake_connect
            return snowflake_connect(config)
    except ImportError as exc:
        raise JdbcAdapterError(f"The optional Python adapter for {driver} is not installed", "JDBCConnectionNotFoundException") from exc
    except Exception as exc:
        raise JdbcAdapterError(f"Unable to connect using {driver}: {exc}", "JDBCConnectionNotFoundException") from exc
    raise JdbcAdapterError(f"Unsupported JDBC driver {driver}", "JDBCConnectionNotFoundException")


def test_connection(config: dict) -> dict:
    if _uses_java(config):
        return _java_test(config)
    connection = connect(config)
    try:
        cursor = connection.cursor()
        cursor.execute("SELECT 1")
        cursor.fetchone()
        return {"ok": True, "message": f"{str(config.get('driver') or 'sqlite').upper()} connection succeeded"}
    finally:
        connection.close()


def _metadata_queries(driver: str, schema: str) -> tuple[str, str, Any]:
    if driver in ("sqlserver", "mssql", "databricks", "db2"):
        marker = "?"
    else:
        marker = "%s"
    if driver == "oracle":
        return (
            "SELECT owner, table_name, 'TABLE' FROM all_tables WHERE owner = :1 ORDER BY table_name",
            "SELECT column_name, data_type, nullable, column_id FROM all_tab_columns WHERE owner=:1 AND table_name=:2 ORDER BY column_id",
            schema.upper(),
        )
    if driver == "db2":
        return (
            "SELECT tabschema, tabname, type FROM syscat.tables WHERE tabschema = ? ORDER BY tabname",
            "SELECT colname, typename, nulls, colno FROM syscat.columns WHERE tabschema=? AND tabname=? ORDER BY colno",
            schema.upper(),
        )
    return (
        f"SELECT table_schema, table_name, table_type FROM information_schema.tables WHERE table_schema = {marker} ORDER BY table_name",
        f"SELECT column_name, data_type, is_nullable, ordinal_position FROM information_schema.columns WHERE table_schema={marker} AND table_name={marker} ORDER BY ordinal_position",
        schema,
    )


def metadata(config: dict) -> dict:
    if _uses_java(config):
        return _java_metadata(config)
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
            schema = config.get("schema") or ("PUBLIC" if driver == "snowflake" else "dbo" if driver in ("sqlserver", "mssql") else "default" if driver == "databricks" else config.get("username") if driver == "oracle" else "public")
            table_sql, column_sql, schema_value = _metadata_queries(driver, str(schema or ""))
            cursor.execute(table_sql, (schema_value,))
            for table_schema, name, kind in cursor.fetchall():
                cursor.execute(column_sql, (table_schema, name))
                columns = [{"name": row[0], "dataType": row[1], "notNull": str(row[2]).upper() in ("NO", "N"), "ordinal": row[3]} for row in cursor.fetchall()]
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
        if driver == "oracle" and re.search(r":[A-Za-z_][A-Za-z0-9_]*", sql):
            return sql, parameters
        names = re.findall(r":([A-Za-z_][A-Za-z0-9_]*)", sql)
        placeholder = "?" if driver in ("sqlserver", "mssql", "db2", "databricks") else "%s"
        if names:
            return re.sub(r":[A-Za-z_][A-Za-z0-9_]*", placeholder, sql), [parameters.get(name) for name in names]
        return (sql if placeholder == "?" else sql.replace("?", placeholder)), list(parameters.values())
    if driver == "oracle" and isinstance(parameters, (list, tuple)):
        index = iter(range(1, len(parameters) + 1))
        return re.sub(r"\?", lambda _: f":{next(index)}", sql), parameters
    if driver not in ("sqlite", "sqlserver", "mssql", "db2", "databricks"):
        sql = sql.replace("?", "%s")
    return sql, parameters


def execute(connection_config: dict, config: dict) -> dict:
    if _uses_java(connection_config):
        return _java_execute(connection_config, config)
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
