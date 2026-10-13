"""Supported shell entry points; business operations remain separate from TUI."""
import contextlib
import io
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from app.entry import main, default_data_directory
from tests.support import run_python

class EntryTests(unittest.TestCase):
    def setUp(self):
        from app.i18n import get_language, set_language
        self.addCleanup(set_language, get_language())
        detector = patch('app.entry.system_language', return_value='zh-CN')
        detector.start()
        self.addCleanup(detector.stop)

    def test_system_language_and_explicit_override(self):
        from app.i18n import get_language
        with tempfile.TemporaryDirectory() as directory, patch('app.entry.system_language', return_value='en'), patch('app.tui.ui.main'):
            main(['--data-dir', directory])
            self.assertEqual(get_language(), 'en')
            main(['--language', 'zh-CN'])
            self.assertEqual(get_language(), 'zh-CN')

    def test_saved_language_and_cli_precedence(self):
        from app.preferences import save_language
        from app.i18n import get_language
        with tempfile.TemporaryDirectory() as directory, patch('app.tui.ui.main'):
            for preference, expected in [('en', 'en'), ('zh-CN', 'zh-CN'), ('auto', 'zh-CN')]:
                save_language(directory, preference)
                main(['--data-dir', directory])
                self.assertEqual(get_language(), expected)
            save_language(directory, 'zh-CN')
            main(['--data-dir', directory, '--language', 'en'])
            self.assertEqual(get_language(), 'en')
            from app.preferences import load_language
            self.assertEqual(load_language(directory), 'zh-CN')

    def test_data_directory_forwarded(self):
        with tempfile.TemporaryDirectory() as directory,patch('app.tui.ui.main') as run:
            main(['--data-dir',directory]);run.assert_called_once_with(directory)
    def test_default_directory_is_user_home_relative(self):
        with patch('app.tui.ui.main') as run:
            main([])
            self.assertEqual(Path(run.call_args.args[0]),Path.home()/'.smooth-caddy')
    def test_frozen_data_uses_home_not_executable(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory).resolve()
            with patch.object(sys, 'frozen', True, create=True), patch.object(sys, 'executable', str(base/'bin'/'smooth-caddy')), patch('pathlib.Path.home', return_value=base):
                self.assertEqual(default_data_directory(), base/'.smooth-caddy')

    def test_root_and_module_help(self):
        for args in (['smooth_caddy.py'],['-m','app']):
            result=run_python(*args,'--help')
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertIn('--data-dir',result.stdout);self.assertNotIn('--prototype',result.stdout)
    def test_package_import_does_not_load_legacy_or_tui(self):
        result=run_python('-c',"import app,sys; assert not any(n in sys.modules for n in ('app.core','app.cli','app.tui.ui','prompt_toolkit'))")
        self.assertEqual(result.returncode,0,result.stderr)
    def test_removed_prototype_option_rejected(self):
        with contextlib.redirect_stderr(io.StringIO()),self.assertRaises(SystemExit) as error:main(['--prototype'])
        self.assertEqual(error.exception.code,2)
