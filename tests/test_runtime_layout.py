import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from app.network.runtime import Runtime
from app.network.application import Application
from app.network.files import publish
from tests.ui_helpers import ReadyTerminal

class RuntimeTests(unittest.TestCase):
    def test_single_owner_and_cleanup(self):
        with tempfile.TemporaryDirectory() as root:
            data=Path(root)/'data';temp=data/'.tmp';temp.mkdir(parents=True)
            (temp/'stale').write_text('old')
            runtime=Runtime(data)
            try:
                runtime.ready.result()
                self.assertEqual(list(temp.iterdir()),[])
                with self.assertRaises(ValueError):Runtime(data)
                (temp/'work').write_text('new')
            finally:runtime.close()
            self.assertEqual(list(temp.iterdir()),[])
            again=Runtime(data);again.ready.result();again.close()

    def test_paths_and_failed_publish(self):
        with tempfile.TemporaryDirectory() as root:
            app=Application(Path(root)/'data')
            try:
                self.assertEqual(app.store.path.name,'smooth-caddy.db')
                self.assertEqual(app.store.exports,Path(root).resolve()/'export')
                self.assertEqual(app.releases.cache.root,app.store.directory/'tool_caddy')
                target=app.store.exports/'test.cer'
                publish(target,b'old',app.store.temporary)
                with patch('app.network.files.os.replace',side_effect=OSError('failed')):
                    with self.assertRaises(OSError):publish(target,b'new',app.store.temporary)
                self.assertEqual(target.read_bytes(),b'old')
                self.assertEqual(list(app.store.temporary.iterdir()),[])
            finally:app.close()

class EmptyNavigationTests(unittest.IsolatedAsyncioTestCase):
    async def test_empty_then_configured(self):
        with tempfile.TemporaryDirectory() as root:
            app=Application(Path(root)/'data');app.security.setup('test')
            try:
                ui=ReadyTerminal(app)
                async with ui.run_test() as pilot:
                    self.assertEqual(ui.page,'deployment')
                    self.assertFalse(ui.query_one('#nav-deployment').disabled)
                    await pilot.press('f1')
                    self.assertEqual(ui.page,'deployment')
                    app.create('regions','Home');ui.render_page()
                    self.assertFalse(ui.query_one('#nav-deployment').disabled)
                    await pilot.press('f1')
                    self.assertEqual(ui.page,'deployment')
            finally:app.close()
