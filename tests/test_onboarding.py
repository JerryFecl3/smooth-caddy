from app.network.models import Service, service_policy
import tempfile
import unittest
from cryptography import x509
from cryptography.x509.oid import NameOID
from textual.widgets import Input
from app.network.application import Application
from app.tui.ui import Terminal
from app.tui.dialogs import InitializationDialog, PasswordDialog, Form
from tests.support import wait_for_screen, wait_until

class StartupTests(unittest.IsolatedAsyncioTestCase):
    async def test_first_launch_combined_initialization(self):
        with tempfile.TemporaryDirectory() as directory:
            app=Application(directory)
            try:
                ui=Terminal(app)
                async with ui.run_test(size=(140,40)) as pilot:
                    await wait_for_screen(ui, InitializationDialog, controls=('#password', '#save'))
                    self.assertIsInstance(ui.screen,InitializationDialog)
                    self.assertFalse(app.security.initialized)
                    for key in ('password','repeat'):ui.screen.query_one('#'+key,Input).value='test-secret'
                    await pilot.press('ctrl+s');await pilot.pause()
                    self.assertFalse(app.security.initialized);self.assertFalse(app.ssh.initialized)
                    self.assertFalse(app.certificates.initialized)
                    self.assertIn('Personal WEB',ui.screen.query_one('#name',Input).placeholder)
                    ui.screen.query_one('#name',Input).value='abc'
                    await pilot.press('ctrl+s');await pilot.pause()
                    await wait_until(lambda: len(ui.screen_stack)==1, description='initialization saved')
                    self.assertTrue(app.security.unlocked);self.assertTrue(app.ssh.initialized)
                    config=app.snapshot()
                    self.assertEqual([r.name for r in config.regions],['Private','Public'])
                    self.assertEqual([n.name for n in config.nodes],['HomeRouter','CloudServer1','CloudServer2'])
                    self.assertEqual([n.arch for n in config.nodes],['armv7','amd64','arm64'])
                    self.assertEqual([s.name for s in config.sites],['Blog','Dashboard'])
                    self.assertEqual([(r.tls_source,r.mtls) for r in config.regions],
                                     [('private_ca',False),('private_ca',True)])
                    for site in config.sites:
                        for region in config.regions:
                            self.assertEqual(site.areas[region.id],Service(True))
                            self.assertEqual(service_policy(site,region),Service(True,'private_ca',region.mtls))
                    self.assertEqual(config.nodes[1].upstream_url,'https://192.168.1.1:8443')
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
                    await wait_for_screen(ui, InitializationDialog, controls=('#password', '#save'))
                    await pilot.press('escape');await pilot.pause()
                    self.assertFalse(ui.is_running);self.assertFalse(app.security.initialized)
                app.security.setup('test-secret');app.security.lock()
                ui=Terminal(app)
                async with ui.run_test() as pilot:
                    await wait_for_screen(ui, PasswordDialog, controls=('#password', '#save'), caption='解锁程序')
                    ui.screen.query_one('#password',Input).value='test-secret'
                    await pilot.press('ctrl+s');await pilot.pause()
                    await wait_for_screen(ui, Form, controls=('#save',), caption='创建 CA')
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
                    await wait_for_screen(ui, PasswordDialog, controls=('#password', '#save'))
                    ui.screen.query_one('#password',Input).value='test-secret'
                    await pilot.press('ctrl+s');await pilot.pause()
                    self.assertEqual(app.ssh.public(),public);self.assertEqual(len(ui.screen_stack),1)
            finally:app.close()
