"""Regression checks for shared policy, task plans and download behavior."""
import asyncio
import io
import tempfile
import threading
import unittest
from unittest.mock import patch
from app.network.downloads import fetch
from app.network.task_progress import TaskCancelled
from app.network.plans import TaskPlan
from app.network.models import Site, duplicate_domain, canonical_domain
from app.network.certificate_policy import renewal_status
from app.network.public_tls import REUSED
from tests import test_public_batch as fixtures

class SharedServiceTests(unittest.TestCase):
    def test_task_identity_mapping_survives_display_rename(self):
        first=TaskPlan.group('first',[('a','original')])
        second=TaskPlan.group('second',[('b','original')])
        combined=first.join(second)
        renamed=TaskPlan.group('second',[('b','renamed')])
        event=combined.map(renamed.event('b','done','success'))
        self.assertEqual(event.index,1)
        self.assertEqual(event.task_ids,('a','b'))
        self.assertEqual(event.status,'done')
        with self.assertRaises(ValueError):first.join(first)
    def test_domain_duplicate_normalization_shared_with_editor(self):
        unicode='例子.测试';ascii=canonical_domain(unicode)
        self.assertTrue(duplicate_domain([Site('a','first',domain=unicode)],ascii))
        self.assertFalse(duplicate_domain([Site('a','first',domain=unicode)],ascii,'a'))
    def test_download_cancellation_and_limits_are_shared(self):
        response=io.BytesIO(b'content');response.headers={'Content-Length':'7'}
        stop=threading.Event()
        with patch('app.network.downloads.urlopen',return_value=response):
            with self.assertRaises(TaskCancelled):
                fetch('https://example.test',progress=lambda _:stop.set(),cancel=stop)
        self.assertTrue(response.closed)
        stop=threading.Event();stop.set()
        with patch('app.network.downloads.urlopen') as network:
            with self.assertRaises(TaskCancelled):fetch('https://example.test',cancel=stop)
            network.assert_not_called()
    def test_one_certificate_checked_once_for_multiple_sites_and_real_expiry_used(self):
        fixture=fixtures.PublicBatchTests();fixture.setUp()
        try:
            app=fixture.app;identity=fixture.record();cert,_=fixture.store_material(identity)
            app.create('sites','Other');cfg=app.snapshot();site=cfg.sites[-1]
            site.domain='other.example.com';site.source='http://192.0.2.3';site.tls_source='公共 CA';site.areas=cfg.sites[0].areas.copy();app.save_configuration(cfg)
            with patch.object(app.public_tls,'validate',wraps=app.public_tls.validate) as validate:
                report=app.batches.inspect(app.snapshot())
                self.assertFalse(report.errors);self.assertEqual(validate.call_count,1)
            item=app.public_tls.get(identity);item['expires']='2000-01-01T00:00:00+00:00'
            with app.store.transaction():app.public_tls._put_result(identity,item)
            self.assertEqual(renewal_status(cert),'')
            with patch.object(app.public_tls,'_run',side_effect=AssertionError('must use certificate expiry')):
                self.assertEqual(app.public_tls.issue(identity),REUSED)
        finally:fixture.doCleanups()

class ValidationRefreshTests(unittest.IsolatedAsyncioTestCase):
    async def test_render_checks_once_and_does_not_cache_across_refreshes(self):
        from app.network.application import Application
        from tests.ui_helpers import ReadyTerminal as Terminal
        with tempfile.TemporaryDirectory() as directory:
            app=Application(directory);app.security.setup('test')
            try:
                for i in range(10):app.create('sites',f'Site{i}')
                ui=Terminal(app)
                async with ui.run_test(size=(140,40)) as pilot:
                    await pilot.press('f2');await pilot.pause()
                    with patch.object(app.batches,'inspect',wraps=app.batches.inspect) as inspect:
                        ui.render_page();self.assertEqual(inspect.call_count,1)
                        ui.refresh_navigation_labels();self.assertEqual(inspect.call_count,1)
                        ui.render_page();self.assertEqual(inspect.call_count,2)
            finally:app.close()
