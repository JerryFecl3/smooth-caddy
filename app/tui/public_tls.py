"""Independent public certificate UI; no site or publishing integration."""
from ..i18n import tr
import asyncio
from rich.cells import cell_len
from textual import on
from textual.binding import Binding
from textual.widgets import Static
from .widgets import Button, DataTable
from .dialogs import Form, Field
from .task_progress import TaskProgress
from ..network.public_tls import PROVIDERS

class PublicTLSPage:
    """Controller for the main navigation page; dialogs remain independent."""
    def __init__(self,app):
        self.app=app
        self.records=[]

    @property
    def service(self):return self.app.application.public_tls

    def refresh_records(self, *, refresh_validation=True):
        if self.app.page!='public_tls':return
        if refresh_validation:self.app.demo.refresh_validation()
        table=self.app.query_one('#matrix',DataTable);row=table.cursor_row
        table.clear(columns=True)
        domain_width=32
        for label,width in ((tr('域名'),domain_width),(tr('通配'),8),(tr('状态'),12),(tr('有效期至'),14),(tr('环境'),6)):
            table.add_column(label,width=max(width, cell_len(label), 18 if label == tr('状态') else 0))
        self.records=self.service.list()
        self.app.query_one('#nav-sites').set_class(any(k[0]=='sites' for k in self.app.demo.errors()),'config-error')
        self.app.refresh_navigation_labels()
        mode=tr('测试') if self.service.settings()['staging'] else tr('正式')
        for item in self.records:table.add_row(item['domain'],tr('是') if item['wildcard'] else tr('否'),self.service.state(item),item['expires'][:10] or '—',mode,key=item['id'])
        table.move_cursor(row=min(row,max(0,len(self.records)-1)))
        for name in ('pub-details','delete','pub-all'):self.app.query_one('#'+name).disabled=not self.records
        self.app.call_after_refresh(self.app.refresh_button_focus)

    def selected(self):
        row=self.app.query_one('#matrix',DataTable).cursor_row
        return self.records[row] if 0<=row<len(self.records) else None

    def action_new(self):self.app.require_unlock(lambda:self.edit_record(None))

    def edit_record(self,item):
        fields=[Field('domain',tr('域名'),item['domain'] if item else '',readonly=bool(item)),
                Field('wildcard',tr('通配证书'),item['wildcard'] if item else False,boolean=True),
                Field('provider',tr('DNS 服务商'),item['provider'] if item else 'alidns',[(v[0],k) for k,v in PROVIDERS.items()]),
                Field('credential_id','AccessKey ID / SecretId','',secret=True),
                Field('credential_key','AccessKey Secret / SecretKey','',secret=True)]
        # Domain coverage is fixed for an existing certificate identity.
        if item:fields[1]=Field('wildcard',tr('通配证书'),tr('是') if item['wildcard'] else tr('否'),readonly=True)
        def validate(values):
            try:self.service.save(values['domain'],item['wildcard'] if item else values['wildcard'],values['provider'],values['credential_id'],values['credential_key'],item['id'] if item else None)
            except (ValueError,OSError) as error:return str(error)
        note=tr('凭据留空则保留原值；更换服务商需重新填写。') if item else tr('通配证书同时包含根域名和一级通配域名。')
        self.app.push_screen(Form(tr('编辑公共 TLS') if item else tr('新增公共 TLS'),fields,validate,note),lambda _:self.refresh_records())

    def action_details(self):
        item=self.selected()
        if item:
            def chosen(action):
                if action=='edit':self.app.require_unlock(lambda:self.edit_record(item))
                elif action in ('issue','force'):self.app.require_unlock(lambda:self.issue(item,action=='force'))
            self.app.push_screen(CertificateDetails(item,self.service.state(item)),chosen)

    def issue(self,item,force):
        def launch(answer):
            if answer is None:return
            def operation(progress,steps,cancel):return self.service.issue(item['id'],force,progress,steps,cancel)
            self.app.push_screen(TaskProgress(tr('申请证书'),operation,lambda _: '',success_title=tr('申请完成')),lambda _:self.refresh_records())
        note=item['domain']+'\n'+(tr('测试模式') if item['staging'] else tr('正式模式'))+tr('\n继续即同意 Let’s Encrypt 服务条款：\nhttps://letsencrypt.org/repository/')
        self.app.push_screen(Form(tr('强制申请？') if force else tr('申请证书？'),[],note=note),launch)

    def action_delete(self):
        item=self.selected()
        if not item:return
        def ask():
            def done(answer):
                if answer is not None:self.service.delete(item['id']);self.refresh_records()
            self.app.push_screen(Form(tr('删除公共 TLS？'),[],note=item['domain']+tr('\n删除本地配置与材料，不撤销已签发证书。')),done)
        self.app.require_unlock(ask)

    def apply_all(self):
        if not self.records:return
        identities=[item['id'] for item in self.records]
        def opened():
            def confirmed(answer):
                if answer is None:return
                operation=lambda progress,steps,cancel:self.service.issue_all(identities,progress,steps,cancel)
                self.app.push_screen(PublicTLSBatchProgress(tr('全部申请'),operation,
                    lambda result:'\n'.join(result['errors']),success_title=tr('申请完成')),lambda _:self.refresh_records())
            mode=tr('测试模式') if self.service.settings()['staging'] else tr('正式模式')
            note=mode+'\n'+tr('证书：{0} 条\n继续即同意 Let’s Encrypt 服务条款：\nhttps://letsencrypt.org/repository/', len(identities))
            self.app.push_screen(Form(tr('全部申请？'),[],note=note),confirmed)
        self.app.require_unlock(opened)

    def settings(self):
        def opened():
            settings=self.service.settings()
            def validate(values):
                try:self.service.configure(values['staging'],values['email'])
                except ValueError as error:return str(error)
            self.app.push_screen(Form(tr('公共 TLS 设置'),[Field('staging',tr('测试模式'),settings['staging'],boolean=True),Field('email',tr('联系邮箱'),settings['email'])],validate,
                tr('测试证书不受系统信任，不能用于正式服务。')),lambda _:self.refresh_records())
        self.app.require_unlock(opened)

    def tool(self):self.app.push_screen(LegoManager())

class CertificateDetails(Form):
    BINDINGS=[Binding('ctrl+o','edit',tr('编辑')),Binding('ctrl+s','issue',tr('申请'))]
    def __init__(self,item,state):
        self.item=item
        domains=item['domain']+('、*.'+item['domain'] if item['wildcard'] else '')
        note=tr('域名范围：{0}\nDNS 服务商：{1}\n状态：{2}\n有效期至：{3}', domains, PROVIDERS[item['provider']][0], state, item['expires'][:10] or '—')
        if item['error']:note+=tr('\n\n最近申请失败：')+item['error']
        super().__init__(item['domain']+' / '+(tr('测试模式') if item['staging'] else tr('正式模式')),[],note=note,return_only=True)
    def compose_actions(self):
        yield Button(tr('返回 · Esc'),id='cancel')
        yield Button(tr('编辑 · ^o'),id='cert-edit')
        yield Button(tr('申请 · ^s'),id='cert-issue')
        if self.item['certificate']:yield Button(tr('强制申请'),id='cert-force')
    @on(Button.Pressed,'#cert-edit')
    def action_edit(self):self.dismiss('edit')
    @on(Button.Pressed,'#cert-issue')
    def action_issue(self):self.dismiss('issue')
    @on(Button.Pressed,'#cert-force')
    def force(self):self.dismiss('force')

class LegoManager(Form):
    BINDINGS=[Binding('ctrl+s','install',tr('下载 / 更新'))]
    def __init__(self):
        super().__init__(tr('lego 管理'),[],note=tr('读取本地版本'),return_only=True)
        self.release=None
        self.checking=False
    def compose_actions(self):
        yield Button(tr('返回 · Esc'),id='cancel')
        yield Button(tr('检查更新'),id='lego-check')
        yield Button(tr('下载 / 更新 · ^s'),id='lego-install',disabled=True)
    def on_mount(self):
        super().on_mount()
        try:self.local=self.app.application.public_tls.tool.version()
        except (ValueError,OSError) as error:self.local=str(error)
        self.query_one('#dialog-note',Static).update(tr('本地版本：')+self.local)
    @on(Button.Pressed,'#lego-check')
    def check(self):
        if not self.checking:self.run_worker(self.fetch_latest(),exclusive=True)
    async def fetch_latest(self):
        self.checking=True;self.release=None
        note=self.query_one('#dialog-note',Static);button=self.query_one('#lego-install')
        button.disabled=True
        note.update(tr('本地版本：')+self.local+tr('\n正在检查更新'))
        try:
            result=await asyncio.to_thread(self.app.application.public_tls.tool.latest)
            if self.is_attached:self.release=result;note.update(tr('本地版本：')+self.local+tr('\n官方版本：')+result['tag_name']);button.disabled=False
        except Exception as error:
            if self.is_attached:note.update(tr('本地版本：')+self.local+tr('\n检查失败：')+str(error))
        finally:self.checking=False
    @on(Button.Pressed,'#lego-install')
    def action_install(self):
        if not self.release:return
        release=self.release;app=self.app
        def launch():
            tool=app.application.public_tls.tool
            self.dismiss(None)
            app.call_after_refresh(lambda:app.push_screen(TaskProgress(tr('下载 / 更新 lego'),lambda progress,steps,cancel:tool.install(release,progress,steps,cancel),lambda _: '',success_title=tr('lego 已就绪'))))
        app.require_unlock(launch)


class PublicTLSBatchProgress(TaskProgress):
    stop_title=tr('停止申请？')
    stop_note=tr('保留已完成结果，停止后续申请。')

    def result_success(self,result):return result['success']

