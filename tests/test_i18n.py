import ast
import json
from pathlib import Path
import string
import subprocess
import sys
import tempfile
import unittest

from app.i18n import get_language, saved_language, save_language, set_language, tr
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

    def test_preferences_validation_and_user_text(self):
        previous = get_language()
        try:
            with tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / 'ui.json'
                self.assertEqual(saved_language(directory), 'zh-CN')
                path.write_text('{"other": 42}', encoding='utf-8')
                save_language(directory, 'en')
                self.assertEqual(saved_language(directory), 'en')
                self.assertEqual(json.loads(path.read_text())['other'], 42)
                set_language('en')
                self.assertEqual(tr('节点'), 'Nodes')
                self.assertIn('我的节点', tr('新增') + '我的节点')
                for invalid in ('[]', '{"language":"fr"}', 'invalid'):
                    path.write_text(invalid, encoding='utf-8')
                    with self.assertRaises(ValueError):
                        saved_language(directory)
                path.write_text('[]', encoding='utf-8')
                with self.assertRaises(ValueError):
                    save_language(directory, 'en')
        finally:
            set_language(previous)

    def test_cli_saved_language_and_temporary_override(self):
        with tempfile.TemporaryDirectory() as directory:
            save_language(directory, 'en')
            def help_text(*args):
                return subprocess.run([sys.executable, 'smooth_caddy.py', '--data-dir', directory,
                                       *args, '--help'], cwd=ROOT, check=True,
                                      capture_output=True, text=True, encoding='utf-8').stdout
            self.assertNotIn('个人网络', help_text())
            self.assertIn('个人网络', help_text('--language', 'zh-CN'))
            self.assertEqual(saved_language(directory), 'en')
            self.assertFalse((Path(directory) / 'smooth-caddy.db').exists())

    def test_english_ui_in_fresh_process(self):
        # Production chooses the language before loading UI classes and bindings.
        script = '''
import asyncio
import tempfile
from app.i18n import set_language, saved_language
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
                await pilot.pause()
                assert isinstance(ui.screen, InitializationDialog)
                assert ui.screen.caption == 'Initialize', ui.screen.caption
                for key in ('password', 'repeat'):
                    ui.screen.query_one('#' + key, Input).value = 'test-secret'
                ui.screen.query_one('#name', Input).value = 'Test CA'
                await pilot.press('ctrl+s')
                await pilot.pause()
                assert len(ui.screen_stack) == 1
                assert str(ui.query_one('#language', Button).label) == 'Language'
                assert PAGES['nodes'] == 'Nodes'
                for key in ('f1', 'f2', 'f3', 'f4', 'f5', 'f6'):
                    await pilot.press(key)
                    await pilot.pause()
                before = app.snapshot().to_dict()
                ui.language_settings()
                await pilot.pause()
                assert ui.screen.caption == 'Interface language'
                ui.screen.query_one('#language', Select).value = 'zh-CN'
                await pilot.press('ctrl+s')
                await pilot.pause()
                assert saved_language(directory) == 'zh-CN'
                assert app.snapshot().to_dict() == before
                assert options(['direct'])[0][1] == 'direct'
                assert 'Smooth Caddy' in usage_guide()
        finally:
            app.close()
asyncio.run(check())
'''
        result = subprocess.run([sys.executable, '-c', script], cwd=ROOT,
                                capture_output=True, text=True, encoding='utf-8', timeout=60)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
