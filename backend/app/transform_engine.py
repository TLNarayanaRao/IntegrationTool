"""Shared transformation contracts and transactional output planning."""
import copy
import json
import asyncio
import threading

from .script_transform import ScriptTransformError, _decode_payload, execute_details, _xml
from .schema_validation import schema_errors
from .retry_policy import retry_boolean


class TransformContractError(ScriptTransformError):
    fault_type = 'ValidationException'


def resolved_contracts(config, schemas=()):
    if not isinstance(config, dict): raise ScriptTransformError('Transform configuration must be an object')
    config = copy.deepcopy(config)
    if config.get('outputs') is not None and (not isinstance(config['outputs'], list) or any(not isinstance(item, dict) for item in config['outputs'])):
        raise ScriptTransformError('Transform outputs must be an array of target definitions')
    if not isinstance(config.get('libraries') or {}, dict): raise ScriptTransformError('Transform libraries must be a module/source object')
    assets = [item if isinstance(item, dict) else item.model_dump() for item in schemas]
    def resolve(item, prefix):
        identifier = item.get(prefix + 'SchemaId')
        if identifier and identifier != 'inline':
            asset = next((a for a in assets if identifier in (a.get('id'), a.get('name'))), None)
            if not asset: raise ScriptTransformError('Selected ' + prefix + ' schema was not found: ' + identifier)
            from .xsd_catalog import inherit_schema_selection
            text = asset.get('content') or ''
            if text.lstrip().startswith('<'):
                text = inherit_schema_selection(text, item.get(prefix + 'SchemaText') or item.get(prefix + 'Schema'))
            item[prefix + 'Schema'] = text
            item[prefix + 'SchemaText'] = text
            item[prefix + 'SchemaPath'] = asset.get('source_path') or asset.get('name') or ''
    for prefix in ('source', 'target'): resolve(config, prefix)
    for output in config.get('outputs') or []: resolve(output, 'target')
    config['_schemaAssets'] = assets
    return config


def validate_contract(value, config, prefix, mime=''):
    schema = config.get(prefix + 'SchemaText') or config.get(prefix + 'Schema')
    if schema is None or schema == '' or not retry_boolean(config.get('validate' + prefix.capitalize(), True)): return
    try:
        if isinstance(schema, str) and schema.lstrip().startswith('<'):
            from .data_formats import DataFormats, xsd_shape, xml_from_value
            from lxml import etree
            assets = config.get('_schemaAssets') or []
            bundle = (config.get(prefix + 'SchemaPath') or '', tuple((a.get('source_path') or a.get('name'), a.get('content')) for a in assets))
            if not isinstance(value, (str, bytes)):
                shape = xsd_shape(schema, bundle=bundle)
                name = shape.get('xml', {}).get('name') or 'root'
                inner = value.get(name) if isinstance(value, dict) and name in value else value
                value = etree.tostring(xml_from_value(name, inner, shape), encoding='unicode')
            DataFormats.validate_xml_document(value, schema, bundle)
            return
        document = _decode_payload(value, mime) if isinstance(value, (str, bytes)) and mime.split(';')[0].strip() == 'application/json' else value
        if isinstance(schema, str): schema = json.loads(schema)
        from referencing import Registry, Resource
        from referencing.jsonschema import DRAFT202012
        from .schema_validation import _offline_schema
        from urllib.parse import quote
        def uri(path): return 'https://mina.invalid/transform-schema/' + quote(str(path).replace('\\', '/').lstrip('/'), safe='/')
        registry = Registry(retrieve=_offline_schema)
        for asset in config.get('_schemaAssets') or []:
            try: definition = json.loads(asset.get('content') or '')
            except (ValueError, TypeError): continue
            if not isinstance(definition, (dict, bool)): continue
            resource = Resource.from_contents(definition, default_specification=DRAFT202012)
            registry = registry.with_resource(uri(asset.get('source_path') or asset.get('name')), resource)
            if isinstance(definition, dict) and definition.get('$id'): registry = registry.with_resource(definition['$id'], resource)
        if isinstance(schema, dict) and '$id' not in schema and config.get(prefix + 'SchemaPath'):
            schema = {**schema, '$id': uri(config[prefix + 'SchemaPath'])}
        errors = schema_errors(document, schema, registry=registry)
        if errors: raise ScriptTransformError('; '.join(errors[:10]))
    except Exception as exc:
        raise TransformContractError(prefix.capitalize() + ' schema validation failed: ' + str(exc)) from exc


def execute_plan(config, payload, attributes=None, variables=None, schemas=()):
    """Compute every result against the same snapshot; callers commit on success."""
    config = resolved_contracts(config, schemas)
    if not isinstance(config.get('variables') or {}, dict): raise ScriptTransformError('Transform variables must be an object')
    variables = {**(variables or {}), **(config.get('variables') or {})}
    source = config.get('payload', payload)
    attributes = config.get('attributes', attributes or {})
    validate_contract(source, config, 'source', config.get('inputMimeType') or '')
    outputs = config.get('outputs')
    legacy = not outputs
    if legacy:
        outputs = [{'target': config.get('outputTarget') or 'payload',
                    'name': config.get('outputVariable') or 'transformResult',
                    'script': config.get('script') or '%mina 2.0\noutput application/json\n---\npayload'}]
    plan = {'output': source, 'variables': {}, 'attributesChanged': False, 'outputs': []}
    targets = set()
    for output in outputs:
        target = output.get('target') or 'payload'
        name = str(output.get('name') or '').strip()
        key = (target, name if target == 'variable' else '')
        if target not in ('payload', 'attributes', 'variable') or target == 'variable' and not name:
            raise ScriptTransformError('Each output requires payload, attributes or a named variable target')
        if key in targets: raise ScriptTransformError('Duplicate transform output target: ' + str(key))
        targets.add(key)
        result = execute_details(str(output.get('script') or config.get('script') or ''),
            payload=copy.deepcopy(source), attributes=copy.deepcopy(attributes), variables=copy.deepcopy(variables),
            input_mime_type=config.get('inputMimeType') or '', libraries=config.get('libraries') or {})
        contract = {**config, **output}
        # A per-output contract replaces, rather than accidentally inheriting, another selected contract.
        if not legacy:
            for field in ('targetSchema', 'targetSchemaText', 'targetSchemaId', 'targetSchemaPath'):
                if field not in output: contract.pop(field, None)
        validate_contract(result['output'], contract, 'target', result['mimeType'])
        value = result['output']
        if target == 'attributes':
            if not isinstance(value, dict): raise ScriptTransformError('Attributes output must be an object')
            plan.update(attributes=value, attributesChanged=True)
        elif target == 'variable': plan['variables'][name] = value
        if target == 'payload' or legacy: plan['output'] = value
        plan['outputs'].append({'target': target, 'name': name, **result})
    return plan


def execute_activity(config, payload, attributes=None, variables=None, schemas=(), kind='script_transform', cancel=None, mapping_context=None):
    if retry_boolean(config.get('streamEnabled', False)):
        if config.get('outputs') and config.get('streamOutputFormat') == 'csv':
            raise ScriptTransformError('Multiple streamed targets require JSON or JSON Lines output envelopes')
        from .transform_stream import execute_file
        settings = {**config}
        # Stream contracts and scripts describe one record, never the complete file.
        def transform(record):
            if kind == 'script_transform':
                local = {**settings, 'payload': record, 'streamEnabled': False}
                plan = execute_plan(local, record, attributes, variables, schemas)
                if settings.get('outputs'):
                    return {'payload': plan['output'], 'attributes': plan.get('attributes', attributes or {}), 'variables': plan['variables']}
                return plan['output']
            from .mapper import execute, rewrite_references
            local = resolved_contracts(settings, schemas)
            local.setdefault('validateTarget', local.get('validateOutput', True))
            validate_contract(record, local, 'source', 'application/json')
            rules = copy.deepcopy(local.get('mappings') or [])
            if isinstance(rules, dict): rules = [{'target': key, 'source': value} for key, value in rules.items()]
            for rule in rules:
                for field in ('source', 'select'):
                    expression = rule.get(field)
                    if isinstance(expression, str) and expression.startswith('${') and expression.endswith('}'):
                        rule[field] = expression[2:-1]
                if isinstance(rule.get('condition'), str):
                    rule['condition'] = rewrite_references(rule['condition'], lambda expression: expression[2:-1])
                for branch in rule.get('whens') or []:
                    if isinstance(branch.get('condition'), str): branch['condition'] = rewrite_references(branch['condition'], lambda expression: expression[2:-1])
                    if isinstance(branch.get('source'), str) and branch['source'].startswith('${') and branch['source'].endswith('}'): branch['source'] = branch['source'][2:-1]
            value = execute({**(record if isinstance(record, dict) else {}), **(mapping_context or {}), 'input': record, 'last': record, 'vars': variables or {}, 'properties': (mapping_context or {}).get('properties', {})}, rules, local)
            validate_contract(value, local, 'target', 'application/json')
            return value
        result = execute_file(settings, transform, cancel)
        return {'output': result, 'variables': {}, 'attributesChanged': False, 'outputs': []}
    return execute_plan(config, payload, attributes, variables, schemas)


async def execute_activity_async(*args, **kwargs):
    cancelled = threading.Event()
    task = asyncio.create_task(asyncio.to_thread(execute_activity, *args, **kwargs, cancel=cancelled.is_set))
    try: return await asyncio.shield(task)
    except asyncio.CancelledError:
        cancelled.set()
        # Drain the owned worker so it cannot silently commit after Stop.
        try: await asyncio.shield(task)
        except Exception: pass
        raise
