from contextlib import closing
from pathlib import Path
import tempfile
import unittest
from textual.widgets import Input
from app.network.application import Application
from tests.ui_helpers import ReadyTerminal

class ArchiveControlsTests(unittest.IsolatedAsyncioTestCase):
    async def test_global_import_and_selected_export_without_default_action(self):
        with tempfile.TemporaryDirectory() as directory,closing(Application(directory)) as app:
            app.security.setup('test');app.store.exports=Path(directory)/'exports'
            app.create('nodes','Saved');identity=app.archives.save('Snapshot')
            document=app.archives.get(identity)
            source=app.archives.export_json(document)
            app.create('nodes','Current only')
            ui=ReadyTerminal(app)
            async with ui.run_test(size=(140,40)) as pilot:
                await pilot.press('f6');await pilot.pause()
                self.assertTrue(ui.query_one('#settings-import').is_on_screen)
                self.assertEqual(ui.query_one('#settings-import').parent.id,'settings-tabs')
                await pilot.click('#settings-import');await pilot.pause()
                self.assertIn('不创建新存档',ui.screen.note)
                ui.screen.query_one('#path',Input).value=str(source)
                await pilot.press('ctrl+s');await pilot.pause()
                self.assertIn('不自动保存旧设置',ui.screen.note)
                await pilot.press('ctrl+s');await pilot.pause()
                self.assertEqual([n.name for n in app.snapshot().nodes],['Saved'])
                self.assertEqual(len(app.archives.list()),1)
                self.assertEqual(ui.page,'regions')
                app.create('nodes','Not in archive');ui.after_change('')
                await pilot.click('#settings-archives');await pilot.pause()
                self.assertFalse(ui.query_one('#page-summary').display)
                buttons=list(ui.query('#archive-actions Button'))
                self.assertEqual([b.render().plain for b in buttons],['新增存档','载入','删除','导出'])
                self.assertEqual(len({b.region.y for b in buttons}),1)
                ui.query_one('#matrix').focus()
                await pilot.press('enter');await pilot.pause()
                self.assertEqual(len(ui.screen_stack),1)
                before=set(app.store.exports.rglob('*.json'))
                await pilot.press('ctrl+e');await pilot.pause()
                self.assertIn('TLS / mTLS',ui.screen.note)
                await pilot.press('escape');await pilot.pause()
                self.assertEqual(set(app.store.exports.rglob('*.json')),before)
                await pilot.click('#archive-export');await pilot.pause()
                await pilot.press('ctrl+s');await pilot.pause()
                exported=set(app.store.exports.rglob('*.json'))-before
                self.assertEqual(len(exported),1)
                result=app.archives.read_json(exported.pop())
                self.assertEqual(result,document)
                await pilot.press('escape');await pilot.pause()
                await pilot.click('#archive-save');await pilot.pause()
                self.assertIn('TLS / mTLS',ui.screen.note)
                ui.screen.query_one('#name',Input).value='New'
                await pilot.press('ctrl+s');await pilot.pause()
                self.assertEqual(len(app.archives.list()),2)
