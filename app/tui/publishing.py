"""Configuration batches, version selection and transient package operations."""
from ..i18n import tr
import asyncio
from textual import on
from textual.containers import Vertical,Horizontal
from textual.widgets import Static,DataTable
from textual.screen import ModalScreen
from textual.binding import Binding
from .widgets import Button
from .dialogs import Form, PasswordDialog


def batch_summary(batch):
    labels={'nodes':tr('节点'),'sites':tr('站点'),'regions':tr('区域')}
    return tr('配置批次：')+batch.version+'\n'+'\n'.join(f'{labels[key]}：{len(names)}  '+ '、'.join(names) for key,names in batch.summary.items())



class BatchDetails(Form):
    BINDINGS=[Binding('ctrl+d','deploy',tr('部署')),Binding('ctrl+e','export',tr('导出'))]

    def __init__(self,batch):
        super().__init__(tr('配置批次详情'),[],note=batch_summary(batch),return_only=True)

    def compose_actions(self):
        yield Button(tr('返回 · Esc'),id='cancel')
        yield Button(tr('部署 · ^d'),id='detail-deploy',variant='primary')
        yield Button(tr('导出 package · ^e'),id='detail-export')

    @on(Button.Pressed,'#detail-deploy')
    def action_deploy(self):self.dismiss('deploy')

    @on(Button.Pressed,'#detail-export')
    def action_export(self):self.dismiss('package')


def create_batch(app):
    config=app.application.snapshot()
    note=tr('节点：{0}    站点：{1}    区域：{2}', len(config.nodes), len(config.sites), len(config.regions))
    if app.application.batches.inspect(config)[1] and app.application.public_tls.settings()['staging']:
        note+=tr('\n包含公共 CA 测试证书')
    def confirmed(answer):
        if answer is None:return
        from .task_progress import TaskProgress
        def operation(progress,steps,cancel):
            return app.application.batches.create(progress,task_progress=steps,cancel=cancel)
        app.push_screen(TaskProgress(tr('新增配置批次'),operation,lambda _: '',success_title=tr('配置批次已生成')),lambda _:app.after_change(''))
    app.push_screen(Form(tr('新增配置批次'),[],note=note),confirmed)


class Export(ModalScreen):
    BINDINGS=[Binding('escape','cancel',tr('返回')),Binding('ctrl+s','generate',tr('确认'))]

    def __init__(self,mode,batch=None):
        super().__init__()
        self.mode=mode;self.selected_batch=batch;self.versions=[];self.busy=False

    def compose(self):
        with Vertical(id='dialog'):
            yield Static({'deploy':tr('部署配置批次'),'new-deploy':tr('新增并部署'),'package':tr('导出 package')}[self.mode],id='dialog-title')
            yield Static(tr('联网更新版本列表中'),id='version-refresh',markup=False)
            yield DataTable(id='versions',cursor_type='row')
            yield Static('',id='job-status',markup=False)
            with Horizontal(classes='dialog-actions'):
                yield Button(tr('返回 · Esc'),id='cancel')
                yield Button({'deploy':tr('部署'),'new-deploy':tr('新增并部署'),'package':tr('导出 package')}[self.mode]+' · ^s',id='generate',variant='primary')

    def on_mount(self):
        service=self.app.application
        try:self.config=service.releases.load(self.selected_batch)[0] if self.selected_batch else service.snapshot()
        except (ValueError,OSError) as error:
            self.query_one('#job-status',Static).update(str(error));self.query_one('#generate').disabled=True
            self.query_one('#version-refresh').display=False
            return
        self.draw_versions(service.releases.cache.cached_versions())
        self.run_worker(self.refresh_online());self.query_one('#versions').focus()

    def selected_version(self):
        row=self.query_one('#versions',DataTable).cursor_row
        return self.versions[row] if 0<=row<len(self.versions) else None

    def draw_versions(self,online):
        selected=self.selected_version();cache=self.app.application.releases.cache.versions()
        arches=sorted({node.arch for node in self.config.nodes})
        table=self.query_one('#versions',DataTable);table.clear(columns=True)
        table.add_columns(tr('版本'),tr('来源'),*arches)
        self.versions=list(dict.fromkeys(online+sorted(cache,reverse=True)))
        for version in self.versions:
            table.add_row(version,tr('官方 / 本地') if version in online and version in cache else tr('官方') if version in online else tr('本地'),
                          *[tr('已有') if arch in cache.get(version,[]) else tr('需下载') for arch in arches])
        table.styles.height=min(10,len(self.versions)+3)
        if selected in self.versions:table.move_cursor(row=self.versions.index(selected))
        self.query_one('#generate').disabled=not self.versions

    async def refresh_online(self):
        indicator=self.query_one('#version-refresh',Static);status=self.query_one('#job-status',Static);table=self.query_one('#versions',DataTable)
        try:
            versions=await asyncio.wait_for(asyncio.to_thread(self.app.application.releases.cache.online_versions),20)
            if table.is_attached and status.is_attached:self.draw_versions(versions);status.update('')
        except asyncio.TimeoutError:
            if status.is_attached:status.update(tr('更新超时，已保留版本列表。'))
        except Exception as error:
            if status.is_attached:status.update(tr('无法获取官方版本：')+str(error))
        finally:
            if indicator.is_attached:indicator.display=False

    @on(Button.Pressed,'#cancel')
    def action_cancel(self):self.dismiss(None)

    @on(DataTable.RowSelected,'#versions')
    @on(Button.Pressed,'#generate')
    def action_generate(self):
        version=self.selected_version()
        if version is None:return
        app=self.app
        def launch(password=None):
            from .task_progress import TaskProgress,DeploymentProgress
            if self.mode=='package':
                def operation(progress,steps,cancel):
                    return app.application.releases.assemble(self.selected_batch,version,progress=progress,task_progress=steps,cancel=cancel,password=password)
                panel=TaskProgress(tr('导出 package'),operation,lambda package:str(app.application.releases.directory(package).resolve()),success_title=tr('package 已导出'))
            else:panel=DeploymentProgress(self.selected_batch,version)
            self.dismiss(None)
            app.call_after_refresh(lambda:app.push_screen(panel,lambda _:app.after_change('')))
        if self.mode=='package':
            app.push_screen(PasswordDialog(tr('部署包导出口令'),lambda password:None,visible=True,submit_label=tr('导出')),
                lambda values:launch(values['password']) if values is not None else None)
            return
        from ..network.models import ssh_route
        try:routes=[' → '.join(n.name for n in ssh_route(self.config,node.id)) for node in self.config.nodes]
        except ValueError as error:self.query_one('#job-status',Static).update(str(error));return
        note=((tr('配置批次：')+self.selected_batch.version+'\n') if self.selected_batch else tr('新增配置批次\n'))+tr('Caddy 版本：{0}\n节点（{1}）\n', version, len(routes))+'\n'.join('  '+r for r in routes)
        if not self.selected_batch and app.application.batches.inspect(self.config)[1] and app.application.public_tls.settings()['staging']:
            note+=tr('\n包含公共 CA 测试证书')
        app.push_screen(Form(tr('部署？') if self.selected_batch else tr('新增并部署？'),[],note=note),lambda answer:launch() if answer is not None else None)
