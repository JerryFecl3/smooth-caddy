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
from ..network.models import Listen, MODES, PORTS, node_tree

PAGES = {'deployment': tr('部署'), 'sites': tr('站点'), 'nodes': tr('节点'), 'regions': tr('区域'), 'clients': tr('mTLS证书'), 'public_tls': tr('TLS证书'), 'ca': tr('mTLS证书 / CA')}

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
        Binding('f10', 'toggle_shortcuts', tr('帮助'), priority=True),
        *[Binding(f'f{i}', f'nav_page({i})', title, priority=True) for i, title in enumerate((tr('部署'), tr('站点'), tr('节点'), tr('区域'), tr('mTLS证书'), tr('TLS证书')), 1)],
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
        self.page = 'deployment'
        self.rendered_page = None
        self.site_order = []
        self.col_keys = []
        self.row_ids = []
        self.positions = {}

    def compose(self):
        yield Static('Smooth Caddy', id='brand')
        with Horizontal(id='workspace'):
            with Vertical(id='sidebar'):
                yield ListView(*[ListItem(Label(title), id='nav-' + key) for key, title in {k: v for k, v in PAGES.items() if k != 'ca'}.items()], id='nav')
                yield Static('', id='nav-note')
                yield Button(tr('修改口令'), id='password')
                yield Button(tr('帮助 · F10'), id='help')
                yield Button(tr('退出 · ^q'), id='quit')
            with Vertical(id='main'):
                yield DataTable(id='matrix', fixed_columns=1, zebra_stripes=True, cursor_type='cell', cursor_foreground_priority='css')
                with VerticalScroll(id='ca-panel'):
                    yield Static('', id='ca-info', markup=False)
                with HorizontalScroll(id='actions'):
                    yield Button(tr('禁用 · ^t'), id='client-toggle')
                    yield Button(tr('编辑 · ^o'), id='edit', variant='primary')
                    yield Button(tr('详情 · ^o'), id='batch-details', variant='primary')
                    yield Button(tr('详情 · ^o'), id='pub-details', variant='primary')
                    yield Button(tr('新增 · ^n'), id='new')
                    yield Button(tr('删除 · Del'), id='delete')
                    yield Button(tr('导出 P12 · ^e'), id='p12')
                    yield Static('', classes='action-spacer')
                    yield Button(tr('返回证书 · Esc'), id='ca-back')
                    yield Button(tr('导出信任 CA · ^e'), id='public-ca')
                    yield Button(tr('全部申请'), id='pub-all')
                    yield Button(tr('公共TLS设置'), id='pub-settings')
                    yield Button(tr('lego 管理'), id='pub-tool')
                    yield Button(tr('高级设置'), id='site-settings')
                    yield Button(tr('CA 管理'), id='ca-open')
                    yield Button(tr('新增并部署'), id='generate-deploy')
                    yield Button(tr('SSH 公钥'), id='ssh-guide')
                    yield Button(tr('初始化 CA'), id='initialize')
                    yield Button(tr('重置 SSH 私钥'), id='ssh-reset', variant='error')

    def on_mount(self):
        self.theme = 'textual-dark'
        self.query_one('#nav', ListView).index = list(PAGES).index(self.page)
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
        self.page = target
        self.render_page()
        self.query_one('#matrix').focus()

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
        for i, key in enumerate((k for k in PAGES if k != 'ca'), 1):
            item = self.screen_stack[0].query_one('#nav-' + key, ListItem)
            count = sum(1 for k in errors if k[0] == key)
            item.set_class(bool(count), 'config-error')
            item.query_one(Label).update(PAGES[key] + (f' · F{i}' if self.show_shortcuts else '') + ('  !' if count else ''))

    def action_nav_page(self, number):
        if len(self.screen_stack) != 1: return
        nav = self.query_one('#nav', ListView)
        nav.index = number - 1
        nav.focus()
        nav.action_select_cursor()

    def check_action(self, action, parameters):
        if action == 'quit' and any(getattr(screen, 'busy', False) or (hasattr(screen, 'finished') and not screen.finished) for screen in self.screen_stack):
            return False
        if action in ('next_region', 'previous_region', 'nav_page'):
            return len(self.screen_stack) == 1
        return True

    def action_next_region(self):
        self.move_region(1)

    def action_previous_region(self):
        self.move_region(-1)

    def move_region(self, direction):
        focused = self.focused
        ids = {w.id for w in ([focused] + list(focused.ancestors))} if focused else set()
        current = 0 if 'sidebar' in ids else 2 if 'actions' in ids else 1
        target = (current + direction) % 3
        if target == 0:
            self.query_one('#nav').focus()
        elif target == 1:
            self.query_one('#ca-panel' if self.page == 'ca' else '#matrix').focus()
        else:
            self.screen.focus_next('#actions Button')

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
        if self.page == 'sites':
            if self.rendered_page != 'sites':
                self.demo.reload()
                self.site_order = [site.id for site in sorted(self.demo.sites, key=lambda site: (site.name.casefold(), site.name))]
            else:
                present = {site.id for site in self.demo.sites}
                self.site_order = [identity for identity in self.site_order if identity in present]
                known = set(self.site_order)
                self.site_order.extend(site.id for site in self.demo.sites if site.id not in known)
        self.rendered_page = self.page
        self.demo.refresh_validation()
        errors = self.demo.errors()
        for key in (k for k in PAGES if k != 'ca'):
            item = self.query_one('#nav-' + key, ListItem)
            item.set_class(key == self.page or (key == 'clients' and self.page == 'ca'), 'active-page')
            count = sum(1 for k in errors if k[0] == key)
            item.set_class(bool(count), 'config-error')
        self.refresh_navigation_labels()
        table = self.query_one('#matrix', DataTable)
        table.display = self.page != 'ca'
        table.cursor_type = 'row' if self.page in ('deployment', 'clients', 'public_tls') else 'cell'
        self.query_one('#ca-panel').display = self.page == 'ca'
        self.query_one('#new').display = self.page != 'ca'
        self.query_one('#edit').display = self.page in ('nodes', 'sites', 'regions')
        self.query_one('#site-settings').display = self.page == 'sites'
        self.query_one('#ca-open').display = self.page == 'clients'
        for key in ('pub-details','pub-all','pub-settings','pub-tool'):
            self.query_one('#'+key).display = self.page == 'public_tls'
        self.query_one('#ca-back').display = self.page == 'ca'
        for key in ('generate-deploy', 'ssh-guide', 'ssh-reset'):
            self.query_one('#' + key).display = self.page == 'deployment'
        self.query_one('#delete').display = self.page in ('nodes', 'sites', 'regions', 'deployment', 'public_tls')
        self.query_one('#p12').display = self.page == 'clients'
        self.query_one('#client-toggle').display = self.page == 'clients'
        for key in ('initialize', 'public-ca'):
            self.query_one('#' + key).display = self.page == 'ca'
        for key in ('batch-details',):
            self.query_one('#'+key).display=self.page=='deployment'
        self.query_one('#delete').disabled = False
        table.clear(columns=True)
        self.row_ids, self.col_keys = [], []
        if self.page == 'public_tls':
            self.public_tls_page.refresh_records(refresh_validation=False)
        elif self.page == 'deployment':
            releases = self.demo.releases
            table.add_columns(tr('配置批次'),tr('节点数'),tr('站点数'),tr('区域数'))
            for r in releases:
                table.add_row(r.version,*[str(len(r.summary[key])) for key in ('nodes','sites','regions')],key=r.version)
            pos = self.positions.get(self.page, (0, 0))
            table.move_cursor(row=min(pos[0], max(0, len(releases)-1)))
            self.query_one('#delete').disabled = not releases
            for key in ('batch-details',):self.query_one('#'+key).disabled=not releases
            self.update_selection()
        elif self.page == 'ca':
            self.render_ca()
        else:
            columns = [('name', tr('名称'), 18 if self.page == 'clients' else 11)]
            if self.page == 'nodes':
                columns[0]=('name',tr('名称'),11+max((len(prefix) for _,prefix in node_tree(self.demo.nodes)),default=0))
                columns += [('platform', tr('平台 / 架构'), 20), ('ssh_ip', tr('SSH 地址'), max(18, min(42, max((len(n.ssh_ip) for n in self.demo.nodes), default=0) + 3)))]
            elif self.page == 'sites':
                columns += [('domain', tr('服务域名'), 25), ('tls_source', tr('TLS 来源'), 20), ('source', tr('源头地址'), 30)]
            elif self.page == 'regions':
                columns += [(f'p{i}', p + tr(' 默认端口'), len(p) + (2 if i == 2 else 0) + 9) for i, p in enumerate(PORTS)]
            else:
                columns += [('enabled', tr('状态'), 6), ('expiry', tr('有效期至'), 10)]
            if self.page in ('nodes', 'sites'):
                columns += [('area:' + r.id, tr('WEB服务地址({0})', r.name) if self.page == 'nodes' else r.name, 32 if self.page == 'nodes' else 20) for r in self.demo.regions]
            if self.page == 'nodes': columns += [('upstream',tr('中继上游IP'),max(15,min(39,max((len(a.ip) for n in self.demo.nodes for a in n.areas.values()),default=0))))]
            for key, label, width in columns:
                table.add_column(label, key=key, width=max(width, cell_len(label)))
                self.col_keys.append(key)
            items = [self.demo.find('sites', identity) for identity in self.site_order] if self.page == 'sites' else self.demo.items(self.page)
            prefixes={}
            if self.page == 'nodes':
                tree=node_tree(items);items=[n for n,_ in tree];prefixes={n.id:p for n,p in tree}
            for obj in items:
                cells = []
                for key in self.col_keys:
                    value = self.cell_value(obj, key)
                    if key == "name":value=prefixes.get(obj.id, "")+value
                    bad = (self.page, obj.id, key) in errors or (key == 'platform' and (self.page, obj.id, 'arch') in errors)
                    cells.append(Text(('! ' if bad else '') + value, style='#ffb4a2' if bad else ''))
                table.add_row(*cells, key=obj.id)
                self.row_ids.append(obj.id)
            pos = self.positions.get(self.page, (0, 0))
            table.move_cursor(row=min(pos[0], max(0, len(self.row_ids)-1)), column=min(pos[1], len(self.col_keys)-1))
            self.update_selection()

    def cell_value(self, obj, key):
        if key == 'tls_source':
            pending=self.demo.validation.pending.get(obj.id)
            return label(obj.tls_source)+(' / '+pending if pending else '')
        if key == 'upstream':
            if not obj.upstream:return ''
            parent=self.demo.find('nodes',obj.upstream[0])
            if not parent:return tr('已删除节点')
            if not obj.upstream[1]:return tr('未选择')
            if not self.demo.find('regions',obj.upstream[1]):return tr('已删除区域')
            return parent.areas.get(obj.upstream[1],Listen()).ip or tr('未配置 IP')
        if key == 'platform':
            return f'{label(obj.platform)} {obj.arch}' if obj.platform and obj.arch else tr('未配置')
        if key == 'expiry':
            return '2099-12-31'
        if key == 'enabled':
            return tr('启用') if obj.enabled else tr('禁用')
        if key.startswith('p') and self.page == 'regions':
            return obj.ports[int(key[1:])]
        if key.startswith('area:'):
            rid = key[5:]
            if self.page == 'sites':
                return label(obj.areas.get(rid, MODES[0]))
            a = obj.areas.get(rid, Listen())
            if not a.enabled:
                return tr('关闭')
            region = self.demo.find('regions', rid)
            ports = [a.overrides[i] if a.overrides[i] is not None else region.ports[i] for i in range(2)]
            return f"{a.ip or tr('未填写 IP')} : {ports[0]}/{ports[1]}"
        return str(getattr(obj, key)) or tr('未填写')

    def current(self):
        if self.page in ('ca', 'deployment') or not self.row_ids:
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
        obj, key = self.current()
        self.query_one('#edit').disabled = obj is None or (self.page == 'nodes' and key == 'upstream' and not obj.upstream)
        if self.page == 'clients':
            self.query_one('#client-toggle').disabled = obj is None
            self.query_one('#p12').disabled = obj is None
            self.query_one('#client-toggle', Button).label = (tr('禁用') if obj and obj.enabled else tr('启用')) + ' · ^t'

    @on(DataTable.RowSelected, '#matrix')
    def release_selected(self):
        if self.page == 'deployment': self.batch_details()
        elif self.page == 'public_tls': self.public_tls_page.action_details()

    @on(DataTable.RowHighlighted, '#matrix')
    def release_highlighted(self):
        if self.page in ('deployment', 'clients'): self.update_selection()

    @unlocked_operation
    def action_toggle_client(self):
        if len(self.screen_stack) != 1 or self.page != 'clients': return
        obj, _ = self.current()
        if obj is not None:
            self.application.certificates.set_enabled(obj.id, not obj.enabled)
            self.after_change('')

    @on(DataTable.CellSelected)
    def edit_selected(self):
        obj,key=self.current()
        if self.page == 'nodes' and key == 'upstream' and obj and not obj.upstream:return
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
        if len(self.screen_stack) == 1 and self.page == 'deployment':
            self.open_export('export')
            return
        if len(self.screen_stack) != 1 or self.page in ('ca', 'deployment'):
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
            self.demo.create(page, v['name'], v.get('parent'))
            self.positions[page] = (len(self.demo.items(page))-1, 0)
            self.render_page()
            if page == 'nodes':
                identity=self.demo.nodes[-1].id
                self.query_one('#matrix').move_cursor(row=self.row_ids.index(identity))
            self.query_one('#matrix').focus()
        self.push_screen(Form(tr('签发 Client') if page == 'clients' else tr('新增') + PAGES[page],
                              [Field('name', tr('名称'), placeholder=tr('例如：Personal-Phone') if page == 'clients' else '')] + ([Field('parent',tr('上游节点'),'',[(tr('无'),'')]+[(n.name,n.id) for n in self.demo.nodes])] if page == 'nodes' else []), lambda v: self.name_error(page, v['name']),
                              '' if page != 'clients' else tr('仅允许英文字母、数字、空格及 - _ .；有效期至 2099-12-31')), saved)

    @unlocked_operation
    def action_delete(self):
        if self.page=='public_tls' and len(self.screen_stack)==1:
            self.public_tls_page.action_delete();return
        if len(self.screen_stack) == 1 and self.page == 'deployment':
            release = self.selected_release()
            if release is None: return
            def deleted(v):
                if v is not None:
                    self.application.releases.delete(release.version)
                    self.after_change(tr('已删除：') + release.version)
            self.push_screen(Form(tr('删除配置批次？'), [], note=release.version + tr('\n删除此批次的配置、证书和记录，不影响已部署节点及已导出的 package。')), deleted)
            return
        if len(self.screen_stack) != 1 or self.page not in ('nodes', 'sites', 'regions'):
            return
        obj, _ = self.current()
        if obj is None:
            return
        page = self.page
        refs = [n.name for n in self.demo.nodes if n.upstream and
                ((page == 'nodes' and n.upstream[0] == obj.id) or (page == 'regions' and n.upstream[1] == obj.id))]
        note = tr('受影响上游引用：') + ('、'.join(refs) if refs else tr('无'))
        if page == 'regions':
            note += tr('\n同时移除所有节点和站点的该区域设置。')
        if refs: note += tr('\n这些节点的上游配置需要修正，否则无法生成配置批次。')
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

    @unlocked_operation
    def site_settings(self):
        def saved(values):
            if values is None: return
            self.demo.config.verify_origin_https = values['verify']
            self.demo.save()
            self.after_change('')
        self.push_screen(Form(tr('站点 / 高级设置'),
            [Field('verify', tr('校验 HTTPS 源头证书'), self.demo.config.verify_origin_https, boolean=True)],
            note=tr('对所有站点统一生效。关闭后仍加密，但不验证源头证书的信任链和名称。\n不影响用户入口及节点间 TLS/mTLS。')), saved)

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
        self.query_one('#initialize', Button).variant = 'error' if self.demo.initialized else 'primary'

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
        if self.page=='deployment':self.batch_details()
        elif self.page in ('nodes', 'sites', 'regions'): self.edit_selected()

    def action_export(self):
        if len(self.screen_stack) != 1: return
        if self.page == 'clients':
            client, _ = self.current()
            if client: self.export_certificate(client)
        elif self.page == 'ca':
            if self.demo.initialized: self.export_certificate()
        elif self.page == 'deployment': return

    def open_export(self, mode):
        if len(self.screen_stack) != 1:
            return
        if self.demo.errors() or not self.demo.initialized or not self.demo.nodes:
            self.show_info(tr('无法新增配置批次'), tr('请初始化 CA、添加节点，并修正配置错误。'))
            return
        from .publishing import Export,create_batch
        self.require_unlock(lambda: create_batch(self) if mode=='export' else self.push_screen(Export('new-deploy'),lambda _:self.after_change('')))

    def selected_release(self):
        releases = self.demo.releases
        row = self.query_one('#matrix', DataTable).cursor_row
        return releases[row] if 0 <= row < len(releases) else None

    def action_deploy(self):
        if len(self.screen_stack) != 1: return
        if self.page != 'deployment':
            self.page = 'deployment'
            self.render_page()
            self.query_one('#matrix').focus()
            return
        self.batch_details()

    def batch_details(self):
        if len(self.screen_stack)!=1:return
        batch=self.selected_release()
        if batch:
            from .publishing import BatchDetails,Export
            def chosen(mode):
                if mode:
                    self.require_unlock(lambda:self.push_screen(Export(mode,batch)))
            self.push_screen(BatchDetails(batch),chosen)

    def action_help(self):
        self.action_toggle_shortcuts()

    @on(Button.Pressed)
    def buttons(self, event):
        key = event.button.id
        if key=='batch-details': self.batch_details()
        elif key == 'client-toggle': self.action_toggle_client()
        elif key == 'site-settings': self.site_settings()
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
