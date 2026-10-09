import asyncio
import tempfile
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from app.network.application import Application
from app.network.task_progress import TaskStep,TaskCancelled,DownloadProgress
from app.network.deployment import DeploymentIssue
from tests.ui_helpers import ReadyTerminal as Terminal
from app.tui.task_progress import TaskProgress,DeploymentProgress
from textual.widgets import Static

class TaskProgressTests(unittest.IsolatedAsyncioTestCase):
    async def test_failure_retry_and_retained_completion(self):
        with tempfile.TemporaryDirectory() as directory:
            service=Application(directory)
            count=0
            def operation(progress,steps,cancel):
                nonlocal count
                count+=1
                steps(TaskStep(('下载','打包'),0))
                progress(DownloadProgress('amd64',10,20,5))
                if count==1:raise OSError('模拟下载失败')
                steps(TaskStep(('下载','打包'),1))
                return 'result'
            try:
                ui=Terminal(service)
                async with ui.run_test(size=(120,36)) as pilot:
                    panel=TaskProgress('生成完整包',operation,lambda result:result)
                    ui.push_screen(panel)
                    for _ in range(30):
                        await pilot.pause(0.05)
                        if panel.finished:break
                    self.assertTrue(panel.failed)
                    self.assertIn('模拟下载失败',str(panel.query_one('#task-detail',Static).render()))
                    self.assertTrue(panel.query_one('#task-retry').display)
                    await pilot.press('ctrl+s')
                    for _ in range(30):
                        await pilot.pause(0.05)
                        if panel.finished:break
                    self.assertFalse(panel.failed)
                    self.assertEqual(panel.result,'result')
                    self.assertIs(ui.screen,panel)
                    self.assertIn('✓ 打包',str(panel.query_one('#task-step-list',Static).render()))
                    await pilot.press('escape');await pilot.pause()
                    self.assertEqual(len(ui.screen_stack),1)
            finally:service.close()

    async def test_stop_confirmation_and_escape_does_not_abandon_task(self):
        release=threading.Event()
        with tempfile.TemporaryDirectory() as directory:
            service=Application(directory);service.security.setup('secret')
            def operation(progress,steps,cancel):
                steps(TaskStep(('打包',),0))
                release.wait(5)
                if cancel.is_set():raise TaskCancelled()
                return 'done'
            try:
                ui=Terminal(service)
                async with ui.run_test(size=(120,36)) as pilot:
                    panel=TaskProgress('生成配置包',operation,str);ui.push_screen(panel)
                    await pilot.pause()
                    await pilot.press('escape');await pilot.pause()
                    self.assertIs(ui.screen,panel)
                    self.assertTrue(panel.query_one('#task-back').disabled)
                    await pilot.click('#task-stop');await pilot.pause()
                    self.assertFalse(ui.screen.confirm)
                    await pilot.press('ctrl+s');await pilot.pause()
                    self.assertTrue(panel.stop.is_set())
                    release.set()
                    for _ in range(30):
                        await pilot.pause(0.05)
                        if panel.finished:break
                    self.assertTrue(panel.finished)
                    self.assertIn('已停止',str(panel.query_one('#task-summary',Static).render()))
                    self.assertFalse(panel.query_one('#task-back').disabled)
            finally:release.set();service.close()

    async def test_deployment_failure_inline_requery_and_success(self):
        with tempfile.TemporaryDirectory() as directory:
            service=Application(directory)
            batch=SimpleNamespace(version='test')
            node=SimpleNamespace(id='node',name='ECS')
            async def execute(batch,version,confirm,decide,progress,steps,cancel,created):
                steps(TaskStep(('探测','打包','上传','部署'),3))
                answer=await decide(DeploymentIssue('node','ECS','install','连接中断',True))
                self.assertEqual(answer,'retry')
                return {'batch':batch,'nodes':[node],'statuses':{'node':'success'},'success':True,'warnings':[]}
            try:
                ui=Terminal(service)
                with patch.object(service.deployment,'execute',side_effect=execute):
                    async with ui.run_test(size=(120,36)) as pilot:
                        panel=DeploymentProgress(batch,'v2.11.7');ui.push_screen(panel);await pilot.pause()
                        self.assertIsNotNone(panel.decision)
                        self.assertIn('重新查询',panel.query_one('#task-retry').label.plain)
                        await pilot.press('ctrl+s');await pilot.pause()
                        self.assertTrue(panel.finished)
                        self.assertIn('部署完成',str(panel.query_one('#task-summary',Static).render()))
                        self.assertFalse(panel.query_one('#task-detail').display)
            finally:service.close()

    async def test_combined_version_selection_and_single_confirmation(self):
        from app.tui.publishing import Export
        from app.tui.widgets import Button
        with tempfile.TemporaryDirectory() as directory:
            service=Application(directory);service.security.setup('secret')
            identity=service.create('nodes','Node')
            cfg=service.snapshot();cfg.nodes[0].ssh_ip='192.0.2.1';service.save_configuration(cfg)
            batch=SimpleNamespace(version='test')
            async def execute(original,version,confirm,decide,progress,steps,cancel,created):
                created(batch);steps(TaskStep(('生成配置批次','探测','打包','上传','部署'),4))
                return {'batch':batch,'nodes':cfg.nodes,'statuses':{identity:'success'},'success':True,'warnings':[]}
            try:
                ui=Terminal(service)
                with patch.object(service.releases.cache,'online_versions',return_value=['v2.11.7']),patch.object(service.deployment,'execute',side_effect=execute) as run:
                    async with ui.run_test(size=(120,36)) as pilot:
                        panel=Export('new-deploy');ui.push_screen(panel);await pilot.pause()
                        self.assertFalse(panel.query('#generate-config'))
                        await pilot.press('ctrl+s');await pilot.pause()
                        self.assertFalse(ui.screen.confirm)
                        await pilot.press('ctrl+s');await pilot.pause()
                        self.assertIsInstance(ui.screen,DeploymentProgress)
                        self.assertTrue(ui.screen.finished)
                        self.assertEqual(run.await_count,1)
                        self.assertEqual(len(ui.screen_stack),2)
            finally:service.close()

class DeploymentResultPresentationTests(unittest.TestCase):
    def test_results_update_steps_without_duplicate_summary(self):
        from types import SimpleNamespace
        from app.tui.task_progress import DeploymentProgress
        batch=SimpleNamespace(version='20261009-001609')
        panel=DeploymentProgress(batch,'v2.11.7')
        panel.steps=('生成配置批次','部署 / Router','部署 / ECS')
        panel.step_notes={0:batch.version}
        result={'batch':batch,'nodes':[SimpleNamespace(id='r',name='Router'),SimpleNamespace(id='e',name='ECS')],
                'statuses':{'r':'success','e':'失败'},'warnings':[]}
        self.assertEqual(panel.describe(result),'')
        self.assertEqual(panel.step_notes,{0:batch.version})
        result['warnings']=['ECS：临时文件清理失败']
        self.assertEqual(panel.describe(result),'ECS：临时文件清理失败')
