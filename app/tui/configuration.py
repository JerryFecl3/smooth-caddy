"""Node, site and region cell editing; persistence stays in Application."""
from copy import deepcopy
from .widgets import DataTable
from .dialogs import Field, Form
from ..network.models import Listen, MODES, PORTS, PLATFORMS, ARCHES, duplicate_domain, check_node_parent


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
            self.show_info(obj.name, '证书名称：' + obj.name)
            return
        fields = [Field('value', '名称', obj.name)]
        validator = lambda v: self.name_error(page, v['value'], obj.id)
        if page == 'nodes':
            parent=obj.upstream[0] if obj.upstream else ''
            options=[('无','')]+[(n.name,n.id) for n in self.demo.nodes if n.id!=obj.id]
            if parent and parent not in [value for _,value in options]:options.append(('已删除节点',parent))
            fields.append(Field('parent','上游节点',parent,options))
            def validator(v):
                error=self.name_error(page,v['value'],obj.id)
                if error:return error
                try:check_node_parent(self.demo.config,obj.id,v['parent'])
                except ValueError as error:return str(error)
    elif key == 'platform':
        fields = [Field('platform', '目标平台', obj.platform, [('未选择', '')] + [(x, x) for x in PLATFORMS]),
                  Field('arch', 'CPU 架构', obj.arch, [('未选择', '')] + [(x, x) for x in ARCHES])]
    elif key == 'ssh_ip':
        fields = [Field('value', 'SSH 地址', obj.ssh_ip)]
        note = 'root · 端口 22'
    elif key == 'upstream':
        if not obj.upstream:
            return
        parent=self.demo.find('nodes',obj.upstream[0])
        options=[('未选择','')]
        if parent:
            options += [(f'{parent.name}-{r.name}-{parent.areas.get(r.id,Listen()).ip or "未配置 IP"}'+('' if parent.areas.get(r.id,Listen()).enabled else '（未启用）'),r.id) for r in self.demo.regions]
        value=obj.upstream[1]
        if value and value not in [v for _,v in options]:options.append(('已删除区域',value))
        fields=[Field('region','上游中继区域',value,options)]
    elif key.startswith('area:'):
        r = self.demo.find('regions', key[5:])
        if page == 'sites':
            fields = [Field('value', '服务方式', obj.areas.get(r.id, MODES[0]), [(x, x) for x in MODES])]
            note = ''
        else:
            a = deepcopy(obj.areas.get(r.id, Listen()))
            fields = [Field('enabled', '启用此区域', a.enabled, boolean=True), Field('ip', '监听 IP', a.ip)]
            for i, p in enumerate(PORTS):
                fields += [Field(f'override{i}', f'覆盖 {p} 端口（默认 {r.ports[i]}）', a.overrides[i] is not None, boolean=True),
                           Field(f'port{i}', p + ' 端口', a.overrides[i] if a.overrides[i] is not None else r.ports[i])]
            note = ''
    elif key == 'tls_source':
        fields = [Field('value', 'TLS 来源', obj.tls_source, [(x,x) for x in ('私有 CA','公共 CA')])]
        note = '公共证书来自 TLS证书页面。'
    elif key == 'enabled':
        fields = [Field('value', 'Client 状态', obj.enabled, [('启用', True), ('禁用', False)])]
    elif key == 'expiry':
        self.show_info(obj.name + ' / 有效期', '有效期至 2099-12-31。')
        return
    else:
        fields = [Field('value', {'domain':'服务域名','source':'源头地址'}.get(key, '端口' if key.startswith('p') else '值'), self.cell_value(obj, key) if self.cell_value(obj, key) != '未填写' else '')]
        if key == 'domain':
            validator = lambda v: ('域名已存在' if v['value'] and duplicate_domain(self.demo.sites,v['value'],obj.id) else None)
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
        elif key == 'upstream':
            obj.upstream = (obj.upstream[0],v['region'])
        elif key == 'name' and page == 'nodes':
            obj.name=v['value']
            old=obj.upstream[0] if obj.upstream else ''
            if old!=v['parent']:
                obj.upstream=(v['parent'],'') if v['parent'] else None
            obj.mode='经上游转发' if obj.upstream else '直连源头'
        else:
            setattr(obj, key, v['value'])
        self.demo.save()
        self.after_change('已保存：' + title)
        if page == 'nodes' and obj.id in self.row_ids:
            self.query_one('#matrix').move_cursor(row=self.row_ids.index(obj.id))
    self.push_screen(Form(title, fields, validator, note), saved)

