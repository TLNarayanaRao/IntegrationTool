from __future__ import annotations

import base64
import json
import re
import sqlite3
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

from .java_bridge import JavaBridgeError, invoke as invoke_java, start_jdbc_worker

_POSTGRES = {"postgresql", "postgres"}


class JdbcConnection:
    """One native transaction session, without a global connection/lock registry."""
    def __init__(self,connection):
        import threading
        object.__setattr__(self,'_mina_connection',connection)
        object.__setattr__(self,'_mina_lock',threading.RLock())
        object.__setattr__(self,'_mina_closed',False)
    def __getattr__(self,name):return getattr(self._mina_connection,name)
    def __setattr__(self,name,value):
        if name.startswith('_mina_'):object.__setattr__(self,name,value)
        else:setattr(self._mina_connection,name,value)
    def commit(self):
        with self._mina_lock:return self._mina_connection.commit()
    def rollback(self):
        with self._mina_lock:return self._mina_connection.rollback()
    def close(self):
        with self._mina_lock:
            if not self._mina_closed:
                try:return self._mina_connection.close()
                finally:self._mina_closed=True

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
    from psycopg import sql

    value = _connection_url(config, "jdbc:")
    options = {"connect_timeout": int(config.get("timeoutSeconds") or 30)}
    for key, field in (("user", "username"), ("password", "password"),
                       ("sslmode", "postgresSslMode"), ("sslrootcert", "postgresSslRootCert")):
        if config.get(field) not in (None, ""):
            options[key] = config[field]
    if not value:
        options.update(host=config.get("host") or "localhost", port=int(config.get("port") or 5432))
        if config.get("database"):
            options["dbname"] = config["database"]
    connection = psycopg.connect(value, **options)
    try:
        if config.get("schema"):
            connection.execute(sql.SQL("SET search_path TO {}").format(sql.Identifier(str(config["schema"]))))
            connection.commit()
        return connection
    except BaseException:
        connection.close()
        raise


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
        read_timeout=_seconds(config.get('readTimeoutSeconds'),int(config.get('timeoutSeconds') or 30)),
        write_timeout=_seconds(config.get('writeTimeoutSeconds'),int(config.get('timeoutSeconds') or 30)),
        ssl_ca=config.get('sslCaFile') or None,
        ssl_verify_cert=True if config.get('sslCaFile') else None,
        ssl_verify_identity=True if config.get('sslCaFile') else None,
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
        "user_agent_entry": "MINAStudio",
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


def _seconds(value,default=0):
    value=default if value in (None,'') else value
    try:
        number=int(value)
        if number<0 or number!=float(value):raise ValueError()
        return number
    except (ValueError,TypeError,OverflowError) as error:
        raise JdbcAdapterError('Timeout and row limits require nonnegative whole numbers','InvalidInputException') from error


def _validate_operation(config):
    if str(config.get('operation') or 'query') not in ('query','insert','update','delete','direct','dynamic','call','truncate'):
        raise JdbcAdapterError('Unsupported database operation','InvalidInputException')
    _seconds(config.get('timeout'))


def _procedure_name(name):
    identifier=r'(?:[A-Za-z_][\w$#]*|"(?:[^"]|"")+"|\[(?:[^\]]|\]\])+\])'
    if not re.fullmatch(rf'{identifier}(?:\.{identifier}){{0,2}}',name):
        raise JdbcAdapterError('Enter a qualified procedure identifier, without SQL or argument text','InvalidInputException')
    return name


def _call_parameters(config,driver=''):
    parameters=_parameters(config,driver)
    definitions=config.get('preparedParameters') or []
    if not isinstance(definitions,list) or any(not isinstance(item,dict) for item in definitions):raise JdbcAdapterError('Procedure parameter definitions must be a list of named parameters','InvalidInputException')
    if not definitions:return parameters,[]
    entries=[];result={}
    for index,item in enumerate(definitions):
        name=str(item.get('name') or '')
        if name in result or not re.fullmatch(r'[A-Za-z_][\w-]*',name):raise JdbcAdapterError('Procedure parameter names must be unique identifiers','InvalidInputException')
        direction=str(item.get('direction') or 'IN').upper()
        if direction not in ('IN','OUT','INOUT'):raise JdbcAdapterError('Parameter direction must be IN, OUT or INOUT','InvalidInputException')
        entries.append({**item,'name':name,'direction':direction,'type':str(item.get('type') or 'string').lower()})
        result[name]=None if direction=='OUT' else parameters.get(name) if isinstance(parameters,dict) else parameters[index] if index<len(parameters) else None
    if isinstance(parameters,dict):result.update({name:value for name,value in parameters.items() if name not in result})
    return result,entries


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


_SQL_BIND_TOKENS = re.compile(
    r"""--[^\r\n]*|/\*.*?\*/|\$(?P<tag>[A-Za-z_][A-Za-z0-9_]*|)\$.*?\$(?P=tag)\$"""
    r"""|\bq'\[.*?\]'|\bq'\{.*?\}'|\bq'\(.*?\)'|\bq'<.*?>'|\bq'(?P<delimiter>[^\s']).*?(?P=delimiter)'"""
    r"""|'(?:''|\\.|[^'])*'|"(?:""|[^"])*"|`(?:``|[^`])*`"""
    r"""|(?<!:):(?P<name>[A-Za-z_][A-Za-z0-9_]*)|(?P<position>(?<!\?)\?(?![|&?]))""",
    re.DOTALL | re.IGNORECASE,
)


def _named_bindings(sql, parameters, placeholder):
    names = []

    def replace(match):
        name = match.group("name")
        if name is None:
            return match.group()
        if name not in parameters:
            raise JdbcAdapterError(f"Missing SQL parameter: {name}", "InvalidInputException")
        names.append(name)
        return placeholder if placeholder is not None else match.group()

    return _SQL_BIND_TOKENS.sub(replace, sql), names


def _positional_sql(sql, replacement):
    return _SQL_BIND_TOKENS.sub(lambda match: replacement() if match.group("position") else match.group(), sql)


def _java_parameters(sql: str, parameters: Any) -> tuple[str, list[Any], list[str]]:
    if isinstance(parameters, dict):
        statement, names = _named_bindings(sql, parameters, "?")
        if names:
            return statement, [parameters[name] for name in names], names
        return sql, list(parameters.values()), list(parameters.keys())
    values = list(parameters or [])
    return sql, values, [f"Parameter{index + 1}" for index in range(len(values))]


def _java_parameter_type(value: Any, declared_type: str = "") -> str:
    if value is None: return "null"
    if declared_type: return declared_type.lower()
    if isinstance(value, bool): return "boolean"
    if isinstance(value, int): return "integer"
    if isinstance(value, float): return "number"
    return "string"


def _java_parameter_value(value: Any, data_type: str) -> Any:
    if value is None: return ""
    if data_type == "binary" and isinstance(value, bytes): return base64.b64encode(value).decode("ascii")
    if data_type == "json" and isinstance(value, (dict, list)): return json.dumps(value, separators=(",", ":"))
    return value


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


def _java_execute(connection_config: dict, config: dict, worker=None) -> dict:
    _validate_operation(config)
    operation = str(config.get("operation") or "query")
    sql = str(config.get("SqlStatement") or config.get("SqlUpdateStatement") or config.get("statement") or config.get("sql") or "").strip()
    parameters = _parameters(config,'java')
    call_definitions=[]
    if operation=='call':parameters,call_definitions=_call_parameters(config,'java')
    if operation == "call" and not sql:
        procedure = str(config.get("procedure") or "").strip()
        _procedure_name(procedure)
        sql = "{call " + procedure + "(" + ",".join("?" for _ in parameters) + ")}"
    if not sql: raise JdbcAdapterError("An SQL statement is required", "InvalidInputException")
    declared = _parameter_types(config)
    maximum, subset, offset = _query_window(config)
    values = {**_java_connection_values(connection_config), "queryTimeoutSeconds": config.get("timeout", 0),
              "maxRows": maximum, "subsetSize": subset, "rowOffset": offset,'operation':operation}

    def add_statement(statement, rows, prefix=""):
        for index, row in enumerate(rows):
            bound_sql, bindings, names = _java_parameters(statement, _empty_as_null(row, config))
            if index and (bound_sql != values[prefix + "sql"] or len(bindings) != values[prefix + "parameterCount"]):
                raise JdbcAdapterError("Batch records must use the same SQL parameter style", "InvalidInputException")
            values[prefix + "sql"] = bound_sql
            values[prefix + "parameterCount"] = len(bindings)
            binding_prefix = prefix + (f"batch.{index}." if batch is not None else "")
            for position, value in enumerate(bindings):
                data_type = _java_parameter_type(value, declared.get(names[position], list(declared.values())[position] if position<len(declared) else ""))
                values[f"{binding_prefix}parameter.{position}.type"] = data_type
                values[f"{binding_prefix}parameter.{position}.value"] = _java_parameter_value(value, data_type)
                if operation=='call':
                    entry=next((item for item in call_definitions if item['name']==names[position]),call_definitions[position] if position<len(call_definitions) else {})
                    values[f'parameter.{position}.direction']=entry.get('direction','IN')
                    values[f'parameter.{position}.name']=entry.get('name',names[position])
                    values[f'parameter.{position}.declaredType']=entry.get('type','string')

    batch = _write_batch(config, operation,'java')
    if batch == []:
        return {"noOfUpdates": 0, "rowCount": 0}
    if batch is not None:
        values["batchCount"] = len(batch)
    rows = batch if batch is not None else [parameters]
    add_statement(sql, rows)
    fallback = _insert_fallback(config, operation)
    if fallback:
        add_statement(fallback, rows, "fallback.")
    try:
        if worker is not None: return worker.request("execute", values, timeout=float(config.get("timeout") or connection_config.get("timeoutSeconds") or 30) + 5)
        return invoke_java("jdbc.execute", connection_config, values, family=_java_family(connection_config), timeout=float(config.get("timeout") or connection_config.get("timeoutSeconds") or 30) + 5)
    except JavaBridgeError as exc: raise JdbcAdapterError(str(exc), "JDBCSQLException") from exc


class JavaJdbcTransaction:
    """DB-API-like handle backed by one persistent Java JDBC connection."""
    def __init__(self, config: dict):
        self.config = dict(config); self.closed = False; self.completed = False
        try: self.worker = start_jdbc_worker(self.config, _java_connection_values(self.config), _java_family(self.config))
        except JavaBridgeError as exc: raise JdbcAdapterError(str(exc), "JDBCConnectionNotFoundException") from exc

    def execute(self, config: dict) -> dict:
        if self.closed or self.completed: raise JdbcAdapterError("JDBC transaction session is closed", "JDBCTransactionException")
        return _java_execute(self.config, config, self.worker)

    def commit(self):
        if not self.closed and not self.completed:
            self.worker.request("commit"); self.completed = True

    def rollback(self):
        if not self.closed and not self.completed:
            self.worker.request("rollback"); self.completed = True

    def close(self):
        if self.closed: return
        try:
            if not self.completed: self.rollback()
        finally:
            self.worker.close(); self.closed = True


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


def _connect_native(config: dict):
    driver = str(config.get("driver") or "sqlite").lower()
    try:
        if _uses_java(config): return JavaJdbcTransaction(config)
        if driver == "sqlite":
            connection = sqlite3.connect(_sqlite_path(config.get("url")), timeout=float(config.get("timeoutSeconds") or 30), check_same_thread=False)
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
            return oracledb.connect(user=config.get("username"), password=config.get("password"), dsn=config.get("dsn") or _oracle_dsn(config, oracledb),tcp_connect_timeout=_seconds(config.get('timeoutSeconds'),30))
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


def connect(config: dict):
    connection=_connect_native(config)
    return connection if isinstance(connection,JavaJdbcTransaction) else JdbcConnection(connection)


def test_connection(config: dict) -> dict:
    if _uses_java(config):
        return _java_test(config)
    connection = connect(config)
    cursor = None
    try:
        cursor = connection.cursor()
        driver = str(config.get('driver') or 'sqlite').lower()
        cursor.execute('SELECT 1 FROM DUAL' if driver == 'oracle' else 'VALUES 1' if driver == 'db2' else 'SELECT 1')
        cursor.fetchone()
        return {"ok": True, "message": f"{str(config.get('driver') or 'sqlite').upper()} connection succeeded"}
    finally:
        try:
            if cursor is not None: cursor.close()
        finally: connection.close()


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
    cursor = None
    try:
        cursor = connection.cursor()
        tables: list[dict] = []
        if driver == "sqlite":
            cursor.execute("SELECT name, type FROM sqlite_master WHERE type IN ('table','view') AND name NOT LIKE 'sqlite_%' ORDER BY name")
            for name, kind in cursor.fetchall():
                escaped = str(name).replace(chr(34), chr(34) * 2)
                columns = []
                details=connection.cursor()
                try:
                    details.execute(f'PRAGMA table_info("{escaped}")')
                    rows=details.fetchall()
                finally:details.close()
                for row in rows:
                    columns.append({"name": row[1], "dataType": row[2] or "TEXT", "notNull": bool(row[3]), "default": row[4], "primaryKey": bool(row[5])})
                tables.append({"schema": "main", "name": name, "type": kind.upper(), "columns": columns})
        else:
            schema = config.get("schema") or (config.get('database') or _parsed_url(config,'jdbc:').path.lstrip('/') if driver in ('mysql','mariadb') else "PUBLIC" if driver == "snowflake" else "dbo" if driver in ("sqlserver", "mssql") else "default" if driver == "databricks" else config.get("username") if driver in ('oracle','db2') else "public")
            table_sql, column_sql, schema_value = _metadata_queries(driver, str(schema or ""))
            cursor.execute(table_sql, (schema_value,))
            for table_schema, name, kind in cursor.fetchall():
                cursor.execute(column_sql, (table_schema, name))
                columns = [{"name": row[0], "dataType": row[1], "notNull": str(row[2]).upper() in ("NO", "N"), "ordinal": row[3]} for row in cursor.fetchall()]
                tables.append({"schema": table_schema, "name": name, "type": kind, "columns": columns})
        return {"driver": driver, "tables": tables}
    finally:
        try:
            if cursor is not None:cursor.close()
        finally:connection.close()


def _parameters(config: dict, driver: str = "") -> Any:
    value = config.get("parameters") or {}
    value = _empty_as_null(value, config)
    if isinstance(value, list):
        definitions=list(_parameter_types(config).values())
        return [_coerce_parameter(None if _as_bool(config.get('interpretEmptyStringAsNull')) and item.get('value')=='' else item.get('value'),item.get('type') or (definitions[index] if index<len(definitions) else ''),driver)
                if isinstance(item,dict) and 'value' in item else _coerce_parameter(item,definitions[index],driver) if index<len(definitions) else item for index,item in enumerate(value)]
    definitions = _parameter_types(config)
    if isinstance(value, dict):
        return _typed_parameters(value, definitions, driver)
    return value


def _parameter_types(config: dict) -> dict[str, str]:
    definitions = config.get("preparedParameters") or []
    if not isinstance(definitions, list): return {}
    return {
        str(item.get("name")): str(item.get("type") or "string").lower()
        for item in definitions if isinstance(item, dict) and item.get("name")
    }


def _coerce_parameter(value: Any, data_type: str, driver: str = "") -> Any:
    if value is None: return None
    kind = str(data_type or "string").lower()
    if kind=='decimal' and driver in ('java','oracle','mysql','mariadb','sqlserver','mssql'):
        from decimal import Decimal
        return Decimal(str(value))
    if driver in _POSTGRES:
        from datetime import date, datetime, time
        from decimal import Decimal
        from psycopg.types.json import Json, Jsonb

        if kind == "decimal": return Decimal(str(value))
        if kind == "date": return date.fromisoformat(str(value))
        if kind == "time": return time.fromisoformat(str(value))
        if kind in ("timestamp", "datetime"): return datetime.fromisoformat(str(value))
        if kind in ("json", "jsonb"):
            parsed = json.loads(value) if isinstance(value, str) else value
            return (Json if kind == "json" else Jsonb)(parsed)
    if kind in ("string", "date", "time", "timestamp", "datetime"): return str(value)
    if kind in ("integer", "long"):
        from decimal import Decimal, InvalidOperation
        try: number = Decimal(str(value))
        except InvalidOperation as exc: raise JdbcAdapterError('Integer parameters require a finite whole number', 'InvalidInputException') from exc
        if not number.is_finite() or number != number.to_integral_value():
            raise JdbcAdapterError('Integer parameters require a finite whole number', 'InvalidInputException')
        return int(number)
    if kind in ("number", "decimal", "float", "double"): return float(value)
    if kind == "boolean":
        if isinstance(value,bool): return value
        text = str(value).strip().lower()
        if text not in ('1','true','yes','on','0','false','no','off'):
            raise JdbcAdapterError('Boolean parameters require true or false', 'InvalidInputException')
        return text in ('1','true','yes','on')
    if kind == "json": return value if isinstance(value, (dict, list)) else json.loads(str(value))
    if kind == "binary": return value if isinstance(value, bytes) else base64.b64decode(str(value),validate=True)
    return value


def _typed_parameters(values, definitions, driver=""):
    return {key: _coerce_parameter(value, definitions[key], driver) if key in definitions else value
            for key, value in values.items()}


def _empty_as_null(values, config):
    if _as_bool(config.get("interpretEmptyStringAsNull")):
        if isinstance(values, dict):
            return {key: None if value == "" else value for key, value in values.items()}
        if isinstance(values, (list, tuple)):
            return [None if value == "" else value for value in values]
    return values


def _write_batch(config, operation, driver=""):
    if operation not in ("insert", "update", "delete") or not _as_bool(config.get("batchUpdate")):
        return None
    records = config.get("records")
    if records is None:
        return None
    if not isinstance(records, list) or any(not isinstance(row, (list, tuple, dict)) for row in records):
        raise JdbcAdapterError("Batch records must be a list of parameter records", "InvalidInputException")
    definitions = _parameter_types(config)
    records = [_empty_as_null(row, config) for row in records]
    return [_typed_parameters(row, definitions, driver) if isinstance(row, dict) else _parameters({**config,'parameters':list(row)},driver) for row in records]


def _insert_fallback(config, operation):
    if operation != "update" or not _as_bool(config.get("insertIfRecordDoesNotExist")):
        return ""
    statement = str(config.get("InsertStatement") or "").strip()
    if not re.match(r"INSERT\b", statement, re.IGNORECASE):
        raise JdbcAdapterError("Insert if missing requires an INSERT statement", "InvalidInputException")
    return statement


def _query_window(config):
    maximum = _seconds(config.get("maxRows") if config.get("maxRows") is not None else config.get("maximumRows"))
    subset = _seconds(config.get("subsetSize")) if _as_bool(config.get("processInSubsets")) else 0
    offset = _seconds(config.get("rowOffset")) if _as_bool(config.get("processInSubsets")) else 0
    if min(maximum, subset, offset) < 0:
        raise JdbcAdapterError("Maximum rows, subset size, and row offset cannot be negative", "InvalidInputException")
    return maximum, subset, offset


def _normalize_sql(sql: str, parameters: Any, driver: str):
    if driver in _POSTGRES:
        return _postgres_bindings(sql, parameters)
    if isinstance(parameters, dict):
        if driver == "sqlite":
            _named_bindings(sql, parameters, None)
            return sql, parameters
        placeholder = "?" if driver in ("sqlserver", "mssql", "db2", "databricks") else "%s"
        statement, names = _named_bindings(sql, parameters, None if driver == "oracle" else placeholder)
        if names:
            return (statement, parameters) if driver == "oracle" else (statement, [parameters[name] for name in names])
        parameters = list(parameters.values())
    if driver == "oracle":
        from itertools import count
        positions = count(1)
        sql = _positional_sql(sql, lambda: f":{next(positions)}")
    elif parameters and driver not in ("sqlite", "sqlserver", "mssql", "db2", "databricks"):
        sql = _positional_sql(sql, lambda: "%s")
    return sql, parameters


def _postgres_bindings(sql, parameters):
    if isinstance(parameters, dict):
        statement, names = _named_bindings(sql.replace("%", "%%"), parameters, "%s")
        if names:
            return statement, [parameters[name] for name in names]
        if re.search(r"%\([A-Za-z_][A-Za-z0-9_]*\)[sbt]", sql):
            return sql, parameters
        parameters = list(parameters.values())
    if parameters and not re.search(r"(?<!%)%[sbt]", sql):
        sql = _positional_sql(sql.replace("%", "%%"), lambda: "%s")
    return sql, parameters


def _postgres_call(cursor, procedure, parameters, schema=None):
    from psycopg import sql

    identifier = r'(?:[A-Za-z_][\w$]*|"(?:[^"]|"")+")'
    if not re.fullmatch(rf'{identifier}(?:\.{identifier})?', procedure):
        raise JdbcAdapterError("Enter a PostgreSQL procedure name or schema.procedure", "InvalidInputException")
    parts = [part[1:-1].replace('""', '"') if part.startswith('"') else part.lower()
             for part in re.findall(identifier, procedure)]
    if schema and len(parts) == 1:
        parts.insert(0, str(schema))
    cursor.execute(sql.SQL("CALL {}({})").format(sql.Identifier(*parts),
                   sql.SQL(", ").join(sql.Placeholder() for _ in parameters)), parameters)
    if cursor.description:
        names = [column[0] for column in cursor.description]
        row = cursor.fetchone()
        return dict(zip(names, row)) if row is not None else {}
    return {}


def execute(connection_config: dict, config: dict, connection=None, manage_transaction: bool = True) -> dict:
    if isinstance(connection,JdbcConnection):
        with connection._mina_lock:return _execute(connection_config,config,connection,manage_transaction)
    return _execute(connection_config,config,connection,manage_transaction)


def _execute(connection_config: dict, config: dict, connection=None, manage_transaction: bool = True) -> dict:
    _validate_operation(config)
    if connection is None and _as_bool(config.get('overrideTransactionBehavior')):
        raise JdbcAdapterError('Override transaction behavior requires a JDBC Transaction group','JDBCTransactionException')
    if _uses_java(connection_config):
        if isinstance(connection, JavaJdbcTransaction): return connection.execute(config)
        if connection is not None or not manage_transaction: raise JdbcAdapterError("Invalid Java JDBC transaction session", "JDBCTransactionException")
        return _java_execute(connection_config, config)
    operation = str(config.get("operation") or "query")
    if operation not in ('query','insert','update','delete','direct','dynamic','call','truncate'):
        raise JdbcAdapterError('Unsupported database operation '+operation, 'InvalidInputException')
    sql = str(config.get("SqlStatement") or config.get("SqlUpdateStatement") or config.get("statement") or config.get("sql") or "").strip()
    if operation == "truncate" and sql.lower().startswith("truncate ") and str(connection_config.get("driver") or "sqlite").lower() == "sqlite":
        sql = "DELETE FROM " + sql.split()[-1]
    owns_connection = connection is None
    connection = connection or connect(connection_config)
    driver = str(connection_config.get("driver") or "sqlite").lower()
    cursor = None
    previous_timeout = None
    sqlite_timeout = None
    native_timeout = None
    try:
        cursor = connection.cursor()
        timeout = int(config.get("timeout") or 0)
        if timeout < 0: raise JdbcAdapterError('SQL timeout cannot be negative', 'InvalidInputException')
        if driver == "sqlite" and timeout > 0:
            if not owns_connection: sqlite_timeout = connection.execute('PRAGMA busy_timeout').fetchone()[0]
            connection.execute(f"PRAGMA busy_timeout={timeout * 1000}")
        if timeout>0 and driver=='oracle':
            native_timeout=('call_timeout',connection.call_timeout)
            connection.call_timeout=timeout*1000
        if timeout>0 and driver in ('sqlserver','mssql'):
            native_timeout=('timeout',connection.timeout)
            connection.timeout=timeout
        if driver in _POSTGRES and timeout > 0:
            if not manage_transaction:
                cursor.execute("SHOW statement_timeout")
                previous_timeout = cursor.fetchone()[0]
            cursor.execute("SELECT set_config('statement_timeout', %s, true)", (str(timeout * 1000),))
        if operation == "call":
            procedure = str(config.get("procedure") or "").strip()
            if not procedure:
                raise JdbcAdapterError("A stored procedure or function is required", "InvalidInputException")
            _procedure_name(procedure)
            if driver not in _POSTGRES and not hasattr(cursor, "callproc"):
                raise JdbcAdapterError("The selected database adapter does not support stored procedures", "JDBCSQLException")
            parameters,call_definitions = _call_parameters(config,driver)
            if isinstance(parameters, dict):
                ordered_names = [name for name in _parameter_types(config) if name in parameters]
                declared_names = set(ordered_names)
                ordered_names.extend(name for name in parameters if name not in declared_names)
                parameters = [parameters[name] for name in ordered_names]
            if driver in _POSTGRES:
                result = _postgres_call(cursor, procedure, list(parameters or []), config.get("schema"))
                if manage_transaction and not _as_bool(config.get("overrideTransactionBehavior")):
                    connection.commit()
                return {"resultSets": [[result]] if result else [], "outParameters": result, "UnresolvedResultSets": []}
            if driver=='oracle' and any(item['direction']!='IN' for item in call_definitions):
                import oracledb
                types={'integer':int,'long':int,'number':float,'double':float,'decimal':getattr(oracledb,'DB_TYPE_NUMBER',float),'boolean':bool,'binary':bytes,'date':getattr(oracledb,'DB_TYPE_DATE',str),'timestamp':getattr(oracledb,'DB_TYPE_TIMESTAMP',str)}
                for index,item in enumerate(call_definitions):
                    if item['direction']!='IN':
                        variable=cursor.var(types.get(item.get('type','string'),str))
                        if item['direction']=='INOUT':variable.setvalue(0,parameters[index])
                        parameters[index]=variable
            result = cursor.callproc(procedure, list(parameters or []))
            result_sets = []
            while True:
                if cursor.description:
                    names = [item[0] for item in cursor.description]
                    result_sets.append([dict(zip(names, row)) for row in cursor.fetchall()])
                if not getattr(cursor, "nextset", lambda: False)():
                    break
            if driver in ('mysql','mariadb') and any(item['direction']!='IN' for item in call_definitions):
                # PyMySQL returns original IN arguments; OUT values live in server variables.
                variables=['@`'+f'_{procedure}_{index}'.replace('`','``')+'`' for index,item in enumerate(call_definitions) if item['direction']!='IN']
                cursor.execute('SELECT '+','.join(variables))
                row=cursor.fetchone()
                result={item['name']:value for item,value in zip([item for item in call_definitions if item['direction']!='IN'],row or [])}
            elif driver=='oracle' and call_definitions:
                result={item['name']:value.getvalue() if hasattr(value,'getvalue') else value for item,value in zip(call_definitions,result) if item['direction']!='IN'}
            if manage_transaction and not _as_bool(config.get("overrideTransactionBehavior")):
                connection.commit()
            return {"resultSets": result_sets, "outParameters": result, "UnresolvedResultSets": []}
        if not sql:
            raise JdbcAdapterError("An SQL statement is required", "InvalidInputException")
        maximum, subset, offset = _query_window(config)

        def bind(statement, values):
            return _normalize_sql(statement, _empty_as_null(values, config), driver)

        batch = _write_batch(config, operation, driver)
        fallback = _insert_fallback(config, operation)
        if batch == []:
            return {"noOfUpdates": 0, "rowCount": 0, "lastInsertId": None}
        if fallback:
            rows = batch if batch is not None else [_parameters(config, driver)]
            statements = [(bind(sql, row), bind(fallback, row)) for row in rows]
            count = 0
            for (statement, bindings), (insert, insert_bindings) in statements:
                cursor.execute(statement, bindings)
                if cursor.rowcount == 0:
                    cursor.execute(insert, insert_bindings)
                count = -2 if count < 0 or cursor.rowcount < 0 else count + cursor.rowcount
            if manage_transaction:
                connection.commit()
            return {"noOfUpdates": count, "rowCount": count, "lastInsertId": getattr(cursor, "lastrowid", None)}
        if batch is not None:
            bound = []
            for row in batch:
                if driver == "sqlite" and isinstance(row, dict):
                    tokens = list(_SQL_BIND_TOKENS.finditer(sql))
                    if any(token.group("position") for token in tokens) and not any(token.group("name") for token in tokens):
                        row = list(row.values())
                bound.append(bind(sql, row))
            statement = bound[0][0]
            if any(item[0] != statement for item in bound):
                raise JdbcAdapterError("Batch records must use the same SQL parameter style", "InvalidInputException")
            cursor.executemany(statement, [bindings for _, bindings in bound])
        else:
            sql, parameters = bind(sql, _parameters(config, driver))
            if driver in _POSTGRES and not parameters:
                cursor.execute(sql)
            else:
                cursor.execute(sql, parameters or ())
        if cursor.description:
            names = [item[0] for item in cursor.description]
            types = connection.adapters.types if driver in _POSTGRES else None
            columns = [{"name": item[0], "dataType": getattr(types.get(item[1]), "name", str(item[1] or "unknown"))
                        if types is not None else str(item[1] or "unknown")} for item in cursor.description]
            remaining = min(offset, maximum) if maximum else offset
            while remaining:
                skipped = cursor.fetchmany(min(remaining, 1024))
                if not skipped:
                    break
                remaining -= len(skipped)
            available = max(0, maximum - offset) if maximum else None
            limit = min(subset, available) if subset and available is not None else subset or available
            lookahead = bool(subset and limit and (available is None or limit < available))
            rows = cursor.fetchall() if limit is None else cursor.fetchmany(limit + lookahead) if limit else []
            has_next = lookahead and len(rows) > limit
            if has_next:
                rows = rows[:limit]
            output = [dict(zip(names, row)) for row in rows]
            cursor.close()
            cursor = None
            if manage_transaction:
                connection.commit()
            return {"resultSet": {"Record": output}, "rows": output, "rowCount": len(output), "lastSubset": not has_next,
                    "nextRowOffset": offset + len(output) if has_next else None, "columns": columns}
        if manage_transaction: connection.commit()
        count = int(cursor.rowcount or 0)
        return {"noOfUpdates": count, "rowCount": count, "lastInsertId": getattr(cursor, "lastrowid", None)}
    except Exception as exc:
        previous_timeout = None
        if manage_transaction:
            try: connection.rollback()
            except Exception: pass
        if isinstance(exc, JdbcAdapterError):
            raise
        raise JdbcAdapterError(str(exc), "JDBCSQLException") from exc
    finally:
        try:
            if cursor is not None:
                cursor.close()
            if sqlite_timeout is not None:
                connection.execute(f'PRAGMA busy_timeout={int(sqlite_timeout)}')
            if native_timeout is not None:setattr(connection,*native_timeout)
            if previous_timeout is not None:
                with connection.cursor() as restore:
                    restore.execute("SELECT set_config('statement_timeout', %s, true)", (previous_timeout,))
        finally:
            if owns_connection:
                connection.close()


jdbc_adapter = type("JdbcAdapter", (), {
    "test": staticmethod(test_connection), "metadata": staticmethod(metadata),
    "execute": staticmethod(execute), "connect": staticmethod(connect)
})()
