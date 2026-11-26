"""Locate SQL parameter markers while preserving quoted text and comments."""
import re


SQL_BIND_TOKENS = re.compile(
    r"""--[^\r\n]*|/\*.*?\*/|\$(?P<tag>[A-Za-z_][A-Za-z0-9_]*|)\$.*?\$(?P=tag)\$"""
    r"""|\bq'\[.*?\]'|\bq'\{.*?\}'|\bq'\(.*?\)'|\bq'<.*?>'|\bq'(?P<delimiter>[^\s']).*?(?P=delimiter)'"""
    r"""|'(?:''|\\.|[^'])*'|"(?:""|[^"])*"|`(?:``|[^`])*`"""
    r"""|(?<!:):(?P<name>[A-Za-z_][A-Za-z0-9_]*)|(?P<position>(?<!\?)\?(?![|&?]))""",
    re.DOTALL | re.IGNORECASE,
)


def replace_positional(sql, replacement):
    return SQL_BIND_TOKENS.sub(lambda match: replacement() if match.group('position') else match.group(), sql)
