"""Responsive navigation, independent overview tables and deployment selection."""
from contextlib import closing
import tempfile
import unittest
from app.network.application import Application
from tests.ui_helpers import ReadyTerminal


class ResponsiveLayoutTests(unittest.IsolatedAsyncioTestCase):
    async def test_resize_navigation_and_independent_tables(self):
        with tempfile.TemporaryDirectory() as directory, closing(Application(directory)) as app:
            app.initialize('test-secret', 'Test')
            ui = ReadyTerminal(app)
            async with ui.run_test(size=(160, 48)) as pilot:
                await pilot.pause()
                matrix = ui.query_one('#matrix')
                sites = ui.query_one('#deployment-sites')
                original_sites = [sites.get_row_at(i) for i in range(sites.row_count)]
                matrix.move_cursor(row=1)
                original_position = sites.cursor_coordinate
                await pilot.click('#deployment-sites', offset=(2, 2))
                await pilot.pause()
                self.assertIsNot(ui.focused, sites)
                self.assertFalse(sites.show_cursor)
                self.assertEqual(sites.cursor_coordinate, original_position)
                self.assertEqual(matrix.cursor_row, 1)
                self.assertEqual([sites.get_row_at(i) for i in range(sites.row_count)], original_sites)
                matrix.focus()
                await pilot.press('tab')
                self.assertEqual(ui.focused.id, 'run-export')
                await pilot.press('shift+tab')
                self.assertEqual(ui.focused.id, 'matrix')
                for width, height in ((80,24), (120,36), (160,48)):
                    await pilot.resize_terminal(width, height)
                    await pilot.pause()
                    for key in ('help', 'quit', 'nav', 'matrix', 'deployment-sites'):
                        widget=ui.query_one('#'+key)
                        self.assertGreater(widget.size.height, 0, (width,key))
                        self.assertTrue(ui.screen.region.contains_region(widget.region), (width,key,widget.region))
                    expected_height = 3
                    for key in ('nav-sites', 'nav-nodes', 'help', 'quit'):
                        self.assertEqual(ui.query_one('#'+key).region.height, expected_height)
                    item = ui.query_one('#nav-sites')
                    self.assertEqual(ui.query_one('#nav-sites Label').region.y - item.region.y, expected_height - 2)
                    brand = ui.query_one('#brand')
                    self.assertEqual(str(brand.render()), 'smooth caddy')
                    self.assertLess(ui.query_one('#nav-sites').size.width, 14)
                    if not ui.query_one('#sidebar').has_class('compact'):
                        self.assertLessEqual(ui.query_one('#nav').region.right, ui.query_one('#help').region.x)
                    self.assertGreaterEqual(ui.query_one('#actions').region.y - ui.query_one('#tables').region.bottom, 1)
                    self.assertEqual(matrix.cursor_row, 1)
                    self.assertEqual(ui.query_one('#tables').has_class('stacked'), width==80)
                    await pilot.press('f6')
                    await pilot.pause()
                    for key in ('settings-regions','settings-archives','settings-import','password','settings-language'):
                        self.assertTrue(ui.screen.region.contains_region(ui.query_one('#'+key).region), (width,key))
                    await pilot.press('f1')
                    await pilot.pause()
                for focus in (ui.query_one('#nav'), matrix):
                    focus.focus();await pilot.pause()
                    self.assertEqual(ui.query_one('#nav-sites').region.right, ui.query_one('#nav-nodes').region.x)
                await pilot.press('f10')
                await pilot.pause()
                self.assertIn(' F2', str(ui.query_one('#nav-sites Label').render()))
                self.assertEqual(ui.query_one('#nav-sites Label').region.height, 1)
                self.assertTrue(ui.query_one('#help').render().plain.endswith(' F10'))
                await pilot.click('#nav-sites', offset=(1, 2))
                await pilot.pause()
                self.assertEqual(ui.page, 'sites')
                await pilot.press('f1')
                await pilot.press('escape','right')
                await pilot.pause()
                self.assertEqual(ui.page, 'sites')
                await pilot.press('enter')
                self.assertEqual(ui.focused.id,'matrix')
                self.assertFalse(ui.query_one('#deployment-sites-panel').display)
