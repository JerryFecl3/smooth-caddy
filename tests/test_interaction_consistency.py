from contextlib import closing
from pathlib import Path
import tempfile
import unittest
from textual.widgets import Input
from app.network.application import Application
from tests.ui_helpers import ReadyTerminal

class InteractionConsistencyTests(unittest.IsolatedAsyncioTestCase):
    async def test_main_shortcuts_do_not_escape_modal_and_unsupported_actions_do_not_unlock(self):
        with tempfile.TemporaryDirectory() as directory,closing(Application(directory)) as app:
            app.security.setup('test');app.create('sites','Site')
            ui=ReadyTerminal(app)
            async with ui.run_test(size=(140,40)) as pilot:
                await pilot.press('f2','enter');await pilot.pause()
                screen=ui.screen
                for key in ('ctrl+o','ctrl+n','ctrl+d','ctrl+e','f1','f7'):
                    await pilot.press(key);await pilot.pause()
                    self.assertIs(ui.screen,screen)
                    self.assertEqual(ui.page,'sites')
                await pilot.press('escape');await pilot.pause()
                app.security.lock()
                for key in ('f1','f2','f3','f5','f6'):
                    await pilot.press(key,'ctrl+t');await pilot.pause()
                    self.assertEqual(len(ui.screen_stack),1)
                await pilot.press('f1','delete');await pilot.pause()
                self.assertEqual(len(ui.screen_stack),1)
                for key in ('f1','f4'):
                    await pilot.press(key,'enter');await pilot.pause()
                    self.assertEqual(len(ui.screen_stack),1)

    async def test_export_default_custom_path_and_overwrite_cancellation(self):
        with tempfile.TemporaryDirectory() as directory,closing(Application(directory)) as app:
            app.security.setup('test');app.store.exports=Path(directory)/'export'
            app.archives.save('Saved')
            ui=ReadyTerminal(app)
            async with ui.run_test(size=(140,40)) as pilot:
                await pilot.press('f6');await pilot.click('#settings-archives');await pilot.pause()
                await pilot.press('ctrl+e');await pilot.pause()
                default=Path(ui.screen.query_one('#path',Input).value)
                # Windows temporary directories may use an 8.3 alias (RUNNER~1).
                # Compare canonical paths, as the export dialog resolves its default.
                self.assertEqual(default.parent.resolve(),(app.store.exports/'settings').resolve())
                self.assertEqual(default.suffix,'.json')
                self.assertFalse(default.exists())
                ui.screen.query_one('#path',Input).value=''
                await pilot.press('ctrl+s');await pilot.pause()
                self.assertEqual(len(ui.screen_stack),2)
                target=Path(directory)/'chosen.json';target.write_text('keep')
                ui.screen.query_one('#path',Input).value=str(target)
                await pilot.press('ctrl+s');await pilot.pause()
                self.assertEqual(ui.screen.caption,'覆盖现有文件？')
                await pilot.press('escape');await pilot.pause()
                self.assertEqual(target.read_text(),'keep')
                await pilot.press('ctrl+e');await pilot.pause()
                ui.screen.query_one('#path',Input).value=str(target)
                await pilot.press('ctrl+s');await pilot.pause()
                await pilot.press('ctrl+s');await pilot.pause()
                self.assertEqual(app.archives.read_json(target)['name'],'Saved')

    async def test_settings_toolbar_keyboard_reaches_offscreen_actions(self):
        with tempfile.TemporaryDirectory() as directory,closing(Application(directory)) as app:
            app.security.setup('test')
            ui=ReadyTerminal(app)
            async with ui.run_test(size=(80,30)) as pilot:
                await pilot.press('f6','shift+tab','right','right','right');await pilot.pause()
                self.assertEqual(ui.focused.id,'password')
                self.assertTrue(ui.query_one('#settings-tabs').scrollable_content_region.contains_region(ui.focused.region))
                await pilot.press('enter');await pilot.pause()
                self.assertEqual(len(ui.screen_stack),2)
                await pilot.press('escape');await pilot.pause()
                self.assertEqual(ui.focused.id,'password')
