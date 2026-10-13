from contextlib import closing
import tempfile
import unittest
from unittest.mock import patch
from app.network.application import Application
from tests.ui_helpers import ReadyTerminal


class PageShortcutTests(unittest.IsolatedAsyncioTestCase):
    async def test_page_actions_and_modal_isolation(self):
        with tempfile.TemporaryDirectory() as d, closing(Application(d)) as app:
            app.security.setup('test')
            ui = ReadyTerminal(app)
            async with ui.run_test(size=(140, 40)) as pilot:
                with patch.object(ui, 'open_export') as export:
                    await pilot.press('ctrl+e')
                    export.assert_called_once_with('package', all_nodes=True)
                    export.reset_mock()
                    await pilot.press('ctrl+d')
                    export.assert_called_once_with('deploy', all_nodes=True)
                await pilot.press('f3')
                with patch.object(ui.query_one('#ssh-guide'), 'press') as press:
                    await pilot.press('ctrl+e')
                    press.assert_called_once()
                await pilot.press('f4')
                with patch.object(ui.query_one('#ca-open'), 'press') as press:
                    await pilot.press('enter')
                    press.assert_not_called()
                    from textual._ansi_sequences import ANSI_SEQUENCES_KEYS
                    self.assertEqual(ANSI_SEQUENCES_KEYS['\x07'][0].value, 'ctrl+g')
                    await pilot.press(ANSI_SEQUENCES_KEYS['\x07'][0].value)
                    press.assert_called_once()
                await pilot.press('f5')
                with patch.object(ui.query_one('#pub-all'), 'press') as press:
                    await pilot.press('ctrl+s')
                    press.assert_called_once()
                    press.reset_mock()
                    from app.tui.dialogs import Form, Field
                    ui.push_screen(Form('Edit', [Field('value','Value')], validate=lambda values: 'Error'))
                    await pilot.pause()
                    await pilot.press('ctrl+s','ctrl+g','ctrl+e','ctrl+d')
                    press.assert_not_called()
