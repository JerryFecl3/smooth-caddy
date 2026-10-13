"""Frozen columns retain row colors and remain visible during horizontal scrolling."""
import unittest
from textual.app import App, ComposeResult
from app.tui.widgets import DataTable


class TableApp(App):
    CSS_PATH = '../app/tui/tui.tcss'

    def compose(self) -> ComposeResult:
        yield DataTable(fixed_columns=1, zebra_stripes=True, show_cursor=False)

    def on_mount(self):
        table = self.query_one(DataTable)
        table.add_column('Name', min_width=12, max_width=12)
        table.add_column('Value', min_width=80, max_width=80)
        for index in range(3):
            table.add_row(f'Name{index}', f'Value{index}')


class TableStripeTests(unittest.IsolatedAsyncioTestCase):
    async def test_frozen_column_matches_rows_before_and_after_scroll(self):
        ui = TableApp()
        async with ui.run_test(size=(50, 15)) as pilot:
            await pilot.pause()
            table = ui.query_one(DataTable)

            def background_at(line, x):
                offset = 0
                for segment in line:
                    offset += segment.cell_length
                    if offset > x:
                        return segment.style.bgcolor

            for scroll in (0, 20):
                table.scroll_to(x=scroll, animate=False)
                await pilot.pause()
                colors = []
                for row in range(3):
                    line = table.render_line(row + 1)
                    self.assertIn(f'Name{row}', ''.join(segment.text for segment in line))
                    fixed = background_at(line, 2)
                    self.assertEqual(fixed, background_at(line, 18))
                    colors.append(fixed)
                self.assertNotEqual(colors[0], colors[1])
                self.assertEqual(colors[0], colors[2])
            table.show_cursor = True
            table.cursor_type = 'row'
            table.move_cursor(row=1)
            table.focus()
            await pilot.pause()
            line = table.render_line(2)
            self.assertEqual(background_at(line, 2), background_at(line, 18))
            self.assertEqual(background_at(line, 2).get_truecolor(), (0, 120, 212))
