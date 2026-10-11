from contextlib import closing
import tempfile
import unittest
from textual.widgets import Checkbox, TextArea
from app.network.application import Application
from app.network.models import Listen
from app.tui.choice_row import ChoiceRow
from tests.ui_helpers import ReadyTerminal


class NodeFormControlsTests(unittest.IsolatedAsyncioTestCase):
    async def test_platform_arch_exclusive_choices_save_and_cancel(self):
        with tempfile.TemporaryDirectory() as directory, closing(Application(directory)) as app:
            app.security.setup('test');app.create('nodes','Node')
            ui=ReadyTerminal(app)
            async with ui.run_test(size=(120,36)) as pilot:
                await pilot.press('f3');await pilot.pause()
                table=ui.query_one('#matrix')
                table.move_cursor(row=0,column=ui.col_keys.index('platform'));table.focus()
                await pilot.press('enter');await pilot.pause()
                platform=ui.screen.query_one('#platform',ChoiceRow)
                arch=ui.screen.query_one('#arch',ChoiceRow)
                self.assertEqual([str(c.label) for c in platform.query(Checkbox)],['Debian','OpenWrt'])
                self.assertEqual(len(list(arch.query(Checkbox))),4)
                self.assertFalse(any(c.value for c in ui.screen.query(Checkbox)))
                await pilot.press('space','right','space','down','space','right','space')
                await pilot.pause()
                self.assertEqual(platform.value,'openwrt_25_12')
                self.assertEqual(arch.value,'arm64')
                for row in (platform,arch):
                    self.assertEqual(sum(c.value for c in row.query(Checkbox)),1)
                    for c in row.query(Checkbox):self.assertGreater(c.content_size.width,5)
                await pilot.press('ctrl+s');await pilot.pause()
                node=app.snapshot().nodes[0]
                self.assertEqual((node.platform,node.arch),('openwrt_25_12','arm64'))
                table.focus();await pilot.press('enter');await pilot.pause()
                ui.screen.query_one('#platform',ChoiceRow).value='debian_13'
                await pilot.press('escape');await pilot.pause()
                self.assertEqual(app.snapshot().nodes[0],node)

    async def test_binding_arrows_reach_multiline_input(self):
        with tempfile.TemporaryDirectory() as directory, closing(Application(directory)) as app:
            app.security.setup('test');rid=app.create('regions','LAN');app.create('nodes','Node')
            cfg=app.snapshot();cfg.nodes[0].areas[rid]=Listen(True,['192.0.2.1','192.0.2.2'])
            app.save_configuration(cfg)
            ui=ReadyTerminal(app)
            async with ui.run_test(size=(120,36)) as pilot:
                await pilot.press('f3');await pilot.pause()
                table=ui.query_one('#matrix')
                table.move_cursor(row=0,column=ui.col_keys.index('area:'+rid));table.focus()
                await pilot.press('enter');await pilot.pause()
                await pilot.press('down');await pilot.pause()
                address=ui.screen.query_one('#ips',TextArea)
                self.assertIs(ui.screen.focused,address)
                address.move_cursor((0,0))
                await pilot.press('down');await pilot.pause()
                self.assertIs(ui.screen.focused,address)
                self.assertEqual(address.cursor_location[0],1)
                await pilot.press('tab');await pilot.pause()
                self.assertEqual(ui.screen.focused.id,'override0')
                await pilot.press('up');await pilot.pause()
                self.assertIs(ui.screen.focused,address)
                await pilot.press('shift+tab');await pilot.pause()
                self.assertEqual(ui.screen.focused.id,'enabled')
                await pilot.press('space','down');await pilot.pause()
                self.assertTrue(address.disabled)
                self.assertNotEqual(ui.screen.focused.id,'ips')
