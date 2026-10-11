import tempfile
import unittest
from pathlib import Path
from app.network.application import Application
from tests.ui_helpers import ReadyTerminal as Terminal
from app.tui.widgets import Input

class TerminalTests(unittest.IsolatedAsyncioTestCase):
    async def test_persistent_new_region_and_navigation(self):
        with tempfile.TemporaryDirectory() as directory:
            service = Application(directory)
            service.store.exports = Path(directory)/"export"
            service.security.setup('secret')
            ui = Terminal(service)
            async with ui.run_test(size=(140, 40)) as pilot:
                await pilot.press('f4', 'ctrl+n')
                await pilot.pause()
                ui.screen.query_one('#name', Input).value = '内网'
                await pilot.press('ctrl+s')
                await pilot.pause()
                self.assertEqual(service.snapshot().regions[0].name, '内网')
                await pilot.press('enter')
                await pilot.pause()
                ui.screen.query_one('#value', Input).value = '家庭'
                await pilot.press('ctrl+s')
                await pilot.pause()
                self.assertEqual(service.snapshot().regions[0].name, '家庭')
                await pilot.press('f5', 'tab')
                await pilot.pause()
            service.close()
            reopened = Application(directory)
            self.assertEqual(reopened.snapshot().regions[0].name, '家庭')
            reopened.close()

    async def test_real_ca_and_client(self):
        with tempfile.TemporaryDirectory() as directory:
            service = Application(directory)
            service.store.exports = Path(directory)/"export"
            service.security.setup('secret')
            ui = Terminal(service)
            async with ui.run_test(size=(150, 45)) as pilot:
                ui.page = 'ca'; ui.render_page()
                await pilot.pause()
                await pilot.click('#initialize')
                await pilot.pause()
                for key,value in [('name','Network')]:
                    ui.screen.query_one('#'+key, Input).value=value
                await pilot.press('ctrl+s'); await pilot.pause()
                self.assertTrue(service.certificates.initialized)
                ui.page='clients';ui.render_page();ui.action_new()
                await pilot.pause()
                ui.screen.query_one('#name', Input).value='Phone'
                await pilot.press('ctrl+s');await pilot.pause()
                self.assertEqual(service.certificates.clients()[0].name,'Phone')
                ui.action_toggle_client();await pilot.pause()
                self.assertFalse(service.certificates.clients()[0].enabled)
            service.close()

    async def test_offline_batch_creation_from_tui_has_no_version_or_path(self):
        from app.network.models import Listen
        from app.tui.task_progress import TaskProgress
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as directory:
            service=Application(directory);service.store.exports=Path(directory)/"export";service.security.setup('secret')
            rid=service.create('regions','内网');service.create('nodes','Node')
            cfg=service.snapshot();cfg.nodes[0].platform='debian_13';cfg.nodes[0].arch='amd64';cfg.nodes[0].ssh_hops=[['127.0.0.2']];cfg.nodes[0].areas[rid]=Listen(True,['127.0.0.2'])
            service.save_configuration(cfg);service.certificates.initialize('Network')
            try:
                ui=Terminal(service)
                with patch('app.network.releases.BinaryCache.online_versions',side_effect=AssertionError('Must stay offline')):
                    async with ui.run_test(size=(140,40)) as pilot:
                        await pilot.press('f1','ctrl+n');await pilot.pause()
                        self.assertFalse(ui.screen.query('#versions'))
                        await pilot.press('ctrl+s')
                        for _ in range(30):
                            await pilot.pause(.05)
                            if isinstance(ui.screen,TaskProgress) and ui.screen.finished:break
                        self.assertEqual(len(service.releases.list()),1)
                        self.assertNotIn(directory,str(ui.screen.query_one('#task-detail').render()))
                        self.assertFalse(list(Path(directory).rglob('*.run')))
            finally:service.close()

    async def test_ctrl_c_does_not_exit_public_key_dialog(self):
        with tempfile.TemporaryDirectory() as directory:
            service = Application(directory)
            service.store.exports = Path(directory)/"export"
            service.security.setup('secret')
            try:
                ui = Terminal(service)
                async with ui.run_test(size=(140, 40)) as pilot:
                    ui.show_info('SSH 公钥', service.ssh.public())
                    await pilot.pause()
                    await pilot.press('ctrl+c')
                    self.assertTrue(ui.is_running)
                    self.assertEqual(len(ui.screen_stack), 2)
                    await pilot.press('ctrl+q')
                    self.assertFalse(ui.is_running)
            finally: service.close()


    async def test_export_trust_ca_is_der_root_without_unlock(self):
        from cryptography import x509
        from cryptography.hazmat.primitives import serialization
        with tempfile.TemporaryDirectory() as directory:
            service = Application(directory)
            service.store.exports = Path(directory)/"export"
            service.security.setup('secret')
            try:
                service.certificates.initialize('Network')
                expected = x509.load_pem_x509_certificate(service.certificates.public('root'))
                service.security.lock()
                ui = Terminal(service)
                async with ui.run_test(size=(140, 40)) as pilot:
                    ui.export_certificate()
                    await pilot.pause()
                    self.assertFalse(ui.screen.query('#password'))
                    from textual.widgets import Static
                    path = Path(str(ui.screen.query_one('#path', Static).render()))
                    self.assertFalse(ui.screen.query('#path Input'))
                    self.assertFalse(ui.screen.query_one('#path').can_focus)
                    self.assertEqual(path.name, 'root-ca.cer')
                    await pilot.press('ctrl+s')
                    await pilot.pause()
                    data = path.read_bytes()
                    cert = x509.load_der_x509_certificate(data)
                    self.assertEqual(data, expected.public_bytes(serialization.Encoding.DER))
                    self.assertEqual(cert.subject, cert.issuer)
                    self.assertTrue(cert.extensions.get_extension_for_class(x509.BasicConstraints).value.ca)
                    self.assertFalse(service.certificates.unlocked)
            finally: service.close()


    async def test_site_global_settings_save_and_cancel(self):
        from app.tui.widgets import Checkbox
        with tempfile.TemporaryDirectory() as directory:
            service = Application(directory)
            service.store.exports = Path(directory)/"export"
            service.security.setup('secret')
            try:
                ui = Terminal(service)
                async with ui.run_test(size=(140, 40)) as pilot:
                    await pilot.press('f2')
                    self.assertTrue(ui.query_one('#site-settings').display)
                    ui.site_settings()
                    await pilot.pause()
                    self.assertTrue(ui.screen.query_one('#verify', Checkbox).value)
                    await pilot.press('space', 'ctrl+s')
                    await pilot.pause()
                    self.assertFalse(service.snapshot().verify_origin_https)
                    ui.site_settings()
                    await pilot.pause()
                    await pilot.press('space', 'escape')
                    await pilot.pause()
                    self.assertFalse(service.snapshot().verify_origin_https)
                    await pilot.press('f3')
                    self.assertFalse(ui.query_one('#site-settings').display)
            finally: service.close()

    async def test_cached_versions_visible_while_refreshing(self):
        import json
        import threading
        from unittest.mock import patch
        from app.tui.publishing import Export
        from app.network.files import atomic
        from textual.widgets import DataTable
        with tempfile.TemporaryDirectory() as directory:
            service=Application(directory)
            service.store.exports=Path(directory)/"export"
            service.security.setup('secret')
            ready=threading.Event()
            try:
                cache=service.releases.cache
                atomic(cache.catalog,json.dumps([{'tag_name':'v2.11.7','draft':False,'prerelease':False}]).encode())
                def refresh():
                    ready.wait(5)
                    return ['v2.12.0','v2.11.7']
                ui=Terminal(service)
                with patch.object(cache,'online_versions',side_effect=refresh):
                    async with ui.run_test(size=(140,40)) as pilot:
                        screen=Export('new-deploy');ui.push_screen(screen)
                        await pilot.pause()
                        self.assertEqual(screen.selected_version(),'v2.11.7')
                        indicator=screen.query_one('#version-refresh')
                        self.assertTrue(indicator.display)
                        self.assertFalse(indicator.can_focus)
                        self.assertEqual(screen.query_one('#versions',DataTable).row_count,1)
                        ready.set()
                        for _ in range(30):
                            await pilot.pause(0.05)
                            if not indicator.display:break
                        self.assertFalse(indicator.display)
                        self.assertEqual(screen.selected_version(),'v2.11.7')
            finally:
                ready.set()
                service.close()


    async def test_p12_destination_is_readonly_and_uses_current_data_directory(self):
        from textual.widgets import Static
        from cryptography.hazmat.primitives.serialization import pkcs12
        with tempfile.TemporaryDirectory() as directory:
            service=Application(directory)
            service.store.exports=Path(directory)/"export"
            service.security.setup('secret')
            try:
                service.certificates.initialize('Network')
                service.certificates.sign_client('Phone')
                ui=Terminal(service)
                async with ui.run_test(size=(140,40)) as pilot:
                    ui.export_certificate(service.certificates.clients()[0])
                    await pilot.pause()
                    field=ui.screen.query_one('#path',Static)
                    self.assertFalse(field.can_focus)
                    self.assertEqual(str(field.render()),str(Path(directory).resolve()/'export'/'Phone.p12'))
                    self.assertFalse(ui.screen.query('#visible'))
                    self.assertTrue(all(not field.password for field in ui.screen.query(Input)))
                    ui.screen.query_one('#password',Input).value='export'
                    self.assertFalse(ui.screen.query('#repeat'))
                    await pilot.press('ctrl+s');await pilot.pause()
                    key,cert,_=pkcs12.load_key_and_certificates((Path(directory)/'export'/'Phone.p12').read_bytes(),b'export')
                    self.assertIsNotNone(key)
                    self.assertIsNotNone(cert)
            finally:service.close()

    async def test_process_unlock_retry_reuse_change_password_and_separate_confirmation(self):
        from app.tui.dialogs import PasswordDialog, Form
        with tempfile.TemporaryDirectory() as directory:
            service=Application(directory)
            service.store.exports=Path(directory)/"export"
            service.security.setup('initial');service.security.lock()
            try:
                ui=Terminal(service)
                async with ui.run_test(size=(140,40)) as pilot:
                    await pilot.press('f4','ctrl+n');await pilot.pause()
                    self.assertIsInstance(ui.screen,PasswordDialog)
                    await pilot.press('escape');await pilot.pause()
                    self.assertFalse(service.security.unlocked)
                    self.assertEqual(service.snapshot().regions,[])
                    await pilot.press('ctrl+n');await pilot.pause()
                    ui.screen.query_one('#password',Input).value='incorrect'
                    await pilot.press('ctrl+s');await pilot.pause()
                    self.assertIsInstance(ui.screen,PasswordDialog)
                    self.assertFalse(service.security.unlocked)
                    self.assertFalse(ui.screen.query('#visible'))
                    self.assertTrue(ui.screen.query_one('#password',Input).password)
                    ui.screen.query_one('#password',Input).value='initial'
                    await pilot.press('ctrl+s');await pilot.pause()
                    self.assertNotIsInstance(ui.screen,PasswordDialog)
                    ui.screen.query_one('#name',Input).value='Home'
                    await pilot.press('ctrl+s');await pilot.pause()
                    self.assertTrue(service.security.unlocked)
                    await pilot.press('ctrl+n');await pilot.pause()
                    self.assertFalse(ui.screen.query('#password'))
                    await pilot.press('escape','delete');await pilot.pause()
                    self.assertIsInstance(ui.screen,Form)
                    self.assertNotIsInstance(ui.screen,PasswordDialog)
                    self.assertFalse(ui.screen.query('#password'))
                    await pilot.press('escape');await pilot.pause()
                    ui.change_program_password();await pilot.pause()
                    self.assertIsInstance(ui.screen,PasswordDialog)
                    self.assertFalse(ui.screen.query('#old'))
                    self.assertFalse(ui.screen.query('#visible'))
                    self.assertTrue(all(not field.password for field in ui.screen.query(Input)))
                    for key in ('password','repeat'):ui.screen.query_one('#'+key,Input).value='replacement'
                    await pilot.press('ctrl+s');await pilot.pause()
                    self.assertTrue(service.security.unlocked)
                service.security.lock()
                with self.assertRaises(ValueError):service.security.unlock('initial')
                service.security.unlock('replacement')
            finally:service.close()

    async def test_semantic_shortcuts_and_danger_confirmation(self):
        from app.tui.dialogs import Form
        from app.tui.widgets import Button
        with tempfile.TemporaryDirectory() as directory:
            service=Application(directory);service.store.exports=Path(directory)/"export";service.security.setup('secret')
            service.create('regions','Home');service.certificates.initialize('Network')
            service.certificates.sign_client('Phone')
            try:
                ui=Terminal(service)
                async with ui.run_test(size=(140,40)) as pilot:
                    await pilot.press('f4','delete');await pilot.pause()
                    self.assertFalse(ui.screen.confirm)
                    self.assertEqual(ui.screen.query_one('#save',Button).label.plain,'确认 · ^s')
                    await pilot.press('ctrl+s');await pilot.pause()
                    self.assertEqual(service.snapshot().regions,[])
                    await pilot.press('f5','ctrl+e');await pilot.pause()
                    self.assertEqual(ui.screen.caption,'导出 P12')
                    await pilot.press('escape');await pilot.pause()
                    ui.page='ca';ui.render_page()
                    await pilot.press('ctrl+e');await pilot.pause()
                    self.assertEqual(ui.screen.caption,'导出信任 CA')
                    self.assertEqual(ui.screen.query_one('#save',Button).label.plain,'保存 · ^s')
                    self.assertFalse(any('Enter' in b.label.plain for screen in ui.screen_stack for b in screen.query(Button)))
                    await pilot.press('escape');await pilot.pause()
                    ui.show_info('信息','完成');await pilot.pause()
                    await pilot.press('ctrl+s');await pilot.pause()
                    self.assertEqual(len(ui.screen_stack),1)
            finally:service.close()

    async def test_navigation_and_three_state_help_cycle(self):
        from app.tui.widgets import Button
        with tempfile.TemporaryDirectory() as directory:
            service=Application(directory);service.store.exports=Path(directory)/"export";service.security.setup('secret')
            service.create('regions','Home')
            try:
                ui=Terminal(service)
                async with ui.run_test(size=(140,40)) as pilot:
                    self.assertEqual(ui.query_one('#help',Button).render().plain,'帮助 · F10')
                    for number,page in enumerate(('deployment','sites','nodes','regions','clients','public_tls'),1):
                        await pilot.press(f'f{number}');await pilot.pause()
                        self.assertEqual(ui.page,page)
                    await pilot.press('f10');await pilot.pause()
                    self.assertTrue(ui.show_shortcuts)
                    self.assertEqual(ui.help_state,1)
                    await pilot.press('f10');await pilot.pause()
                    self.assertEqual(ui.screen.caption,'使用说明')
                    note=ui.screen.query_one('#guide-scroll')
                    self.assertGreater(note.max_scroll_y,0)
                    await pilot.press('pagedown');await pilot.pause()
                    self.assertGreater(note.scroll_y,0)
                    self.assertEqual([b.id for b in ui.screen.query(Button)],['cancel'])
                    await pilot.press('f10');await pilot.pause()
                    self.assertFalse(ui.show_shortcuts)
                    self.assertEqual(len(ui.screen_stack),1)
                    await pilot.press('f3','ctrl+n');await pilot.pause()
                    original=ui.screen
                    await pilot.press('f10','f10');await pilot.pause()
                    self.assertEqual(ui.screen.caption,'使用说明')
                    await pilot.press('escape');await pilot.pause()
                    self.assertIs(ui.screen,original)
                    self.assertEqual(ui.help_state,0)
                    await pilot.press('escape');await pilot.pause()
                    await pilot.click('#help');await pilot.pause(0.4)
                    self.assertEqual(ui.help_state,1)
                    await pilot.click('#help');await pilot.pause(0.4)
                    self.assertEqual(ui.screen.caption,'使用说明')
            finally:service.close()

    async def test_matrix_row_accent_and_row_selection_survive_blur(self):
        from app.tui.widgets import DataTable
        def colors(table):
            result={}
            for y in range(table.size.height):
                for segment in table.render_line(y):
                    if not segment.style or not segment.text.strip(): continue
                    meta=segment.style.meta
                    if 'row' in meta and 'column' in meta and segment.style.bgcolor:
                        result[(meta['row'],meta['column'])]=segment.style.bgcolor.get_truecolor()
            return result
        with tempfile.TemporaryDirectory() as directory:
            service=Application(directory);service.store.exports=Path(directory)/"export";service.security.setup('secret')
            service.create('regions','Home');service.create('regions','Public')
            service.certificates.initialize('Network');service.certificates.sign_client('Phone')
            try:
                ui=Terminal(service)
                async with ui.run_test(size=(140,40)) as pilot:
                    await pilot.press('f4');await pilot.pause()
                    table=ui.query_one('#matrix',DataTable)
                    table.move_cursor(row=0,column=1);await pilot.pause()
                    selected=colors(table)
                    self.assertEqual(selected[(0,0)],(144,194,232))
                    self.assertEqual(selected[(0,1)],(0,120,212))
                    self.assertEqual(selected[(0,2)],(144,194,232))
                    await pilot.press('down');await pilot.pause()
                    selected=colors(table)
                    self.assertNotEqual(selected[(0,0)],(144,194,232))
                    self.assertEqual(selected[(1,0)],(144,194,232))
                    await pilot.press('f5');await pilot.pause()
                    focused=colors(table)
                    for column in range(3): self.assertEqual(focused[(0,column)],(0,120,212))
                    await pilot.press('tab');await pilot.pause()
                    self.assertFalse(table.has_focus)
                    blurred=colors(table)
                    for column in range(3): self.assertEqual(blurred[(0,column)],focused[(0,column)])
            finally:service.close()

    async def test_dialog_return_buttons_and_information_only_actions(self):
        from app.tui.widgets import Button
        from app.tui.dialogs import Form
        from app.tui.publishing import Export
        from unittest.mock import patch
        from types import SimpleNamespace
        with tempfile.TemporaryDirectory() as directory:
            service=Application(directory);service.store.exports=Path(directory)/"export";service.security.setup('secret')
            service.create('regions','Home')
            try:
                ui=Terminal(service)
                async with ui.run_test(size=(140,40)) as pilot:
                    await pilot.press('f3','ctrl+n');await pilot.pause()
                    ui.screen.query_one('#name',Input).value='Unsaved'
                    await pilot.click('#cancel');await pilot.pause()
                    self.assertEqual(service.snapshot().nodes,[])
                    ui.push_screen(Form('删除测试？',[],confirm=True));await pilot.pause()
                    ui.screen.query_one('#cancel').focus()
                    await pilot.press('enter');await pilot.pause()
                    self.assertEqual(len(ui.screen_stack),1)
                    await pilot.press('f10','f10');await pilot.pause()
                    self.assertEqual([b.label.plain for b in ui.screen.query(Button)],['返回 · Esc'])
                    await pilot.click('#cancel');await pilot.pause()
                    await pilot.press('f1');await pilot.pause()
                    await pilot.click('#ssh-guide');await pilot.pause()
                    self.assertEqual([b.label.plain for b in ui.screen.query(Button)],['返回 · Esc'])
                    await pilot.press('enter');await pilot.pause()
                    with patch('app.network.releases.BinaryCache.online_versions',return_value=[]):
                        ui.push_screen(Export('new-deploy'));await pilot.pause()
                        await pilot.click('#cancel');await pilot.pause()
                    self.assertEqual(len(ui.screen_stack),1)
            finally:service.close()

    async def test_close_export_during_refresh_after_indicator_removed(self):
        import threading
        from unittest.mock import patch
        from app.tui.publishing import Export
        ready=threading.Event()
        with tempfile.TemporaryDirectory() as directory:
            service=Application(directory)
            service.store.exports=Path(directory)/"export"
            try:
                ui=Terminal(service)
                def refresh():
                    ready.wait(5)
                    return ['v2.11.7']
                with patch.object(service.releases.cache,'online_versions',side_effect=refresh):
                    async with ui.run_test(size=(140,40)) as pilot:
                        screen=Export('new-deploy');ui.push_screen(screen)
                        await pilot.pause()
                        # Reproduce teardown ordering: child gone, parent still mounted.
                        await screen.query_one('#version-refresh').remove()
                        self.assertTrue(screen.is_mounted)
                        workers=list(ui.workers)
                        await pilot.press('escape');await pilot.pause()
                        ready.set();await pilot.pause()
                        self.assertEqual(len(ui.screen_stack),1)
                        self.assertTrue(all(worker.state.name != 'ERROR' for worker in workers),
                                        [(worker.state.name,repr(worker.error)) for worker in workers])
                        # The application remains usable after the cancelled refresh.
                        await pilot.press('f4');await pilot.pause()
                        self.assertEqual(ui.page,'regions')
            finally:
                ready.set();service.close()

    async def test_download_progress_and_unknown_size(self):
        from app.tui.task_progress import TaskProgress
        from app.network.task_progress import DownloadProgress
        from textual.widgets import ProgressBar
        import threading
        ready=threading.Event()
        with tempfile.TemporaryDirectory() as directory:
            service=Application(directory)
            service.store.exports=Path(directory)/"export"
            try:
                ui=Terminal(service)
                async with ui.run_test(size=(140,40)) as pilot:
                    panel=TaskProgress('下载',lambda *args:ready.wait(5),str)
                    ui.push_screen(panel);await pilot.pause()
                    panel.show_detail(DownloadProgress('amd64',1024,4096,512))
                    self.assertEqual(panel.query_one('#task-current',ProgressBar).percentage,.25)
                    panel.show_detail(DownloadProgress('amd64',1024,None,512))
                    self.assertIsNone(panel.query_one('#task-current',ProgressBar).total)
                    ready.set();await pilot.pause()
            finally:ready.set();service.close()

class ConfirmationStyleTests(unittest.IsolatedAsyncioTestCase):
    async def test_danger_enter_and_return_shortcuts(self):
        from app.tui.dialogs import Form
        from app.tui.widgets import Button
        with tempfile.TemporaryDirectory() as directory:
            service=Application(directory)
            service.store.exports=Path(directory)/"export"
            try:
                ui=Terminal(service)
                async with ui.run_test(size=(140,40)) as pilot:
                    for title in ('重置 SSH 私钥？','重新初始化 CA？'):
                        answers=[]
                        dialog=Form(title,[],confirm=True)
                        ui.push_screen(dialog,answers.append)
                        await pilot.pause()
                        self.assertEqual(dialog.query_one('#save',Button).variant,'error')
                        await pilot.press('enter','ctrl+s')
                        await pilot.pause()
                        self.assertEqual(answers,[])
                        self.assertIs(ui.screen,dialog)
                        back=dialog.query_one('#cancel',Button)
                        ui.show_shortcuts=False
                        self.assertEqual(back.render().plain,'返回')
                        ui.show_shortcuts=True
                        self.assertEqual(back.render().plain,'返回 · Esc')
                        await pilot.press('escape')
                        await pilot.pause()
                        self.assertEqual(answers,[None])
            finally:
                service.close()

    async def test_danger_requires_fresh_password_even_when_unlocked(self):
        from app.tui.dialogs import Form, PasswordDialog
        with tempfile.TemporaryDirectory() as directory:
            service=Application(directory);service.store.exports=Path(directory)/"export";service.security.setup('secret')
            try:
                ui=Terminal(service)
                async with ui.run_test(size=(140,40)) as pilot:
                    answers=[]
                    dialog=Form('重置 SSH 私钥？',[],confirm=True)
                    ui.push_screen(dialog,answers.append);await pilot.pause()
                    await pilot.press('ctrl+y');await pilot.pause()
                    self.assertIsInstance(ui.screen,PasswordDialog)
                    self.assertTrue(ui.screen.query_one('#password').password)
                    ui.screen.query_one('#password').value='wrong'
                    await pilot.press('ctrl+s');await pilot.pause()
                    self.assertEqual(answers,[])
                    self.assertTrue(service.security.unlocked)
                    await pilot.press('escape');await pilot.pause()
                    self.assertIs(ui.screen,dialog)
                    await pilot.press('ctrl+y');await pilot.pause()
                    self.assertEqual(ui.screen.query_one('#password').value,'')
                    ui.screen.query_one('#password').value='secret'
                    await pilot.press('ctrl+s');await pilot.pause()
                    self.assertEqual(answers,[{}])
            finally:
                service.close()

class SiteOrderingTests(unittest.IsolatedAsyncioTestCase):
    async def test_saved_order_and_append_survive_reentry(self):
        with tempfile.TemporaryDirectory() as directory:
            service=Application(directory);service.store.exports=Path(directory)/"export";service.security.setup('secret')
            z=service.create('sites','Zulu');b=service.create('sites','bravo')
            ui=Terminal(service)
            try:
                async with ui.run_test(size=(140,40)) as pilot:
                    await pilot.press('f2');await pilot.pause()
                    self.assertEqual(ui.row_ids,[z,b])
                    await pilot.press('ctrl+n');await pilot.pause()
                    ui.screen.query_one('#name',Input).value='Alpha'
                    await pilot.press('ctrl+s');await pilot.pause()
                    a=next(site.id for site in service.snapshot().sites if site.name=='Alpha')
                    self.assertEqual(ui.row_ids,[z,b,a])
                    ui.after_change('')
                    self.assertEqual(ui.row_ids,[z,b,a])
                    await pilot.press('f1','f2');await pilot.pause()
                    self.assertEqual(ui.row_ids,[z,b,a])
                    self.assertEqual([site.id for site in service.snapshot().sites],[z,b,a])
            finally:
                service.close()
