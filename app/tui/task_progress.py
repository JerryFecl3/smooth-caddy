"""Reusable task presentation; operations and cooperative cancellation stay outside UI."""
import asyncio
import threading
import time
from rich.text import Text
from ..network.task_progress import TaskState, TERMINAL
from textual import on
from textual.binding import Binding
from textual.containers import Vertical, VerticalScroll, Horizontal
from textual.screen import ModalScreen
from textual.widgets import Static, ProgressBar
from .widgets import Button
from .dialogs import Form
from ..network.task_progress import DownloadProgress, TaskCancelled


class TaskProgress(ModalScreen):
    BINDINGS = [Binding('escape','back','返回'), Binding('ctrl+s','retry','重试'), Binding('up','scroll_steps(-1)',show=False), Binding('down','scroll_steps(1)',show=False)]

    def __init__(self, title, operation, describe_result, *, asynchronous=False, success_title="已完成"):
        super().__init__()
        self.title_text=title
        self.asynchronous=asynchronous
        self.success_title=success_title
        self.operation=operation
        self.describe_result=describe_result
        self.finished=False
        self.failed=False
        self.stop=threading.Event()
        self.task_state=TaskState()
        self.steps=()
        self.step_notes={}
        self.current=0
        self.result=None
        self.step_outcome=None
        self.started=time.monotonic()

    def action_scroll_steps(self, direction):
        area=self.query_one('#task-steps',VerticalScroll)
        area.scroll_relative(y=direction,animate=False)

    def extra_buttons(self):
        return []

    def compose(self):
        with Vertical(id='task-dialog'):
            yield Static(self.title_text,id='dialog-title',markup=False)
            with Horizontal(id='task-summary-row'):
                yield Static('准备中',id='task-summary',markup=False)
                yield Static('',id='task-elapsed',markup=False)
            yield ProgressBar(total=None,show_eta=False,id='task-overall')
            with VerticalScroll(id='task-steps'):
                yield Static('',id='task-step-list',markup=False)
            yield Static('准备中',id='task-detail',markup=False)
            yield ProgressBar(total=None,show_eta=False,id='task-current')
            yield Static('',id='task-bytes',markup=False)
            with Horizontal(classes='dialog-actions'):
                yield Button('返回 · Esc',id='task-back',disabled=True)
                yield Button('重试 · ^s',id='task-retry')
                yield from self.extra_buttons()
                yield Button('停止',id='task-stop')

    def on_mount(self):
        self.query_one('#task-retry').display=False
        self.set_interval(1,self.tick)
        self.begin()

    def tick(self):
        if not self.finished:
            elapsed=int(time.monotonic()-self.started)
            self.query_one('#task-elapsed',Static).update(f'已用时 {elapsed//60:02d}:{elapsed%60:02d}')

    def begin(self):
        self.step_outcome=None
        self.finished=self.failed=False
        self.stop.clear()
        self.result=None
        self.task_state=TaskState()
        self.steps=()
        self.step_notes={}
        self.current=0
        self.started=time.monotonic()
        self.query_one('#task-back').disabled=True
        self.query_one('#task-retry').display=False
        button=self.query_one('#task-stop',Button)
        button.display=True;button.disabled=False;button.focus()
        self.query_one('#task-detail').remove_class('task-error')
        self.query_one('#task-step-list',Static).update('')
        self.query_one('#task-summary',Static).update('准备中')
        self.query_one('#task-overall',ProgressBar).update(total=None,progress=0)
        self.query_one('#task-current').display=True
        self.show_detail('准备中')
        self.tick()
        self.run_worker(self.execute())

    def show_step(self,event):
        self.task_state.update(event)
        self.steps=event.steps;self.current=event.index
        self.step_notes=self.task_state.notes
        completed,total=self.task_state.counts()
        self.query_one('#task-summary',Static).update(f'总体进度    {completed} / {total}')
        self.query_one('#task-overall',ProgressBar).update(total=total,progress=completed)
        self.render_steps()
        self.query_one('#task-current').display=False
        self.query_one('#task-detail').display=False
        self.query_one('#task-bytes').display=False

    def on_resize(self):
        self.call_after_refresh(lambda:self.render_steps(self.step_outcome))

    def render_steps(self, outcome=None):
        self.step_outcome=outcome
        model=self.task_state
        if outcome:model.finish(outcome)
        width=self.query_one('#task-step-list').size.width
        lines=[]
        sections=model.sections();nested=len(sections)>1
        marks={'success':'✓','skipped':'·','failed':'✗','stopped':'■','running':'●','pending':'○'}
        defaults={'success':'已完成','skipped':'已跳过','failed':'失败','stopped':'已停止','running':'进行中','pending':'等待中'}
        def line(label,note):
            left=Text(label);right=Text(note)
            # Keep each task on one line even at narrow terminal sizes.
            right.truncate(max(8,width//2),overflow='ellipsis')
            left.truncate(max(1,width-right.cell_len-2),overflow='ellipsis')
            return left.plain+' '*max(2,width-left.cell_len-right.cell_len)+right.plain
        for name,indices in sections:
            if nested:
                states=[model.states.get(i,'pending') for i in indices]
                done=sum(state in TERMINAL for state in states)
                state='failed' if 'failed' in states else 'stopped' if 'stopped' in states else 'success' if done==len(indices) else 'running' if any(s!='pending' for s in states) else 'pending'
                lines.append(line(marks[state]+' '+name,f'{done} / {len(indices)}'))
            for i in indices:
                state=model.states.get(i,'pending')
                note=self.step_notes.get(i) or defaults[state]
                lines.append(line(('    ' if nested else '')+marks[state]+' '+self.steps[i],note))
            if nested:lines.append('')
        self.query_one('#task-step-list',Static).update('\n'.join(lines).rstrip())

    def show_detail(self,message):
        bar=self.query_one('#task-current',ProgressBar)
        detail=self.query_one('#task-detail',Static)
        detail.display=True
        sizes=self.query_one('#task-bytes',Static)
        if isinstance(message,DownloadProgress):
            bar.display=True;sizes.display=True
            detail.update('下载 '+message.label)
            bar.update(total=message.total,progress=message.received)
            size=lambda value:f'{value/1048576:.1f} MiB'
            total=size(message.total) if message.total else '总大小未知'
            sizes.update(f'{size(message.received)} / {total}    {size(message.speed)}/s')
        else:
            detail.update(str(message))
            detail.display=False
            bar.display=False;sizes.display=False
            sizes.update('')

    async def execute(self):
        app=self.app
        try:
            if self.asynchronous:
                self.result=await self.operation(self.show_detail,self.show_step,self.stop)
            else:
                self.result=await asyncio.to_thread(self.operation,
                    lambda message:app.call_from_thread(self.show_detail,message),
                    lambda event:app.call_from_thread(self.show_step,event),self.stop)
        except TaskCancelled:
            outcome='stopped';message='已停止后续工作，已完成操作保留。'
        except Exception as error:
            outcome='failed';message=str(error);self.failed=True
        else:
            outcome='success' if self.result_success(self.result) else 'partial';message=self.describe_result(self.result)
        self.tick()
        self.finished=True
        self.render_steps(outcome)
        self.query_one('#task-summary',Static).update({'success':self.success_title,'failed':'任务失败','stopped':'已停止','partial':'未全部完成'}[outcome])
        completed,total=self.task_state.counts()
        self.query_one('#task-overall',ProgressBar).update(total=total or None,progress=completed)
        self.query_one('#task-current').display=False
        self.query_one('#task-bytes',Static).update('')
        if outcome in ('failed','stopped') and getattr(self,'batch_record',None):message='配置批次：'+self.batch_record.version+'\n'+message
        self.query_one('#task-detail',Static).update(message)
        self.query_one('#task-detail').display=bool(message)
        self.query_one('#task-detail').set_class(self.failed,'task-error')
        self.query_one('#task-stop').display=False
        self.query_one('#task-retry').display=self.failed
        self.query_one('#task-back').disabled=False
        self.query_one('#task-back').focus()

    def result_success(self,result):return True

    stop_title='停止任务？'
    stop_note='停止后续工作，保留已完成操作和已校验缓存。'

    def on_stop_confirmed(self):
        pass

    @on(Button.Pressed,'#task-stop')
    def request_stop(self):
        if self.finished or self.stop.is_set():return
        def confirmed(answer):
            if answer is not None and not self.finished:
                self.stop.set()
                self.query_one('#task-summary',Static).update('正在停止，等待当前操作安全结束')
                self.query_one('#task-stop').disabled=True
                self.on_stop_confirmed()
        self.app.push_screen(Form(self.stop_title,[],note=self.stop_note),confirmed)

    @on(Button.Pressed,'#task-back')
    def action_back(self):
        if self.finished:self.dismiss(self.result)

    @on(Button.Pressed,'#task-retry')
    def action_retry(self):
        if self.finished and self.failed:self.begin()


class DeploymentProgress(TaskProgress):
    stop_title='停止部署？'
    stop_note='保留配置批次，停止后续工作。已提交的部署等待结果，不自动回滚。'

    def __init__(self,batch,version):
        self.batch_record=batch
        self.version=version
        self.decision=None
        super().__init__('部署配置批次' if batch else '新增并部署',self.perform_deployment,self.describe,
                         asynchronous=True,success_title='部署完成')

    def extra_buttons(self):return [Button('跳过',id='task-skip')]

    def begin(self):
        self.query_one('#task-skip').display=False
        super().begin()

    def result_success(self,result):return result['success']

    def describe(self,result):
        return '\n'.join(result['warnings'])

    def on_stop_confirmed(self):
        if self.decision is not None and not self.decision.done():self.decision.set_result('stop')

    @on(Button.Pressed,'#task-skip')
    def skip(self):
        if self.decision is not None and not self.decision.done():self.decision.set_result('skip')

    def action_retry(self):
        if self.decision is not None and not self.decision.done():self.decision.set_result('retry')
        else:super().action_retry()

    async def perform_deployment(self,progress,steps,cancel):
        async def confirm(host):
            if cancel.is_set():return False
            note=f'{host.name} / {host.address}\n新指纹：{host.fingerprint}'
            if host.previous:note+='\n原指纹：'+host.previous+'\n主机密钥已变化，请核实。'
            return await self.app.push_screen_wait(Form('信任 SSH 主机？',[],note=note)) is not None
        async def decide(issue):
            if cancel.is_set():return 'stop'
            self.query_one('#task-summary',Static).update('任务暂停 / '+issue.name)
            self.show_detail(issue.message)
            self.query_one('#task-detail').display=True
            self.query_one('#task-detail').add_class('task-error')
            self.query_one('#task-current').display=False
            retry=self.query_one('#task-retry',Button)
            retry.label=('重新查询' if issue.uncertain else '重试')+' · ^s';retry.display=True
            self.query_one('#task-skip').display=issue.stage!='probe'
            self.decision=asyncio.get_running_loop().create_future()
            answer=await self.decision
            self.decision=None
            retry.display=False;self.query_one('#task-skip').display=False
            self.query_one('#task-current').display=True
            self.query_one('#task-detail').remove_class('task-error')
            return answer
        def created(batch):
            self.batch_record=batch
        return await self.app.application.deployment.execute(self.batch_record,self.version,confirm,decide,progress,steps,cancel,created)
