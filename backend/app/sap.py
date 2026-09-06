from __future__ import annotations
import json, os, re, uuid
from xml.etree import ElementTree as ET
from typing import Any
from xml.sax.saxutils import escape
from .java_bridge import JavaBridgeError, invoke as invoke_java, start_sap_listener, SapJcoListener

class SapAdapter:
    """SAP ECC adapter. External mode uses SAP's separately licensed Java Connector (JCo)."""
    def __init__(self): self.sessions: dict[str, Any] = {}; self.listeners: dict[str, SapJcoListener] = {}; self._listener_start_lock = __import__('asyncio').Lock()

    @staticmethod
    def _mode(cfg: dict) -> str:
        return str(cfg.get('mode') or 'external').strip().lower()

    @staticmethod
    def _connection_type(cfg: dict) -> str:
        return str(cfg.get('connectionType') or 'dedicated').strip().lower()

    @staticmethod
    def _xml_name(tag: str) -> str:
        return tag.rsplit('}', 1)[-1]

    @classmethod
    def _xml_to_json(cls, element: ET.Element) -> Any:
        children = list(element)
        if not children:
            return (element.text or '').strip()
        result: dict[str, Any] = {}
        for child in children:
            name = cls._xml_name(child.tag)
            value = cls._xml_to_json(child)
            if name in result: result[name] = result[name] if isinstance(result[name], list) else [result[name]]; result[name].append(value)
            else: result[name] = value
        if element.attrib: result['_attributes'] = dict(element.attrib)
        return result

    @staticmethod
    def _json_to_xml(value: Any, root: str = 'IDoc') -> str:
        def build(parent: ET.Element, name: str, item: Any) -> None:
            node = ET.SubElement(parent, re.sub(r'[^A-Za-z0-9_.-]', '_', str(name)) or 'item')
            if isinstance(item, dict):
                for key, child in item.items():
                    if key != '_attributes': build(node, key, child)
                for key, attr in (item.get('_attributes') or {}).items(): node.set(str(key), str(attr))
            elif isinstance(item, list):
                parent.remove(node)
                for child in item: build(parent, name, child)
            elif item is not None: node.text = str(item)
        container = ET.Element(root)
        if isinstance(value, dict):
            for key, item in value.items(): build(container, key, item)
        else: container.text = '' if value is None else str(value)
        return ET.tostring(container, encoding='unicode')

    @classmethod
    def _segment_field_definitions(cls, fields: list[dict] | None, segments: list[dict] | None) -> dict[str, list[dict]]:
        """Index SAP field metadata by both segment type and segment definition.

        IDOC_DATA_REC_40 uses the segment definition name (for example
        E2BPE1MATHEAD002), while IDOCTYPE_READ_COMPLETE field rows commonly
        use the logical segment type (E1BPE1MATHEAD). Supporting both names is
        required across ECC releases.
        """
        aliases: dict[str, set[str]] = {}
        for segment in segments or []:
            if not isinstance(segment, dict):
                continue
            logical = str(segment.get('SEGMENTTYP') or segment.get('SEGMENTTYPE') or '').strip().upper()
            definition = str(segment.get('SEGMENTDEF') or segment.get('SEGMENTDEFN') or '').strip().upper()
            names = {name for name in (logical, definition) if name}
            for name in names:
                aliases.setdefault(name, set()).update(names)
        indexed: dict[str, list[dict]] = {}
        for field in fields or []:
            if not isinstance(field, dict):
                continue
            segment = str(field.get('SEGMENTTYP') or field.get('SEGMENTTYPE') or field.get('SEGMENT') or '').strip().upper()
            name = str(field.get('FIELDNAME') or field.get('FIELDNAM') or field.get('FIELD') or '').strip()
            if not segment or not name:
                continue
            for alias in aliases.get(segment, {segment}):
                indexed.setdefault(alias, []).append(field)
        for name in indexed:
            indexed[name].sort(key=lambda item: int(str(item.get('FIELD_POS') or '0').strip() or 0))
        return indexed

    @staticmethod
    def _segment_logical_names(segments: list[dict] | None) -> dict[str, str]:
        names: dict[str, str] = {}
        for segment in segments or []:
            if not isinstance(segment, dict):
                continue
            logical = str(segment.get('SEGMENTTYP') or segment.get('SEGMENTTYPE') or '').strip()
            definition = str(segment.get('SEGMENTDEF') or segment.get('SEGMENTDEFN') or '').strip()
            if logical:
                names[logical.upper()] = logical
            if definition and logical:
                names[definition.upper()] = logical
        return names

    @classmethod
    def _decode_segment_fields(cls, segment_name: str, sdata: Any, row: dict, field_index: dict[str, list[dict]]) -> dict[str, str]:
        raw = '' if sdata is None else str(sdata)
        definitions = field_index.get(str(segment_name or '').strip().upper(), [])
        if not definitions:
            return {}
        # Some SAP RFC table variants prepend DOCNUM to SDATA even though the
        # metadata byte offsets start at the first byte of the segment data.
        # Remove it using the row value when available, with a conservative
        # 16-digit fallback for flattened listener payloads.
        docnum = str(row.get('DOCNUM') or '').strip()
        leading = len(raw) - len(raw.lstrip())
        if docnum and raw[leading:].startswith(docnum):
            raw = raw[leading + len(docnum):]
        if docnum and raw[3:21] == docnum:
            raw = raw[:3] + raw[21:]
        # Do not strip a numeric prefix heuristically. Valid IDoc fields often
        # begin with digits (for example ARTMAS FUNCTION=005 and MATERIAL).
        # Only a separately supplied DOCNUM is safe to remove here.
        values: dict[str, str] = {}
        for field in definitions:
            name = re.sub(r'[^A-Za-z0-9_.-]', '_', str(field.get('FIELDNAME') or field.get('FIELDNAM') or field.get('FIELD') or '').strip())
            if not name:
                continue
            try:
                # SAP BYTE_FIRST/BYTE_LAST are 1-based positions in the full
                # IDoc record; the SDATA value begins at full-record byte 64.
                start = max(0, int(str(field.get('BYTE_FIRST') or '').strip()) - 64)
                end = int(str(field.get('BYTE_LAST') or '').strip()) - 63
                if end <= start:
                    continue
                # BYTE_FIRST/BYTE_LAST are authoritative.  INTLEN/EXTLEN is
                # retained as a second guard for older metadata exports that
                # contain an inconsistent byte range.
                try:
                    declared_length = int(str(field.get('INTLEN') or field.get('EXTLEN') or '').strip())
                    if declared_length > 0:
                        end = min(end, start + declared_length)
                except (TypeError, ValueError):
                    pass
                # Emit every field defined for the segment. Empty values are
                # meaningful in an IDoc schema and must remain addressable by
                # mappings even when SAP sends a shorter/non-padded SDATA row.
                values[name] = raw[start:min(end, len(raw))].rstrip() if start < len(raw) else ''
            except (TypeError, ValueError):
                continue
        return values

    @classmethod
    def _schema_metadata(cls, schema: str | None) -> tuple[list[dict], list[dict]]:
        """Derive field offsets from a fetched XSD when RFC metadata is absent.

        SAP's RFC metadata is preferred. The XSD fallback keeps older/imported
        projects parseable and uses each xsd:maxLength, so values can never
        spill into the following field.
        """
        if not schema or not isinstance(schema, str):
            return [], []
        try:
            root = ET.fromstring(schema)
        except ET.ParseError:
            return [], []
        xs = 'http://www.w3.org/2001/XMLSchema'
        r3 = 'http://www.tibco.com/xmlns/sapscalar/2015/05'
        local = lambda tag: cls._xml_name(tag)
        types = {str(node.get('name')): node for node in root.findall(f'{{{xs}}}complexType') if node.get('name')}
        segment_defs: dict[str, str] = {}
        for node in root.iter(f'{{{xs}}}element'):
            logical = node.get(f'{{{r3}}}segmentType')
            type_name = str(node.get('type') or '').rsplit('}', 1)[-1].removesuffix('_Type')
            if logical and type_name:
                segment_defs[str(logical)] = type_name
        segments = [{'SEGMENTTYP': logical, 'SEGMENTDEF': definition} for logical, definition in segment_defs.items()]
        fields: list[dict] = []
        for logical, definition in segment_defs.items():
            type_node = types.get(definition + '_Type') or types.get(definition)
            if type_node is None:
                continue
            sequence = type_node.find(f'{{{xs}}}sequence')
            if sequence is None:
                continue
            offset = 64
            field_pos = 1
            for element in list(sequence):
                if local(element.tag) != 'element' or not element.get('name'):
                    continue
                name = str(element.get('name'))
                if name == 'EDI_DD40' or element.get('type'):
                    continue
                restriction = element.find(f'.//{{{xs}}}restriction')
                max_length = restriction.find(f'{{{xs}}}maxLength') if restriction is not None else None
                try:
                    length = int(max_length.get('value')) if max_length is not None else 0
                except (TypeError, ValueError):
                    length = 0
                if length <= 0:
                    continue
                fields.append({'SEGMENTTYP': logical, 'FIELDNAME': name, 'FIELD_POS': f'{field_pos:06d}', 'BYTE_FIRST': f'{offset:06d}', 'BYTE_LAST': f'{offset + length - 1:06d}', 'INTLEN': f'{length:06d}'})
                offset += length
                field_pos += 1
        return fields, segments

    @classmethod
    def _metadata_for_idoc(cls, selected_idoc: dict) -> tuple[list[dict], list[dict]]:
        selected_idoc = selected_idoc if isinstance(selected_idoc, dict) else {}
        fields = selected_idoc.get('fields') or []
        segments = selected_idoc.get('segments') or []
        if fields and segments:
            return fields, segments
        schema_fields, schema_segments = cls._schema_metadata(selected_idoc.get('schema') or selected_idoc.get('idocSchema'))
        return fields or schema_fields, segments or schema_segments

    @classmethod
    def _expand_sdata_xml(cls, xml_text: str, fields: list[dict] | None, segments: list[dict] | None, schema: str | None = None) -> str:
        """Upgrade an older XML IDoc containing SDATA into named fields."""
        root = ET.fromstring(xml_text)
        if not fields or not segments:
            schema_fields, schema_segments = cls._schema_metadata(schema)
            fields, segments = fields or schema_fields, segments or schema_segments
        field_index = cls._segment_field_definitions(fields, segments)
        logical_names = cls._segment_logical_names(segments)
        # Legacy captured JSON sometimes repeats the same DOCNUM inside every
        # SDATA row. Only treat a numeric prefix as DOCNUM when the same value
        # is observed in multiple segments; a single numeric field must never
        # be guessed or shifted.
        sdata_nodes = [(node, next((child for child in list(node) if cls._xml_name(child.tag) == 'SDATA'), None)) for node in root.iter()]
        candidates: list[tuple[str, int]] = []
        for _, sdata_node in sdata_nodes:
            raw = str(sdata_node.text or '') if sdata_node is not None else ''
            if len(raw) >= 18 and raw[:18].isdigit(): candidates.append((raw[:18], 0))
            if len(raw) >= 21 and raw[3:21].isdigit(): candidates.append((raw[3:21], 3))
        repeated = {}
        for candidate in candidates: repeated[candidate] = repeated.get(candidate, 0) + 1
        repeated_after_function = {key: count for key, count in repeated.items() if key[1] == 3 and count > 1}
        repeated_at_start = {key: count for key, count in repeated.items() if key[1] == 0 and count > 1}
        if repeated_after_function:
            legacy_docnum = max(repeated_after_function.items(), key=lambda item: item[1])[0]
        elif repeated_at_start:
            legacy_docnum = max(repeated_at_start.items(), key=lambda item: item[1])[0]
        else:
            legacy_docnum = None
        for node in list(root.iter()):
            original_name = cls._xml_name(node.tag)
            sdata_node = next((child for child in list(node) if cls._xml_name(child.tag) == 'SDATA'), None)
            if sdata_node is not None:
                row = {}
                raw = str(sdata_node.text or '')
                if legacy_docnum and (raw.startswith(legacy_docnum[0]) if legacy_docnum[1] == 0 else raw[3:21] == legacy_docnum[0]):
                    row['DOCNUM'] = legacy_docnum[0]
                decoded = cls._decode_segment_fields(original_name, sdata_node.text, row, field_index)
                if decoded:
                    node.remove(sdata_node)
                    for field_name, value in decoded.items():
                        child = ET.SubElement(node, field_name)
                        child.text = value
            # Metadata describes the logical E1 segment while SAP RFC rows
            # and older captured XML commonly use the physical E2 definition.
            # Normalize it so JSON/XML output matches the fetched XSD.
            logical_name = logical_names.get(original_name.upper())
            if logical_name and original_name.upper() != logical_name.upper():
                node.tag = logical_name
        return ET.tostring(root, encoding='unicode')

    @classmethod
    def _xml_to_raw_idoc(cls, value: Any, idoc_type: str, fields: list[dict] | None, segments: list[dict] | None, schema: str | None = None) -> dict:
        """Render named XML/JSON fields back into SAP fixed-width IDoc rows.

        The renderer is deliberately metadata-driven.  A field is truncated
        to its SAP byte range and a segment is padded to its declared length;
        no value can overwrite the next field or grow an SDATA record.
        """
        if not fields or not segments:
            schema_fields, schema_segments = cls._schema_metadata(schema)
            fields, segments = fields or schema_fields, segments or schema_segments
        field_index = cls._segment_field_definitions(fields, segments)
        logical_names = cls._segment_logical_names(segments)
        definition_lengths: dict[str, int] = {}
        for segment in segments or []:
            if not isinstance(segment, dict):
                continue
            names = [str(segment.get(key) or '').strip().upper() for key in ('SEGMENTTYP', 'SEGMENTTYPE', 'SEGMENTDEF', 'SEGMENTDEFN')]
            try:
                length = int(str(segment.get('SEGLEN') or segment.get('SEGMENT_LENGTH') or '').strip())
            except (TypeError, ValueError):
                length = 0
            if length > 0:
                for name in names:
                    if name:
                        definition_lengths[name] = length

        if isinstance(value, dict) and ('control' in value or 'data' in value):
            document = value
        else:
            if isinstance(value, dict) and idoc_type in value:
                value = value[idoc_type]
            if isinstance(value, str):
                try:
                    document = {'xml': ET.fromstring(value)}
                except ET.ParseError:
                    try:
                        value = json.loads(value)
                    except ValueError:
                        return {'control': {}, 'data': [], 'rawIDoc': value}
            if isinstance(value, dict) and 'xml' not in locals():
                xml_text = cls._json_to_xml(value, idoc_type or 'IDoc')
                document = {'xml': ET.fromstring(xml_text)}
        if isinstance(document, dict) and 'xml' in document:
            xml_root = document['xml']
            idoc_node = next((node for node in xml_root.iter() if cls._xml_name(node.tag) == 'IDOC'), xml_root)
            control_node = next((node for node in list(idoc_node) if cls._xml_name(node.tag) == 'EDI_DC40'), None)
            control = {cls._xml_name(child.tag): (child.text or '') for child in list(control_node or [])}
            segment_nodes = []
            def walk(parent: ET.Element, parent_number: str = '0') -> None:
                for child in list(parent):
                    name = cls._xml_name(child.tag)
                    if name == 'EDI_DC40':
                        continue
                    number = str(len(segment_nodes) + 1)
                    segment_nodes.append((number, parent_number, child))
                    walk(child, number)
            walk(idoc_node)
            rows = []
            for number, parent_number, node in segment_nodes:
                logical = cls._xml_name(node.tag)
                physical = next((str(segment.get('SEGMENTDEF') or segment.get('SEGMENTDEFN')).strip() for segment in segments or [] if str(segment.get('SEGMENTTYP') or segment.get('SEGMENTTYPE') or '').strip().upper() == logical.upper() and (segment.get('SEGMENTDEF') or segment.get('SEGMENTDEFN'))), logical)
                definitions = field_index.get(logical.upper()) or field_index.get(physical.upper()) or []
                max_end = max([int(str(field.get('BYTE_LAST') or '0')) - 63 for field in definitions if str(field.get('BYTE_LAST') or '').isdigit()] or [0])
                segment_length = definition_lengths.get(physical.upper()) or definition_lengths.get(logical.upper()) or max_end
                chars = [' '] * max(0, segment_length)
                supplied_sdata = next((child.text or '' for child in list(node) if cls._xml_name(child.tag) == 'SDATA'), '')
                if supplied_sdata:
                    chars[:min(len(chars), len(supplied_sdata))] = list(supplied_sdata[:len(chars)])
                child_values = {cls._xml_name(child.tag).upper(): (child.text or '') for child in list(node) if cls._xml_name(child.tag) != 'SDATA'}
                for field in definitions:
                    name = str(field.get('FIELDNAME') or field.get('FIELDNAM') or field.get('FIELD') or '').strip()
                    if not name or name.upper() not in child_values:
                        continue
                    try:
                        start = max(0, int(str(field.get('BYTE_FIRST') or '64')) - 64)
                        end = int(str(field.get('BYTE_LAST') or '63')) - 63
                    except (TypeError, ValueError):
                        continue
                    if end <= start or start >= len(chars):
                        continue
                    text = child_values[name.upper()][:max(0, end - start)]
                    chars[start:min(end, len(chars))] = list(text.ljust(min(end, len(chars)) - start))
                rows.append({'SEGNAM': physical, 'SEGNUM': number, 'PSGNUM': parent_number, 'SDATA': ''.join(chars)})
            return {'control': control, 'data': rows}
        return {'control': document.get('control') or {}, 'data': document.get('data') or []}

    @classmethod
    def _idoc_structured_to_xml(cls, structured: dict, idoc_type: str = '', fields: list[dict] | None = None, segments: list[dict] | None = None, schema: str | None = None) -> str:
        """Convert the JCo IDOC_INBOUND_ASYNCHRONOUS result to IDoc XML.

        JCo exposes an inbound IDoc as an import structure plus rows in
        IDOC_DATA_REC_40/30.  That is an RFC representation, not the XML
        representation expected by the IDoc parser and mapping canvas.  Keep
        the segment hierarchy from PSGNUM/SEGNUM and retain SDATA when field
        offsets are not available.  This produces stable, parseable XML
        without pretending that the fixed-width SDATA can safely be split
        into fields without the matching SAP segment definition.
        """
        if not isinstance(structured, dict):
            return cls._json_to_xml(structured, idoc_type or 'IDoc')
        root_name = re.sub(r'[^A-Za-z0-9_.-]', '_', str(idoc_type or 'IDoc')) or 'IDoc'
        root = ET.Element(root_name)
        idoc_node = ET.SubElement(root, 'IDOC')

        control = structured.get('control') or {}
        if isinstance(control, dict) and control:
            control_node = ET.SubElement(idoc_node, 'EDI_DC40')
            for key, value in control.items():
                if value is not None and str(value) != '':
                    child = ET.SubElement(control_node, re.sub(r'[^A-Za-z0-9_.-]', '_', str(key)) or 'field')
                    child.text = str(value)

        rows = structured.get('data') or []
        if not isinstance(rows, list):
            rows = [rows]
        nodes: dict[str, ET.Element] = {}
        parents: dict[str, str] = {}
        pending: list[tuple[str, ET.Element, str]] = []
        if not fields or not segments:
            schema_fields, schema_segments = cls._schema_metadata(schema)
            fields, segments = fields or schema_fields, segments or schema_segments
        field_index = cls._segment_field_definitions(fields, segments)
        logical_names = cls._segment_logical_names(segments)
        for index, row in enumerate(rows):
            if not isinstance(row, dict):
                continue
            name = str(row.get('SEGNAM') or row.get('SEGMENT') or row.get('SEGMENTNAME') or 'SEGMENT').strip()
            logical_name = logical_names.get(name.upper(), name)
            tag = re.sub(r'[^A-Za-z0-9_.-]', '_', logical_name) or 'SEGMENT'
            number = str(row.get('SEGNUM') or index + 1).strip()
            parent_number = str(row.get('PSGNUM') or '').strip().lstrip('0') or '0'
            node = ET.Element(tag, {'SEGMENT': '1'})
            sdata = row.get('SDATA')
            decoded = cls._decode_segment_fields(name, sdata, row, field_index)
            if decoded:
                for field_name, value in decoded.items():
                    child = ET.SubElement(node, field_name)
                    child.text = value
            elif sdata is not None and str(sdata) != '':
                data_node = ET.SubElement(node, 'SDATA')
                data_node.text = str(sdata)
            nodes[number.lstrip('0') or str(index + 1)] = node
            parents[number.lstrip('0') or str(index + 1)] = parent_number
            pending.append((number.lstrip('0') or str(index + 1), node, parent_number))
        for number, node, parent_number in pending:
            parent = nodes.get(parent_number)
            (parent if parent is not None else idoc_node).append(node)
        return ET.tostring(root, encoding='unicode')

    @staticmethod
    def _release(value: Any) -> str:
        release = str(value or '').strip().lower().replace('.', '')
        if release in ('', 'current', 'latest', 'auto', 'autodetect'): return ''
        if release not in ('720', '730'): raise ValueError('SAP release must be current, 720, or 730')
        return release

    def _params(self, cfg: dict) -> dict:
        connection_type = self._connection_type(cfg)
        params = {
            'client': cfg.get('client'), 'user': cfg.get('username') or cfg.get('user'),
            'passwd': cfg.get('password') or cfg.get('passwd'), 'lang': cfg.get('language') or 'EN',
            'saprouter': cfg.get('sapRouter') or cfg.get('saprouter'),
        }
        if connection_type in ('logongroup', 'sncwithlogongroup'):
            params.update({'mshost': cfg.get('messageServerHost') or cfg.get('mshost'),
                           'sysid': cfg.get('systemId') or cfg.get('sysid'),
                           'group': cfg.get('logonGroup') or cfg.get('group')})
        else:
            params.update({'ashost': cfg.get('applicationServerHost') or cfg.get('ashost'),
                           'sysnr': cfg.get('systemNumber') or cfg.get('sysnr')})
        if connection_type in ('snc', 'sncwithlogongroup') or cfg.get('sncMode'):
            params.update({'snc_mode': cfg.get('sncMode') or '1',
                           'snc_partnername': cfg.get('sncPartnerName') or cfg.get('snc_partnername'),
                           'snc_lib': cfg.get('sncLibraryPath') or cfg.get('snc_lib'),
                           'snc_myname': cfg.get('sncMyName') or cfg.get('snc_myname'),
                           'snc_qop': cfg.get('sncQop') or cfg.get('snc_qop')})
        return {key: value for key, value in params.items() if value not in (None, '')}

    def _validate_config(self, cfg: dict) -> None:
        if self._mode(cfg) == 'mock': return
        connection_type = self._connection_type(cfg)
        common = {'Client number': cfg.get('client'), 'Username': cfg.get('username') or cfg.get('user'),
                  'Password': cfg.get('password') or cfg.get('passwd')}
        if connection_type in ('logongroup', 'sncwithlogongroup'):
            common.update({'Message server host': cfg.get('messageServerHost') or cfg.get('mshost'),
                           'System ID': cfg.get('systemId') or cfg.get('sysid'),
                           'Logon group': cfg.get('logonGroup') or cfg.get('group')})
        else:
            common.update({'Application server host': cfg.get('applicationServerHost') or cfg.get('ashost'),
                           'System number': cfg.get('systemNumber') or cfg.get('sysnr')})
        if connection_type in ('snc', 'sncwithlogongroup'):
            common.update({'SNC partner name': cfg.get('sncPartnerName') or cfg.get('snc_partnername'),
                           'SNC library path': cfg.get('sncLibraryPath') or cfg.get('snc_lib')})
        missing = [label for label, value in common.items() if not str(value or '').strip()]
        if missing: raise ValueError(f"Required SAP connection values are missing: {', '.join(missing)}")

    def _jco_values(self, cfg: dict) -> dict:
        self._validate_config(cfg)
        params = self._params(cfg)
        return {'destinationName': str(cfg.get('destinationName') or 'integration-fabric-sap'),
                **{f'jco.client.{key}': value for key, value in params.items()}}

    def _jco_call(self, cfg: dict, function_name: str, arguments: dict | None = None, tables: dict | None = None) -> dict:
        protocol = str(cfg.get('transactionProtocol') or cfg.get('idocInputMode') or '').strip().lower()
        transactional = bool(cfg.get('transactional')) or protocol in ('trfc', 'qrfc', 't-rfc', 'q-rfc')
        if protocol in ('qrfc', 'q-rfc') and not str(cfg.get('queueName') or '').strip():
            raise ValueError('qRFC IDoc delivery requires a SAP queue name')
        values = {**self._jco_values(cfg), 'functionName': function_name, 'transactional': str(transactional).lower(), 'transactionProtocol': protocol or 'srfc'}
        if cfg.get('queueName'): values['queueName'] = cfg.get('queueName')
        for key, value in (arguments or {}).items(): values[f'argument.{key}'] = value
        for table_name, rows in (tables or {}).items():
            for row_index, row in enumerate(rows):
                prefix = 'readTable' if function_name == 'RFC_READ_TABLE' else 'tableArg'
                for field, value in row.items(): values[f'{prefix}.{table_name}.{row_index}.{field}'] = value
        try: return invoke_java('sap.call', cfg, values, family='sap', timeout=float(cfg.get('timeoutSeconds') or 30) + 5)
        except JavaBridgeError as exc: raise RuntimeError(f'SAP JCo call failed: {exc}') from exc

    @staticmethod
    def _listener_key(cfg: dict) -> str:
        return '|'.join(str(cfg.get(key) or '').strip().lower() for key in ('gatewayHost', 'gatewayService', 'programId', 'driverDirectory'))

    @staticmethod
    def _idoc_response_parts(payload: dict) -> tuple[dict, list]:
        """Extract IDoc control/data defensively across JCo response variants."""
        if not isinstance(payload, dict):
            return {}, []
        containers = [payload.get('imports') or {}, payload.get('exports') or {}]
        control: dict = {}
        for container in containers:
            if not isinstance(container, dict):
                continue
            for key, value in container.items():
                normalized = re.sub(r'[^A-Z0-9]', '', str(key).upper())
                if 'IDOCCONTROLREC' in normalized and isinstance(value, dict):
                    control = value
                    break
            if control:
                break
        tables = payload.get('tables') or {}
        data: list = []
        if isinstance(tables, dict):
            for key, value in tables.items():
                normalized = re.sub(r'[^A-Z0-9]', '', str(key).upper())
                if 'IDOCDATAREC' in normalized and isinstance(value, list):
                    data = value
                    break
        return control, data

    def _listener_values(self, cfg: dict) -> dict:
        destination_name = str(cfg.get('destinationName') or 'integration-fabric-sap-listener')
        program_id = str(cfg.get('programId') or cfg.get('progid') or 'sap-listener')
        default_tid_store = os.path.join(os.getenv('FABRIC_DATA_DIR', os.getcwd()), 'sap-tids-' + re.sub(r'[^A-Za-z0-9_.-]', '_', program_id) + '.properties')
        tid_management = str(cfg.get('tidManagement') or 'active').strip().lower()
        values = {
            'destinationName': destination_name,
            **{f'jco.client.{key}': value for key, value in self._params(cfg).items()},
            'jco.server.gwhost': cfg.get('gatewayHost') or cfg.get('gwhost'),
            'jco.server.gwserv': cfg.get('gatewayService') or cfg.get('gwserv'),
            'jco.server.saprouter': cfg.get('sapRouter') or cfg.get('saprouter'),
            'jco.server.progid': program_id,
            'jco.server.repository_destination': destination_name,
            'jco.server.tid_store': cfg.get('tidStorePath') or default_tid_store,
            'jco.server.connection_count': int(cfg.get('maximumConnections') or cfg.get('connectionCount') or 8),
            'jco.server.ack_timeout_seconds': max(1, int(float(cfg.get('ackTimeoutSeconds') or cfg.get('sapAckTimeoutSeconds') or 300))),
            'listenerFunction': 'IDOC_INBOUND_ASYNCHRONOUS',
        }
        # Preserve the existing durable default, while allowing an explicitly
        # disabled SAP TIDManager resource to opt out for non-transactional
        # test flows. The Java bridge still receives a deterministic property.
        if tid_management in ('disabled', 'none', 'off', 'false', '0'):
            values['jco.server.tid_management'] = 'disabled'
        else:
            values['jco.server.tid_management'] = 'active'
        return values

    async def receive_idoc(self, cfg: dict) -> dict:
        if self._mode(cfg) == 'mock':
            idoc_type = str(cfg.get('idocType') or (cfg.get('selectedIdoc') or {}).get('idocType') or 'MOCKIDOC')
            xml_payload = f'<{re.sub(r"[^A-Za-z0-9_.-]", "_", idoc_type)}><IDOC><EDI_DC40><TABNAM>EDI_DC40</TABNAM><IDOCTYP>{idoc_type}</IDOCTYP></EDI_DC40></IDOC></{re.sub(r"[^A-Za-z0-9_.-]", "_", idoc_type)}>'
            parsed = self._xml_to_json(ET.fromstring(xml_payload))
            return {'SAPIDoc': parsed, 'controlRecord': parsed.get('IDOC', {}).get('EDI_DC40', {}), 'payload': xml_payload, 'IDocXML': xml_payload, 'format': 'XML', 'received': True, 'mock': True, 'jcoDiagnostics': []}
        for label, key in (('Program ID', 'programId'), ('Gateway host', 'gatewayHost'), ('Gateway service', 'gatewayService')):
            if not str(cfg.get(key) or '').strip(): raise RuntimeError(f'{label} is required for an SAP IDoc listener')
        listener_key = self._listener_key(cfg)
        listener = self.listeners.get(listener_key)
        starting_listener = listener is None or listener.process.poll() is not None
        if listener is None or listener.process.poll() is not None:
            async with self._listener_start_lock:
                listener = self.listeners.get(listener_key)
                if listener is None or listener.process.poll() is not None:
                    if listener: listener.close()
                    try: listener = start_sap_listener(cfg, self._listener_values(cfg))
                    except JavaBridgeError as exc: raise RuntimeError(f'SAP JCo listener failed to start: {exc}') from exc
                    self.listeners[listener_key] = listener
                    starting_listener = True
                else:
                    starting_listener = False
        delivery_id = None
        try:
            # The timeout is only for initial listener registration. Once the
            # JCo server is established, waiting for the next IDoc is a normal
            # long-running state; an idle SAP gateway must not be treated as a
            # broken listener and closed after 30 seconds.
            startup_timeout = float(cfg.get('timeoutMilliseconds') or cfg.get('timeoutMs') or 30000) / 1000
            diagnostics = []
            event = await listener.next_event(timeout=startup_timeout if starting_listener else None)
            while event.get('event') == 'jco_log':
                diagnostics.append({key: event[key] for key in ('level', 'phase', 'message', 'serverName', 'programId', 'gatewayHost', 'gatewayService', 'repositoryDestination', 'tidStore', 'functionName', 'connectionCount') if key in event})
                event = await listener.next_event(timeout=startup_timeout if starting_listener else None)
            if event.get('event') == 'listening':
                # Once the JCo server is registered, an idle listener is
                # healthy. Do not use the activity timeout while waiting for
                # SAP to deliver the next IDoc.
                if starting_listener:
                    # Return the lifecycle state immediately.  The caller
                    # persists these diagnostics before waiting for an IDoc;
                    # otherwise startup logs misleadingly appear only when
                    # SAP eventually sends the first message.
                    diagnostics.append({'level': 'INFO', 'phase': 'listening', 'message': 'SAP JCo RFC server is listening for IDocs', 'serverName': event.get('serverName'), 'programId': event.get('programId'), 'gatewayHost': event.get('gatewayHost'), 'gatewayService': event.get('gatewayService'), 'repositoryDestination': event.get('repositoryDestination'), 'jcoServerClass': event.get('jcoServerClass')})
                    return {'listening': True, 'received': False, 'format': 'XML', 'jcoDiagnostics': diagnostics}
                event = await listener.next_event()
                while event.get('event') == 'jco_log':
                    diagnostics.append({key: event[key] for key in ('level', 'phase', 'message', 'serverName', 'programId', 'gatewayHost', 'gatewayService', 'repositoryDestination', 'tidStore', 'functionName', 'connectionCount') if key in event})
                    event = await listener.next_event()
            payload = event.get('payload') or {}
            delivery_id = str(event.get('deliveryId') or '').strip() or None
            # IDOC_INBOUND_ASYNCHRONOUS carries control data as an import
            # structure and IDoc segments as table rows.
            control, data = self._idoc_response_parts(payload)
            structured = {'control': control, 'data': data, 'raw': payload}
            # JCo returns RFC structures/tables.  Publish XML as the canonical
            # listener payload so downstream IDoc Parser and Log activities do
            # not receive an implementation-specific JSON envelope.
            idoc_type = cfg.get('idocType') or (cfg.get('selectedIdoc') or {}).get('idocType') or 'IDoc'
            selected_idoc = cfg.get('selectedIdoc') or {}
            metadata_fields, metadata_segments = self._metadata_for_idoc(selected_idoc)
            xml_payload = self._idoc_structured_to_xml(
                structured,
                str(idoc_type),
                metadata_fields,
                metadata_segments,
                selected_idoc.get('schema'),
            )
            # Expose the same named-field representation in both formats.  The
            # raw RFC rows remain available separately for low-level JCo
            # diagnostics, but must not be the primary JSON IDoc payload.
            try:
                parsed_payload = self._xml_to_json(ET.fromstring(xml_payload))
            except ET.ParseError:
                parsed_payload = structured
            control_record = parsed_payload.get('IDOC', {}).get('EDI_DC40', {}) if isinstance(parsed_payload, dict) else {}
            if not control_record:
                control_record = control
            # Keep the named SAPIDoc JSON view for mappings/debugging, while
            # `payload` is deliberately XML because that is the listener
            # contract. The raw RFC representation is retained separately.
            return {'SAPIDoc': parsed_payload, 'controlRecord': control_record, 'rawSAPIDoc': structured, 'payload': xml_payload, 'IDocXML': xml_payload, 'format': 'XML', 'received': True, 'jcoDiagnostics': diagnostics, '_sapDeliveryId': delivery_id, '_sapListenerKey': listener_key}
        except JavaBridgeError as exc:
            if delivery_id:
                try: listener.acknowledge(delivery_id, False)
                except Exception: pass
            self.listeners.pop(listener_key, None)
            listener.close()
            raise RuntimeError(str(exc)) from exc
        except Exception:
            if delivery_id:
                try: listener.acknowledge(delivery_id, False)
                except Exception: pass
            raise

    def acknowledge_idoc(self, listener_key: str, delivery_id: str, success: bool) -> None:
        listener = self.listeners.get(listener_key)
        if not listener:
            raise RuntimeError(f'SAP JCo listener is unavailable for delivery {delivery_id}')
        listener.acknowledge(delivery_id, success)

    def stop_listener(self, cfg: dict) -> None:
        listener = self.listeners.pop(self._listener_key(cfg), None)
        if listener: listener.close()

    def test(self, cfg: dict) -> dict:
        release = self._release(cfg.get('release'))
        release_label = f'7.{release[-2:]}' if release else 'current / auto-detect'
        if self._mode(cfg) == 'mock': return {'ok':True,'message':f'SAP ECC {release_label} mock connection is ready for design-time execution'}
        try:
            result = invoke_java('sap.test', cfg, self._jco_values(cfg), family='sap', timeout=float(cfg.get('timeoutSeconds') or 30) + 5)
            return {'ok': True, 'message': result.get('message', 'SAP JCo connection succeeded'), 'destination': result.get('destination')}
        except JavaBridgeError as exc: return {'ok': False, 'message': f'SAP JCo connection failed: {exc}'}

    @staticmethod
    def _mock_idocs() -> list[dict]:
        return [
            {'idocType':'ORDERS05','description':'Sales order / purchase order','release':'750','extensionType':''},
            {'idocType':'INVOIC02','description':'Invoice document','release':'750','extensionType':''},
            {'idocType':'DELVRY07','description':'Delivery document','release':'750','extensionType':''},
            {'idocType':'MATMAS05','description':'Material master','release':'750','extensionType':''},
        ]

    @staticmethod
    def _schema(idoc_type: str, release: str, extension: str, segments: list[dict], fields: list[dict] | None = None) -> str:
        fields = fields or []
        records: dict[str, dict] = {}

        def value(item: dict, *names: str) -> str:
            """Read SAP JCo row values defensively across ECC releases."""
            lowered = {str(key).upper(): item_value for key, item_value in item.items()}
            for name in names:
                item_value = lowered.get(name.upper())
                if item_value is not None and str(item_value).strip():
                    return str(item_value).strip()
            return ''

        def key(name: str) -> str:
            return re.sub(r'[^A-Z0-9_]', '', name.upper())

        def max_occurs(item: dict) -> str:
            # SAP's complete IDoc metadata reports OCCMAX for a segment
            # occurrence within its parent. The generated IDoc schema follows
            # the standard SAP/TIBCO convention: the envelope/header and
            # level-1 segments occur once, top-level level-2 business segments
            # may repeat, and nested segments use their declared OCCMAX.
            try:
                level = int(value(item, 'HLEVEL', 'HIERARCHY_LEVEL') or '0')
            except ValueError:
                level = 0
            if level <= 1:
                return '1'
            if level == 2:
                return 'unbounded'
            try:
                maximum = int(value(item, 'OCCMAX', 'MAXOCCURS', 'MAX_OCCURS') or '1')
            except ValueError:
                maximum = 1
            return 'unbounded' if maximum > 1 else '1'

        for item in segments:
            name = value(item, 'SEGMENTTYPE', 'SEGMENTTYP', 'SEGTYP', 'SEGMENT', 'SEGTYP30', 'SEGTYP2')
            if name:
                records.setdefault(name, {'parent': value(item, 'PARSEG', 'PARENT', 'PARENTSEGMENT'), 'fields': [], 'maxOccurs': max_occurs(item)})
        # EDI_DC40 is part of every IDoc envelope but is not returned as a
        # business segment by every SAP release. Keep its standard control
        # fields in the generated mapping schema regardless.
        control_fields = (
            'TABNAM', 'MANDT', 'DOCNUM', 'DOCREL', 'STATUS', 'DIRECT',
            'OUTMOD', 'EXPRSS', 'TEST', 'IDOCTYP', 'CIMTYP', 'MESTYP',
            'MESCOD', 'MESFCT', 'STD', 'STDVRS', 'STDMES', 'SNDPOR',
            'SNDPRT', 'SNDPFC', 'SNDPRN', 'RCVPOR', 'RCVPRT',
            'RCVPFC', 'RCVPRN', 'CREDAT', 'CRETIM', 'REFINT', 'REFGRP',
            'REFMES', 'ARCKEY', 'SERIAL',
        )
        records.setdefault('EDI_DC40', {'parent': '', 'fields': list(control_fields), 'maxOccurs': '1'})
        for item in fields:
            segment = value(item, 'SEGMENTTYP', 'SEGMENTTYPE', 'SEGTYP', 'SEGMENT', 'SEGTYP30', 'SEGTYP2')
            name = value(item, 'FIELDNAME', 'FIELDNAM', 'FIELD', 'FNAME')
            if not segment or not name:
                continue
            matching_segment = next((existing for existing in records if key(existing) == key(segment)), None)
            if matching_segment is None:
                # Some SAP releases return field rows for a segment that is
                # omitted from PT_SEGMENTS. Keep the field rather than losing
                # it, so the generated schema remains useful for mapping.
                matching_segment = segment
                records[matching_segment] = {'parent': '', 'fields': [], 'maxOccurs': '1'}
            records[matching_segment]['fields'].append(name)
        if not records:
            records = {'EDI_DC40': {'parent': '', 'fields': []}, f'E1{re.sub("[^A-Z0-9]", "", idoc_type.upper())[:12]}': {'parent': '', 'fields': []}}
        def safe(value: str) -> str: return re.sub(r'[^A-Za-z0-9_.-]', '_', value) or 'Segment'
        children = {name: [] for name in records}
        roots = []
        for name, item in records.items():
            parent = item['parent']
            if parent in records: children[parent].append(name)
            else: roots.append(name)
        types = []
        for name, item in records.items():
            elements = ''.join(f'<xs:element name="{escape(safe(field))}" minOccurs="0" type="xs:string"/>' for field in dict.fromkeys(item['fields']))
            elements += ''.join(f'<xs:element name="{escape(child)}" minOccurs="0" maxOccurs="{records[child].get("maxOccurs", "1")}" type="{escape(safe(child))}Type"/>' for child in children[name])
            if not elements: elements = '<xs:sequence/>'
            types.append(f'<xs:complexType name="{escape(safe(name))}Type"><xs:sequence>{elements}</xs:sequence></xs:complexType>')
        root_segments = [name for name in roots if name != 'EDI_DC40']
        idoc_elements = '<xs:element name="EDI_DC40" minOccurs="0" type="EDI_DC40Type"/>'
        idoc_elements += ''.join(f'<xs:element name="{escape(name)}" minOccurs="0" maxOccurs="{records[name].get("maxOccurs", "1")}" type="{escape(safe(name))}Type"/>' for name in root_segments)
        types.append(f'<xs:complexType name="IDOCType"><xs:sequence>{idoc_elements}</xs:sequence></xs:complexType>')
        return f'''<?xml version="1.0" encoding="UTF-8"?>
<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema" targetNamespace="urn:sap-com:document:sap:idoc:{escape(idoc_type)}" elementFormDefault="qualified">
  <xs:annotation><xs:documentation>SAP IDoc {escape(idoc_type)} release {escape(release or '')} extension {escape(extension or '')}</xs:documentation></xs:annotation>
  {''.join(types)}
  <xs:element name="{escape(idoc_type)}"><xs:complexType><xs:sequence><xs:element name="IDOC" minOccurs="0" type="IDOCType"/></xs:sequence></xs:complexType></xs:element>
</xs:schema>'''

    def list_idocs(self, cfg: dict, search: str = '', limit: int = 250) -> list[dict]:
        configured_release = self._release(cfg.get('release'))
        if self._mode(cfg) == 'mock':
            term = search.lower().strip()
            return [{**item, 'release':configured_release or item['release']} for item in self._mock_idocs() if not term or term in (item['idocType']+' '+item['description']).lower()]
        # SAP's IDoc API provides the type catalog directly. This avoids
        # querying EDBAS through RFC_READ_TABLE, which is intended for the
        # explicit Read Table activity and varies across ECC installations.
        result = self._jco_call(cfg, 'IDOCTYPES_LIST_WITH_MESSAGES',
                                {'PI_RELEASE': configured_release} if configured_release else {})
        found = []
        term = search.lower().strip()
        for row in result.get('tables', {}).get('PT_IDOCTYPES', []):
            idoc_type = str(row.get('IDOCTYP') or row.get('IDOCTYPE') or '').strip()
            description = str(row.get('DESCRIPT') or row.get('DESCRIPTION') or row.get('DESCRP') or '').strip()
            if idoc_type and (not term or term in f'{idoc_type} {description}'.lower()) and not any(item['idocType'] == idoc_type for item in found):
                found.append({'idocType': idoc_type, 'release': configured_release or str(row.get('RELEASE') or '').strip(), 'extensionType': str(row.get('EXTTYPE') or row.get('CIMTYP') or '').strip(), 'description': description or 'SAP IDoc basic type'})
            if len(found) >= int(limit): break
        return found

    def idoc_metadata(self, cfg: dict, idoc_type: str, extension: str = '', release: str = '') -> dict:
        effective_release = self._release(release or cfg.get('release'))
        fields: list[dict] = []
        if self._mode(cfg) == 'mock':
            found = next((item for item in self._mock_idocs() if item['idocType'] == idoc_type), {'idocType':idoc_type,'description':'Mock SAP IDoc','release':'750','extensionType':extension})
            base = {**found, 'release':effective_release or found.get('release','750'), 'extensionType':extension or found.get('extensionType','')}
            segments = [{'SEGMENTTYPE':'EDI_DC40'},{'SEGMENTTYPE':f'E1{idoc_type[:12]}'}]
        else:
            result = self._jco_call(cfg, 'IDOCTYPE_READ_COMPLETE', {'PI_IDOCTYP': idoc_type, 'PI_CIMTYP': extension or '', 'PI_RELEASE': effective_release, 'PI_VERSION': '3'})
            tables = result.get('tables', {})
            segments = tables.get('PT_SEGMENTS') or tables.get('IDOC_STRUCT') or tables.get('PT_IDOC_STRUCT') or tables.get('SEGMENTS') or []
            fields = tables.get('PT_FIELDS') or tables.get('FIELDS') or []
            base = {'idocType': idoc_type, 'description': 'SAP IDoc metadata', 'release': effective_release or 'current', 'extensionType': extension}
        return {**base, 'segments': segments, 'fields': fields, 'schema': self._schema(idoc_type, base.get('release',''), base.get('extensionType',''), segments, fields), 'fetched': True}

    def execute(self, operation: str, cfg: dict, payload: Any) -> dict:
        if operation == 'idoc_listener': return payload if isinstance(payload, dict) else {'payload':payload}
        if operation == 'rfc_bapi_listener': return payload if isinstance(payload, dict) else {'payload':payload}
        if operation == 'dynamic_connection':
            session_id = cfg.get('sessionID') or str(uuid.uuid4())
            if cfg.get('terminateConnection'):
                conn = self.sessions.pop(session_id, None)
                if conn: conn.close()
                return {'sessionID':session_id,'terminated':True,'transactional':bool(cfg.get('transactional'))}
            if self._mode(cfg) != 'mock': self.test(cfg)
            self.sessions[session_id] = None
            return {'sessionID':session_id,'connected':True,'transactional':bool(cfg.get('transactional'))}
        if operation in ('idoc_converter','idoc_parser'):
            # Prefer explicit parser input mappings when present. This makes
            # the Input tab contract executable instead of merely visual,
            # while retaining the normal listener -> parser previous-output
            # shortcut for existing projects.
            mapped_raw = cfg.get('IDoc') or cfg.get('RawIDoc') or cfg.get('rawIDoc')
            raw = mapped_raw if mapped_raw is not None else (payload.get('payload', payload.get('IDocXML', payload.get('SAPIDoc', payload.get('rawIDoc', payload.get('IDoc', payload))))) if isinstance(payload,dict) else payload)
            mapped_control = cfg.get('SAPIDoc')
            if mapped_control is not None and isinstance(raw, dict) and 'control' not in raw and isinstance(mapped_control, dict):
                raw = {**raw, 'control': mapped_control}
            mode = str(cfg.get('idocOutputMode') or cfg.get('outputFormat') or 'JSON').strip().upper()
            if mode not in ('JSON', 'XML', 'RAW'): mode = 'JSON'
            xml_text = raw.decode('utf-8', errors='replace') if isinstance(raw, bytes) else str(raw or '') if isinstance(raw, str) else ''
            json_value: Any
            if isinstance(raw, str):
                try: json_value = json.loads(raw)
                except ValueError:
                    try:
                        selected_idoc = cfg.get('selectedIdoc') or {}
                        metadata_fields, metadata_segments = self._metadata_for_idoc(selected_idoc)
                        xml_text = self._expand_sdata_xml(raw, metadata_fields, metadata_segments, selected_idoc.get('schema'))
                        json_value = self._xml_to_json(ET.fromstring(xml_text))
                    except ET.ParseError: json_value = {'rawIDoc': raw, 'segments': [line for line in raw.splitlines() if line]}
            else:
                json_value = raw
                if isinstance(raw, dict) and ('control' in raw or 'data' in raw):
                    idoc_type_hint = cfg.get('idocType') or (cfg.get('selectedIdoc') or {}).get('idocType') or 'IDoc'
                    selected_idoc = cfg.get('selectedIdoc') or {}
                    metadata_fields, metadata_segments = self._metadata_for_idoc(selected_idoc)
                    xml_text = self._idoc_structured_to_xml(
                        raw,
                        str(idoc_type_hint),
                        metadata_fields,
                        metadata_segments,
                        selected_idoc.get('schema'),
                    )
                    try: json_value = self._xml_to_json(ET.fromstring(xml_text))
                    except ET.ParseError: json_value = raw
                elif isinstance(raw, dict) and any(isinstance(item, (dict, list)) and ('SDATA' in item or (isinstance(item, list) and any(isinstance(row, dict) and 'SDATA' in row for row in item))) for item in raw.values()):
                    # Captured listener payloads and older projects may store
                    # the IDoc as a named JSON object keyed by physical E2
                    # segment definitions. Convert that representation to XML
                    # first so the exact same XSD/byte-offset decoder is used
                    # as for a live JCo delivery.
                    idoc_type_hint = cfg.get('idocType') or (cfg.get('selectedIdoc') or {}).get('idocType') or 'IDoc'
                    selected_idoc = cfg.get('selectedIdoc') or {}
                    metadata_fields, metadata_segments = self._metadata_for_idoc(selected_idoc)
                    xml_text = self._json_to_xml(raw, str(idoc_type_hint))
                    try:
                        xml_text = self._expand_sdata_xml(xml_text, metadata_fields, metadata_segments, selected_idoc.get('schema'))
                        json_value = self._xml_to_json(ET.fromstring(xml_text))
                    except ET.ParseError:
                        json_value = raw
            idoc_type = cfg.get('idocType') or cfg.get('selectedIdoc',{}).get('idocType')
            if not idoc_type and xml_text.lstrip().startswith('<'):
                try: idoc_type = self._xml_name(ET.fromstring(xml_text).tag)
                except ET.ParseError: pass
            if mode == 'XML':
                output = xml_text if xml_text.lstrip().startswith('<') else self._json_to_xml(json_value)
                # `payload` is the canonical downstream value for listener,
                # parser, mapper, and log activities. Keep the structured
                # JSON view for compatibility, but never make consumers know
                # which internal field contains the XML representation.
                result = {'SAPIDoc': json_value, 'payload': output, 'IDocXML': output, 'format': 'XML', 'contentType': 'application/xml', 'idocType': idoc_type, 'schema': cfg.get('idocSchema') or cfg.get('selectedIdoc',{}).get('schema')}
            elif mode == 'RAW': result = {'SAPIDoc': raw, 'format': 'RAW', 'idocType': idoc_type, 'schema': cfg.get('idocSchema') or cfg.get('selectedIdoc',{}).get('schema')}
            else: result = {'SAPIDoc': json_value, 'format': 'JSON', 'idocType': idoc_type, 'schema': cfg.get('idocSchema') or cfg.get('selectedIdoc',{}).get('schema')}
            # The Input tree displays the selected basic type (for example
            # ARTMAS05) as its root. Publish that same key at runtime so a
            # mapping to the visible root does not resolve to an empty value.
            if idoc_type and idoc_type not in result: result[idoc_type] = json_value
            return result
        if operation == 'idoc_renderer':
            selected_idoc = cfg.get('selectedIdoc') or {}
            metadata_fields, metadata_segments = self._metadata_for_idoc(selected_idoc)
            idoc_type = str(cfg.get('idocType') or selected_idoc.get('idocType') or 'IDoc')
            rendered = self._xml_to_raw_idoc(payload, idoc_type, metadata_fields, metadata_segments, selected_idoc.get('schema'))
            return {'rawIDoc': rendered, 'SAPIDoc': rendered, 'format': 'RAW', 'idocType': idoc_type, 'schema': selected_idoc.get('schema')}
        if operation in ('idoc_acknowledgment','idoc_confirmation'):
            if self._mode(cfg) == 'mock':
                return {'acknowledged':True,'status':cfg.get('status') or cfg.get('idocStatus','39'),'idocNumber':cfg.get('idocNumber') or (payload.get('idocNumber') if isinstance(payload,dict) else None)}
            function_name = str(cfg.get('functionName') or '').strip()
            if not function_name:
                raise RuntimeError(f'{operation} requires the SAP acknowledgment RFC function configured by the SAP system')
            arguments = payload if isinstance(payload, dict) else {'DATA': payload}
            result = self._jco_call(cfg, function_name, arguments)
            return {**result, 'acknowledged': True, 'status': cfg.get('status') or cfg.get('idocStatus'), 'idocNumber': cfg.get('idocNumber') or (payload.get('idocNumber') if isinstance(payload,dict) else None)}
        if operation == 'reply_rfc_bapi': return {'replied':True,'response':payload}
        if self._mode(cfg) == 'mock':
            return cfg.get('mockOutput') or {'operation':operation,'function':cfg.get('functionName'),'table':cfg.get('tableName'),'input':payload,'successful':True}
        if operation == 'read_table':
            result = self._jco_call(cfg, 'RFC_READ_TABLE', {'QUERY_TABLE': cfg['tableName'], 'DELIMITER': cfg.get('delimiter', '|'), 'ROWCOUNT': int(cfg.get('rowCount', 0)), 'ROWSKIPS': int(cfg.get('rowSkip', 0))},
                                    {'OPTIONS': [{'TEXT': x} for x in cfg.get('where', [])], 'FIELDS': [{'FIELDNAME': x} for x in cfg.get('fields', [])]})
            delimiter = cfg.get('delimiter', '|'); data = result.get('tables', {})
            return {'rows': [str(row.get('WA', '')).split(delimiter) for row in data.get('DATA', [])], 'fields': data.get('FIELDS', [])}
        function = cfg.get('functionName') or ('IDOC_INBOUND_ASYNCHRONOUS' if operation in ('post_idoc', 'idoc_reader') else '')
        if not function: raise RuntimeError(f'{operation} requires a functionName')
        args = payload if isinstance(payload, dict) else {'DATA': payload}
        call_cfg = dict(cfg)
        if operation in ('post_idoc', 'idoc_reader'):
            # TIBCO's sender uses transactional RFC by default for Post IDoc;
            # IDoc Reader defaults to queued RFC so ordering can be retained.
            call_cfg.setdefault('transactional', True)
            call_cfg.setdefault('transactionProtocol', 'qRFC' if operation == 'idoc_reader' else 'tRFC')
        result = self._jco_call(call_cfg, function, args)
        if cfg.get('autoCommit'): self._jco_call(cfg, 'BAPI_TRANSACTION_COMMIT', {'WAIT': 'X'})
        return result

sap_adapter = SapAdapter()
