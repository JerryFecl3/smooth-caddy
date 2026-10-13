"""Short editors retain visible actions while the fields scroll."""
from contextlib import closing
import tempfile
import unittest
from app.network.application import Application
from app.tui.dialogs import Form, Field
from tests.ui_helpers import ReadyTerminal


class CompactFormTests(unittest.IsolatedAsyncioTestCase):
    async def test_short_terminal_actions_and_validation(self):
        with tempfile.TemporaryDirectory() as directory, closing(Application(directory)) as app:
            app.security.setup('test')
            ui = ReadyTerminal(app)
            async with ui.run_test(size=(80, 24)) as pilot:
                fields = [Field('enabled', '启用此区域', True, boolean=True),
                          Field('ips', '绑定地址', '10.10.200.1\nfd00:200::1', multiline=True)]
                for index in range(3):
                    fields += [Field(f'override{index}', f'覆盖端口 {index}', True, boolean=True),
                               Field(f'port{index}', '端口', '443')]
                form = Form('Router-2 / 内网', fields,
                            validate=lambda values: '请检查输入\n端口发生冲突',
                            note='每行一个 IP，共用下面的一组端口。\nHTTP 端口仅用于 HTTPS 跳转。')
                ui.push_screen(form)
                await pilot.pause()
                for height in (24, 18, 36):
                    await pilot.resize_terminal(80, height)
                    await pilot.pause()
                    for key in ('dialog-title', 'save', 'cancel'):
                        self.assertTrue(ui.screen.region.contains_region(form.query_one('#'+key).region), (height, key))
                    self.assertEqual(form.query_one('#save').region.height, 3)
                    self.assertEqual(form.query_one('#ips').content_size.height, 3)
                    form.query_one('#port2').focus()
                    await pilot.pause(0.3)
                    self.assertTrue(form.query_one('#form-fields').region.contains_region(form.query_one('#port2').region), (height, form.query_one('#form-fields').region, form.query_one('#port2').region, form.focused, form.query_one('#form-fields').scroll_y, form.query_one('#form-fields').max_scroll_y))
                await pilot.resize_terminal(80, 18)
                await pilot.press('ctrl+s')
                await pilot.pause()
                self.assertTrue(form.query_one('#form-error').display)
                self.assertTrue(ui.screen.region.contains_region(form.query_one('#save').region))

    async def test_deferred_layout_callbacks_after_dialog_closes(self):
        with tempfile.TemporaryDirectory() as directory, closing(Application(directory)) as app:
            app.security.setup('test')
            ui = ReadyTerminal(app)
            async with ui.run_test() as pilot:
                form = Form('Closing', [Field('name', 'Name', 'value')])
                ui.push_screen(form)
                await pilot.pause()
                await pilot.press('escape')
                await pilot.pause()
                self.assertIsNot(ui.screen, form)
                self.assertFalse(list(form.query('#form-fields')))
                # Emulate refresh callbacks already queued before dismissal.
                form.fit_fields()
                form.reveal_field()
