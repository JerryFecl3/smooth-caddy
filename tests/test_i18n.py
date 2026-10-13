import ast
import os
from pathlib import Path
import string
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch, Mock

from app.i18n import get_language, system_language, set_language, tr
from app.messages import EN

ROOT = Path(__file__).resolve().parents[1]


class LanguageTests(unittest.TestCase):
    def test_catalog_covers_literals_and_preserves_placeholders(self):
        formatter = string.Formatter()
        for path in (ROOT / 'app').rglob('*.py'):
            for node in ast.walk(ast.parse(path.read_text(encoding='utf-8'))):
                if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                        and node.func.id == 'tr' and node.args
                        and isinstance(node.args[0], ast.Constant)):
                    source = node.args[0].value
                    self.assertIn(source, EN, f'{path}: {source}')
        for source, translated in EN.items():
            fields = lambda text: sorted((field, spec, conversion) for _, field, spec, conversion
                                         in formatter.parse(text) if field is not None)
            self.assertEqual(fields(source), fields(translated), source)

    def test_posix_language_detection(self):
        cases = [({}, 'en'), ({'LANG': 'zh_CN.UTF-8'}, 'zh-CN'),
                 ({'LANG': 'zh_TW.UTF-8'}, 'zh-CN'), ({'LANG': 'zh-HK'}, 'zh-CN'),
                 ({'LANG': 'de_DE.UTF-8'}, 'en'), ({'LANG': 'invalid'}, 'en'),
                 ({'LANG': 'zh_CN', 'LC_MESSAGES': 'en_US'}, 'en'),
                 ({'LANG': 'en_US', 'LC_MESSAGES': 'en_US', 'LC_ALL': 'zh_CN'}, 'zh-CN'),
                 ({'LANG': 'zh_CN', 'LC_ALL': 'C.UTF-8'}, 'en')]
        cases.extend(({'LANG': value}, 'zh-CN') for value in
                     ('zh', 'zh_CN', 'zh_SG', 'zh_TW', 'zh_HK', 'zh_MO',
                      'zh-Hans', 'zh-Hant', 'zh-Hant-HK', 'zh_CN.GB18030', 'zh_TW.UTF-8@variant'))
        with patch('app.i18n.sys.platform', 'linux'), patch('app.i18n.locale.getlocale', return_value=(None, None)):
            for environment, expected in cases:
                with self.subTest(environment=environment), patch.dict(os.environ, environment, clear=True):
                    self.assertEqual(system_language(), expected)
        with patch('app.i18n.sys.platform', 'linux'), patch.dict(os.environ, {}, clear=True), patch('app.i18n.locale.LC_MESSAGES', 5, create=True):
            with patch('app.i18n.locale.getlocale', return_value=('zh_CN', 'UTF-8')):
                self.assertEqual(system_language(), 'zh-CN')
            with patch('app.i18n.locale.getlocale', side_effect=ValueError):
                self.assertEqual(system_language(), 'en')

    def test_windows_display_language(self):
        api = Mock()
        with patch('app.i18n.sys.platform', 'win32'), patch('ctypes.windll', api, create=True):
            for language_id, expected in [(0x0804, 'zh-CN'), (0x0404, 'zh-CN'), (0x0c04, 'zh-CN'), (0x1004, 'zh-CN'), (0x1404, 'zh-CN'), (0x0409, 'en'), (0x0407, 'en'), (0, 'en')]:
                api.kernel32.GetUserDefaultUILanguage.return_value = language_id
                self.assertEqual(system_language(), expected)
            api.kernel32.GetUserDefaultUILanguage.side_effect = OSError
            self.assertEqual(system_language(), 'en')

    def test_cli_ignores_old_settings_and_does_not_write_files(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'ui.json'
            path.write_text('invalid old settings', encoding='utf-8')
            def help_text(*args):
                return subprocess.run([sys.executable, 'smooth_caddy.py', '--data-dir', directory,
                                       *args, '--help'], cwd=ROOT, check=True,
                                      capture_output=True, text=True, encoding='utf-8').stdout
            self.assertNotIn('个人网络', help_text('--language', 'en'))
            self.assertIn('个人网络', help_text('--language', 'zh-CN'))
            help_text()
            self.assertEqual(path.read_text(), 'invalid old settings')
            self.assertEqual(list(Path(directory).iterdir()), [path])

    @unittest.skipIf(sys.platform == 'win32', 'Windows uses the display-language API')
    def test_real_entry_follows_message_locale_without_creating_settings(self):
        with tempfile.TemporaryDirectory() as directory:
            for language, chinese in [('zh_Hant_TW.UTF-8', True), ('en_US.UTF-8', False), ('C', False)]:
                environment = dict(os.environ, LC_ALL=language, LANG='zh_CN.UTF-8')
                result = subprocess.run(
                    [sys.executable, 'smooth_caddy.py', '--data-dir', directory, '--help'],
                    cwd=ROOT, env=environment, check=True, capture_output=True,
                    text=True, encoding='utf-8')
                self.assertEqual('个人网络' in result.stdout, chinese, result.stdout)
            self.assertEqual(list(Path(directory).iterdir()), [])

    def test_english_ui_in_fresh_process(self):
        # Production chooses the language before loading UI classes and bindings.
        script = '''
import asyncio
import tempfile
from app.i18n import set_language
set_language('en')
from app.network.application import Application
from app.tui.ui import Terminal, PAGES
from app.tui.dialogs import InitializationDialog
from app.tui.labels import options
from app.tui.guide import usage_guide
from textual.widgets import Input, Select, Button
async def check():
    with tempfile.TemporaryDirectory() as directory:
        app = Application(directory)
        try:
            ui = Terminal(app)
            async with ui.run_test(size=(140, 40)) as pilot:
                # Startup pushes the dialog after a refresh. A single pause can
                # return after it enters the stack but before its children mount.
                async def wait_for_initialization():
                    while not (isinstance(ui.screen, InitializationDialog) and ui.screen.is_mounted):
                        await asyncio.sleep(0.01)
                await asyncio.wait_for(wait_for_initialization(), timeout=10)
                await pilot.pause()
                assert isinstance(ui.screen, InitializationDialog)
                assert ui.screen.caption == 'Initialize', ui.screen.caption
                for key in ('password', 'repeat'):
                    ui.screen.query_one('#' + key, Input).value = 'test-secret'
                ui.screen.query_one('#name', Input).value = 'Test CA'
                await pilot.press('ctrl+s')
                await pilot.pause()
                assert len(ui.screen_stack) == 1
                assert not ui.query('#language')
                assert PAGES['nodes'] == 'Nodes'
                for key in ('f1', 'f2', 'f3', 'f6', 'f4', 'f5'):
                    await pilot.press(key)
                    await pilot.pause()
                assert options(['direct'])[0][1] == 'direct'
                assert 'Smooth Caddy' in usage_guide()
        finally:
            app.close()
asyncio.run(check())
print('ENGLISH_UI_OK')
'''
        # Windows children otherwise inherit a code-page encoding while the
        # parent decodes UTF-8; a reader-thread decode failure can leave None.
        environment = dict(os.environ, PYTHONIOENCODING='utf-8', PYTHONUTF8='1')
        result = subprocess.run([sys.executable, '-c', script], cwd=ROOT, env=environment,
                                capture_output=True, text=True, encoding='utf-8',
                                errors='backslashreplace', timeout=60)
        output = (result.stdout or '') + (result.stderr or '')
        self.assertEqual(result.returncode, 0, output)
        self.assertIn('ENGLISH_UI_OK', result.stdout or '', output)
