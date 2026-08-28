from __future__ import annotations
import json, uuid
from typing import Any

class SapAdapter:
    """SAP ECC adapter. External mode uses SAP's separately licensed NW RFC SDK through pyrfc."""
    def __init__(self): self.sessions: dict[str, Any] = {}

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
        if cfg.get('mode','mock') == 'mock': return {'ok':True,'message':'SAP ECC mock connection is ready for design-time execution'}
        conn = self.connect(cfg)
        try:
            result = conn.call('STFC_CONNECTION', REQUTEXT='Integration Fabric connection test')
            return {'ok':True,'message':f"SAP ECC connection succeeded: {result.get('ECHOTEXT','connected')}"}
        finally: conn.close()

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
            return {'SAPIDoc':parsed,'format':'XML'}
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
