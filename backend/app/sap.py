from __future__ import annotations
import json, re, uuid
from typing import Any
from xml.sax.saxutils import escape

class SapAdapter:
    """SAP ECC adapter. External mode uses SAP's separately licensed NW RFC SDK through pyrfc."""
    def __init__(self): self.sessions: dict[str, Any] = {}

    @staticmethod
    def _release(value: Any) -> str:
        release = str(value or '').strip().lower().replace('.', '')
        if release in ('', 'current', 'latest', 'auto', 'autodetect'): return ''
        if release not in ('720', '730'): raise ValueError('SAP release must be current, 720, or 730')
        return release

    def _params(self, cfg: dict) -> dict:
        return {k:v for k,v in {
            'ashost': cfg.get('applicationServerHost') or cfg.get('ashost'), 'sysnr': cfg.get('systemNumber') or cfg.get('sysnr'),
            'client': cfg.get('client'), 'user': cfg.get('username') or cfg.get('user'), 'passwd': cfg.get('password') or cfg.get('passwd'),
            'lang': cfg.get('language','EN'), 'mshost': cfg.get('messageServerHost'), 'group': cfg.get('logonGroup'),
            'sysid': cfg.get('systemId'), 'saprouter': cfg.get('sapRouter'), 'snc_mode': cfg.get('sncMode'),
            'snc_partnername': cfg.get('sncPartnerName'), 'snc_lib': cfg.get('sncLibraryPath')}.items() if v not in (None,'')}

    def connect(self, cfg: dict):
        if cfg.get('mode','mock') == 'mock': return None
        try: from pyrfc import Connection
        except ImportError as exc: raise RuntimeError('External SAP mode requires SAP NetWeaver RFC SDK and the pyrfc package') from exc
        return Connection(**self._params(cfg))

    def test(self, cfg: dict) -> dict:
        release = self._release(cfg.get('release'))
        release_label = f'7.{release[-2:]}' if release else 'current / auto-detect'
        if cfg.get('mode','mock') == 'mock': return {'ok':True,'message':f'SAP ECC {release_label} mock connection is ready for design-time execution'}
        conn = self.connect(cfg)
        try:
            result = conn.call('STFC_CONNECTION', REQUTEXT='Integration Fabric connection test')
            return {'ok':True,'message':f"SAP ECC connection succeeded: {result.get('ECHOTEXT','connected')}"}
        finally: conn.close()

    @staticmethod
    def _mock_idocs() -> list[dict]:
        return [
            {'idocType':'ORDERS05','description':'Sales order / purchase order','release':'750','extensionType':''},
            {'idocType':'INVOIC02','description':'Invoice document','release':'750','extensionType':''},
            {'idocType':'DELVRY07','description':'Delivery document','release':'750','extensionType':''},
            {'idocType':'MATMAS05','description':'Material master','release':'750','extensionType':''},
        ]

    @staticmethod
    def _schema(idoc_type: str, release: str, extension: str, segments: list[dict]) -> str:
        segment_names = []
        for item in segments:
            name = str(item.get('SEGMENTTYPE') or item.get('SEGTYP') or item.get('SEGMENT') or '').strip()
            if name and name not in segment_names: segment_names.append(name)
        if not segment_names: segment_names = ['EDI_DC40', f'E1{re.sub("[^A-Z0-9]", "", idoc_type.upper())[:12]}']
        choices = ''.join(f'<xs:element name="{escape(name)}" minOccurs="0" maxOccurs="unbounded" type="xs:anyType"/>' for name in segment_names)
        return f'''<?xml version="1.0" encoding="UTF-8"?>
<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema" targetNamespace="urn:sap-com:document:sap:idoc:{escape(idoc_type)}" elementFormDefault="qualified">
  <xs:annotation><xs:documentation>SAP IDoc {escape(idoc_type)} release {escape(release or '')} extension {escape(extension or '')}</xs:documentation></xs:annotation>
  <xs:element name="{escape(idoc_type)}"><xs:complexType><xs:sequence>{choices}</xs:sequence></xs:complexType></xs:element>
</xs:schema>'''

    def list_idocs(self, cfg: dict, search: str = '', limit: int = 250) -> list[dict]:
        configured_release = self._release(cfg.get('release'))
        if cfg.get('mode','mock') == 'mock':
            term = search.lower().strip()
            return [{**item, 'release':configured_release or item['release']} for item in self._mock_idocs() if not term or term in (item['idocType']+' '+item['description']).lower()]
        conn = self.connect(cfg)
        try:
            options = [{'TEXT':f"IDOCTYP LIKE '%{search.upper().replace("'", "") }%'"}] if search else []
            result = conn.call('RFC_READ_TABLE', QUERY_TABLE='EDBAS', DELIMITER='|', ROWCOUNT=int(limit), OPTIONS=options, FIELDS=[{'FIELDNAME':'IDOCTYP'},{'FIELDNAME':'RELEASE'}])
            found = []
            for row in result.get('DATA', []):
                values = [value.strip() for value in row.get('WA','').split('|')]
                if values and values[0] and not any(item['idocType'] == values[0] for item in found): found.append({'idocType':values[0],'release':configured_release or (values[1] if len(values)>1 else ''),'extensionType':'','description':'SAP basic IDoc type'})
            return found
        finally: conn.close()

    def idoc_metadata(self, cfg: dict, idoc_type: str, extension: str = '', release: str = '') -> dict:
        effective_release = self._release(release or cfg.get('release'))
        if cfg.get('mode','mock') == 'mock':
            found = next((item for item in self._mock_idocs() if item['idocType'] == idoc_type), {'idocType':idoc_type,'description':'Mock SAP IDoc','release':'750','extensionType':extension})
            base = {**found, 'release':effective_release or found.get('release','750'), 'extensionType':extension or found.get('extensionType','')}
            segments = [{'SEGMENTTYPE':'EDI_DC40'},{'SEGMENTTYPE':f'E1{idoc_type[:12]}'}]
        else:
            conn = self.connect(cfg)
            try:
                result = conn.call('IDOCTYPE_READ_COMPLETE', PI_IDOCTYP=idoc_type, PI_CIMTYP=extension or '', PI_RELEASE=effective_release)
                segments = result.get('IDOC_STRUCT') or result.get('PT_IDOC_STRUCT') or result.get('SEGMENTS') or []
                base = {'idocType':idoc_type,'description':'SAP IDoc metadata','release':effective_release or 'current','extensionType':extension}
            finally: conn.close()
        return {**base, 'segments':segments, 'schema':self._schema(idoc_type, base.get('release',''), base.get('extensionType',''), segments), 'fetched':True}

    def execute(self, operation: str, cfg: dict, payload: Any) -> dict:
        if operation in ('idoc_listener','rfc_bapi_listener'): return payload if isinstance(payload, dict) else {'payload':payload}
        if operation == 'dynamic_connection':
            session_id = cfg.get('sessionID') or str(uuid.uuid4())
            if cfg.get('terminateConnection'):
                conn = self.sessions.pop(session_id, None)
                if conn: conn.close()
                return {'sessionID':session_id,'terminated':True,'transactional':bool(cfg.get('transactional'))}
            self.sessions[session_id] = None if cfg.get('mode','mock') == 'mock' else self.connect(cfg)
            return {'sessionID':session_id,'connected':True,'transactional':bool(cfg.get('transactional'))}
        if operation in ('idoc_converter','idoc_parser'):
            raw = payload.get('rawIDoc', payload.get('IDoc', payload)) if isinstance(payload,dict) else payload
            if isinstance(raw, str):
                try: parsed = json.loads(raw)
                except ValueError: parsed = {'rawIDoc':raw,'segments':[line for line in raw.splitlines() if line]}
            else: parsed = raw
            return {'SAPIDoc':parsed,'format':'XML','idocType':cfg.get('idocType') or cfg.get('selectedIdoc',{}).get('idocType'),'schema':cfg.get('idocSchema') or cfg.get('selectedIdoc',{}).get('schema')}
        if operation == 'idoc_renderer': return {'rawIDoc':payload if isinstance(payload,str) else json.dumps(payload,separators=(',',':'))}
        if operation in ('idoc_acknowledgment','idoc_confirmation'):
            return {'acknowledged':True,'status':cfg.get('status','53'),'idocNumber':cfg.get('idocNumber') or (payload.get('idocNumber') if isinstance(payload,dict) else None)}
        if operation == 'reply_rfc_bapi': return {'replied':True,'response':payload}
        if cfg.get('mode','mock') == 'mock':
            return cfg.get('mockOutput') or {'operation':operation,'function':cfg.get('functionName'),'table':cfg.get('tableName'),'input':payload,'successful':True}
        connection = self.sessions.get(cfg.get('sessionID')) or self.connect(cfg); owned = cfg.get('sessionID') not in self.sessions
        try:
            if operation == 'read_table':
                result = connection.call('RFC_READ_TABLE', QUERY_TABLE=cfg['tableName'], DELIMITER=cfg.get('delimiter','|'), ROWCOUNT=int(cfg.get('rowCount',0)), ROWSKIPS=int(cfg.get('rowSkip',0)), OPTIONS=[{'TEXT':x} for x in cfg.get('where',[])], FIELDS=[{'FIELDNAME':x} for x in cfg.get('fields',[])])
                return {'rows':[row.get('WA','').split(cfg.get('delimiter','|')) for row in result.get('DATA',[])], 'fields':result.get('FIELDS',[])}
            function = cfg.get('functionName') or ('IDOC_INBOUND_ASYNCHRONOUS' if operation in ('post_idoc','idoc_reader') else '')
            if not function: raise RuntimeError(f'{operation} requires a functionName')
            args = payload if isinstance(payload,dict) else {'DATA':payload}
            result = connection.call(function, **args)
            if cfg.get('autoCommit'): connection.call('BAPI_TRANSACTION_COMMIT', WAIT='X')
            return result
        finally:
            if owned: connection.close()

sap_adapter = SapAdapter()
