"""Released database v2 migration and immutable batch compatibility."""
from contextlib import closing
from copy import deepcopy
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
from app.network.models import Configuration
from app.network.storage import APPLICATION_ID, Store
from app.tui.labels import label, options


def old_configuration():
    return {
        'regions': [{'id': 'a'*32, 'name': '我的内网', 'ports': ['80', '443', '8443']}],
        'nodes': [
            {'id': 'b'*32, 'name': '直连源头', 'mode': '直连源头', 'upstream': None,
             'areas': {}, 'platform': 'Debian 13', 'arch': 'amd64', 'ssh_ip': ''},
            {'id': 'c'*32, 'name': '设备', 'mode': '经上游转发', 'upstream': ['b'*32, ''],
             'areas': {}, 'platform': 'OpenWrt 25.12', 'arch': 'armv7', 'ssh_ip': ''},
            {'id': 'd'*32, 'name': '未配置设备', 'mode': '直连源头', 'upstream': None,
             'areas': {}, 'platform': '', 'arch': '', 'ssh_ip': ''},
        ],
        'sites': [{'id': 'e'*32, 'name': '公共 CA', 'domain': '', 'source': '',
                   'areas': {'a'*32: 'HTTPS + mTLS', 'http': 'HTTP', 'https': 'HTTPS', 'off': '不提供服务'},
                   'tls_source': '公共 CA'},
                  {'id': 'f'*32, 'name': '私有站点', 'domain': '', 'source': '',
                   'areas': {}, 'tls_source': '私有 CA'}],
        'revision': 7, 'verify_origin_https': False,
    }


class MigrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.path = self.root / 'smooth-caddy.db'
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute(f'PRAGMA application_id={APPLICATION_ID}')
            db.execute('PRAGMA user_version=2')
            db.execute('CREATE TABLE configuration (id INTEGER PRIMARY KEY, revision INTEGER NOT NULL, payload TEXT NOT NULL)')
            db.execute('INSERT INTO configuration VALUES (1,7,?)', (json.dumps(old_configuration()),))
            db.execute('CREATE TABLE secrets (name TEXT PRIMARY KEY, value BLOB NOT NULL)')
            db.execute('INSERT INTO secrets VALUES (?,?)', ('encrypted-material', b'unchanged-encrypted-bytes'))

    def test_backup_conversion_and_idempotent_reopen(self):
        store = Store(self.root)
        try:
            config = store.load()
            self.assertEqual([n.upstream_url for n in config.nodes], ['', 'https://', ''])
            self.assertEqual([n.platform for n in config.nodes], ['debian_13','openwrt_25_12',''])
            self.assertEqual([s.tls_source for s in config.sites], ['public_ca','private_ca'])
            self.assertEqual(set(config.sites[0].areas.values()), {'https_mtls','http','https','disabled'})
            self.assertEqual(config.nodes[0].name, '直连源头')
            self.assertEqual(config.sites[0].name, '公共 CA')
            self.assertNotIn('upstream', config.to_dict()['nodes'][1])
            self.assertFalse(config.verify_origin_https)
            self.assertEqual(config.revision, 8)
            self.assertEqual(store.db.execute('PRAGMA user_version').fetchone()[0], 6)
            self.assertEqual(store.db.execute('SELECT value FROM secrets').fetchone()[0], b'unchanged-encrypted-bytes')
        finally:
            store.close()
        backups = list((self.root/'backups').glob('*.db'))
        self.assertEqual(len(backups), 1)
        with closing(sqlite3.connect(backups[0])) as db, db:
            self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0], 2)
            self.assertEqual(json.loads(db.execute('SELECT payload FROM configuration').fetchone()[0]), old_configuration())
            self.assertEqual(db.execute('SELECT value FROM secrets').fetchone()[0], b'unchanged-encrypted-bytes')
        reopened = Store(self.root)
        reopened.close()
        self.assertEqual(list((self.root/'backups').glob('*.db')), backups)

    def test_backup_failure_leaves_original_untouched(self):
        before = self.path.read_bytes()
        with patch('app.network.migrations.os.fsync', side_effect=OSError('disk full')):
            with self.assertRaises(OSError):
                Store(self.root)
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(list((self.root/'backups').glob('*.db')), [])

    def test_backup_includes_committed_wal_data(self):
        writer = sqlite3.connect(self.path)
        try:
            writer.execute('PRAGMA journal_mode=WAL')
            writer.execute('INSERT INTO secrets VALUES (?,?)', ('wal-value', b'committed'))
            writer.commit()
            store = Store(self.root)
            store.close()
            backup = next((self.root/'backups').glob('*.db'))
            with closing(sqlite3.connect(backup)) as db, db:
                self.assertEqual(db.execute("SELECT value FROM secrets WHERE name='wal-value'").fetchone()[0], b'committed')
                self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0], 2)
        finally:
            writer.close()

    def test_write_failure_rolls_back_but_preserves_backup(self):
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("CREATE TRIGGER refuse BEFORE UPDATE ON configuration BEGIN SELECT RAISE(ABORT, 'test'); END")
        before = self.path.read_bytes()
        with self.assertRaises(sqlite3.IntegrityError):
            Store(self.root)
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(len(list((self.root/'backups').glob('*.db'))), 1)

    def test_future_version_and_unknown_legacy_value_are_rejected(self):
        for version, payload in [(99, old_configuration()), (2, old_configuration())]:
            if version == 2:
                payload['nodes'][0]['mode'] = 'unrecognized'
            with closing(sqlite3.connect(self.path)) as db, db:
                db.execute(f'PRAGMA user_version={version}')
                db.execute('UPDATE configuration SET payload=?', (json.dumps(payload),))
            before = self.path.read_bytes()
            with self.assertRaises(ValueError):
                Store(self.root)
            self.assertEqual(self.path.read_bytes(), before)
        self.assertFalse((self.root/'backups').exists())

    def test_only_versioned_decoder_accepts_old_values(self):
        from app.network.migrations import legacy_configuration
        original = old_configuration()
        saved = deepcopy(original)
        config = legacy_configuration(original)
        self.assertEqual(original, saved)
        with self.assertRaises(ValueError):
            Configuration.from_dict(original)
        config.nodes[0].upstream_url = ['invalid']
        with self.assertRaises(ValueError):
            config.to_dict()
        self.assertEqual(label('https_mtls'), 'HTTPS + mTLS')
        self.assertEqual(options(['private_ca','public_ca']), [('私有 CA','private_ca'),('公共 CA','public_ca')])
