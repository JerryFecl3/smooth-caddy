import unittest
from app.network.task_progress import TaskStep
from app.network.task_progress import TaskState

class TaskStateTests(unittest.TestCase):
    def test_parallel_completion_does_not_complete_neighbors(self):
        state=TaskState();steps=('a','b','c','d')
        state.update(TaskStep(steps,0,'验证中',state='running'))
        state.update(TaskStep(steps,2,'已保存',state='success'))
        self.assertEqual(state.counts(),(1,4))
        self.assertEqual(state.states,{0:'running',2:'success'})
        state.finish('stopped')
        self.assertEqual(state.states[0],'stopped')
        self.assertEqual(state.states[2],'success')
        self.assertEqual(state.notes[1],'未执行')

    def test_groups_serial_results_and_fixed_plan(self):
        state=TaskState();steps=('证书','保存','探测','部署');groups=('生成','生成','部署','部署')
        state.update(TaskStep(steps,0,groups=groups))
        state.update(TaskStep(steps,1,groups=groups))
        state.update(TaskStep(steps,1,'批次编号',groups,'success'))
        state.update(TaskStep(steps,2,'v2.11.7',groups))
        self.assertEqual(state.counts(),(2,4))
        self.assertEqual(state.notes[1],'批次编号')
        state.update(TaskStep(steps,3,'失败',groups,'failed'))
        state.finish('partial')
        self.assertEqual(state.states[3],'failed')
        with self.assertRaises(ValueError):state.update(TaskStep(('changed',),0))

    def test_grouped_progress_counts_each_leaf_and_retry(self):
        state=TaskState()
        self.assertEqual(state.counts(),(0,0))
        steps=('a','b','c','d','e');groups=('small',)+('large',)*4
        def update(index,status):
            state.update(TaskStep(steps,index,groups=groups,state=status))
        update(3,'success')
        self.assertEqual(state.counts(),(1,5))
        update(0,'skipped')
        update(2,'failed')
        self.assertEqual(state.counts(),(3,5))
        update(2,'running')
        self.assertEqual(state.counts(),(2,5))
        update(2,'success')
        update(2,'success')
        self.assertEqual(state.counts(),(3,5))
        state.finish('stopped')
        self.assertEqual(state.counts(),(3,5))
        self.assertEqual(state.notes[1],'未执行')

    def test_unstarted_tasks_never_become_success(self):
        state=TaskState();state.update(TaskStep(('a','b'),0,state='success'))
        state.finish('success')
        self.assertNotIn(1,state.states)
        self.assertEqual(state.notes[1],'未执行')

class TaskLayoutTests(unittest.IsolatedAsyncioTestCase):
    async def test_single_and_grouped_layout_at_terminal_sizes(self):
        import asyncio,tempfile
        from app.network.application import Application
        from tests.ui_helpers import ReadyTerminal as Terminal
        from app.tui.task_progress import TaskProgress
        from textual.widgets import Static, ProgressBar
        from rich.cells import cell_len
        for size in ((80,24),(120,36),(160,48)):
            with tempfile.TemporaryDirectory() as directory:
                service=Application(directory);ui=Terminal(service)
                finished=asyncio.Event()
                async def operation(*args):await finished.wait();return None
                try:
                    async with ui.run_test(size=size) as pilot:
                        panel=TaskProgress('新增并部署',operation,lambda _: '',asynchronous=True)
                        ui.push_screen(panel);await pilot.pause()
                        steps=('生成证书','保存配置','探测 / Router','上传 / Router','部署 / Router')
                        groups=('准备运行材料',)*2+('部署到节点',)*3
                        panel.show_step(TaskStep(steps,0,'已完成',groups,'success'))
                        panel.show_step(TaskStep(steps,1,'20261009-120000',groups,'success'))
                        panel.show_step(TaskStep(steps,2,'v2.11.7',groups,'success'))
                        panel.show_step(TaskStep(steps,3,'上传中',groups,'running'))
                        await pilot.pause()
                        content=panel.query_one('#task-step-list',Static)
                        text=content.render().plain
                        self.assertIn('准备运行材料',text);self.assertIn('部署到节点',text)
                        self.assertIn('3 / 5',panel.query_one('#task-summary',Static).render().plain)
                        bar=panel.query_one('#task-overall',ProgressBar)
                        self.assertEqual((bar.progress,bar.total),(3,5))
                        self.assertTrue(all(cell_len(line)<=content.size.width for line in text.splitlines()))
                        self.assertGreater(panel.query_one('#task-stop').region.height,0)
                        ui.save_screenshot(f'task-progress-{size[0]}.svg',path=directory)
                        # A single group keeps the exact same row style without its header.
                        panel.task_state=TaskState();panel.steps=()
                        panel.show_step(TaskStep(('a.example.com','b.example.com'),1,'申请中',('申请公共TLS证书',)*2,'running'))
                        self.assertNotIn('申请公共TLS证书',content.render().plain)
                        finished.set();await pilot.pause()
                finally:
                    finished.set();service.close()
