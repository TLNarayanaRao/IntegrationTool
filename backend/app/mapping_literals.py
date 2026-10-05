"""Literal syntax shared by generic Input mappings and standalone Python code."""
import ast
import json
import re


def parse_literal(value):
    if not isinstance(value, str): return value, False
    text = value.strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in ('"', "'"):
        return ast.literal_eval(text), True
    if text in ('true', 'false', 'null'): return json.loads(text), True
    if re.fullmatch(r'[+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?', text):
        return float(text) if any(char in text for char in '.eE') else int(text), True
    if text.startswith(('{', '[')):
        try: return json.loads(text), True
        except (ValueError, TypeError): pass
    return value, False
