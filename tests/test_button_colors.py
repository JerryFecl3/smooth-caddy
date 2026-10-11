from contextlib import closing
import tempfile
import unittest
from app.network.application import Application
from app.tui.dialogs import Form,Field
from app.tui.widgets import Button
from tests.ui_helpers import ReadyTerminal

class ButtonColorTests(unittest.IsolatedAsyncioTestCase):
    async def test_list_defaults_focus_and_danger_colors(self):
        with tempfile.TemporaryDirectory() as directory,closing(Application(directory)) as app:
            app.security.setup('test');app.create('sites','Site');app.create('nodes','Node');app.create('regions','LAN')
            ui=ReadyTerminal(app)
            async with ui.run_test(size=(140,40)) as pilot:
                for key in ('f2','f3','f6'):
                    await pilot.press(key);await pilot.pause()
                    button=ui.query_one('#edit',Button)
                    self.assertTrue(button.has_class('list-default'))
                    self.assertEqual(button.styles.background.hex,'#0078D4')
                    await pilot.press('tab','right');await pilot.pause()
                    self.assertFalse(button.has_class('list-default'))
                    self.assertEqual(ui.focused.styles.background.hex,'#0078D4')
                    self.assertNotEqual(button.styles.background.hex,'#0078D4')
                await pilot.click('#settings-archives');ui.query_one('#matrix').focus();await pilot.pause()
                self.assertFalse(list(ui.query('Button.list-default')))
                await pilot.press('f1');await pilot.pause()
                self.assertFalse(list(ui.query('Button.list-default')))
                self.assertNotEqual(ui.query_one('#generate-deploy').styles.background.hex,'#0078D4')
                await pilot.press('f2');await pilot.pause()
                ui.push_screen(Form('Edit',[Field('name','Name','value')]))
                await pilot.pause()
                self.assertFalse(list(ui.screen_stack[0].query('Button.list-default')))
                save=ui.screen.query_one('#save',Button)
                self.assertEqual(save.variant,'default')
                self.assertNotEqual(save.styles.background.hex,'#0078D4')
                save.focus();await pilot.pause()
                self.assertEqual(save.styles.background.hex,'#0078D4')
                await pilot.press('escape');await pilot.pause()
                self.assertTrue(ui.query_one('#edit').has_class('list-default'))
                ui.push_screen(Form('Danger',[],confirm=True));await pilot.pause()
                save=ui.screen.query_one('#save',Button)
                focused_color=save.styles.background
                self.assertEqual(save.variant,'error')
                self.assertTrue(save.styles.text_style.underline)
                ui.screen.query_one('#cancel').focus();await pilot.pause()
                self.assertEqual(save.styles.background,focused_color)
                self.assertNotEqual(focused_color.hex,'#0078D4')

    async def test_tls_details_and_lego_actions_are_neutral_until_focused(self):
        from app.tui.public_tls import CertificateDetails,LegoManager
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as directory,closing(Application(directory)) as app:
            app.security.setup('test');ui=ReadyTerminal(app)
            async with ui.run_test(size=(140,40)) as pilot:
                item=dict(domain='example.com',wildcard=False,provider='alidns',expires='',error='',staging=False,certificate=False)
                with patch.object(app.public_tls.tool,'version',return_value='test'):
                    for dialog,target in ((CertificateDetails(item,'Pending'),'cert-issue'),(LegoManager(),'lego-install')):
                        ui.push_screen(dialog);await pilot.pause()
                        button=ui.screen.query_one('#'+target,Button)
                        self.assertEqual(button.variant,'default')
                        self.assertFalse(button.has_class('list-default'))
                        self.assertEqual(ui.screen.focused.id,'cancel')
                        button.disabled=False;button.focus();await pilot.pause()
                        self.assertEqual(button.styles.background.hex,'#0078D4')
                        await pilot.press('escape');await pilot.pause()

    async def test_navigation_clears_right_side_highlights_and_preserves_position(self):
        with tempfile.TemporaryDirectory() as directory,closing(Application(directory)) as app:
            app.security.setup('test');app.create('sites','First');app.create('sites','Second')
            ui=ReadyTerminal(app)
            async with ui.run_test(size=(140,40)) as pilot:
                await pilot.press('f2');await pilot.pause()
                table=ui.query_one('#matrix');table.move_cursor(row=1,column=1)
                await pilot.pause();position=table.cursor_coordinate
                self.assertTrue(table.show_cursor)
                self.assertTrue(ui.query_one('#edit').has_class('list-default'))
                await pilot.press('escape');await pilot.pause()
                self.assertEqual(ui.focused.id,'nav')
                self.assertFalse(table.show_cursor)
                self.assertFalse(list(ui.query('#main Button.list-default')))
                for y in range(table.size.height):
                    for segment in table.render_line(y):
                        if segment.style and segment.style.bgcolor:
                            self.assertNotEqual(segment.style.bgcolor.get_truecolor(),(0,120,212))
                ui.query_one('#help').focus();await pilot.pause()
                self.assertFalse(table.show_cursor)
                await pilot.press('tab');await pilot.pause()
                self.assertIs(ui.focused,table)
                self.assertTrue(table.show_cursor)
                self.assertEqual(table.cursor_coordinate,position)
                self.assertTrue(ui.query_one('#edit').has_class('list-default'))
                await pilot.press('f1','escape');await pilot.pause()
                self.assertFalse(table.show_cursor)
                self.assertFalse(list(ui.query('#main Button.list-default')))
