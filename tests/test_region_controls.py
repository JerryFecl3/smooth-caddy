from app.tui.choice_row import ChoiceRow
from textual.widgets import Checkbox
from contextlib import closing
import tempfile
import unittest
from textual.widgets import RadioSet, RadioButton, Checkbox, Select
from app.network.application import Application
from tests.ui_helpers import ReadyTerminal

class RegionControlsTests(unittest.IsolatedAsyncioTestCase):
    async def test_radio_source_and_checkbox_mtls(self):
        with tempfile.TemporaryDirectory() as directory,closing(Application(directory)) as app:
            app.security.setup('test');app.create('regions','LAN')
            ui=ReadyTerminal(app)
            async with ui.run_test(size=(120,36)) as pilot:
                await pilot.press('f6');await pilot.pause()
                table=ui.query_one('#matrix');table.move_cursor(row=0,column=ui.col_keys.index('tls_source'));table.focus()
                await pilot.press('enter');await pilot.pause()
                radios=ui.screen.query_one('#value',ChoiceRow)
                self.assertEqual(len(ui.screen.query(Select)),0)
                self.assertEqual(radios.pressed_index,0)
                self.assertIs(ui.focused,radios.query(Checkbox)[0])
                await pilot.press('down','space');await pilot.pause()
                self.assertEqual(radios.pressed_index,1)
                self.assertEqual(sum(button.value for button in radios.query(Checkbox)),1)
                await pilot.press('space');await pilot.pause()
                self.assertEqual(sum(button.value for button in radios.query(Checkbox)),1)
                await pilot.press('ctrl+s');await pilot.pause()
                self.assertEqual(app.snapshot().regions[0].tls_source,'public_ca')
                table.move_cursor(row=0,column=ui.col_keys.index('mtls'));table.focus()
                await pilot.press('enter');await pilot.pause()
                checkbox=ui.screen.query_one('#value',Checkbox)
                self.assertFalse(checkbox.value)
                await pilot.press('space','ctrl+s');await pilot.pause()
                self.assertTrue(app.snapshot().regions[0].mtls)
                table.move_cursor(row=0,column=ui.col_keys.index('tls_source'));table.focus()
                await pilot.press('enter');await pilot.pause()
                self.assertEqual(ui.screen.query_one('#value',ChoiceRow).pressed_index,1)
                await pilot.press('up','space','escape');await pilot.pause()
                self.assertEqual(app.snapshot().regions[0].tls_source,'public_ca')
