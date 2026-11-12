"""Resolve named Mapper source views without changing the original source."""
import json
import re
from copy import deepcopy


CARDINALITIES = {'?': (0, 1), '1': (1, 1), '*': (0, None), '+': (1, None)}
PATH = re.compile(r'[\w@#-]+(?:(?:\[\d+\])|(?:\.[\w@#-]+))*')
ALIAS = re.compile(r'[A-Za-z_][A-Za-z0-9_-]*')


def validate_source_coercions(settings):
    if not isinstance(settings, dict) or len(settings) > 100:
        raise ValueError('Mapper source coercions must be an object with at most 100 named views')
    for name, rule in settings.items():
        if (not isinstance(name, str) or not ALIAS.fullmatch(name) or not isinstance(rule, dict)
                or not isinstance(rule.get('path'), str) or not PATH.fullmatch(rule['path'])
                or rule['path'].split('.')[0] == 'coerced' or not isinstance(rule.get('cardinality', '?'), str)
                or rule.get('cardinality', '?') not in CARDINALITIES):
            raise ValueError(f'Invalid Mapper source coercion {name!r}')
        contract = rule.get('schema')
        if contract is not None and (not isinstance(contract, (dict, str)) or not contract):
            raise ValueError(f'Mapper source coercion {name!r} requires a valid JSON Schema or XSD')
        type_name = rule.get('type')
        if type_name and (not isinstance(type_name, str) or not ALIAS.fullmatch(type_name)
                          or not isinstance(contract, str) or not contract.lstrip().startswith('<')):
            raise ValueError(f'Mapper source coercion {name!r} requires a named XSD complex type')
    return settings


def source_view(value, rule, name, check, documents=None):
    """Validate each occurrence and preserve, widen, or narrow its shape explicitly."""
    from .mapper import validate_output

    items = value if isinstance(value, list) else [] if value is None else [value]
    cardinality = rule.get('cardinality', '?')
    minimum, maximum = CARDINALITIES[cardinality]
    if len(items) < minimum or maximum is not None and len(items) > maximum:
        raise ValueError(f'Mapper source coercion {name!r}: cardinality {cardinality} rejects {len(items)} occurrences')
    contract = rule.get('schema')
    xml = isinstance(contract, str) and contract.lstrip().startswith('<')
    if isinstance(contract, str) and not xml:
        contract = json.loads(contract)
        if not isinstance(contract, dict) or not contract:
            raise ValueError(f'Mapper source coercion {name!r} requires a JSON Schema object')
    if xml:
        from .mapper_xml import element_value, etree, parse_xml
        schema = parse_xml(contract, documents)
        selected_root=''
        if 'urn:mina:schema-selection' in contract and not rule.get('type'):
            from .xsd_catalog import schema_selection
            from .data_formats import compiled_xsd
            selected_root=schema_selection(contract)[1]
            bundle=(rule.get('schemaPath') or '',tuple((documents or {}).items())) if documents else ()
            validator,_=compiled_xsd(contract,bundle)
        else:validator = etree.XMLSchema(schema)
        namespace, type_name = schema.get('targetNamespace'), rule.get('type')
        if type_name and not any(node.get('name') == type_name for node in schema.findall('{http://www.w3.org/2001/XMLSchema}complexType')):
            raise ValueError(f'Mapper source coercion {name!r}: unknown XSD complex type {type_name!r}')
    result = []
    for item in items:
        check()
        if xml:
            root = parse_xml(item)
            candidate = root
            if type_name:
                nsmap = dict(root.nsmap)
                prefix = 'mina-type'
                while prefix in nsmap:
                    prefix += '-'
                if namespace:
                    nsmap[prefix] = namespace
                candidate = etree.Element(root.tag, nsmap=nsmap, attrib=root.attrib)
                candidate.text = root.text
                candidate.extend(deepcopy(child) for child in root)
                candidate.set('{http://www.w3.org/2001/XMLSchema-instance}type',
                              f'{prefix}:{type_name}' if namespace else type_name)
            errors = (['Expected selected XSD root '+selected_root] if selected_root and root.tag!=(selected_root[2:] if selected_root.startswith('{}') else selected_root)
                      else [] if validator.validate(candidate) else [error.message for error in list(validator.error_log)[:5]])
            item = element_value(root, local_names=True)
        else:
            errors = validate_output(item, contract, check) if contract else []
        if errors:
            raise ValueError(f'Mapper source coercion {name!r}: ' + '; '.join(errors[:5]))
        result.append(item)
    return result if maximum is None else result[0] if result else None
