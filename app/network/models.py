"""Serializable configuration values. Invalid drafts are intentionally representable."""
from ..i18n import tr
from dataclasses import asdict, dataclass, field
from ipaddress import ip_address
from urllib.parse import urlsplit
import re
import hashlib
import json

MODES = ('disabled', 'https')
PORTS = ('HTTPS', tr('中继 HTTPS'))
PLATFORMS = ('debian_13', 'openwrt_25_12')
ARCHES = ('amd64', 'arm64', 'armv7', '386')
RELAY_SERVER_NAME = 'relay.smooth-caddy.internal'
TLS_SOURCES = ('private_ca', 'public_ca')

@dataclass
class Region:
    id: str
    name: str
    tls_source: str = 'private_ca'
    mtls: bool = False

@dataclass
class Listen:
    enabled: bool = False
    ips: list[str] = field(default_factory=list)
    ports: list[str] = field(default_factory=lambda: ['80', '443', '8443'])
    relay_enabled: bool = False

@dataclass
class Node:
    id: str
    name: str
    upstream_url: str = ''
    areas: dict[str, Listen] = field(default_factory=dict)
    platform: str = ''
    arch: str = ''
    ssh_hops: list[list[str]] = field(default_factory=list)

@dataclass
class Service:
    enabled: bool = False
    tls_source: str | None = None
    mtls: bool | None = None

@dataclass
class Site:
    id: str
    name: str
    domain: str = ''
    source: str = ''
    areas: dict[str, Service] = field(default_factory=dict)
    verify_origin_https: bool = False
    homepage_redirect: str = ''
    allowed_paths: list[str] = field(default_factory=list)

@dataclass
class Configuration:
    regions: list[Region] = field(default_factory=list)
    nodes: list[Node] = field(default_factory=list)
    sites: list[Site] = field(default_factory=list)
    revision: int = 0

    def to_dict(self):
        validate_enum_values(self)
        return asdict(self)

    @classmethod
    def from_dict(cls, value):
        required = {'regions', 'nodes', 'sites', 'revision'}
        if set(value) != required:
            raise ValueError(tr('配置格式不受支持'))
        if any(not {'verify_origin_https','homepage_redirect','allowed_paths'}.issubset(site) for site in value['sites']):
            raise ValueError(tr('配置格式不受支持'))
        nodes = []
        for original in value['nodes']:
            n = dict(original)
            if 'ssh_hops' not in n or 'upstream_url' not in n or any(key in n for key in ('ssh_ip', 'mode', 'upstream')):
                raise ValueError(tr('配置格式不受支持'))
            if any('ip' in v or 'ips' not in v or 'relay_enabled' not in v for v in n['areas'].values()):
                raise ValueError(tr('配置格式不受支持'))
            n['areas'] = {k: Listen(**v) for k, v in n['areas'].items()}
            nodes.append(Node(**n))
        config = cls([Region(**r) for r in value['regions']], nodes,
                     [Site(**{**s,'areas':{rid:Service(**area) for rid,area in s['areas'].items()}}) for s in value['sites']], value['revision'])
        validate_enum_values(config)
        return config

    def find(self, collection, identity):
        return next((x for x in getattr(self, collection) if x.id == identity), None)


def validate_enum_values(config):
    for region in config.regions:
        if region.tls_source not in TLS_SOURCES or type(region.mtls) is not bool:
            raise ValueError(tr('区域服务原则无效'))
    for node in config.nodes:
        for area in node.areas.values():
            if type(area.enabled) is not bool or type(area.relay_enabled) is not bool or not isinstance(area.ips,list) or any(not isinstance(ip,str) for ip in area.ips):
                raise ValueError(tr('绑定地址必须为 IP 列表'))
            if not isinstance(area.ports,list) or len(area.ports)!=3 or any(not isinstance(p,str) for p in area.ports):
                raise ValueError(tr('端口配置数量无效'))
        if not isinstance(node.ssh_hops,list) or any(not isinstance(hop,list) or len(hop)!=1 or not isinstance(hop[0],str) for hop in node.ssh_hops):
            raise ValueError(tr('SSH 每一跳必须恰好包含一个 IP'))
        if not isinstance(node.upstream_url,str) or node.platform not in ('',*PLATFORMS):
            raise ValueError(tr('节点配置标识不受支持'))
    for site in config.sites:
        if not isinstance(site.homepage_redirect,str) or not isinstance(site.allowed_paths,list) or any(not isinstance(p,str) for p in site.allowed_paths):
            raise ValueError(tr('路径配置格式无效'))
        if type(site.verify_origin_https) is not bool:
            raise ValueError(tr('源头 HTTPS 校验设置必须为布尔值'))
        for service in site.areas.values():
            if not isinstance(service,Service) or type(service.enabled) is not bool or service.tls_source not in (None,*TLS_SOURCES) or (service.mtls is not None and type(service.mtls) is not bool):
                raise ValueError(tr('站点配置标识不受支持'))


def validate_site_paths(redirect, paths):
    def valid(path):
        return (path.startswith('/') and not path.startswith('//') and '//' not in path
                and not any(c.isspace() or ord(c)<32 or ord(c)==127 or c in "\\?#%*[]{}" for c in path)
                and not any(part in ('.','..') for part in path.split('/')))
    if redirect and (not valid(redirect) or redirect=='/'):
        raise ValueError(tr('首页跳转须为本站非根路径，如 /ui/，不含查询参数'))
    if any(not valid(path) for path in paths):
        raise ValueError(tr('允许访问路径须为目录路径，每行一条，如 /s/，不支持通配符或查询参数'))
    if redirect and paths and not any(path=='/' or redirect==path.rstrip('/') or redirect.startswith(path.rstrip('/')+'/') for path in paths):
        raise ValueError(tr('首页跳转目标必须在允许访问路径内'))


def service_policy(site, region):
    value=site.areas.get(region.id,Service())
    return Service(value.enabled,value.tls_source if value.tls_source is not None else region.tls_source,
                   value.mtls if value.mtls is not None else region.mtls)


def public_sites(config):
    return [site for site in config.sites if any(service_policy(site,r).enabled and service_policy(site,r).tls_source=='public_ca' for r in config.regions)]


def valid_port(value):
    return isinstance(value, str) and value.isascii() and value.isdigit() and 1 <= int(value) <= 65535


def canonical_domain(value):
    try:
        domain = value.rstrip('.').encode('idna').decode('ascii').lower()
        if not domain or len(domain) > 253 or any(not re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?', x) for x in domain.split('.')):
            raise ValueError()
        return domain
    except (UnicodeError, ValueError):
        raise ValueError(tr('请输入有效域名，不含协议、端口或路径')) from None


def domain_key(value):
    try:return canonical_domain(value)
    except ValueError:return value.rstrip('.').casefold()


def duplicate_domain(sites, value, identity=None):
    return bool(value) and any(s.id != identity and s.domain and domain_key(s.domain)==domain_key(value) for s in sites)


def validate_uniqueness(config):
    identities = set()
    for collection in ('regions', 'nodes', 'sites'):
        names = set()
        for obj in getattr(config, collection):
            name = obj.name.strip().casefold()
            if not name: raise ValueError(tr('名称不能为空'))
            if name in names: raise ValueError(tr('名称已存在：') + obj.name)
            if not re.fullmatch(r'[a-f0-9]{32}', obj.id) or obj.id in identities: raise ValueError(tr('对象身份重复或为空'))
            names.add(name); identities.add(obj.id)
    domains = set()
    for site in config.sites:
        if not site.domain: continue
        domain = domain_key(site.domain)
        if domain in domains: raise ValueError(tr('域名已存在：') + site.domain)
        domains.add(domain)


def configuration_errors(config):
    errors = {}
    def add(page, obj, field, message):
        errors.setdefault((page, obj.id, field), []).append(message)
    region_ids = {r.id for r in config.regions}
    for node in config.nodes:
        try: ssh_addresses(node.ssh_hops)
        except ValueError as error: add('nodes', node, 'ssh_hops', str(error))
        if node.platform not in PLATFORMS: add('nodes', node, 'platform', tr('请选择目标平台'))
        if node.arch not in ARCHES: add('nodes', node, 'arch', tr('请选择 CPU 架构'))
        if node.upstream_url:
            try: relay_endpoint(node.upstream_url)
            except ValueError as error: add('nodes', node, 'upstream_url', str(error))
        used = []
        for rid, area in node.areas.items():
            col = 'area:' + rid
            if rid not in region_ids:
                add('nodes', node, col, tr('区域引用不存在')); continue
            if not area.enabled: continue
            try:
                addresses = [ip_address(ip) for ip in binding_addresses(area.ips)]
            except ValueError as error:
                add('nodes', node, col, str(error)); addresses = []
            region = config.find('regions', rid)
            if len(area.ports) != 3:
                add('nodes', node, col, tr('端口配置数量无效')); continue
            if not valid_port(area.ports[0]):add('nodes',node,col,tr('HTTP 跳转端口无效'))
            for i, port in enumerate(area.ports[1:]):
                if i==1 and not area.relay_enabled:continue
                if not valid_port(port): add('nodes', node, col, PORTS[i] + tr(' 端口无效')); continue
                for address in addresses:
                    for other, other_port, other_region, other_kind in used:
                        if int(port) != other_port or address.version != other.version: continue
                        if address != other and not address.is_unspecified and not other.is_unspecified: continue
                        endpoint = lambda ip, p: f'[{ip}]:{p}' if ip.version == 6 else f'{ip}:{p}'
                        message = tr('{0} {1}（{2}）与{3} {4}（{5}）监听冲突，请修改绑定地址或端口',
                                     other_region.name, PORTS[other_kind], endpoint(other, other_port),
                                     region.name, PORTS[i], endpoint(address, int(port)))
                        add('nodes', node, col, message)
                        if other_region.id != rid: add('nodes', node, 'area:' + other_region.id, message)
                    used.append((address, int(port), region, i))
    for site in config.sites:
        try: canonical_domain(site.domain)
        except ValueError as e: add('sites', site, 'domain', str(e))
        try:
            url = urlsplit(site.source)
            if url.scheme not in ('http', 'https') or not url.hostname or url.path or url.username is not None or '?' in site.source or '#' in site.source:
                raise ValueError()
            if url.port is not None and not 1 <= url.port <= 65535: raise ValueError()
        except ValueError: add('sites', site, 'source', tr('源头须为 http/https 地址，可带端口，不带路径或凭据'))
        try: validate_site_paths(site.homepage_redirect,site.allowed_paths)
        except ValueError as e: add('sites',site,'source',str(e))
        for rid, mode in site.areas.items():
            if rid not in region_ids: add('sites', site, 'area:' + rid, tr('区域服务原则无效'))
    for node in config.nodes:
        try: http_bindings(config,node)
        except ValueError as error:
            for rid,area in node.areas.items():
                if area.enabled:add('nodes',node,'area:'+rid,str(error))
        for rid,area in node.areas.items():
            if not area.enabled or not valid_port(area.ports[0]):continue
            try:hosts=[ip_address(ip) for ip in binding_addresses(area.ips)]
            except ValueError:continue
            for other_id,other in node.areas.items():
                if not other.enabled or not any(valid_port(p) and int(p)==int(area.ports[0]) for p in other.ports[1:(3 if other.relay_enabled else 2)]):continue
                try:others=[ip_address(ip) for ip in binding_addresses(other.ips)]
                except ValueError:continue
                if any(a.version==b.version and (a==b or a.is_unspecified or b.is_unspecified) for a in hosts for b in others):
                    for identity in dict.fromkeys((rid,other_id)):
                        add('nodes',node,'area:'+identity,tr('HTTP 跳转端口与 HTTPS 或中继端口冲突'))
    return errors


def http_bindings(config, node):
    """Merge overlapping listeners per family, keeping per-address redirect routes."""
    entries=[]
    for region in config.regions:
        area=node.areas.get(region.id,Listen())
        if not area.enabled:continue
        try: hosts=binding_addresses(area.ips)
        except ValueError:continue  # The area validator reports malformed drafts.
        routes={canonical_domain(site.domain):area.ports[1] for site in config.sites if service_policy(site,region).enabled}
        entries.extend((ip_address(host),routes,area.ports[0]) for host in hosts)
    groups=[]
    for http_port,family in dict.fromkeys((p,ip.version) for ip,_,p in entries):
        members=[(ip,routes) for ip,routes,p in entries if ip.version==family and p==http_port]
        wildcard=next((ip for ip,_ in members if ip.is_unspecified),None)
        hosts=[wildcard] if wildcard else list(dict.fromkeys(ip for ip,_ in members))
        for host in hosts:
            routes={}
            for ip,targets in members:
                if not host.is_unspecified and ip!=host:continue
                for domain,port in targets.items():
                    key=(str(ip),domain)
                    # A wildcard overlaps each concrete address; distinct concrete IPs do not.
                    for (other,name),target in routes.items():
                        if name==domain and (ip.is_unspecified or ip_address(other).is_unspecified or other==str(ip)) and (int(target) if valid_port(target) else target)!=(int(port) if valid_port(port) else port):
                            raise ValueError(tr('HTTP 跳转目标不唯一：')+domain)
                    routes[key]=port
            groups.append((str(host),http_port,routes))
    return groups


def binding_addresses(values, *, allow_empty=False):
    result = []
    for line, value in enumerate(values, 1):
        value = value.strip()
        if not value: continue
        try:
            address = ip_address(value)
            if address.is_multicast or '%' in value: raise ValueError()
            if address.version == 6 and address.ipv4_mapped is not None:
                address = address.ipv4_mapped
            if address.is_multicast: raise ValueError()
        except ValueError:
            raise ValueError(tr('第 {0} 行不是有效的绑定 IP 地址', line)) from None
        canonical = str(address)
        if canonical not in result: result.append(canonical)
    if not result and not allow_empty: raise ValueError(tr('启用区域时至少填写一个绑定地址'))
    return result


def ssh_ip(value):
    address = ip_address(value)
    if address.is_unspecified or address.is_multicast or '%' in value:
        raise ValueError()
    return str(address)


def parse_ssh_path(text):
    hops = []
    for line, value in enumerate(text.splitlines(), 1):
        value = value.strip()
        if not value: continue
        try: hops.append([ssh_ip(value)])
        except ValueError:
            raise ValueError(tr('第 {0} 行不是有效的 SSH IP 地址', line)) from None
    if not hops: raise ValueError(tr('SSH 路径不能为空'))
    return hops


def ssh_addresses(hops):
    if not hops: raise ValueError(tr('SSH 路径不能为空'))
    result = []
    for index, hop in enumerate(hops, 1):
        if not isinstance(hop, list) or len(hop) != 1 or not isinstance(hop[0], str):
            raise ValueError(tr('SSH 每一跳必须恰好包含一个 IP'))
        try: result.append(ssh_ip(hop[0]))
        except ValueError:
            raise ValueError(tr('第 {0} 行不是有效的 SSH IP 地址', index)) from None
    return result


@dataclass(frozen=True)
class SSHHop:
    id: str
    name: str
    address: str
    trust_id: str


def ssh_route(config, node_id):
    node = config.find('nodes', node_id)
    if node is None: raise ValueError(tr('发布对应节点已删除'))
    addresses = ssh_addresses(node.ssh_hops)
    result = []
    for index, address in enumerate(addresses):
        # Same private IP behind different jump hosts is a different SSH identity.
        prefix = json.dumps(addresses[:index+1], separators=(',', ':')).encode()
        result.append(SSHHop(node.id, node.name + (tr(' / SSH 第 {0} 跳', index+1) if index < len(addresses)-1 else ''), address,
                             hashlib.sha256(prefix).hexdigest()))
    return result


def relay_endpoint(value):
    """Return the dial address, independently of the fixed relay TLS identity."""
    try:
        if not isinstance(value, str) or any(c.isspace() or ord(c) < 32 for c in value): raise ValueError()
        url = urlsplit(value)
        if url.scheme != 'https' or not url.hostname or url.username is not None or url.password is not None:
            raise ValueError()
        if url.path not in ('', '/') or '?' in value or '#' in value or '%' in url.hostname or '\\' in value:
            raise ValueError()
        if url.netloc.endswith(':'): raise ValueError()
        port = url.port if url.port is not None else 443
        if not 1 <= port <= 65535: raise ValueError()
        try:
            ip = ip_address(url.hostname)
        except ValueError:
            if ':' in url.hostname or all(c in '0123456789.' for c in url.hostname): raise ValueError()
            host = canonical_domain(url.hostname)
        else:
            if ip.is_unspecified or ip.is_multicast: raise ValueError()
            host = str(ip)
        return host, port
    except (ValueError, TypeError):
        raise ValueError(tr('上游地址须为 HTTPS 地址，可带端口，不带路径、凭据或查询参数')) from None
