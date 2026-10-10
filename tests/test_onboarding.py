import tempfile
import unittest
from cryptography import x509
from cryptography.x509.oid import NameOID
from textual.widgets import Input
from app.network.application import Application
from app.tui.ui import Terminal
from app.tui.dialogs import InitializationDialog

class StartupTests(unittest.IsolatedAsyncioTestCase):
    async def test_first_launch_combined_initialization(self):
        with tempfile.TemporaryDirectory() as directory:
            app=Application(directory)
            try:
                ui=Terminal(app)
                async with ui.run_test(size=(140,40)) as pilot:
                    await pilot.pause()
                    self.assertIsInstance(ui.screen,InitializationDialog)
                    self.assertFalse(app.security.initialized)
                    for key in ('password','repeat'):ui.screen.query_one('#'+key,Input).value='test-secret'
                    await pilot.press('ctrl+s');await pilot.pause()
                    self.assertFalse(app.security.initialized);self.assertFalse(app.ssh.initialized)
                    self.assertFalse(app.certificates.initialized)
                    self.assertIn('Personal WEB',ui.screen.query_one('#name',Input).placeholder)
                    ui.screen.query_one('#name',Input).value='abc'
                    await pilot.press('ctrl+s');await pilot.pause()
                    self.assertEqual(len(ui.screen_stack),1)
                    self.assertTrue(app.security.unlocked);self.assertTrue(app.ssh.initialized)
                    config=app.snapshot()
                    self.assertEqual([r.name for r in config.regions],['Private','Public'])
                    self.assertEqual([n.name for n in config.nodes],['HomeRouter','CloudServer1','CloudServer2'])
                    self.assertEqual([n.arch for n in config.nodes],['armv7','amd64','arm64'])
                    self.assertEqual([s.name for s in config.sites],['Blog','Dashboard'])
                    self.assertEqual(config.sites[1].tls_source,'public_ca')
                    self.assertEqual(config.nodes[1].upstream,(config.nodes[0].id,config.regions[0].id))
                    for role,suffix in [('root','Root CA'),('tls','TLS CA'),('client','mTLS CA'),('relay','Relay CA')]:
                        cert=x509.load_pem_x509_certificate(app.certificates.public(role))
                        self.assertEqual(cert.subject.get_attributes_for_oid(NameOID.COMMON_NAME)[0].value,'abc '+suffix)
                original=app.snapshot().to_dict()
                app.initialize('test-secret','abc')
                self.assertEqual(app.snapshot().to_dict(),original)
                app.security.lock()
                ui=Terminal(app)
                async with ui.run_test() as pilot:
                    await pilot.pause();self.assertEqual(len(ui.screen_stack),1)
                    self.assertFalse(app.security.unlocked)
            finally:app.close()

    async def test_cancel_exits_and_partial_initialization_resumes(self):
        with tempfile.TemporaryDirectory() as directory:
            app=Application(directory)
            try:
                ui=Terminal(app)
                async with ui.run_test() as pilot:
                    await pilot.pause();await pilot.press('escape');await pilot.pause()
                    self.assertFalse(ui.is_running);self.assertFalse(app.security.initialized)
                app.security.setup('test-secret');app.security.lock()
                ui=Terminal(app)
                async with ui.run_test() as pilot:
                    await pilot.pause();self.assertEqual(ui.screen.caption,'解锁程序')
                    ui.screen.query_one('#password',Input).value='test-secret'
                    await pilot.press('ctrl+s');await pilot.pause()
                    self.assertEqual(ui.screen.caption,'创建 CA')
                    await pilot.press('escape');await pilot.pause()
                    self.assertFalse(ui.is_running);self.assertFalse(app.certificates.initialized)
            finally:app.close()

    async def test_missing_ssh_public_key_repaired_without_rotating_private(self):
        with tempfile.TemporaryDirectory() as directory:
            app=Application(directory)
            try:
                app.security.setup('test-secret');app.certificates.initialize('Test')
                public=app.ssh.public()
                app.store.db.execute("DELETE FROM secrets WHERE name='ssh-public'")
                app.security.lock();ui=Terminal(app)
                async with ui.run_test() as pilot:
                    await pilot.pause();ui.screen.query_one('#password',Input).value='test-secret'
                    await pilot.press('ctrl+s');await pilot.pause()
                    self.assertEqual(app.ssh.public(),public);self.assertEqual(len(ui.screen_stack),1)
            finally:app.close()
