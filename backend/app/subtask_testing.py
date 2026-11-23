"""Resolve and validate direct Subtask test input against its Start interface."""
import json
from lxml import etree

from .api_docs import sample
from .data_formats import DataFormats, json_from_xml, xml_from_value, xsd_shape
from .faults import MinaFault
from .mapper import flatten_schema
from .schema_validation import schema_errors
from .xsd_catalog import inherit_schema_selection, schema_selection


def subtask_start(task):
    if task.kind != 'subtask' or task.library_origin:
        raise ValueError('Choose an editable Subtask to test directly.')
    starts = [activity for activity in task.activities if activity.type == 'start']
    if len(starts) != 1 or any(edge.target == starts[0].id for edge in task.transitions):
        raise ValueError('A Subtask test needs exactly one Start activity with no incoming transition.')
    return starts[0]


def subtask_input(project, task, start, payload=None, *, describe=False, input_format='json'):
    config = start.config
    schema_id = config.get('interfaceSchemaId')
    snapshot = config.get('interfaceSchemaText') or task.input_schema
    contract = snapshot
    if schema_id:
        asset = next((item for item in project.schemas if schema_id in (item.id, item.name)), None)
        if not asset:
            raise ValueError('The schema selected on Start was not found.')
        contract = inherit_schema_selection(asset.content, snapshot)
    xml = isinstance(contract, str) and contract.lstrip().startswith('<')
    if input_format == 'xml' and not xml:
        raise ValueError('XML input requires an XSD on the Subtask Start activity.')
    if contract is None or contract == {} or isinstance(contract, str) and not contract.strip():
        return {'format': 'none', 'example': {}, 'fields': [], 'errors': []}

    title = asset.name if schema_id else 'Start input schema'
    errors = []
    result = {'format': 'xsd' if xml else 'json', 'name': title, 'errors': errors}
    if xml:
        bundle = DataFormats.schema_bundle({'schemaId': schema_id}, {'project': project}, contract)
        selected = schema_selection(contract)[1]
        shape = xsd_shape(contract, selected.removeprefix('{}'), bundle)
        root = shape['xml']['name']
        namespace = shape['xml'].get('namespace')
        expected_root = selected or (f'{{{namespace}}}{root}' if namespace else root)
        result['root'] = expected_root.removeprefix('{}')
        definition = {'type': 'object', 'properties': {root: shape}, 'required': [root], 'additionalProperties': False}
        if not describe and input_format == 'xml':
            if not isinstance(payload, str) or not payload.strip():
                raise ValueError('Enter XML or select an XML file.')
            try:
                document = DataFormats.validate_xml_document(payload, contract, bundle, expected_root=expected_root)
                result['input'] = {root: json_from_xml(document, shape, tree_input=True)}
            except (ValueError, TypeError, etree.Error, MinaFault) as error:
                errors.append(str(error))
        elif not describe:
            errors.extend(schema_errors(payload, definition))
            if not errors:
                try:
                    document = xml_from_value(root, payload[root], shape, tree_input=True)
                    DataFormats.validate_xml_document(etree.tostring(document), contract, bundle)
                except (ValueError, TypeError, etree.Error, MinaFault) as error:
                    errors.append(str(error))
    else:
        definition = json.loads(contract) if isinstance(contract, str) else contract
        if not isinstance(definition, (dict, bool)):
            raise ValueError('Start requires a JSON Schema object, a boolean schema, or an XSD.')
        if not describe:
            errors.extend(schema_errors(payload, definition))
    if describe:
        result['example'] = sample(definition)
        result['fields'] = flatten_schema(definition)[:100]
    return result
