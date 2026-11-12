"""Resolve XSD dependencies strictly from the current project's schema assets."""
import posixpath
import re
from functools import lru_cache
from urllib.parse import quote, unquote, urlsplit

from lxml import etree

XS = '{http://www.w3.org/2001/XMLSchema}'
PREFIX = 'https://mina.invalid/project-xsd/'
LIMIT = 8 * 1024**2
SELECTION_NS = 'urn:mina:schema-selection'
SELECTION = '{'+SELECTION_NS+'}'


@lru_cache(maxsize=8)
def schema_selection(source):
    if not isinstance(source,str) or not source.lstrip().startswith('<'):return '', ''
    if len(source.encode())>LIMIT or re.search(r'<!\s*(?:DOCTYPE|ENTITY)\b',source,re.I):
        raise ValueError('Unsafe or oversized XSD selection document')
    root=etree.fromstring(source.encode(),etree.XMLParser(resolve_entities=False,load_dtd=False,no_network=True))
    if root.tag!=XS+'schema':return '', ''
    return root.get(SELECTION+'structure',''),root.get(SELECTION+'element','')


def inherit_schema_selection(source, snapshot):
    """Reload a project asset while preserving the activity's selected entry."""
    if not isinstance(snapshot,str):return source
    choice,_=schema_selection(snapshot)
    if not choice:return source
    schema_selection(source)  # Apply the same offline/size checks before parsing.
    root=etree.fromstring(source.encode(),etree.XMLParser(resolve_entities=False,load_dtd=False,no_network=True))
    kind,_,qualified=choice.partition('|')
    namespace=root.get('targetNamespace') or ''
    name=qualified.rsplit('}',1)[-1]
    if qualified!='{'+namespace+'}'+name or kind not in ('type','element'):
        raise ValueError('Selected XSD structure does not belong to this schema')
    for node in list(root):
        if node.get(SELECTION+'generated'):root.remove(node)
    declaration=next((node for node in root if node.tag==XS+('complexType' if kind=='type' else 'element') and node.get('name')==name),None)
    if declaration is None:raise ValueError('Selected XSD structure is no longer available: '+name)
    if kind=='type':
        names={node.get('name') for node in root if node.tag==XS+'element'}
        element_name=name
        while element_name in names:element_name+='Root'
        prefix=next((prefix for prefix,uri in root.nsmap.items() if prefix and uri==namespace),None) if namespace else None
        if namespace and not prefix:
            prefix='minaType';index=1
            while prefix in root.nsmap:prefix='minaType'+str(index);index+=1
            # QName values do not count as namespace usage when lxml reparents
            # a node. Bind the type prefix on the schema root, not the child.
            replacement=etree.Element(root.tag,attrib=root.attrib,nsmap={**root.nsmap,prefix:namespace})
            replacement.text=root.text;replacement.extend(list(root));root=replacement
        if not namespace and root.nsmap.get(None)=='http://www.w3.org/2001/XMLSchema':
            # A no-namespace type cannot use the schema's default XSD namespace
            # for its QName. Serialize schema tags with an explicit prefix.
            maps={key:value for key,value in root.nsmap.items() if key is not None}
            xs_prefix=next((key for key,value in maps.items() if value=='http://www.w3.org/2001/XMLSchema'),None)
            if not xs_prefix:
                xs_prefix='minaXsd'
                while xs_prefix in maps:xs_prefix+='X'
                maps[xs_prefix]='http://www.w3.org/2001/XMLSchema'
            for node in root.iter():
                if not isinstance(node.tag,str) or not node.tag.startswith(XS) or node.nsmap.get(None)!='http://www.w3.org/2001/XMLSchema':continue
                for attribute in ('type','base','ref','itemType','memberTypes','substitutionGroup','refer'):
                    if node.get(attribute):node.set(attribute,' '.join(xs_prefix+':'+value if ':' not in value else value for value in node.get(attribute).split()))
            replacement=etree.Element(root.tag,attrib=root.attrib,nsmap=maps)
            replacement.text=root.text;replacement.extend(list(root));root=replacement
        declaration=etree.Element(XS+'element',nsmap={None:''} if not namespace and root.nsmap.get(None) else None)
        declaration.set('name',element_name);declaration.set('type',prefix+':'+name if prefix else name)
        declaration.set(SELECTION+'generated','true')
    first=next((node for node in root if node.tag in {XS+local for local in ('element','complexType','simpleType','group','attributeGroup','attribute')}),None)
    if first is not declaration:
        if declaration.getparent() is root:root.remove(declaration)
        root.insert(list(root).index(first) if first is not None else len(root),declaration)
    root.set(SELECTION+'structure',choice)
    root.set(SELECTION+'element','{'+namespace+'}'+declaration.get('name'))
    return etree.tostring(root,encoding='unicode')


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
        selected=self.root.get(SELECTION+'element')
        if selected:
            declarations={}
            owners={}
            for (_,namespace),document in self.scopes.items():
                for node in document:
                    if isinstance(node.tag,str) and node.tag.startswith(XS) and node.get('name'):
                        declarations[(namespace or '',etree.QName(node).localname,node.get('name'))]=node
                        owners[node]=namespace or ''
            needed=set()
            # xsi:type may name a derived type that is not referenced directly
            # by the selected element. Retain those valid schema alternatives.
            derived={}
            for declaration in set(declarations.values()):
                for node in declaration.iter():
                    if node.tag not in (XS+'extension',XS+'restriction') or not node.get('base'):continue
                    prefix,colon,name=node.get('base').rpartition(':')
                    namespace=node.nsmap.get(prefix if colon else None) or (owners[declaration] if not declaration.getroottree().getroot().get('targetNamespace') else '')
                    for kind in ('complexType','simpleType'):
                        base=declarations.get((namespace,kind,name))
                        if base is not None:derived.setdefault(base,[]).append(declaration)
            queue=[node for (namespace,kind,name),node in declarations.items()
                   if kind=='element' and '{'+namespace+'}'+name==selected]
            if not queue:raise ValueError('Selected XSD root is unavailable: '+selected)
            while queue:
                declaration=queue.pop()
                if declaration in needed:continue
                needed.add(declaration)
                queue.extend(derived.get(declaration,()))
                for node in declaration.iter():
                    if not isinstance(node.tag,str):continue
                    for attribute,kinds in (('type',('complexType','simpleType')),('base',('complexType','simpleType')),
                            ('itemType',('simpleType',)),('memberTypes',('simpleType',)),('ref',(etree.QName(node).localname,)),
                            ('substitutionGroup',('element',))):
                        for reference in node.get(attribute,'').split():
                            prefix,colon,name=reference.rpartition(':')
                            namespace=node.nsmap.get(prefix if colon else None) or (owners[declaration] if not declaration.getroottree().getroot().get('targetNamespace') else '')
                            if namespace=='http://www.w3.org/2001/XMLSchema':continue
                            for kind in kinds:
                                target=declarations.get((namespace,kind,name))
                                if target is not None:queue.append(target)
            # Compile only the selected declaration graph. Unselected roots are
            # retained in the saved source so users can switch selections later.
            for document in self.documents.values():
                for node in list(document):
                    if node in owners and node not in needed:document.remove(node)
        documents = {PREFIX + quote(path): etree.tostring(document, encoding='utf-8')
                     for path, document in self.documents.items()}

        class Offline(etree.Resolver):
            def resolve(self, url, public_id, context):
                if url not in documents: raise ValueError(f'XSD location is not a project asset: {url}')
                return self.resolve_string(documents[url], context, base_url=url)

        parser = etree.XMLParser(resolve_entities=False, load_dtd=False, no_network=True, huge_tree=False)
        parser.resolvers.add(Offline())
        return etree.XMLSchema(etree.fromstring(documents[self.root.base], parser, base_url=self.root.base))
