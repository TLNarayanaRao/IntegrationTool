from __future__ import annotations
import json, os, re, uuid
from xml.etree import ElementTree as ET
from typing import Any
from xml.sax.saxutils import escape
from .java_bridge import JavaBridgeError, invoke as invoke_java, start_sap_listener, SapJcoListener

class SapAdapter:
    """SAP ECC adapter. External mode uses SAP's separately licensed Java Connector (JCo)."""
    def __init__(self): self.sessions: dict[str, Any] = {}; self.listeners: dict[str, SapJcoListener] = {}

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
    def _idoc_structured_to_xml(cls, structured: dict, idoc_type: str = '') -> str:
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

        control = structured.get('control') or {}
        if isinstance(control, dict) and control:
            control_node = ET.SubElement(root, 'EDI_DC40')
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
        for index, row in enumerate(rows):
            if not isinstance(row, dict):
                continue
            name = str(row.get('SEGNAM') or row.get('SEGMENT') or row.get('SEGMENTNAME') or 'SEGMENT').strip()
            tag = re.sub(r'[^A-Za-z0-9_.-]', '_', name) or 'SEGMENT'
            number = str(row.get('SEGNUM') or index + 1).strip()
            parent_number = str(row.get('PSGNUM') or '').strip().lstrip('0') or '0'
            node = ET.Element(tag, {'SEGMENT': '1'})
            sdata = row.get('SDATA')
            if sdata is not None and str(sdata) != '':
                data_node = ET.SubElement(node, 'SDATA')
                data_node.text = str(sdata)
            nodes[number.lstrip('0') or str(index + 1)] = node
            parents[number.lstrip('0') or str(index + 1)] = parent_number
            pending.append((number.lstrip('0') or str(index + 1), node, parent_number))
        for number, node, parent_number in pending:
            parent = nodes.get(parent_number)
            (parent if parent is not None else root).append(node)
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
        values = {**self._jco_values(cfg), 'functionName': function_name}
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

    def _listener_values(self, cfg: dict) -> dict:
        destination_name = str(cfg.get('destinationName') or 'integration-fabric-sap-listener')
        program_id = str(cfg.get('programId') or cfg.get('progid') or 'sap-listener')
        default_tid_store = os.path.join(os.getenv('FABRIC_DATA_DIR', os.getcwd()), 'sap-tids-' + re.sub(r'[^A-Za-z0-9_.-]', '_', program_id) + '.properties')
        return {
            'destinationName': destination_name,
            **{f'jco.client.{key}': value for key, value in self._params(cfg).items()},
            'jco.server.gwhost': cfg.get('gatewayHost') or cfg.get('gwhost'),
            'jco.server.gwserv': cfg.get('gatewayService') or cfg.get('gwserv'),
            'jco.server.saprouter': cfg.get('sapRouter') or cfg.get('saprouter'),
            'jco.server.progid': program_id,
            'jco.server.repository_destination': destination_name,
            'jco.server.tid_store': cfg.get('tidStorePath') or default_tid_store,
            'jco.server.connection_count': int(cfg.get('maximumConnections') or cfg.get('connectionCount') or 8),
            'listenerFunction': 'IDOC_INBOUND_ASYNCHRONOUS',
        }

    async def receive_idoc(self, cfg: dict) -> dict:
        for label, key in (('Program ID', 'programId'), ('Gateway host', 'gatewayHost'), ('Gateway service', 'gatewayService')):
            if not str(cfg.get(key) or '').strip(): raise RuntimeError(f'{label} is required for an SAP IDoc listener')
        listener_key = self._listener_key(cfg)
        listener = self.listeners.get(listener_key)
        starting_listener = listener is None or listener.process.poll() is not None
        if listener is None or listener.process.poll() is not None:
            if listener: listener.close()
            try: listener = start_sap_listener(cfg, self._listener_values(cfg))
            except JavaBridgeError as exc: raise RuntimeError(f'SAP JCo listener failed to start: {exc}') from exc
            self.listeners[listener_key] = listener
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
            imports = payload.get('imports') or {}
            tables = payload.get('tables') or {}
            # IDOC_INBOUND_ASYNCHRONOUS carries control data as an import
            # structure and IDoc segments as table rows.
            structured = {'control': imports.get('IDOC_CONTROL_REC_40') or imports.get('IDOC_CONTROL_REC_30') or {}, 'data': tables.get('IDOC_DATA_REC_40') or tables.get('IDOC_DATA_REC_30') or [], 'raw': payload}
            # JCo returns RFC structures/tables.  Publish XML as the canonical
            # listener payload so downstream IDoc Parser and Log activities do
            # not receive an implementation-specific JSON envelope.
            idoc_type = cfg.get('idocType') or (cfg.get('selectedIdoc') or {}).get('idocType') or 'IDoc'
            xml_payload = self._idoc_structured_to_xml(structured, str(idoc_type))
            # Keep SAPIDoc as a compatibility/debug field, while `payload` is
            # deliberately XML because that is the listener contract.
            return {'SAPIDoc': structured, 'payload': xml_payload, 'IDocXML': xml_payload, 'format': 'XML', 'received': True, 'jcoDiagnostics': diagnostics}
        except JavaBridgeError as exc:
            self.listeners.pop(listener_key, None)
            listener.close()
            raise RuntimeError(str(exc)) from exc

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

        for item in segments:
            name = value(item, 'SEGMENTTYPE', 'SEGMENTTYP', 'SEGTYP', 'SEGMENT', 'SEGTYP30', 'SEGTYP2')
            if name:
                records.setdefault(name, {'parent': value(item, 'PARSEG', 'PARENT', 'PARENTSEGMENT'), 'fields': []})
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
                records[matching_segment] = {'parent': '', 'fields': []}
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
            elements += ''.join(f'<xs:element name="{escape(child)}" minOccurs="0" maxOccurs="unbounded" type="{escape(safe(child))}Type"/>' for child in children[name])
            if not elements: elements = '<xs:sequence/>'
            types.append(f'<xs:complexType name="{escape(safe(name))}Type"><xs:sequence>{elements}</xs:sequence></xs:complexType>')
        root_elements = ''.join(f'<xs:element name="{escape(name)}" minOccurs="0" maxOccurs="unbounded" type="{escape(safe(name))}Type"/>' for name in roots)
        return f'''<?xml version="1.0" encoding="UTF-8"?>
<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema" targetNamespace="urn:sap-com:document:sap:idoc:{escape(idoc_type)}" elementFormDefault="qualified">
  <xs:annotation><xs:documentation>SAP IDoc {escape(idoc_type)} release {escape(release or '')} extension {escape(extension or '')}</xs:documentation></xs:annotation>
  {''.join(types)}
  <xs:element name="{escape(idoc_type)}"><xs:complexType><xs:sequence>{root_elements}</xs:sequence></xs:complexType></xs:element>
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
            raw = payload.get('payload', payload.get('IDocXML', payload.get('SAPIDoc', payload.get('rawIDoc', payload.get('IDoc', payload))))) if isinstance(payload,dict) else payload
            mode = str(cfg.get('idocOutputMode') or cfg.get('outputFormat') or 'JSON').strip().upper()
            if mode not in ('JSON', 'XML', 'RAW'): mode = 'JSON'
            xml_text = raw.decode('utf-8', errors='replace') if isinstance(raw, bytes) else str(raw or '') if isinstance(raw, str) else ''
            json_value: Any
            if isinstance(raw, str):
                try: json_value = json.loads(raw)
                except ValueError:
                    try: json_value = self._xml_to_json(ET.fromstring(raw))
                    except ET.ParseError: json_value = {'rawIDoc': raw, 'segments': [line for line in raw.splitlines() if line]}
            else:
                json_value = raw
                if isinstance(raw, dict) and ('control' in raw or 'data' in raw):
                    idoc_type_hint = cfg.get('idocType') or (cfg.get('selectedIdoc') or {}).get('idocType') or 'IDoc'
                    xml_text = self._idoc_structured_to_xml(raw, str(idoc_type_hint))
                    try: json_value = self._xml_to_json(ET.fromstring(xml_text))
                    except ET.ParseError: json_value = raw
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
        if operation == 'idoc_renderer': return {'rawIDoc':payload if isinstance(payload,str) else json.dumps(payload,separators=(',',':'))}
        if operation in ('idoc_acknowledgment','idoc_confirmation'):
            return {'acknowledged':True,'status':cfg.get('status','53'),'idocNumber':cfg.get('idocNumber') or (payload.get('idocNumber') if isinstance(payload,dict) else None)}
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
        result = self._jco_call(cfg, function, args)
        if cfg.get('autoCommit'): self._jco_call(cfg, 'BAPI_TRANSACTION_COMMIT', {'WAIT': 'X'})
        return result

sap_adapter = SapAdapter()
