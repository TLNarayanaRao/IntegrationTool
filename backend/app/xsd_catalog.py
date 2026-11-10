"""Resolve XSD dependencies strictly from the current project's schema assets."""
import posixpath
from urllib.parse import quote, unquote, urlsplit

from lxml import etree

XS = '{http://www.w3.org/2001/XMLSchema}'
PREFIX = 'https://mina.invalid/project-xsd/'
LIMIT = 8 * 1024**2


def asset_path(value, base=''):
    value = value.replace('\\', '/')
    url = urlsplit(value)
    if url.scheme or url.netloc or url.query or url.fragment or value.startswith('/'):
        raise ValueError(f'Only relative project XSD locations are allowed: {value}')
    decoded = unquote(url.path)
    if decoded.startswith('/') or any(char in decoded for char in ('\\', ':', '\x00')):
        raise ValueError(f'Invalid project XSD location: {value}')
    path = posixpath.normpath(posixpath.join(base, decoded))
    if path in ('.', '..') or path.startswith('../'):
        raise ValueError(f'XSD location leaves the project: {value}')
    return path


class SchemaGraph:
    def __init__(self, source, root_path, assets, safe_xml):
        self.documents = {}
        self.roots = []
        self.scopes = {}
        self.total = 0
        root_path = asset_path(root_path or '__inline__.xsd')
        catalog = {}
        for path, text in assets:
            path = asset_path(path)
            if path in catalog:
                catalog[path] = None  # ambiguous; fail if referenced
            else:
                catalog[path] = text
        catalog[root_path] = source
        parser = etree.XMLParser(resolve_entities=False, load_dtd=False, no_network=True, huge_tree=False)

        def document(path):
            if path in self.documents: return self.documents[path]
            text = catalog.get(path)
            if text is None: raise ValueError(f'Project XSD is missing or ambiguous: {path}')
            raw = safe_xml(text)
            self.total += len(raw)
            if len(raw) > LIMIT or self.total > 32 * 1024**2 or len(self.documents) >= 128:
                raise ValueError('Project XSD dependency limits exceeded')
            root = etree.fromstring(raw, parser, base_url=PREFIX + quote(path))
            if root.tag != XS + 'schema': raise ValueError(f'{path} is not an XML Schema')
            if any('{http://www.w3.org/XML/1998/namespace}base' in node.attrib for node in root.iter()):
                raise ValueError('xml:base is not allowed in project schemas')
            self.documents[path] = root
            return root

        # Work from the original locations: the same chameleon include may
        # participate in several namespaces even though it has one source path.
        locations = {}
        def walk(path, namespace, entry, depth=0):
            if depth > 32: raise ValueError('Project XSD includes/imports are nested too deeply')
            root = document(path)
            namespace = root.get('targetNamespace') or namespace
            scope = (path, namespace)
            if scope in self.scopes:
                if entry and scope not in self.roots: self.roots.append(scope)
                return
            self.scopes[scope] = root
            if entry: self.roots.append(scope)
            for directive in root:
                if directive.tag not in (XS + 'import', XS + 'include', XS + 'redefine', XS + 'override'): continue
                if directive.tag in (XS + 'redefine', XS + 'override'):
                    raise ValueError('XSD redefine and override are not supported')
                include = directive.tag == XS + 'include'
                original = locations.setdefault(directive, directive.get('schemaLocation'))
                target_ns = namespace if include else directive.get('namespace')
                if original:
                    target = asset_path(original, posixpath.dirname(path))
                elif include:
                    raise ValueError(f'Missing schemaLocation on XSD include in {path}')
                else:
                    # A locationless import may bind to a unique project schema.
                    candidates = []
                    scanned = 0
                    for name, text in catalog.items():
                        if name == path or not text or len(text) > LIMIT: continue
                        scanned += len(text)
                        if scanned > 32 * 1024**2: raise ValueError('Project XSD namespace lookup limit exceeded')
                        try:
                            candidate = etree.fromstring(safe_xml(text), parser)
                        except (ValueError, etree.Error): continue
                        if candidate.tag == XS + 'schema' and candidate.get('targetNamespace') == target_ns:
                            candidates.append(name)
                            if len(candidates) > 1: break
                    if len(candidates) != 1: raise ValueError(f'XSD import namespace is missing or ambiguous: {target_ns}')
                    target = candidates[0]
                target_doc = document(target)
                actual = target_doc.get('targetNamespace')
                if actual != target_ns and (not include or actual is not None):
                    raise ValueError(f'XSD namespace does not match the reference to {target}')
                directive.set('schemaLocation', PREFIX + quote(target))
                walk(target, target_ns, entry and include, depth + 1)

        walk(root_path, None, True)
        self.root = self.documents[root_path]

    def compile(self):
        documents = {PREFIX + quote(path): etree.tostring(document, encoding='utf-8')
                     for path, document in self.documents.items()}

        class Offline(etree.Resolver):
            def resolve(self, url, public_id, context):
                if url not in documents: raise ValueError(f'XSD location is not a project asset: {url}')
                return self.resolve_string(documents[url], context, base_url=url)

        parser = etree.XMLParser(resolve_entities=False, load_dtd=False, no_network=True, huge_tree=False)
        parser.resolvers.add(Offline())
        return etree.XMLSchema(etree.fromstring(documents[self.root.base], parser, base_url=self.root.base))
