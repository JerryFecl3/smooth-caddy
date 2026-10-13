"""Shared terminal-cell widths, wrapping and shrinking after edits."""
import unittest
from textual.app import App
from textual.coordinate import Coordinate
from rich.text import Text
from app.tui.widgets import DataTable


class WidthApp(App):
    def compose(self):
        yield DataTable(fixed_columns=1)

    def on_mount(self):
        table = self.query_one(DataTable)
        table.add_column('名称', key='name', min_width=6, max_width=10)
        table.add_column('Address', key='address', min_width=8, max_width=12)
        table.add_column('Free', key='free')
        table.add_row(Text('中文名称很长很长'), 'https://example.com/path', '12345678901234567890', key='row')


class TableWidthTests(unittest.IsolatedAsyncioTestCase):
    async def test_limits_wrap_and_edit(self):
        ui = WidthApp()
        async with ui.run_test(size=(30, 15)) as pilot:
            await pilot.pause()
            table = ui.query_one(DataTable)
            self.assertEqual([c.width for c in table.columns.values()], [10, 12, 20])
            self.assertGreater(table.rows[next(iter(table.rows))].height, 1)
            self.assertGreater(table.virtual_size.width, table.size.width)
            position = [c.width for c in table.columns.values()]
            table.move_cursor(column=1)
            await pilot.pause()
            self.assertEqual([c.width for c in table.columns.values()], position)
            table.update_cell('row', 'name', '短')
            table.update_cell('row', 'address', 'short')
            await pilot.pause()
            self.assertEqual([c.width for c in table.columns.values()], [6, 8, 20])
            self.assertEqual(table.rows[next(iter(table.rows))].height, 1)
            table.update_cell_at(Coordinate(0, 2), 'x')
            await pilot.pause()
            self.assertEqual(list(table.columns.values())[2].width, 4)
            table.update_cell_at(Coordinate(0, 2), 'x' * 30)
            await pilot.pause()
            self.assertEqual(list(table.columns.values())[2].width, 30)
            table.clear(columns=True)
            table.add_column('Long header', min_width=3, max_width=5)
            table.add_row('x')
            await pilot.pause()
            self.assertEqual(next(iter(table.columns.values())).width, 5)
            self.assertGreater(table.header_height, 1)

            table.clear(columns=True)
            table.add_column('Value', key='value', max_width=8)
            table.add_row('one\ntwo\nthree', key='node', height=2)
            await pilot.pause()
            self.assertEqual(table.rows[next(iter(table.rows))].height, 3)
            table.update_cell('node', 'value', 'short')
            await pilot.pause()
            self.assertEqual(table.rows[next(iter(table.rows))].height, 2)
