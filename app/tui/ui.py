"""Persistent terminal interface using the application command boundary."""
from ..i18n import tr
from ..i18n import get_language
from .widgets import Button, ListView, DataTable
from functools import wraps
import re
import sqlite3
from rich.text import Text
from rich.table import Table
from rich.cells import cell_len
from ..network.certificates import validate_certificate_name
from textual import on
from textual.app import App
from textual.binding import Binding
from textual.containers import Horizontal, HorizontalScroll, Vertical, VerticalScroll
from textual.widgets import Label, ListItem, Static
from .state import State
from .labels import label
from .guide import usage_guide
from .configuration import edit_configuration
from .dialogs import Field, Form, SSHGuide, HelpGuide, PasswordDialog, InitializationDialog
from ..network.models import Listen, Service, service_policy, MODES, PORTS

PAGES = {'deployment': tr('部署'), 'sites': tr('站点'), 'nodes': tr('节点'), 'regions': tr('区域'), 'clients': tr('mTLS证书'), 'public_tls': tr('TLS证书'), 'archives': tr('存档'), 'ca': tr('mTLS证书 / CA')}

NAV_PAGES = {key: PAGES[key] for key in ('deployment','sites','nodes','clients','public_tls')}
NAV_PAGES['settings'] = tr('设置')

def unlocked_operation(method):
    @wraps(method)
    def guarded(self, *args, **kwargs):
        if len(self.screen_stack) != 1: return
        if not self.application.security.unlocked:
            self.require_unlock(lambda: method(self, *args, **kwargs))
            return
        return method(self, *args, **kwargs)
    return guarded

class Terminal(App, inherit_bindings=False):
    TITLE = 'Smooth Caddy'
    CSS_PATH = 'tui.tcss'
    ENABLE_COMMAND_PALETTE = False
    BINDINGS = [
        Binding("f7", "move_item(-1)", show=False),
        Binding("f8", "move_item(1)", show=False),
        Binding('f10', 'toggle_shortcuts', tr('帮助'), priority=True),
        *[Binding(f'f{i}', f'nav_page({i})', title, priority=True) for i, title in enumerate(NAV_PAGES.values(), 1)],
        Binding('tab', 'next_region', tr('下一区域'), priority=True),
        Binding('shift+tab', 'previous_region', tr('上一区域'), priority=True),
        Binding('ctrl+o', 'edit', tr('编辑')), Binding('ctrl+t', 'toggle_client', tr('启用 / 禁用')), Binding('ctrl+n', 'new', tr('新增')), Binding('delete', 'delete', tr('删除')),
        Binding('ctrl+e', 'export', tr('导出')), Binding('ctrl+d', 'deploy', 'deploy'),
        Binding('ctrl+q', 'quit', tr('退出'), priority=True), Binding('escape', 'navigation', tr('导航')),
    ]

    def __init__(self, application):
        super().__init__()
        self.set_class(get_language() == 'en', 'english')
        self.application = application
        self.show_shortcuts = False
        self.help_state = 0
        self.help_screen = None
        self.demo = State(application)
        from .public_tls import PublicTLSPage
        self.public_tls_page = PublicTLSPage(self)
        from .archives import ArchivesPage
        self.archives_page = ArchivesPage(self)
        self.page = 'deployment'
        self.rendered_page = None
        self.col_keys = []
        self.row_ids = []
        self.positions = {}

    def compose(self):
        yield Static('Smooth Caddy', id='brand')
        with Horizontal(id='workspace'):
            with Vertical(id='sidebar'):
                yield ListView(*[ListItem(Label(title), id='nav-' + key) for key, title in NAV_PAGES.items()], id='nav')
                yield Static('', id='nav-note')
                yield Button(tr('帮助 · F10'), id='help')
                yield Button(tr('退出 · ^q'), id='quit')
            with Vertical(id='main'):
                yield Static(tr('设置'), id='settings-title')
                with HorizontalScroll(id='settings-tabs'):
                    yield Button(tr('区域'), id='settings-regions')
                    yield Button(tr('存档'), id='settings-archives')
                    yield Static('', classes='action-spacer')
                    yield Button(tr('导入配置'), id='settings-import')
                    yield Button(tr('修改口令'), id='password')
                yield Static('', id='page-summary', markup=False)
                yield DataTable(id='matrix', fixed_columns=1, zebra_stripes=True, cursor_type='cell', cursor_foreground_priority='css')
                with VerticalScroll(id='ca-panel'):
                    yield Static('', id='ca-info', markup=False)
                with HorizontalScroll(id='actions'):
                    yield Button(tr('禁用 · ^t'), id='client-toggle')
                    yield Button(tr('编辑 · ^o'), id='edit')
                    yield Button(tr('导出 .run')+' · ^e', id='run-export')
                    yield Button(tr('部署')+' · ^d', id='generate-deploy')
                    yield Button(tr('详情 · ^o'), id='pub-details')
                    yield Button(tr('新增 · ^n'), id='new')
                    yield Button(tr('删除 · Del'), id='delete')
                    yield Button(tr('导出 P12 · ^e'), id='p12')
                    yield Static('', classes='action-spacer')
                    yield Button(tr('返回证书 · Esc'), id='ca-back')
                    yield Button(tr('导出信任 CA · ^e'), id='public-ca')
                    yield Button(tr('全部申请'), id='pub-all')
                    yield Button(tr('公共TLS设置'), id='pub-settings')
                    yield Button(tr('lego 管理'), id='pub-tool')
                    yield Button(tr('CA 管理'), id='ca-open')
                    yield Button(tr('全部导出'), id='run-export-all')
                    yield Button(tr('全部部署'), id='deploy-all')
                    yield Button(tr('SSH 公钥'), id='ssh-guide')
                    yield Button(tr('初始化 CA'), id='initialize')
                    yield Button(tr('重置 SSH 私钥'), id='ssh-reset', variant='error')

                with HorizontalScroll(id='archive-actions'):
                    yield Button(tr('新增存档')+' · ^n',id='archive-save')
                    yield Button(tr('载入'),id='archive-restore')
                    yield Button(tr('删除')+' · Del',id='archive-delete')
                    yield Button(tr('导出')+' · ^e',id='archive-export')

    def on_mount(self):
        self.theme = 'textual-dark'
        self.query_one('#nav', ListView).index = list(NAV_PAGES).index(self.page)
        self.render_page()
        self.query_one('#matrix').focus()
        self.call_after_refresh(self.initialize_startup)

    def initialize_startup(self):
        security = self.application.security
        if not security.initialized:
            def initialized(values):
                if values is None: self.exit()
                else: self.after_change('')
            self.push_screen(InitializationDialog(self.application.initialize), initialized)
            return
        if not self.application.ssh.initialized or not self.demo.initialized:
            def ready(values):
                if values is None:
                    self.exit();return
                self.application.ssh.ensure_identity()
                if not self.demo.initialized:
                    self.initialize(required=True)
                else:
                    self.after_change('')
            if security.unlocked:
                ready({});return
            self.push_screen(PasswordDialog(tr('解锁程序'), security.unlock,
                submit_label=tr('解锁'), note=tr('请输入程序口令。')), ready)

    def on_list_view_highlighted(self, event):
        if event.list_view.id != 'nav' or event.item is None:
            return
        if len(self.screen_stack) != 1 or not event.list_view.has_focus:
            return
        if event.item.disabled: return
        target = event.item.id.removeprefix('nav-')
        if target == 'settings': target = 'regions'
        if target == self.page:
            return
        self.positions[self.page] = self.query_one('#matrix', DataTable).cursor_coordinate
        self.page = target
        self.render_page()

    @on(ListView.Selected, '#nav')
    def navigate(self, event):
        table = self.query_one('#matrix', DataTable)
        self.positions[self.page] = table.cursor_coordinate
        if event.item.disabled: return
        target = event.item.id.removeprefix('nav-')
        if target == 'settings': target = 'regions'
        self.page = target
        self.render_page()
        self.query_one('#matrix').focus()

    def action_move_item(self, offset):
        if len(self.screen_stack) != 1 or self.page not in ('nodes', 'sites', 'regions', 'public_tls'): return
        table = self.query_one('#matrix', DataTable)
        if self.focused is not table: return
        row, column = table.cursor_coordinate
        identities = [item['id'] for item in self.public_tls_page.records] if self.page == 'public_tls' else self.row_ids
        if not 0 <= row + offset < len(identities): return
        identity, page = identities[row], self.page
        def move():
            if page == 'public_tls':
                self.demo.application.public_tls.move(identity, offset)
                self.public_tls_page.refresh_records()
            else:
                self.demo.application.move(page, identity, offset)
                self.demo.reload()
                self.positions[page] = (row + offset, column)
                self.render_page()
            table.move_cursor(row=row + offset, column=column)
            table.focus()
        self.require_unlock(move)

    def action_toggle_shortcuts(self):
        if self.help_state == 2:
            self.help_screen.dismiss(None)
            return
        self.help_state += 1
        self.show_shortcuts = True
        self.refresh_shortcuts()
        if self.help_state == 2:
            self.help_screen = HelpGuide(tr('使用说明'), [], note=usage_guide(), return_only=True)
            self.push_screen(self.help_screen, self.close_help)

    def close_help(self, result):
        self.help_state = 0
        self.help_screen = None
        self.show_shortcuts = False
        self.refresh_shortcuts()

    def refresh_shortcuts(self):
        self.refresh_navigation_labels()
        for screen in self.screen_stack:
            for button in screen.query(Button):
                button.refresh(layout=True)

    def refresh_navigation_labels(self):
        errors = self.demo.errors()
        for i, key in enumerate(NAV_PAGES, 1):
            item = self.screen_stack[0].query_one('#nav-' + key, ListItem)
            count = sum(1 for k in errors if k[0] == ('regions' if key == 'settings' else key))
            item.set_class(bool(count), 'config-error')
            item.query_one(Label).update(NAV_PAGES[key] + (f' · F{i}' if self.show_shortcuts and i<=6 else '') + ('  !' if count else ''))

    def on_descendant_focus(self, event):
        self.call_after_refresh(self.refresh_button_focus)

    def on_descendant_blur(self, event):
        self.call_after_refresh(self.refresh_button_focus)

    def refresh_button_focus(self):
        """Blue mirrors Enter on a focused list, never general importance."""
        for screen in self.screen_stack:
            for button in screen.query(Button):button.remove_class('list-default')
        focused=self.screen.focused
        in_navigation = focused is not None and any(widget.id == 'sidebar' for widget in [focused,*focused.ancestors])
        self.screen_stack[0].query_one('#matrix',DataTable).show_cursor = not in_navigation
        if focused is None or not getattr(focused,'row_count',0):return
        target=None
        if len(self.screen_stack)==1 and focused.id=='matrix':
            target={'sites':'edit','nodes':'edit','regions':'edit','public_tls':'pub-details'}.get(self.page)
        elif focused.id=='versions':
            from .publishing import Export
            if isinstance(self.screen,Export):target='generate'
        if target:
            button=self.screen.query_one('#'+target,Button)
            if not button.disabled and button.display:button.add_class('list-default')

    def action_nav_page(self, number):
        if len(self.screen_stack) != 1: return
        nav = self.query_one('#nav', ListView)
        nav.index = number - 1
        nav.focus()
        nav.action_select_cursor()

    def check_action(self, action, parameters):
        if action == 'quit' and any(getattr(screen, 'busy', False) or (hasattr(screen, 'finished') and not screen.finished) for screen in self.screen_stack):
            return False
        if action in ('next_region', 'previous_region', 'nav_page', 'edit', 'new', 'delete', 'toggle_client', 'export', 'deploy', 'move_item', 'navigation'):
            return len(self.screen_stack) == 1
        return True

    def action_next_region(self):
        self.move_region(1)

    def action_previous_region(self):
        self.move_region(-1)

    def move_region(self, direction):
        focused = self.focused
        ids = {w.id for w in ([focused] + list(focused.ancestors))} if focused else set()
        groups = ['sidebar']
        if self.page in ('regions','archives'): groups.append('settings-tabs')
        groups.extend(['content','archive-actions' if self.page=='archives' else 'actions'])
        current = next((group for group in groups if group in ids),'content')
        target = groups[(groups.index(current)+direction)%len(groups)]
        if target == 'sidebar':
            self.query_one('#nav').focus()
        elif target == 'content':
            self.query_one('#ca-panel' if self.page == 'ca' else '#matrix').focus()
        elif target == 'settings-tabs':
            self.query_one('#settings-'+self.page).focus()
        else:
            self.screen.focus_next('#'+target+' Button')

    def action_navigation(self):
        if len(self.screen_stack) == 1:
            if self.page == 'ca':
                self.page = 'clients'
                self.render_page()
                self.query_one('#ca-open').focus()
            else:
                self.query_one('#nav').focus()

    @on(DataTable.LayoutChanged)
    def table_layout_changed(self):
        if self.page == 'public_tls':
            self.call_after_refresh(self.public_tls_page.refresh_records)

    def render_page(self):
        self.rendered_page = self.page
        self.call_after_refresh(self.refresh_button_focus)
        in_settings = self.page in ('regions','archives')
        self.query_one('#settings-title').display = in_settings
        self.query_one('#settings-tabs').display = in_settings
        for tab in ('regions','archives'):
            self.query_one('#settings-'+tab,Button).set_class(self.page == tab, 'nav-active')
        self.demo.refresh_validation()
        errors = self.demo.errors()
        for key in NAV_PAGES:
            item = self.query_one('#nav-' + key, ListItem)
            item.set_class(key == self.page or (key == 'clients' and self.page == 'ca') or (key == 'settings' and self.page in ('regions','archives')), 'active-page')
            count = sum(1 for k in errors if k[0] == ('regions' if key == 'settings' else key))
            item.set_class(bool(count), 'config-error')
        self.refresh_navigation_labels()
        table = self.query_one('#matrix', DataTable)
        table.display = self.page != 'ca'
        table.cursor_type = 'row' if self.page in ('deployment', 'clients', 'public_tls', 'archives') else 'cell'
        self.query_one('#ca-panel').display = self.page == 'ca'
        self.query_one('#archive-actions').display = self.page == 'archives'
        self.query_one('#actions').display = self.page != 'archives'
        self.query_one('#new').display = self.page not in ('ca','deployment','archives')
        self.query_one('#edit').display = self.page in ('nodes', 'sites', 'regions')
        self.query_one('#ca-open').display = self.page == 'clients'
        for key in ('pub-details','pub-all','pub-settings','pub-tool'):
            self.query_one('#'+key).display = self.page == 'public_tls'
        self.query_one('#ca-back').display = self.page == 'ca'
        for key in ('generate-deploy','run-export','run-export-all','deploy-all'):
            self.query_one('#'+key).display = self.page == 'deployment'
        for key in ('ssh-guide','ssh-reset'):
            self.query_one('#'+key).display = self.page == 'nodes'
        for key in ('archive-save','archive-restore','archive-export','archive-delete'):
            self.query_one('#'+key).display = self.page == 'archives'
        summary=self.query_one('#page-summary',Static)
        summary.display=False
        summary.update('')
        self.query_one('#delete').display = self.page in ('nodes', 'sites', 'regions', 'public_tls')
        self.query_one('#p12').display = self.page == 'clients'
        self.query_one('#client-toggle').display = self.page == 'clients'
        for key in ('initialize', 'public-ca'):
            self.query_one('#' + key).display = self.page == 'ca'
        self.query_one('#delete').disabled = False
        table.clear(columns=True)
        self.row_ids, self.col_keys = [], []
        if self.page == 'public_tls':
            self.public_tls_page.refresh_records(refresh_validation=False)
        elif self.page == 'archives':
            self.archives_page.render(table)
        elif self.page == 'deployment':
            rows=[self.deployment_cells(node,errors) for node in self.demo.nodes]
            headers=[(tr('节点'),'node'),*[(region.name,region.id) for region in self.demo.regions]]
            for index,(heading,identity) in enumerate(headers):
                width=max(22 if index==0 else 34,cell_len(heading),max((cell_len(line) for row in rows for line in row[index].plain.splitlines()),default=0)+2)
                table.add_column(heading,key=identity,width=width)
            for node,cells in zip(self.demo.nodes,rows):
                table.add_row(*cells,key=node.id,height=max(2,*(cell.plain.count('\n')+1 for cell in cells)))
            pos=self.positions.get('deployment',(0,0))
            table.move_cursor(row=min(pos[0],max(0,len(self.demo.nodes)-1)))
            blocked=bool(errors) or not self.demo.nodes or not self.demo.initialized
            for key in ('generate-deploy','run-export','run-export-all','deploy-all'):
                self.query_one('#'+key).disabled=blocked
        elif self.page == 'ca':
            self.render_ca()
        else:
            columns = [('name', tr('名称'), 18 if self.page == 'clients' else 11)]
            if self.page == 'nodes':
                columns += [('platform', tr('平台 / 架构'), 20), ('ssh_hops', tr('SSH 地址'), max(18, min(46, max((cell_len(line) for n in self.demo.nodes for line in self.cell_value(n, 'ssh_hops').splitlines()), default=0) + 1)))]
            elif self.page == 'sites':
                columns=[('name',tr('名称'),max(12,max((cell_len(s.name) for s in self.demo.sites),default=0)+2))]
                columns += [(key,title,max(minimum,min(maximum,max((cell_len(getattr(s,key)) for s in self.demo.sites),default=0)+2))) for key,title,minimum,maximum in [('domain',tr('服务域名'),20,32),('source',tr('源地址'),24,36)]]
            elif self.page == 'regions':
                columns += [('tls_source',tr('默认 TLS 来源'),20),('mtls',tr('默认 mTLS 验证'),20)]
            else:
                columns += [('enabled', tr('状态'), 6), ('expiry', tr('有效期至'), 10)]
            if self.page in ('nodes', 'sites'):
                columns += [('area:' + r.id, tr('绑定地址({0})', r.name) if self.page == 'nodes' else r.name, 32 if self.page == 'nodes' else max(20,max((cell_len(self.service_label(s,r)) for s in self.demo.sites),default=0)+2)) for r in self.demo.regions]
            if self.page == 'nodes': columns += [('upstream_url',tr('上游'),max(28,max((cell_len(n.upstream_url) for n in self.demo.nodes),default=0)))]
            for key, label, width in columns:
                table.add_column(label, key=key, width=max(width, cell_len(label)))
                self.col_keys.append(key)
            items = self.demo.items(self.page)
            for obj in items:
                cells = []
                for key in self.col_keys:
                    value = self.cell_value(obj, key)
                    bad = (self.page, obj.id, key) in errors or (key == 'platform' and (self.page, obj.id, 'arch') in errors) or (self.page=='sites' and key.startswith('area:') and ('sites',obj.id,'tls_source') in errors)
                    cells.append(Text(('! ' if bad else '') + value, style='#ffb4a2' if bad else ''))
                height = max(2,max((cell.plain.count('\n') + 1 for cell in cells),default=1)) if self.page == 'nodes' else 1
                table.add_row(*cells, key=obj.id, height=height)
                self.row_ids.append(obj.id)
            pos = self.positions.get(self.page, (0, 0))
            table.move_cursor(row=min(pos[0], max(0, len(self.row_ids)-1)), column=min(pos[1], len(self.col_keys)-1))
            self.update_selection()

    def deployment_cells(self, node, errors):
        def marked(value, bad):
            return Text(('! ' if bad else '')+value,style='#ffb4a2' if bad else '')
        target=node.ssh_hops[-1][0] if node.ssh_hops else tr('未配置')
        if ':' in target:target='['+target+']'
        bad=any(page=='nodes' and identity==node.id and not field.startswith('area:') for page,identity,field in errors)
        cells=[marked(node.name+'\n'+target,bad)]
        for region in self.demo.regions:
            area=node.areas.get(region.id,Listen())
            if not area.enabled:
                cells.append(Text(tr('未启用')));continue
            bad=('nodes',node.id,'area:'+region.id) in errors or any(page=='regions' and identity==region.id for page,identity,_ in errors)
            cell=marked(self.cell_value(node,'area:'+region.id),bad)
            sites=[site for site in self.demo.sites if service_policy(site,region).enabled]
            name_width=max((cell_len(site.name) for site in sites),default=0)
            for site in sites:
                bad=any(page=='sites' and identity==site.id and (not field.startswith('area:') or field=='area:'+region.id) for page,identity,field in errors)
                name=site.name+' '*(name_width-cell_len(site.name))
                cell.append('\n  ');cell.append(Text(name+'  '+self.service_label(site,region)+(' !' if bad else ''),style='#ffb4a2' if bad else ''))
            cells.append(cell)
        return cells

    def service_label(self, site, region, inheritance=False):
        policy=service_policy(site,region)
        if not policy.enabled:return label('disabled')
        source=tr('私有CA') if policy.tls_source=='private_ca' else tr('公共CA')
        pending=self.demo.validation.pending.get(site.id) if self.demo.validation and policy.tls_source=='public_ca' else None
        return 'TLS('+source+')'+('·mTLS' if policy.mtls else '')+(' / '+pending if pending else '')

    def cell_value(self, obj, key):
        if key == 'tls_source':return label(obj.tls_source)
        if key == 'mtls':return tr('开启') if obj.mtls else tr('关闭')
        if key == 'upstream_url':
            return tr('中继')+'\n'+obj.upstream_url if obj.upstream_url else tr('直连')
        if key == 'platform':
            return (label(obj.platform) if obj.platform else tr('未配置'))+'\n'+(obj.arch or tr('未配置'))
        if key == 'ssh_hops':
            if not obj.ssh_hops: return tr('未配置')
            target=obj.ssh_hops[-1][0]
            if ':' in target:target='['+target+']'
            return target+('\n'+tr('(经{0}个地址跳转)',len(obj.ssh_hops)-1) if len(obj.ssh_hops)>1 else '')
        if key == 'expiry':
            return '2099-12-31'
        if key == 'enabled':
            return tr('启用') if obj.enabled else tr('禁用')
        if key.startswith('area:'):
            rid = key[5:]
            if self.page == 'sites':
                return self.service_label(obj,self.demo.find('regions',rid),inheritance=True)
            a = obj.areas.get(rid, Listen())
            if not a.enabled:
                return tr('未启用')
            ports = a.ports
            hosts = [f'[{ip}]' if ':' in ip else ip for ip in (a.ips or [tr('未填写 IP')])]
            custom=ports[:2]!=['80','443'] or (a.relay_enabled and ports[2]!='8443')
            shown=ports[:2]+[ports[2] if a.relay_enabled else '-']
            suffix=':('+ '/'.join(shown)+')' if custom else ''
            return '\n'.join(host+suffix for host in hosts)
        return str(getattr(obj, key)) or tr('未填写')

    def current(self):
        if self.page in ('ca', 'deployment', 'archives') or not self.row_ids:
            return None, None
        t = self.query_one('#matrix', DataTable)
        row, col = t.cursor_coordinate
        if row >= len(self.row_ids) or col >= len(self.col_keys):
            return None, None
        return self.demo.find(self.page, self.row_ids[row]), self.col_keys[col]

    @on(DataTable.CellHighlighted)
    def highlighted(self):
        self.update_selection()

    def update_selection(self):
        self.call_after_refresh(self.refresh_button_focus)
        obj, key = self.current()
        self.query_one('#edit').disabled = obj is None
        if self.page == 'clients':
            self.query_one('#client-toggle').disabled = obj is None
            self.query_one('#p12').disabled = obj is None
            self.query_one('#client-toggle', Button).label = (tr('禁用') if obj and obj.enabled else tr('启用')) + ' · ^t'

    @on(DataTable.RowSelected, '#matrix')
    def release_selected(self):
        if self.page == 'public_tls': self.public_tls_page.action_details()

    @on(DataTable.RowHighlighted, '#matrix')
    def release_highlighted(self):
        if self.page=='deployment':self.positions[self.page]=self.query_one('#matrix',DataTable).cursor_coordinate
        if self.page in ('deployment', 'clients'): self.update_selection()

    def action_toggle_client(self):
        if len(self.screen_stack) != 1 or self.page != 'clients': return
        self.toggle_selected_client()

    @unlocked_operation
    def toggle_selected_client(self):
        if len(self.screen_stack) != 1 or self.page != 'clients': return
        obj, _ = self.current()
        if obj is not None:
            self.application.certificates.set_enabled(obj.id, not obj.enabled)
            self.after_change('')

    @on(DataTable.CellSelected)
    def edit_selected(self):
        if len(self.screen_stack)!=1 or self.page not in ('nodes','sites','regions'):return
        obj,key=self.current()
        if obj is None:return
        self.require_unlock(lambda:edit_configuration(self))

    def after_change(self, message):
        self.positions[self.page] = self.query_one('#matrix', DataTable).cursor_coordinate
        self.demo.reload()
        self.render_page()

    def name_error(self, page, value, object_id=None):
        if page == 'clients':
            try: value = validate_certificate_name(value)
            except ValueError as error: return str(error)
        if not value:
            return tr('名称不能为空')
        if not self.demo.unique(page, value, object_id):
            return tr('名称已存在')
        return None

    def action_new(self):
        if self.page=='public_tls' and len(self.screen_stack)==1:
            self.public_tls_page.action_new();return
        if len(self.screen_stack)==1 and self.page=='archives':
            self.archives_page.save();return
        if len(self.screen_stack) != 1 or self.page in ('ca', 'deployment', 'archives'):
            return
        if self.page == 'clients':
            self.require_unlock(self.new_item)
        else:
            self.new_item()

    @unlocked_operation
    def new_item(self):
        page = self.page
        def saved(v):
            if v is None:
                return
            self.demo.create(page, v['name'])
            self.positions[page] = (len(self.demo.items(page))-1, 0)
            self.render_page()
            if page == 'nodes':
                identity=self.demo.nodes[-1].id
                self.query_one('#matrix').move_cursor(row=self.row_ids.index(identity))
            self.query_one('#matrix').focus()
        self.push_screen(Form(tr('签发 Client') if page == 'clients' else tr('新增') + PAGES[page],
                              [Field('name', tr('名称'), placeholder=tr('例如：Personal-Phone') if page == 'clients' else '')], lambda v: self.name_error(page, v['name']),
                              '' if page != 'clients' else tr('仅允许英文字母、数字、空格及 - _ .；有效期至 2099-12-31')), saved)

    def action_delete(self):
        if len(self.screen_stack)!=1 or self.page not in ('nodes','sites','regions','public_tls','archives'):return
        if self.page=='public_tls':self.public_tls_page.action_delete();return
        if self.page=='archives':self.archives_page.delete();return
        if self.current()[0] is None:return
        self.delete_selected_item()

    @unlocked_operation
    def delete_selected_item(self):
        obj, _ = self.current()
        if obj is None:
            return
        page = self.page
        note = tr('同时移除所有节点和站点的该区域设置。') if page == 'regions' else ''
        def done(v):
            if v is not None:
                self.demo.delete(page, obj)
                self.after_change(tr('已删除：') + obj.name)
        self.push_screen(Form(tr('删除 ') + obj.name + '？', [], note=note), done)

    def perform(self, operation):
        try:
            return operation()
        except (ValueError, OSError, sqlite3.Error) as error:
            self.demo.reload()
            if len(self.screen_stack) == 1: self.render_page()
            self.show_info(tr('操作失败'), str(error))

    def push_screen(self, screen, callback=None, **kwargs):
        if callback:
            original = callback
            callback = lambda value: self.perform(lambda: original(value))
        return super().push_screen(screen, callback, **kwargs)

    def pop_screen(self):
        result = super().pop_screen()
        self.call_after_refresh(self.refresh_button_focus)
        return result

    def export_certificate(self, client=None):
        from ..network.files import publish
        if client and not self.application.security.unlocked:
            self.require_unlock(lambda: self.export_certificate(client))
            return
        name = 'root-ca.cer'
        if client:
            stem = re.sub(r'[<>:"/\\|?*\x00-\x1f\x7f]', '_', client.name).strip().rstrip('.') or 'client'
            if stem.split('.')[0].upper() in {'CON', 'PRN', 'AUX', 'NUL', *[f'{p}{i}' for p in ('COM', 'LPT') for i in range(1, 10)]}:
                stem = '_' + stem
            name = stem + '.p12'
        path = self.application.store.exports / name
        def exported(): self.show_info(tr('已导出'), str(path.resolve()))
        def begin():
            if client:
                self.push_screen(PasswordDialog(tr('导出 P12'),
                    lambda password: publish(path, self.application.certificates.export_p12(client.id, password), self.application.store.temporary),
                    visible=True, path=path, submit_label=tr('导出'), note=tr('导出口令只保护此 P12 文件，与程序口令无关。')),
                    lambda values: exported() if values is not None else None)
            else:
                self.push_screen(Form(tr('导出信任 CA'), [Field('path', tr('保存路径'), str(path.resolve()), readonly=True)],
                    note=tr('根 CA 证书（DER / .cer），不含私钥。\nWindows：导入受信任的根证书颁发机构。\nAndroid：安装为 CA 证书，应用是否信任由应用决定。')),
                    lambda values: (publish(path, self.application.certificates.export_trust_ca(), self.application.store.temporary), exported()) if values is not None else None)
        if path.exists():
            self.push_screen(Form(tr('覆盖现有文件？'), [], note=str(path.resolve())),
                lambda values: begin() if values is not None else None)
        else: begin()

    def show_info(self, title, message, *, return_only=False):
        self.push_screen(Form(title, [], note=message, return_only=return_only))

    def render_ca(self):
        authorities,clients = self.application.certificates.overview()
        table = Table(expand=True, box=None, padding=(0, 1), collapse_padding=True)
        table.add_column(tr('证书名称'), ratio=1, overflow='fold')
        table.add_column(tr('有效期至'), width=10, justify='right', no_wrap=True)
        if self.demo.initialized:
            table.add_row(Text(authorities['root'][0]), authorities['root'][1])
            for role,prefix in [('relay','├─ '),('tls','├─ '),('client','└─ ')]:
                name,expiry=authorities[role]
                table.add_row(Text(prefix+name),expiry)
                if role != 'client':table.add_row('│  └─ …','')
            for index,(name,expiry,enabled) in enumerate(clients):
                prefix='   └─ ' if index==len(clients)-1 else '   ├─ '
                table.add_row(Text(prefix+name+('' if enabled else ' [disabled]')),expiry)
            if not clients:table.add_row(tr('   └─ 暂无证书'),'')
        else:table.add_row(tr('尚未初始化'),'')
        self.query_one('#ca-info', Static).update(table)
        self.query_one('#public-ca').disabled = not self.demo.initialized
        self.query_one('#initialize', Button).label = tr('重新初始化 CA') if self.demo.initialized else tr('初始化 CA')
        self.query_one('#initialize', Button).variant = 'error' if self.demo.initialized else 'default'

    def require_unlock(self, continuation):
        security = self.application.security
        if security.unlocked:
            continuation()
            return
        def done(values):
            if values is not None:
                self.after_change('')
                continuation()
        initialized = security.initialized
        self.push_screen(PasswordDialog(tr('解锁程序') if initialized else tr('设置程序口令'),
            security.unlock if initialized else security.setup, repeat=not initialized,
            submit_label=tr('解锁') if initialized else tr('保存'),
            note=tr('验证通过后将解锁，直至退出程序。') if initialized else tr('统一保护 CA、Client 和 SSH 私钥；修改配置也需要解锁。')), done)

    @unlocked_operation
    def initialize(self, replace=False, required=False):
        def validate(values):
            try:self.application.certificates.initialize(values['name'], replace=replace)
            except (ValueError, OSError) as error:return str(error)
        def done(values):
            if values is not None:self.after_change('')
            elif required:self.exit()
        self.push_screen(Form(tr('创建 CA') if required else tr('初始化 CA'),
            [Field('name', tr('CA 名称前缀'), placeholder=tr('例如：Personal WEB'))], validate,
            tr('根 CA 是此网络的信任基础，请妥善保管口令及 数据目录。\n名称仅支持英文字母、数字、空格及 - _ .。')), done)

    @unlocked_operation
    def change_program_password(self):
        self.push_screen(PasswordDialog(tr('修改程序口令'), self.application.security.change_password,
            repeat=True, note=tr('修改全部私钥的保护口令，不改变证书或 SSH 身份。')),
            lambda values: self.after_change('') if values is not None else None)

    @unlocked_operation
    def reset_ssh(self):
        def done(values):
            if values is not None:
                self.application.ssh.reset()
                self.after_change('')
        self.push_screen(Form(tr('重置 SSH 私钥？'), [],
            note=tr('全部节点共用此身份。重置后需手动更新节点信任公钥。\n已确认的节点主机指纹不清除。'), confirm=True), done)

    @unlocked_operation
    def reset_ca(self):
        self.push_screen(Form(tr('重新初始化 CA？'), [],
            note=tr('清除所有 CA 及 Client 证书。\n区域、节点、站点、程序口令及 SSH 身份保留。'), confirm=True),
            lambda values: self.initialize(replace=True) if values is not None else None)

    def action_edit(self):
        if self.page=='public_tls' and len(self.screen_stack)==1:
            self.public_tls_page.action_details();return
        if self.page in ('nodes', 'sites', 'regions'): self.edit_selected()

    def action_export(self):
        if len(self.screen_stack) != 1: return
        if self.page == 'clients':
            client, _ = self.current()
            if client: self.export_certificate(client)
        elif self.page == 'ca':
            if self.demo.initialized: self.export_certificate()
        elif self.page == 'deployment': self.open_export('package')
        elif self.page == 'archives': self.archives_page.export(selected=True)

    def open_export(self, mode, all_nodes=False):
        if len(self.screen_stack) != 1:
            return
        if self.demo.errors() or not self.demo.initialized or not self.demo.nodes:
            self.show_info(tr('无法准备运行材料'), tr('请初始化 CA、添加节点，并修正配置错误。'))
            return
        node_ids=None
        if not all_nodes:
            row=self.query_one('#matrix',DataTable).cursor_row
            if not 0<=row<len(self.demo.nodes):return
            node_ids=(self.demo.nodes[row].id,)
        from .publishing import Export
        self.require_unlock(lambda:self.push_screen(Export('package' if mode=='package' else 'deploy',node_ids),lambda _:self.after_change('')))

    def action_deploy(self):
        if len(self.screen_stack)!=1:return
        if self.page!='deployment':
            self.page='deployment';self.render_page();self.query_one('#matrix').focus();return
        self.open_export('deploy')

    def action_help(self):
        self.action_toggle_shortcuts()

    @on(Button.Pressed)
    def buttons(self, event):
        key = event.button.id
        if key in ('settings-regions','settings-archives'):
            self.positions[self.page] = self.query_one('#matrix',DataTable).cursor_coordinate
            self.page = key.removeprefix('settings-')
            self.render_page()
        elif key=='run-export': self.open_export('package')
        elif key=='run-export-all': self.open_export('package',all_nodes=True)
        elif key=='deploy-all': self.open_export('deploy',all_nodes=True)
        elif key=='archive-save': self.archives_page.save()
        elif key=='settings-import': self.archives_page.import_json()
        elif key=='archive-restore': self.archives_page.restore()
        elif key=='archive-export': self.archives_page.export(selected=True)
        elif key=='archive-delete': self.archives_page.delete()
        elif key == 'client-toggle': self.action_toggle_client()
        elif key == 'edit': self.edit_selected()
        elif key == 'help': self.action_help()
        elif key == 'quit': self.exit()
        elif key == 'pub-details': self.public_tls_page.action_details()
        elif key == 'pub-all': self.public_tls_page.apply_all()
        elif key == 'pub-settings': self.public_tls_page.settings()
        elif key == 'pub-tool': self.public_tls_page.tool()
        elif key == 'ca-open':
            self.page = 'ca'
            self.render_page()
            self.query_one('#initialize').focus()
        elif key == 'ca-back': self.action_navigation()
        elif key == 'generate-deploy': self.open_export('new-deploy')
        elif key == 'new': self.action_new()
        elif key == 'delete': self.action_delete()
        elif key == 'ssh-guide':
            self.push_screen(SSHGuide(self.application.ssh.public()))
        elif key == 'ssh-reset': self.reset_ssh()
        elif key == 'initialize' and not self.demo.initialized: self.initialize()
        elif key == 'public-ca': self.export_certificate()
        elif key == 'p12':
            obj, _ = self.current()
            if obj: self.export_certificate(obj)
        elif key == 'password': self.change_program_password()
        elif key == 'initialize':
            self.reset_ca() if self.demo.initialized else self.initialize()


def main(directory='data'):
    from ..network.application import Application
    from ..network.runtime import Runtime
    runtime = Runtime(directory)
    try:
        runtime.ready.result()
        application = Application(directory)
        try: Terminal(application).run()
        finally: application.close()
    finally: runtime.close()
