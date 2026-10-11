from contextlib import closing
import tempfile
import unittest
from textual.widgets import ListItem
from app.network.application import Application
from tests.ui_helpers import ReadyTerminal

class SettingsNavigationTests(unittest.IsolatedAsyncioTestCase):
    async def test_settings_tabs_keyboard_password_and_deployment_first(self):
        with tempfile.TemporaryDirectory() as directory,closing(Application(directory)) as app:
            app.security.setup('test');app.create('regions','LAN');app.archives.save('Snapshot')
            ui=ReadyTerminal(app)
            async with ui.run_test(size=(120,36)) as pilot:
                self.assertEqual([item.id for item in ui.query('#nav ListItem')],
                                 ['nav-deployment','nav-sites','nav-nodes','nav-clients','nav-public_tls','nav-settings'])
                self.assertEqual(ui.page,'deployment')
                self.assertFalse(ui.query_one('#settings-tabs').display)
                await pilot.press('f6');await pilot.pause()
                self.assertEqual(ui.page,'regions')
                self.assertTrue(ui.query_one('#nav-settings',ListItem).has_class('active-page'))
                self.assertTrue(ui.query_one('#settings-tabs').display)
                self.assertNotIn('sidebar',[w.id for w in ui.query_one('#password').ancestors])
                await pilot.press('shift+tab');await pilot.pause()
                self.assertEqual(ui.focused.id,'settings-regions')
                await pilot.press('right','enter');await pilot.pause()
                self.assertEqual(ui.page,'archives')
                self.assertTrue(ui.query_one('#archive-actions').display)
                self.assertFalse(ui.query_one('#actions').display)
                await pilot.press('right','right','enter');await pilot.pause()
                self.assertEqual(len(ui.screen_stack),2)
                await pilot.press('escape');await pilot.pause()
                self.assertEqual(ui.page,'archives')
                self.assertEqual(ui.focused.id,'password')
                await pilot.click('#settings-regions');await pilot.pause()
                self.assertEqual(ui.page,'regions')
                await pilot.press('f1');await pilot.pause()
                self.assertEqual(ui.page,'deployment')
                self.assertFalse(ui.query_one('#settings-tabs').display)
