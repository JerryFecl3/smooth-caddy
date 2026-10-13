from contextlib import closing
from datetime import datetime
import tempfile
import unittest
from app.network.application import Application
from tests.ui_helpers import ReadyTerminal


class DisplayLabelTests(unittest.IsolatedAsyncioTestCase):
    async def test_certificate_display_and_archive_time(self):
        with tempfile.TemporaryDirectory() as d, closing(Application(d)) as app:
            app.security.setup('test')
            app.public_tls.save('example.com', True, 'alidns', 'test-id', 'test-secret')
            archive_id = app.archives.save('Snapshot')
            stamp = app.archives.get(archive_id)['created_at']
            ui = ReadyTerminal(app)
            async with ui.run_test(size=(120, 36)) as pilot:
                await pilot.press('f5')
                table = ui.query_one('#matrix')
                self.assertEqual(table.get_row_at(0)[0], 'example.com, *.example.com')
                self.assertEqual([c.label.plain for c in table.columns.values()], ['域名', '有效期', '环境'])
                self.assertEqual(table.get_row_at(0)[1].plain, '无证书')
                self.assertNotIn('通配', [str(c.label) for c in table.columns.values()])
                ui.public_tls_page.action_details()
                await pilot.pause()
                note = ui.screen.note
                self.assertIn('域名范围：example.com, *.example.com', note.plain)
                self.assertIn('有效期：无证书', note.plain)
                self.assertNotIn('状态：', note.plain)
                self.assertEqual(note.spans[-1].style, '#ff6b6b')
                await pilot.press('escape')
                await pilot.pause()
                ui.public_tls_page.edit_record(ui.public_tls_page.records[0])
                await pilot.pause()
                self.assertFalse(list(ui.screen.query('#wildcard')))
                self.assertEqual(str(ui.screen.query_one('#domain').render()), 'example.com, *.example.com')
                await pilot.press('ctrl+s')
                await pilot.pause()
                record = app.public_tls.list()[0]
                self.assertEqual(record['domain'], 'example.com')
                self.assertTrue(record['wildcard'])
                await pilot.press('f6')
                await pilot.click('#settings-archives')
                await pilot.pause()
                self.assertEqual(table.get_row_at(0)[1], datetime.fromisoformat(stamp).astimezone().strftime('%Y-%m-%d %H:%M:%S'))
                self.assertEqual(table.region.y-ui.query_one('#settings-tabs').region.bottom, 1)
