import tempfile
import unittest
from contextlib import closing

from app.network.application import Application
from tests.ui_helpers import ReadyTerminal


class OrderingTests(unittest.IsolatedAsyncioTestCase):
    async def test_four_pages_keep_selection_and_persist(self):
        with tempfile.TemporaryDirectory() as directory:
            with closing(Application(directory)) as app:
                app.security.setup('test')
                expected = {}
                for collection in ('nodes', 'sites', 'regions'):
                    expected[collection] = [app.create(collection, name) for name in ('Zulu', 'Alpha')]
                expected['public_tls'] = [app.public_tls.save(domain, False, 'alidns', 'test-id', 'test-secret')
                                          for domain in ('z.example.test', 'a.example.test')]
                ui = ReadyTerminal(app)
                async with ui.run_test(size=(140, 40)) as pilot:
                    for page in expected:
                        ui.page = page
                        ui.render_page()
                        table = ui.query_one('#matrix')
                        table.focus()
                        await pilot.pause()
                        table.move_cursor(row=0, column=1)
                        await pilot.press('f7')  # First row stays in place.
                        await pilot.press('f8')
                        await pilot.pause()
                        if page == 'public_tls':
                            ui.public_tls_page.refresh_records()
                            await pilot.pause()
                        self.assertEqual(table.cursor_row, 1)
                        self.assertEqual(table.cursor_column, 1, page)
                        ids = [item['id'] for item in ui.public_tls_page.records] if page == 'public_tls' else ui.row_ids
                        self.assertEqual(ids, expected[page][::-1])
                        await pilot.press('f8')  # Last row stays in place.
                        await pilot.press('f7', 'f8')
                        ui.query_one('#nav').focus()
                        await pilot.pause()
                        await pilot.press('f7')  # Navigation focus must not reorder.
                        if page != 'public_tls':
                            self.assertEqual([item.id for item in getattr(app.snapshot(), page)], expected[page][::-1])
                    # Editing certificate credentials must not move the record.
                    app.public_tls.save('a.example.test', False, 'alidns', '', '', expected['public_tls'][1])
                    self.assertEqual([item['id'] for item in app.public_tls.list()], expected['public_tls'][::-1])
                    extra = app.public_tls.save('new.example.test', False, 'alidns', 'test-id', 'test-secret')
                    expected['public_tls'].insert(0, extra)
            with closing(Application(directory)) as reopened:
                for page, ids in expected.items():
                    actual = [item['id'] for item in reopened.public_tls.list()] if page == 'public_tls' else [item.id for item in getattr(reopened.snapshot(), page)]
                    self.assertEqual(actual, ids[::-1])
