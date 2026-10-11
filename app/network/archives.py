"""Settings-only archives and JSON interchange, independent of certificates."""
from copy import deepcopy
from datetime import datetime
import json
from pathlib import Path
from uuid import uuid4
from ..i18n import tr
from .models import Configuration, validate_uniqueness
from .files import publish

FORMAT = 4
MAX_BYTES = 10 * 1024 * 1024


def encode(config, name):
    value = config.to_dict()
    value.pop('revision')
    return {'format': FORMAT, 'name': name, 'created_at': datetime.now().astimezone().isoformat(timespec='seconds'),
            'configuration': value}


def decode(document):
    """Validate structure, not deployment readiness. Never accept credential fields."""
    try:
        if set(document) != {'format', 'name', 'created_at', 'configuration'}: raise ValueError()
        if type(document['format']) is not int or document['format'] not in (1, 2, 3, FORMAT): raise ValueError()
        if not isinstance(document['name'], str) or not document['name'].strip(): raise ValueError()
        if not isinstance(document['created_at'], str): raise ValueError()
        datetime.fromisoformat(document['created_at'])
        value = deepcopy(document['configuration'])
        if set(value) != ({'regions', 'nodes', 'sites'} | ({'verify_origin_https'} if document['format']<4 else set())): raise ValueError()
        old=document['format']==1
        shapes = {'regions': {'id','name','ports'} if old else {'id','name','tls_source','mtls'},
                  'nodes': {'id','name','upstream_url','areas','platform','arch','ssh_hops'} | ({'http_port'} if document['format']==2 else set()),
                  'sites': {'id','name','domain','source','areas'} | ({'tls_source'} if old else set()) | ({'verify_origin_https'} if document['format']==4 else set())}
        for group, keys in shapes.items():
            if not isinstance(value[group], list): raise ValueError()
            for item in value[group]:
                if not isinstance(item, dict) or set(item) != keys: raise ValueError()
                for key in keys - {'ports','areas','ssh_hops','mtls','verify_origin_https'}:
                    if not isinstance(item[key], str): raise ValueError()
                if group == 'regions' and old:
                    if not isinstance(item['ports'], list) or len(item['ports']) != 3 or any(not isinstance(p,str) for p in item['ports']): raise ValueError()
                if group != 'regions':
                    if not isinstance(item['areas'], dict): raise ValueError()
                    for area in item['areas'].values():
                        if group=='nodes':
                            port_key='overrides' if old else 'ports'
                            if not isinstance(area,dict) or set(area) != {'enabled','ips',port_key} or type(area['enabled']) is not bool:raise ValueError()
                            if not isinstance(area[port_key],list) or len(area[port_key])!=(2 if document['format']==2 else 3) or any(not isinstance(p,str) and not (old and p is None) for p in area[port_key]):raise ValueError()
                        elif old:
                            if area not in ('disabled','http','https','https_mtls'):raise ValueError()
                        elif not isinstance(area,dict) or set(area)!={'enabled','tls_source','mtls'}:raise ValueError()
        value['revision'] = 0
        if old:
            from .migrations import configuration_v7
            config=configuration_v7(value)
        elif document['format']==2:
            from .migrations import configuration_v8
            config=configuration_v8(value)
        elif document['format']==3:
            from .migrations import configuration_v9
            config=configuration_v9(value)
        else:config = Configuration.from_dict(value)
        validate_uniqueness(config)
        regions = {r.id for r in config.regions}
        if any(set(obj.areas)-regions for obj in config.nodes+config.sites): raise ValueError()
        return config
    except (ValueError, KeyError, TypeError, AttributeError, OverflowError) as error:
        raise ValueError(tr('设置文件格式无效或版本不受支持')) from error


class Archives:
    def __init__(self, app):
        self.app = app
        self.store = app.store
        self.import_legacy()

    def list(self):
        rows = self.store.db.execute('SELECT id, payload FROM settings_archives ORDER BY rowid DESC').fetchall()
        return [dict(json.loads(payload), id=identity) for identity, payload in rows]

    def get(self, identity):
        row = self.store.db.execute('SELECT payload FROM settings_archives WHERE id=?', (identity,)).fetchone()
        if row is None: raise ValueError(tr('存档不存在'))
        document = json.loads(row[0]); decode(document)
        return document

    def save(self, name):
        self.app.security.require()
        name = name.strip()
        if not name: raise ValueError(tr('名称不能为空'))
        document = encode(self.app.snapshot(), name); decode(document)
        identity = uuid4().hex
        with self.store.transaction():
            self.store.db.execute('INSERT INTO settings_archives (id,payload) VALUES (?,?)', (identity,json.dumps(document,ensure_ascii=False)))
        return identity

    def restore(self, document, *, expected_revision=None):
        self.app.security.require()
        config = decode(document)
        current = self.app.snapshot()
        config.revision = current.revision if expected_revision is None else expected_revision
        return self.app.save_configuration(config)

    def delete(self, identity):
        self.app.security.require()
        with self.store.transaction():
            if not self.store.db.execute('DELETE FROM settings_archives WHERE id=?',(identity,)).rowcount:
                raise ValueError(tr('存档不存在'))

    def read_json(self, path):
        with Path(path).expanduser().open('rb') as stream: payload = stream.read(MAX_BYTES+1)
        if len(payload)>MAX_BYTES: raise ValueError(tr('设置文件超过 10 MiB'))
        try:
            def unique(pairs):
                result={}
                for key,value in pairs:
                    if key in result: raise ValueError()
                    result[key]=value
                return result
            document=json.loads(payload,object_pairs_hook=unique)
        except (ValueError,UnicodeError,RecursionError) as error:
            raise ValueError(tr('设置文件格式无效或版本不受支持')) from error
        decode(document)
        return document

    def default_export_path(self):
        return self.store.exports/'settings'/(datetime.now().strftime('%Y%m%d-%H%M%S')+'-'+uuid4().hex[:8]+'.json')

    def export_json(self, document, path=None):
        self.app.security.require(); decode(document)
        path=self.default_export_path() if path is None else Path(path).expanduser().resolve()
        publish(path,(json.dumps(document,ensure_ascii=False,indent=2)+'\n').encode(),self.store.temporary,0o600)
        return path

    def current_document(self):
        return encode(self.app.snapshot(), tr('当前设置'))

    def import_legacy(self):
        # Only verified metadata is read; encrypted generated materials stay untouched.
        with self.store.transaction():
            for batch in reversed(self.app.releases.list()):
                source='release:'+batch.version
                if self.store.db.execute('SELECT 1 FROM archive_sources WHERE source=?',(source,)).fetchone(): continue
                config=self.app.releases.load_configuration(batch)
                document=encode(config,batch.version);document['created_at']=batch.created_at
                decode(document)
                self.store.db.execute('INSERT INTO settings_archives (id,payload,source) VALUES (?,?,?)',
                                     (uuid4().hex,json.dumps(document,ensure_ascii=False),source))
                self.store.db.execute('INSERT INTO archive_sources VALUES (?)',(source,))
