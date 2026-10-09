"""Serializable configuration values. Invalid drafts are intentionally representable."""
from dataclasses import asdict, dataclass, field
from ipaddress import ip_address
from urllib.parse import urlsplit
import re

MODES = ('不提供服务', 'HTTP', 'HTTPS', 'HTTPS + mTLS')
PORTS = ('HTTP', 'HTTPS', '中继 HTTPS')
PLATFORMS = ('Debian 13', 'OpenWrt 25.12')
ARCHES = ('amd64', 'arm64', 'armv7', '386')

@dataclass
class Region:
    id: str
    name: str
    ports: list[str] = field(default_factory=lambda: ['80', '443', '8443'])

@dataclass
class Listen:
    enabled: bool = False
    ip: str = ''
    overrides: list[str | None] = field(default_factory=lambda: [None, None, None])

@dataclass
class Node:
    id: str
    name: str
    mode: str = '直连源头'
    upstream: tuple[str, str] | None = None
    areas: dict[str, Listen] = field(default_factory=dict)
    platform: str = ''
    arch: str = ''
    ssh_ip: str = ''

@dataclass
class Site:
    id: str
    name: str
    domain: str = ''
    source: str = ''
    areas: dict[str, str] = field(default_factory=dict)
    tls_source: str = '私有 CA'

@dataclass
class Configuration:
    regions: list[Region] = field(default_factory=list)
    nodes: list[Node] = field(default_factory=list)
    sites: list[Site] = field(default_factory=list)
    revision: int = 0
    verify_origin_https: bool = True

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, value):
        required = {'regions', 'nodes', 'sites', 'revision', 'verify_origin_https'}
        if set(value) != required:
            raise ValueError('配置格式不受支持')
        if type(value['verify_origin_https']) is not bool:
            raise ValueError('源头 HTTPS 校验设置必须为布尔值')
        nodes = []
        for original in value['nodes']:
            n = dict(original)
            n['areas'] = {k: Listen(**v) for k, v in n['areas'].items()}
            if n['upstream'] is not None: n['upstream'] = tuple(n['upstream'])
            nodes.append(Node(**n))
        return cls([Region(**r) for r in value['regions']], nodes,
                   [Site(**s) for s in value['sites']], value['revision'], value['verify_origin_https'])

    def find(self, collection, identity):
        return next((x for x in getattr(self, collection) if x.id == identity), None)


def valid_port(value):
    return isinstance(value, str) and value.isascii() and value.isdigit() and 1 <= int(value) <= 65535


def canonical_domain(value):
    try:
        domain = value.rstrip('.').encode('idna').decode('ascii').lower()
        if not domain or len(domain) > 253 or any(not re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?', x) for x in domain.split('.')):
            raise ValueError()
        return domain
    except (UnicodeError, ValueError):
        raise ValueError('请输入有效域名，不含协议、端口或路径') from None


def domain_key(value):
    try:return canonical_domain(value)
    except ValueError:return value.rstrip('.').casefold()


def duplicate_domain(sites, value, identity=None):
    return bool(value) and any(s.id != identity and s.domain and domain_key(s.domain)==domain_key(value) for s in sites)


def validate_uniqueness(config):
    if type(config.verify_origin_https) is not bool:
        raise ValueError('源头 HTTPS 校验设置必须为布尔值')
    identities = set()
    for collection in ('regions', 'nodes', 'sites'):
        names = set()
        for obj in getattr(config, collection):
            name = obj.name.strip().casefold()
            if not name: raise ValueError('名称不能为空')
            if name in names: raise ValueError('名称已存在：' + obj.name)
            if not re.fullmatch(r'[a-f0-9]{32}', obj.id) or obj.id in identities: raise ValueError('对象身份重复或为空')
            names.add(name); identities.add(obj.id)
    domains = set()
    for site in config.sites:
        if not site.domain: continue
        domain = domain_key(site.domain)
        if domain in domains: raise ValueError('域名已存在：' + site.domain)
        domains.add(domain)


def configuration_errors(config):
    errors = {}
    def add(page, obj, field, message):
        errors.setdefault((page, obj.id, field), []).append(message)
    for region in config.regions:
        if len(region.ports) != 3:
            add('regions', region, 'p0', '必须提供三个默认端口'); continue
        for i, port in enumerate(region.ports):
            if not valid_port(port): add('regions', region, f'p{i}', '端口必须是 1–65535 的整数')
    region_ids = {r.id for r in config.regions}
    for node in config.nodes:
        if node.platform not in PLATFORMS: add('nodes', node, 'platform', '请选择目标平台')
        if node.arch not in ARCHES: add('nodes', node, 'arch', '请选择 CPU 架构')
        if node.mode not in ('直连源头', '经上游转发'): add('nodes', node, 'upstream', '转发方式无效')
        if node.mode == '经上游转发':
            parent = config.find('nodes', node.upstream[0]) if node.upstream and len(node.upstream) == 2 else None
            region = config.find('regions', node.upstream[1]) if parent else None
            if not parent or not region: add('nodes', node, 'upstream', '上游引用缺失，请重新选择')
            elif not parent.areas.get(region.id, Listen()).enabled: add('nodes', node, 'upstream', '上游区域未启用')
            seen = {node.id}; cursor = node
            while cursor and cursor.mode == '经上游转发' and cursor.upstream:
                cursor = config.find('nodes', cursor.upstream[0])
                if cursor:
                    if cursor.id in seen:
                        add('nodes', node, 'upstream', '上游路径存在循环'); break
                    seen.add(cursor.id)
        used = {}
        for rid, area in node.areas.items():
            col = 'area:' + rid
            if rid not in region_ids:
                add('nodes', node, col, '区域引用不存在'); continue
            if not area.enabled: continue
            try:
                address = ip_address(area.ip)
                if address.is_unspecified: raise ValueError()
                address = str(address)
            except ValueError:
                add('nodes', node, col, '必须填写具体 IP，禁止通配地址'); address = area.ip
            region = config.find('regions', rid)
            if len(area.overrides) != 3 or len(region.ports) != 3:
                add('nodes', node, col, '端口配置数量无效'); continue
            for i, override in enumerate(area.overrides):
                port = region.ports[i] if override is None else override
                if not valid_port(port): add('nodes', node, col, PORTS[i] + ' 端口无效'); continue
                endpoint = address, int(port)
                if endpoint in used:
                    message = f'监听冲突：{address}:{port}'
                    add('nodes', node, col, message)
                    if used[endpoint] != col: add('nodes', node, used[endpoint], message)
                used[endpoint] = col
    for site in config.sites:
        try: canonical_domain(site.domain)
        except ValueError as e: add('sites', site, 'domain', str(e))
        try:
            url = urlsplit(site.source)
            if url.scheme not in ('http', 'https') or not url.hostname or url.path or url.username is not None or '?' in site.source or '#' in site.source:
                raise ValueError()
            if url.port is not None and not 1 <= url.port <= 65535: raise ValueError()
        except ValueError: add('sites', site, 'source', '源头须为 http/https 地址，可带端口，不带路径或凭据')
        for rid, mode in site.areas.items():
            if rid not in region_ids or mode not in MODES: add('sites', site, 'area:' + rid, '区域服务原则无效')
    return errors


def ssh_route(config, node_id):
    path = []; seen = set(); node = config.find('nodes', node_id)
    if node is None: raise ValueError('发布对应节点已删除')
    while node:
        if node.id in seen: raise ValueError('SSH 路径存在循环')
        seen.add(node.id)
        try:
            if ip_address(node.ssh_ip).is_unspecified: raise ValueError()
        except ValueError: raise ValueError(node.name + ' 的 SSH IP 无效') from None
        path.append(node)
        if node.mode == '直连源头': break
        if not node.upstream: raise ValueError('SSH 上游未配置')
        node = config.find('nodes', node.upstream[0])
        if node is None: raise ValueError('SSH 上游已删除')
    return list(reversed(path))


def check_node_parent(config, identity, parent):
    seen={identity}
    while parent:
        if parent in seen: raise ValueError('上游路径存在循环')
        seen.add(parent)
        node=config.find('nodes',parent)
        if node is None: break
        parent=node.upstream[0] if node.upstream else None


def node_tree(nodes):
    """Stable preorder, retaining orphaned and invalid nodes for repair."""
    ids={node.id for node in nodes};children={}
    for node in nodes:
        parent=node.upstream[0] if node.upstream else None
        children.setdefault(parent if parent in ids else None,[]).append(node)
    result=[];seen=set()
    def visit(node,label,indent):
        if node.id in seen:return
        seen.add(node.id);result.append((node,label))
        group=children.get(node.id,[])
        for i,child in enumerate(group):
            last=i==len(group)-1
            visit(child,indent+('└─ ' if last else '├─ '),indent+('   ' if last else '│  '))
    for node in children.get(None,[]):visit(node,'','')
    for node in nodes:
        if node.id not in seen:visit(node,'','')
    return result
