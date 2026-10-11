from contextlib import closing
from copy import deepcopy
import json
from pathlib import Path
import sqlite3
import tempfile
import threading
import unittest
from unittest.mock import patch
from app.network.application import Application
from app.network.archives import decode
from app.network.storage import ConflictError
from tests.legacy_batches import legacy_batch, legacy_configuration
from tests.ui_helpers import ReadyTerminal


class ArchivesTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.app=Application(self.tmp.name);self.addCleanup(self.app.close)
        self.app.store.exports=Path(self.tmp.name)/'exports'
        self.app.security.setup('test')

    def test_drafts_roundtrip_excludes_materials_and_does_not_auto_archive(self):
        app=self.app
        app.certificates.initialize('Test');app.certificates.sign_client('User')
        app.public_tls.save('example.test',False,'alidns','fake-key','fake-secret')
        app.create('nodes','B');app.create('nodes','A');app.create('regions','LAN');app.create('sites','Draft')
        original=app.snapshot()
        identity=app.archives.save('Saved')
        document=app.archives.get(identity)
        path=app.archives.export_json(document)
        payload=path.read_text()
        for word in ('fake-secret','fake-key','PRIVATE KEY','certificate','revision'):
            self.assertNotIn(word,payload)
        auth_before=app.store.db.execute('SELECT * FROM authorities').fetchall()
        secrets_before=app.store.db.execute('SELECT * FROM secrets').fetchall()
        app.create('nodes','New')
        app.archives.restore(app.archives.read_json(path))
        restored=app.snapshot();restored.revision=original.revision
        self.assertEqual(restored,original)
        self.assertEqual(len(app.archives.list()),1)
        self.assertEqual(app.store.db.execute('SELECT * FROM authorities').fetchall(),auth_before)
        self.assertEqual(app.store.db.execute('SELECT * FROM secrets').fetchall(),secrets_before)
        self.assertEqual(len(app.certificates.clients()),1)
        with closing(Application(self.tmp.name)) as other:
            self.assertEqual(other.archives.get(identity),document)

    def test_invalid_import_is_atomic_and_revision_conflicts(self):
        self.app.create('nodes','Draft')
        document=self.app.archives.current_document();before=self.app.snapshot()
        for change in (lambda d:d.update(format=99),lambda d:d['configuration'].update(certificates=[]),
                       lambda d:d['configuration']['nodes'][0].update(areas={'x': {'enabled':1,'ips':[],'overrides':[None]*3}}),
                       lambda d:d['configuration']['nodes'][0].update(ssh_hops='bad')):
            bad=deepcopy(document);change(bad)
            with self.assertRaises(ValueError):self.app.archives.restore(bad)
            self.assertEqual(self.app.snapshot(),before)
        with self.assertRaises(ConflictError):self.app.archives.restore(document,expected_revision=before.revision-1)
        self.assertEqual(self.app.snapshot(),before)
        duplicate=Path(self.tmp.name)/'bad.json';duplicate.write_text('{"format":1,"format":1}')
        with self.assertRaises(ValueError):self.app.archives.read_json(duplicate)
        self.assertEqual(self.app.archives.list(),[])

    def test_old_batch_settings_migrate_once_without_reading_keys(self):
        app=self.app;app.certificates.initialize('Test');app.create('nodes','Node')
        cfg=app.snapshot();cfg.nodes[0].platform='debian_13';cfg.nodes[0].arch='amd64';cfg.nodes[0].ssh_hops=[['192.0.2.1']]
        app.save_configuration(cfg);batch=legacy_batch(app)
        directory=app.releases.directory(batch)
        # Generated files are intentionally corrupted; extracting settings only uses metadata.
        for p in directory.rglob('*.pem'):p.write_bytes(b'not-needed')
        before={p.relative_to(directory):p.read_bytes() for p in directory.rglob('*') if p.is_file()}
        app.store.db.execute('UPDATE configuration SET payload=?',(json.dumps(legacy_configuration(app.snapshot())),))
        app.store.db.execute('PRAGMA user_version=6')
        for _ in range(2):
            with closing(Application(self.tmp.name)) as reopened:
                self.assertEqual(len(reopened.archives.list()),1)
                archive=reopened.archives.list()[0]
                self.assertEqual(decode({k:v for k,v in archive.items() if k!='id'}).nodes[0].name,'Node')
        self.assertEqual(before,{p.relative_to(directory):p.read_bytes() for p in directory.rglob('*') if p.is_file()})
        with closing(Application(self.tmp.name)) as reopened:
            reopened.security.unlock('test')
            reopened.archives.delete(reopened.archives.list()[0]['id'])
        with closing(Application(self.tmp.name)) as reopened:
            self.assertEqual(reopened.archives.list(),[])
        backups=list((Path(self.tmp.name)/'backups').glob('smooth-caddy-v6-*.db'))
        self.assertEqual(len(backups),1)
        with closing(sqlite3.connect(backups[0])) as db:self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0],6)

    def test_export_uses_current_settings_and_cleans_failed_packages(self):
        app=self.app;app.certificates.initialize('Test');app.create('nodes','Original')
        cfg=app.snapshot();cfg.nodes[0].platform='debian_13';cfg.nodes[0].arch='amd64';cfg.nodes[0].ssh_hops=[['192.0.2.1']]
        app.save_configuration(cfg);app.archives.save('old')
        cfg=app.snapshot();cfg.nodes[0].name='Current';app.save_configuration(cfg)
        with patch.object(app.releases.cache,'ensure',return_value=b'fake-binary'):
            packages=app.batches.export('v2.11.7','password')
        self.assertEqual(packages.packages[0].name,'Current')
        self.assertTrue(app.releases.directory(packages).is_dir())
        self.assertFalse(app.releases.root.exists())
        self.assertFalse(list(app.store.temporary.rglob('*.run')))
        with patch.object(app.releases.cache,'ensure',return_value=b'fake-binary'),patch('app.network.releases.build_package',side_effect=OSError('failed')):
            with self.assertRaises(OSError):app.batches.export('v2.11.7','password')
        self.assertFalse(list(app.store.temporary.rglob('*.run')))
        self.assertEqual(len(app.archives.list()),1)


class ArchivesUITests(unittest.IsolatedAsyncioTestCase):
    async def test_archives_restore_and_deployment_actions(self):
        with tempfile.TemporaryDirectory() as directory,closing(Application(directory)) as app:
            app.security.setup('test');app.create('nodes','Saved')
            identity=app.archives.save('Snapshot');app.create('nodes','Unsaved')
            ui=ReadyTerminal(app)
            async with ui.run_test(size=(140,40)) as pilot:
                self.assertTrue(ui.query_one('#generate-deploy').display)
                self.assertTrue(ui.query_one('#run-export').display)
                self.assertTrue(ui.query_one('#run-export-all').display)
                self.assertTrue(ui.query_one('#deploy-all').display)
                ui.query_one('#matrix').focus()
                await pilot.press('enter');await pilot.pause()
                self.assertEqual(len(ui.screen_stack),1)
                self.assertFalse(ui.query_one('#new').display)
                self.assertFalse(ui.query_one('#delete').display)
                ui.page='archives';ui.render_page();await pilot.pause()
                self.assertFalse(ui.query_one('#actions').display)
                await pilot.click('#archive-restore');await pilot.pause()
                self.assertFalse(ui.screen.confirm)
                await pilot.press('escape');await pilot.pause()
                self.assertEqual(len(app.snapshot().nodes),2)
                await pilot.click('#archive-restore');await pilot.pause()
                await pilot.press('ctrl+s');await pilot.pause()
                self.assertEqual([n.name for n in app.snapshot().nodes],['Saved'])
                self.assertEqual(len(app.archives.list()),1)
                self.assertFalse(ui.query_one('#generate-deploy').display)

    async def test_node_action_scope_and_button_layout(self):
        with tempfile.TemporaryDirectory() as directory,closing(Application(directory)) as app:
            app.security.setup('test');app.certificates.initialize('Test')
            app.create('nodes','A');app.create('nodes','B')
            config=app.snapshot()
            for i,node in enumerate(config.nodes):
                node.platform='debian_13';node.arch='amd64';node.ssh_hops=[[f'192.0.2.{i+1}']]
            app.save_configuration(config)
            ui=ReadyTerminal(app)
            with patch.object(app.releases.cache,'online_versions',return_value=['v2.11.7']):
                async with ui.run_test(size=(140,40)) as pilot:
                    table=ui.query_one('#matrix');table.move_cursor(row=1);table.focus()
                    await pilot.pause();await pilot.press('enter');await pilot.pause()
                    self.assertEqual(len(ui.screen_stack),1)
                    self.assertLess(ui.query_one('#generate-deploy').region.x,ui.query_one('#run-export-all').region.x)
                    for button,ids,mode in (('run-export',(config.nodes[1].id,),'package'),('generate-deploy',(config.nodes[1].id,),'deploy'),('run-export-all',None,'package'),('deploy-all',None,'deploy')):
                        await pilot.click('#'+button);await pilot.pause()
                        self.assertEqual(ui.screen.node_ids,ids)
                        self.assertEqual(ui.screen.mode,mode)
                        self.assertEqual([n.id for n in ui.screen.config.nodes],list(ids) if ids else [n.id for n in config.nodes])
                        await pilot.press('escape');await pilot.pause()
