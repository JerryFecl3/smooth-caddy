import tempfile
import unittest
from unittest.mock import patch
from rich.console import Console
from io import StringIO
from app.network.application import Application
from app.network.certificates import validate_certificate_name
from app.tui.ui import Terminal
from textual.widgets import Static

class CAOverviewTests(unittest.IsolatedAsyncioTestCase):
    async def test_public_tree_actual_names_expiry_and_disabled(self):
        with tempfile.TemporaryDirectory() as directory:
            app=Application(directory)
            try:
                app.security.setup('test');app.certificates.initialize('Personal WEB')
                identity=app.certificates.sign_client('Phone');app.certificates.set_enabled(identity,False)
                # Simulate a pre-existing Unicode certificate without new-name validation.
                old=app.certificates.leaf('client','旧手机',client=True)
                app.store.db.execute('UPDATE clients SET cert=?,name=? WHERE id=?',(old.certificate,'旧手机',identity))
                app.security.lock();ui=Terminal(app)
                with patch.object(app.security,'decrypt',side_effect=AssertionError('public view must not decrypt')):
                    async with ui.run_test(size=(140,40)) as pilot:
                        await pilot.press('f5');await pilot.click('#ca-open');await pilot.pause()
                        self.assertEqual(ui.page,'ca');self.assertEqual(len(ui.screen_stack),1)
                        for width in (70,120):
                            output=StringIO();console=Console(file=output,width=width,color_system=None)
                            console.print(ui.query_one('#ca-info',Static).content)
                            text=output.getvalue()
                            self.assertLess(text.index('Relay CA'),text.index('TLS CA'))
                            self.assertLess(text.index('TLS CA'),text.index('mTLS CA'))
                            self.assertIn('旧手机 [disabled]',text);self.assertEqual(text.count('…'),2)
                            self.assertNotIn('已解锁',text)
                            dates=[line.index('2099-12-31') for line in text.splitlines() if '2099-12-31' in line]
                            self.assertEqual(len(dates),4);self.assertEqual(len(set(dates)),1)
            finally:app.close()

    def test_names_reject_non_ascii_and_normalize_edges(self):
        self.assertEqual(validate_certificate_name('  Personal WEB-1_a.b  '),'Personal WEB-1_a.b')
        with tempfile.TemporaryDirectory() as directory:
            app=Application(directory)
            try:
                app.security.setup('test')
                for bad in ('中文','bad/name','a\nb','a\tb','😀'):
                    with self.assertRaises(ValueError):app.certificates.initialize(bad)
                app.certificates.initialize('Valid')
                for bad in ('中文','bad/name','a\nb'):
                    with self.assertRaises(ValueError):app.certificates.sign_client(bad)
                self.assertEqual(app.certificates.clients(),[])
            finally:app.close()
