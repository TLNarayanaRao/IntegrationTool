"""XML namespace matching for imported documents."""
from urllib.parse import urlsplit


def legacy_namespace(uri, path):
    """Recognize an external XML vocabulary from its declared namespace path."""
    if not uri:
        return False
    try:
        parts = urlsplit(uri)
        return (parts.scheme in ('http', 'https') and bool(parts.hostname)
                and parts.path == path and not parts.query and not parts.fragment)
    except ValueError:
        return False


def legacy_name(tag, name, path):
    if not isinstance(tag, str) or not tag.startswith('{'):
        return False
    uri, _, local = tag[1:].partition('}')
    return local == name and legacy_namespace(uri, path)
