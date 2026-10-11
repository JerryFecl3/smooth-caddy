from app.tui.choice_row import ChoiceRow
from textual.widgets import Checkbox
from contextlib import closing
import tempfile
import unittest
from textual.widgets import RadioSet,RadioButton,Input
from app.network.application import Application
from tests.ui_helpers import ReadyTerminal

class UpstreamFormTests(unittest.IsolatedAsyncioTestCase):
    async def test_direct_relay_validation_and_persistence(self):
        with tempfile.TemporaryDirectory() as directory,closing(Application(directory)) as app:
            app.security.setup('test');app.create('nodes','Node')
            ui=ReadyTerminal(app)
            async with ui.run_test(size=(120,36)) as pilot:
                await pilot.press('f3');await pilot.pause()
                table=ui.query_one('#matrix');table.move_cursor(row=0,column=ui.col_keys.index('upstream_url'));table.focus()
                await pilot.press('enter');await pilot.pause()
                self.assertTrue(ui.screen.query_one('#value',Input).disabled)
                for button in ui.screen.query(Checkbox):self.assertGreaterEqual(button.content_size.height,1)
                ui.screen.query_one('#mode',ChoiceRow).query(Checkbox)[1].value=True;await pilot.pause()
                self.assertFalse(ui.screen.query_one('#value',Input).disabled)
                await pilot.press('ctrl+s');await pilot.pause()
                self.assertEqual(len(ui.screen_stack),2)
                self.assertEqual(app.snapshot().nodes[0].upstream_url,'')
                ui.screen.query_one('#value',Input).value='https://relay.example.com:9443'
                await pilot.press('ctrl+s');await pilot.pause()
                self.assertEqual(app.snapshot().nodes[0].upstream_url,'https://relay.example.com:9443')
                table.focus();await pilot.press('enter');await pilot.pause()
                self.assertEqual(ui.screen.query_one('#mode',ChoiceRow).pressed_index,1)
                ui.screen.query_one('#mode',ChoiceRow).query(Checkbox)[0].value=True;await pilot.pause()
                self.assertTrue(ui.screen.query_one('#value',Input).disabled)
                await pilot.press('ctrl+s');await pilot.pause()
                self.assertEqual(app.snapshot().nodes[0].upstream_url,'')
