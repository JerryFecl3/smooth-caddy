"""Node, site and region cell editing; persistence stays in Application."""
from ..i18n import tr
from copy import deepcopy
from .widgets import DataTable
from .dialogs import Field, Form
from .labels import options as labeled_options
from ..network.models import Listen, MODES, PORTS, PLATFORMS, ARCHES, duplicate_domain, parse_ssh_path, relay_endpoint


def edit_configuration(self):
    obj, key = self.current()
    if obj is None:
        return
    page = self.page
    fields = []
    validator = None
    note = ''
    if key == 'name':
        if page == 'clients':
            self.show_info(obj.name, tr('证书名称：') + obj.name)
            return
        fields = [Field('value', tr('名称'), obj.name)]
        validator = lambda v: self.name_error(page, v['value'], obj.id)
    elif key == 'platform':
        fields = [Field('platform', tr('目标平台'), obj.platform, [(tr('未选择'), '')] + labeled_options(PLATFORMS)),
                  Field('arch', tr('CPU 架构'), obj.arch, [(tr('未选择'), '')] + [(x, x) for x in ARCHES])]
    elif key == 'ssh_hops':
        fields = [Field('value', tr('SSH 路径'), '\n'.join(hop[0] for hop in obj.ssh_hops), multiline=True)]
        note = tr('每行一个 IP，按连接顺序填写，最后一行是目标节点。') + '\n' + tr('root · 端口 22')
        def validator(v):
            try: parse_ssh_path(v['value'])
            except ValueError as error: return str(error)
    elif key == 'upstream_url':
        fields = [Field('value', tr('上游地址'), obj.upstream_url, placeholder='https://relay.example.com:8443')]
        note = tr('留空直连源头；填写时必须指向已存在的中继服务地址和端口（HTTPS）。请避免转发环路。')
        def validator(v):
            if v['value']:
                try: relay_endpoint(v['value'])
                except ValueError as error: return str(error)
    elif key.startswith('area:'):
        r = self.demo.find('regions', key[5:])
        if page == 'sites':
            fields = [Field('value', tr('服务方式'), obj.areas.get(r.id, MODES[0]), labeled_options(MODES))]
            note = ''
        else:
            a = deepcopy(obj.areas.get(r.id, Listen()))
            fields = [Field('enabled', tr('启用此区域'), a.enabled, boolean=True), Field('ip', tr('监听 IP'), a.ip)]
            for i, p in enumerate(PORTS):
                fields += [Field(f'override{i}', tr('覆盖 {0} 端口（默认 {1}）', p, r.ports[i]), a.overrides[i] is not None, boolean=True),
                           Field(f'port{i}', p + tr(' 端口'), a.overrides[i] if a.overrides[i] is not None else r.ports[i])]
            note = ''
    elif key == 'tls_source':
        fields = [Field('value', tr('TLS 来源'), obj.tls_source, labeled_options(('private_ca','public_ca')))]
        note = tr('公共证书来自 TLS证书页面。')
    elif key == 'enabled':
        fields = [Field('value', tr('Client 状态'), obj.enabled, [(tr('启用'), True), (tr('禁用'), False)])]
    elif key == 'expiry':
        self.show_info(obj.name + tr(' / 有效期'), tr('有效期至 2099-12-31。'))
        return
    else:
        fields = [Field('value', {'domain':tr('服务域名'),'source':tr('源头地址')}.get(key, tr('端口') if key.startswith('p') else tr('值')), self.cell_value(obj, key) if self.cell_value(obj, key) != tr('未填写') else '')]
        if key == 'domain':
            validator = lambda v: (tr('域名已存在') if v['value'] and duplicate_domain(self.demo.sites,v['value'],obj.id) else None)
    title = f'{obj.name} / {str(self.query_one("#matrix", DataTable).ordered_columns[self.query_one("#matrix", DataTable).cursor_column].label)}'
    problems = list(self.demo.errors().get((page, obj.id, key), []))
    if key == 'platform':
        problems += self.demo.errors().get((page, obj.id, 'arch'), [])
    if problems:
        note = '\n'.join(problems) + ('\n' + note if note else '')
    def saved(v):
        if v is None:
            return
        if key.startswith('area:'):
            if page == 'nodes':
                obj.areas[key[5:]] = Listen(v['enabled'], v['ip'], [v[f'port{i}'] if v[f'override{i}'] else None for i in range(3)])
            else:
                obj.areas[key[5:]] = v['value']
        elif key.startswith('p') and page == 'regions':
            obj.ports[int(key[1:])] = v['value']
        elif key == 'platform':
            obj.platform, obj.arch = v['platform'], v['arch']
        elif key == 'ssh_hops':
            obj.ssh_hops = parse_ssh_path(v['value'])
        else:
            setattr(obj, key, v['value'])
        self.demo.save()
        self.after_change(tr('已保存：') + title)
        if page == 'nodes' and obj.id in self.row_ids:
            self.query_one('#matrix').move_cursor(row=self.row_ids.index(obj.id))
    form = Form(title, fields, validator, note)
    if key == 'ssh_hops': form.add_class('ssh-path-dialog')
    self.push_screen(form, saved)

