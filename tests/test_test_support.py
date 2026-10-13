"""Regression coverage for real delayed mounting and subprocess diagnostics."""
import asyncio
from contextlib import closing
import tempfile
import unittest
from unittest.mock import patch
from app.network.application import Application
from app.tui.dialogs import InitializationDialog
from app.tui.ui import Terminal
from tests.support import run_python, wait_for_screen, wait_until


class SupportTests(unittest.TestCase):
    def test_unicode_and_failure_output(self):
        result = run_python('-c', "print('中文输出')")
        self.assertIn('中文输出', result.stdout)
        with self.assertRaises(AssertionError) as caught:
            run_python('-c', "import sys; print('正常输出'); print('失败原因',file=sys.stderr); sys.exit(7)")
        for text in ('exited with 7', '正常输出', '失败原因'):
            self.assertIn(text, str(caught.exception))

    def test_timeout_keeps_partial_output(self):
        with self.assertRaises(AssertionError) as caught:
            run_python('-u', '-c', "import time; print('before timeout'); time.sleep(30)", timeout=2)
        self.assertIn('timed out', str(caught.exception))
        self.assertIn('before timeout', str(caught.exception))


class MountTests(unittest.IsolatedAsyncioTestCase):
    async def test_screen_waits_for_mount_completion(self):
        entered, release = asyncio.Event(), asyncio.Event()
        original = InitializationDialog.on_mount
        async def delayed_mount(dialog):
            entered.set()
            await release.wait()
            original(dialog)
        with tempfile.TemporaryDirectory() as directory, closing(Application(directory)) as app:
            with patch.object(InitializationDialog, 'on_mount', delayed_mount):
                ui = Terminal(app)
                async with ui.run_test(size=(140, 40)):
                    await asyncio.wait_for(entered.wait(), 10)
                    waiter = asyncio.create_task(wait_for_screen(ui, InitializationDialog, controls=('#password', '#save')))
                    try:
                        await asyncio.sleep(0)  # Run the waiter while mount is held by the gate.
                        self.assertFalse(waiter.done())
                        release.set()
                        self.assertIs(await waiter, ui.screen)
                        self.assertTrue(ui.screen.is_mounted)
                    finally:
                        release.set()
                        if not waiter.done():
                            waiter.cancel()
                        await asyncio.gather(waiter, return_exceptions=True)

    async def test_missing_state_has_bounded_diagnostic(self):
        with self.assertRaisesRegex(AssertionError, 'waiting for missing control'):
            await wait_until(lambda: False, description='missing control', timeout=0.02)
