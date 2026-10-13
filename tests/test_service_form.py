from app.tui.choice_row import ChoiceRow
from textual.widgets import Checkbox
from contextlib import closing
import tempfile
import unittest
from textual.widgets import RadioSet, RadioButton, Checkbox, Select
from app.network.application import Application
from app.network.models import Service
from tests.ui_helpers import ReadyTerminal

class ServiceFormTests(unittest.IsolatedAsyncioTestCase):
    async def test_defaults_custom_toggle_save_and_compact_labels(self):
        with tempfile.TemporaryDirectory() as directory,closing(Application(directory)) as app:
            app.security.setup('test');rid=app.create('regions','LAN');app.create('sites','Web')
            cfg=app.snapshot();cfg.regions[0].mtls=True;cfg.sites[0].areas[rid]=Service(False)
            cfg.sites[0].domain='example.test';cfg.sites[0].source='http://127.0.0.1:8000';app.save_configuration(cfg)
            ui=ReadyTerminal(app)
            async with ui.run_test(size=(120,36)) as pilot:
                await pilot.press('f2');await pilot.pause()
                table=ui.query_one('#matrix');table.move_cursor(row=0,column=ui.col_keys.index('area:'+rid));table.focus()
                await pilot.press('enter');await pilot.pause()
                form=ui.screen
                self.assertEqual(len(form.query(Select)),0)
                for button in form.query(Checkbox):
                    self.assertGreaterEqual(button.content_size.height,1)
                    self.assertGreater(button.content_size.width,8)
                    self.assertTrue(form.query_one('#form-fields').region.contains_region(button.region))
                self.assertTrue(form.query_one('#custom',Checkbox).disabled)
                self.assertTrue(form.query_one('#tls_source',ChoiceRow).disabled)
                self.assertEqual(form.query_one('#mtls',ChoiceRow).pressed_index,1)
                form.query_one('#enabled',Checkbox).value=True;await pilot.pause()
                self.assertFalse(form.query_one('#custom',Checkbox).disabled)
                self.assertTrue(form.query_one('#mtls',ChoiceRow).disabled)
                form.query_one('#custom',Checkbox).value=True;await pilot.pause()
                self.assertFalse(form.query_one('#mtls',ChoiceRow).disabled)
                form.query_one('#tls_source',ChoiceRow).query(Checkbox)[1].value=True
                form.query_one('#mtls',ChoiceRow).query(Checkbox)[0].value=True;await pilot.pause()
                form.query_one('#custom',Checkbox).value=False;await pilot.pause()
                self.assertEqual(form.query_one('#tls_source',ChoiceRow).pressed_index,0)
                self.assertEqual(form.query_one('#mtls',ChoiceRow).pressed_index,1)
                await pilot.press('ctrl+s');await pilot.pause()
                self.assertEqual(app.snapshot().sites[0].areas[rid],Service(True))
                self.assertEqual(ui.cell_value(ui.demo.sites[0],'area:'+rid),'TLS·mTLS')
                table.focus();await pilot.press('enter');await pilot.pause()
                form=ui.screen;form.query_one('#custom',Checkbox).value=True;await pilot.pause()
                form.query_one('#mtls',ChoiceRow).query(Checkbox)[0].value=True;await pilot.pause()
                await pilot.press('ctrl+s');await pilot.pause()
                self.assertEqual(app.snapshot().sites[0].areas[rid],Service(True,'private_ca',False))
                self.assertEqual(ui.cell_value(ui.demo.sites[0],'area:'+rid),'TLS')

                # Disabling hides every other check without discarding saved overrides.
                table.focus();await pilot.press('enter');await pilot.pause()
                form=ui.screen
                form.query_one('#enabled',Checkbox).value=False;await pilot.pause()
                for checkbox in form.query(Checkbox):
                    self.assertEqual(checkbox._button.plain, '[ ]')
                    self.assertEqual(checkbox.styles.opacity, 1.0)
                self.assertTrue(form.query_one('#custom',Checkbox).value)
                await pilot.press('ctrl+s');await pilot.pause()
                self.assertEqual(app.snapshot().sites[0].areas[rid],Service(False,'private_ca',False))
                table.focus();await pilot.press('enter');await pilot.pause()
                form=ui.screen
                for checkbox in form.query(Checkbox):
                    self.assertEqual(checkbox._button.plain, '[ ]')
                    self.assertEqual(checkbox.styles.opacity, 1.0)
                form.query_one('#enabled',Checkbox).value=True;await pilot.pause()
                self.assertEqual(form.query_one('#custom',Checkbox)._button.plain, '[x]')
                self.assertEqual(form.query_one('#tls_source',ChoiceRow).value,'private_ca')
                self.assertEqual(form.query_one('#mtls',ChoiceRow).value,False)
                self.assertEqual(form.query_one('#mtls',ChoiceRow).query(Checkbox)[0]._button.plain, '[x]')
                await pilot.press('ctrl+s');await pilot.pause()
                self.assertEqual(app.snapshot().sites[0].areas[rid],Service(True,'private_ca',False))
