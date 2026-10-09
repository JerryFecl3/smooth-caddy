"""Real encryption and command authorization, independent of the UI."""
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from cryptography.hazmat.primitives.serialization import pkcs12
from app.network.application import Application
from app.network.security import LockedError

class SecurityTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.app=Application(self.tmp.name);self.addCleanup(self.app.close)

    def provision(self):
        self.app.security.setup('initial')
        self.app.certificates.initialize('Private network')
        return self.app.certificates.sign_client('Phone')

    def test_locked_writes_and_keys_rejected_but_reads_allowed(self):
        client=self.provision();app=self.app
        rid=app.create('regions','Home')
        public=app.ssh.public();root=app.certificates.export_trust_ca()
        app.security.lock()
        for operation in [lambda:app.create('sites','Blocked'),
                          lambda:app.save_configuration(app.snapshot()),
                          lambda:app.delete('regions',rid),
                          lambda:app.certificates.set_enabled(client,False),
                          app.certificates.reset, app.ssh.reset, app.ssh.private,
                          lambda:app.certificates.export_p12(client,'export'),
                          lambda:app.releases.delete('missing'),
                          app.releases.create]:
            with self.subTest(operation=operation), self.assertRaises(LockedError):operation()
        self.assertEqual(app.ssh.public(),public)
        self.assertEqual(app.certificates.export_trust_ca(),root)
        self.assertEqual(len(app.snapshot().regions),1)
        with self.assertRaisesRegex(ValueError,'口令错误'):app.security.unlock('incorrect')
        self.assertFalse(app.security.unlocked)
        app.security.unlock('initial');app.create('sites','Allowed')

    def test_all_keys_encrypted_and_password_rotation_preserves_identities(self):
        client=self.provision();app=self.app
        root=app.certificates.public('root');public=app.ssh.public()
        _,cert,_=pkcs12.load_key_and_certificates(app.certificates.export_p12(client,'export'),b'export')
        keys=[r[0] for r in app.store.db.execute('SELECT key FROM authorities UNION ALL SELECT key FROM clients')]
        keys.append(app.store.db.execute("SELECT value FROM secrets WHERE name='ssh-key'").fetchone()[0])
        self.assertEqual(len(keys),6)
        self.assertTrue(all(b'PRIVATE KEY' not in key and app.security.decrypt(key) for key in keys))
        self.assertFalse((Path(self.tmp.name)/'client-protection.key').exists())
        app.security.change_password('replacement')
        self.assertTrue(app.security.unlocked)
        self.assertEqual(app.ssh.public(),public)
        self.assertEqual(app.certificates.public('root'),root)
        other=Application(self.tmp.name)
        try:
            self.assertFalse(other.security.unlocked)
            with self.assertRaises(ValueError):other.security.unlock('initial')
            other.security.unlock('replacement')
            private,newcert,_=pkcs12.load_key_and_certificates(other.certificates.export_p12(client,'p12-only'),b'p12-only')
            self.assertEqual(newcert,cert)
            self.assertIsNotNone(private)
            self.assertEqual(other.ssh.private().export_public_key().decode().strip(),public)
            other.certificates.leaf('tls','site',dns='example.test')
        finally:other.close()

    def test_failed_password_rotation_is_atomic(self):
        self.provision();app=self.app
        before=list(app.store.db.iterdump())
        app.store.db.execute("CREATE TEMP TRIGGER reject_rotation BEFORE UPDATE ON clients BEGIN SELECT RAISE(ABORT,'simulated failure'); END")
        with self.assertRaises(sqlite3.IntegrityError):app.security.change_password('replacement')
        self.assertEqual(list(app.store.db.iterdump()),before)
        self.assertTrue(app.security.unlocked)
        app.ssh.private()
        app.security.lock();app.security.unlock('initial')
        with self.assertRaises(ValueError):app.security.unlock('replacement')

    def test_ca_reset_does_not_reset_program_password_or_ssh(self):
        self.provision();app=self.app;ssh=app.ssh.public()
        app.certificates.reset()
        self.assertTrue(app.security.initialized)
        self.assertTrue(app.security.unlocked)
        self.assertEqual(app.ssh.public(),ssh)
        app.certificates.initialize('New CA')
        app.security.change_password('replacement')

    def test_other_process_password_change_invalidates_stale_session(self):
        self.provision();other=Application(self.tmp.name)
        try:
            other.security.unlock('initial')
            self.app.security.change_password('replacement')
            with self.assertRaises(LockedError):other.create('regions','stale')
            self.assertFalse(other.security.unlocked)
        finally:other.close()

    def test_obsolete_database_and_release_formats_are_rejected(self):
        self.app.store.db.execute('PRAGMA user_version=1')
        with self.assertRaisesRegex(ValueError,'一次性转换'):Application(self.tmp.name)
        root=self.app.releases.root;root.mkdir()
        (root/'index.json').write_text(json.dumps({'format':1,'releases':[]}))
        with self.assertRaises(ValueError):self.app.releases.list()
