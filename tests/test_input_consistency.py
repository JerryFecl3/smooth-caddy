from contextlib import closing
import tempfile
import unittest
from app.network.application import Application
from app.tui.dialogs import Form, Field, PasswordDialog
from tests.ui_helpers import ReadyTerminal


class InputConsistencyTests(unittest.IsolatedAsyncioTestCase):
    async def test_width_focus_and_boundary_navigation(self):
        with tempfile.TemporaryDirectory() as d, closing(Application(d)) as app:
            app.security.setup('test')
            ui = ReadyTerminal(app)
            async with ui.run_test(size=(80, 24)) as pilot:
                form = Form('Edit', [Field('before', 'Before', 'x'),
                                    Field('multi', 'Multi', 'first\nsecond\nthird', multiline=True),
                                    Field('after', 'After', 'y')])
                ui.push_screen(form)
                await pilot.pause()
                before, multi, after = [form.query_one('#'+key) for key in ('before','multi','after')]
                self.assertEqual(before.region.x, multi.region.x)
                self.assertEqual(before.region.width, multi.region.width)
                self.assertEqual(before.content_region.x, multi.content_region.x)
                self.assertEqual(multi.content_size.height, 3)
                await pilot.press('down')
                self.assertIs(ui.focused, multi)
                self.assertEqual(multi.styles.border_top[1].hex, '#0078D4')
                await pilot.press('down')
                self.assertEqual(multi.cursor_location[0], 1)
                self.assertIs(ui.focused, multi)
                await pilot.press('down','down')
                self.assertIs(ui.focused, after)
                self.assertEqual(multi.styles.border_top[1].hex, '#686868')
                multi.focus();multi.move_cursor((0,0))
                await pilot.press('shift+down')
                self.assertIs(ui.focused, multi)
                self.assertNotEqual(multi.selection.start, multi.selection.end)
                multi.move_cursor((0,0))
                await pilot.press('up')
                self.assertIs(ui.focused, before)
                self.assertEqual(multi.text, 'first\nsecond\nthird')

    async def test_inputs_follow_dialog_background(self):
        with tempfile.TemporaryDirectory() as d, closing(Application(d)) as app:
            app.security.setup('test')
            ui = ReadyTerminal(app)
            async with ui.run_test(size=(80, 24)) as pilot:
                for form in (Form('Edit', [Field('single', 'Single'), Field('multi', 'Multi', 'text', multiline=True)]),
                             PasswordDialog('Password', lambda value: None)):
                    if isinstance(form, PasswordDialog):
                        form.fields.append(Field('multi', 'Multi', 'text', multiline=True))
                    ui.push_screen(form)
                    await pilot.pause()
                    for control in form.query('Input, TextArea'):
                        control.focus()
                        await pilot.pause()
                        self.assertEqual(control.background_colors[1], form.query_one('#dialog').background_colors[1])
                        self.assertEqual(control.styles.border_top[1].hex, '#0078D4')
                    await pilot.press('escape')
