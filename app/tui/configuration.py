"""Node, site and region cell editing; persistence stays in Application."""
from ..i18n import tr
from copy import deepcopy
from .widgets import DataTable
from .dialogs import Field, Form
from .labels import options as labeled_options
from ..network.models import Listen, Service, MODES, PORTS, PLATFORMS, ARCHES, duplicate_domain, parse_ssh_path, relay_endpoint, binding_addresses, configuration_errors


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
        fields = [Field('platform', tr('目标平台'), obj.platform, labeled_options(PLATFORMS),radio=True),
                  Field('arch', tr('CPU 架构'), obj.arch, [(x, x) for x in ARCHES],radio=True)]
    elif key == 'ssh_hops':
        fields = [Field('value', tr('SSH 地址'), '\n'.join(hop[0] for hop in obj.ssh_hops), multiline=True)]
        note = tr('每行一个 IP，按连接顺序填写，最后一行是目标节点。') + '\n' + tr('root · 端口 22')
        def validator(v):
            try: parse_ssh_path(v['value'])
            except ValueError as error: return str(error)
    elif key == 'upstream_url':
        fields=[]
        note=tr('选择中继时，地址必须指向已存在的中继服务及其 HTTPS 端口。请避免转发环路。')
    elif key.startswith('area:'):
        r = self.demo.find('regions', key[5:])
        if page == 'sites':
            fields=[]  # ServiceForm renders the grouped policy controls.
        else:
            a = deepcopy(obj.areas.get(r.id, Listen()))
            fields = [Field('enabled', tr('启用此区域'), a.enabled, boolean=True), Field('ips', tr('绑定地址'), '\n'.join(a.ips), multiline=True)]
            for i,(title,default,value) in enumerate(zip(('HTTP',*PORTS),('80','443','8443'),a.ports)):
                fields.extend([Field(f'override{i}',tr('覆盖 {0} 端口（默认 {1}）',title,default),value!=default,boolean=True),
                               Field(f'port{i}',title+tr(' 端口'),value)])
            note = tr('每行一个 IP，共用下面的一组端口。0.0.0.0 监听全部 IPv4，:: 监听全部 IPv6。')
            def candidate(v):
                addresses = binding_addresses(v['ips'].splitlines()) if v['enabled'] else [ip.strip() for ip in v['ips'].splitlines() if ip.strip()]
                return Listen(v['enabled'], addresses,
                              [v[f'port{i}'] if v[f'override{i}'] else default for i,default in ((0,'80'),(1,'443'),(2,'8443'))])
            def validator(v):
                try: area = candidate(v)
                except ValueError as error: return str(error)
                config = deepcopy(self.demo.config)
                node=config.find('nodes',obj.id)
                node.areas[r.id]=area
                errors=configuration_errors(config)
                problems=errors.get(('nodes',obj.id,key),[])
                return '\n'.join(problems) or None
    elif page == 'sites' and key == 'source':
        fields=[Field('value',tr('源地址'),obj.source),
                Field('verify',tr('校验 HTTPS 源证书'),obj.verify_origin_https,boolean=True)]
    elif key == 'tls_source':
        fields = [Field('value', tr('TLS 来源'), obj.tls_source, labeled_options(('private_ca','public_ca')),radio=True)]
        note = tr('公共证书来自 TLS证书页面。')
    elif key == 'mtls':
        fields=[Field('value',tr('mTLS 验证'),obj.mtls,boolean=True)]
    elif key == 'enabled':
        fields = [Field('value', tr('Client 状态'), obj.enabled, [(tr('启用'), True), (tr('禁用'), False)])]
    elif key == 'expiry':
        self.show_info(obj.name + tr(' / 有效期'), tr('有效期至 2099-12-31。'))
        return
    else:
        fields = [Field('value', {'domain':tr('服务域名'),'source':tr('源地址')}.get(key, tr('端口') if key.startswith('p') else tr('值')), self.cell_value(obj, key) if self.cell_value(obj, key) != tr('未填写') else '')]
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
                obj.areas[key[5:]] = candidate(v)
            else:
                obj.areas[key[5:]] = Service(v['enabled'],v['tls_source'] if v['custom'] else None,v['mtls'] if v['custom'] else None)
        elif page == 'sites' and key == 'source':
            obj.source,obj.verify_origin_https=v['value'],v['verify']
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
    if page=='sites' and key.startswith('area:'):
        from .service_form import ServiceForm
        form=ServiceForm(title,obj,r,note)
    elif key=='upstream_url':
        from .upstream_form import UpstreamForm
        form=UpstreamForm(title,obj.upstream_url,note)
    else:form = Form(title, fields, validator, note)
    if key == 'ssh_hops': form.add_class('ssh-path-dialog')
    self.push_screen(form, saved)

