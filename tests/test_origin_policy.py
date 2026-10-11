"""Preserve origin verification through DB upgrades and settings interchange."""
from contextlib import closing
import json
import sqlite3
import tempfile
import unittest
from uuid import uuid4
from app.network.application import Application
from app.network.archives import encode, decode
from app.network.models import Configuration, Site


class OriginPolicyTests(unittest.TestCase):
    def test_v9_backup_preserves_both_global_values_and_new_site_default(self):
        for verify in (False, True):
            with self.subTest(verify=verify), tempfile.TemporaryDirectory() as directory:
                cfg=Configuration(sites=[Site(uuid4().hex,'First'),Site(uuid4().hex,'Second')])
                old=cfg.to_dict();old['verify_origin_https']=verify
                for site in old['sites']:site.pop('verify_origin_https')
                with closing(Application(directory)) as app:
                    app.store.db.execute('UPDATE configuration SET payload=?',(json.dumps(old),))
                    app.store.db.execute('PRAGMA user_version=9')
                with closing(Application(directory)) as app:
                    self.assertEqual([s.verify_origin_https for s in app.snapshot().sites],[verify,verify])
                    self.assertNotIn('verify_origin_https',app.snapshot().to_dict())
                    self.assertEqual(app.store.db.execute('PRAGMA user_version').fetchone()[0],10)
                    backups=list(app.store.directory.glob('backups/smooth-caddy-v9-*.db'))
                    self.assertEqual(len(backups),1)
                    with closing(sqlite3.connect(backups[0])) as db:
                        self.assertEqual(json.loads(db.execute('SELECT payload FROM configuration').fetchone()[0]),old)
                    app.security.setup('test');app.create('sites','New')
                    self.assertFalse(app.snapshot().sites[-1].verify_origin_https)
                with closing(Application(directory)) as app:
                    self.assertEqual(len(list(app.store.directory.glob('backups/*.db'))),1)
                document=encode(cfg,'Legacy');document['format']=3
                old.pop('revision');document['configuration']=old
                self.assertEqual([s.verify_origin_https for s in decode(document).sites],[verify,verify])

    def test_current_json_preserves_independent_choices(self):
        cfg=Configuration(sites=[Site(uuid4().hex,'Unchecked'),Site(uuid4().hex,'Checked',verify_origin_https=True)])
        document=encode(cfg,'Mixed')
        self.assertEqual(document['format'],4)
        self.assertEqual(decode(document),cfg)
        document['configuration']['sites'][0]['verify_origin_https']='false'
        with self.assertRaises(ValueError):decode(document)
