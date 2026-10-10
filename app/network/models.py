"""Serializable configuration values. Invalid drafts are intentionally representable."""
from ..i18n import tr
from dataclasses import asdict, dataclass, field
from ipaddress import ip_address
from urllib.parse import urlsplit
import re
import hashlib
import json

MODES = ('disabled', 'http', 'https', 'https_mtls')
PORTS = ('HTTP', 'HTTPS', tr('中继 HTTPS'))
PLATFORMS = ('debian_13', 'openwrt_25_12')
ARCHES = ('amd64', 'arm64', 'armv7', '386')
RELAY_SERVER_NAME = 'relay.smooth-caddy.internal'
TLS_SOURCES = ('private_ca', 'public_ca')

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
    upstream_url: str = ''
    areas: dict[str, Listen] = field(default_factory=dict)
    platform: str = ''
    arch: str = ''
    ssh_hops: list[list[str]] = field(default_factory=list)

@dataclass
class Site:
    id: str
    name: str
    domain: str = ''
    source: str = ''
    areas: dict[str, str] = field(default_factory=dict)
    tls_source: str = 'private_ca'

@dataclass
class Configuration:
    regions: list[Region] = field(default_factory=list)
    nodes: list[Node] = field(default_factory=list)
    sites: list[Site] = field(default_factory=list)
    revision: int = 0
    verify_origin_https: bool = True

    def to_dict(self):
        validate_enum_values(self)
        return asdict(self)

    @classmethod
    def from_dict(cls, value):
        required = {'regions', 'nodes', 'sites', 'revision', 'verify_origin_https'}
        if set(value) != required:
            raise ValueError(tr('配置格式不受支持'))
        if type(value['verify_origin_https']) is not bool:
            raise ValueError(tr('源头 HTTPS 校验设置必须为布尔值'))
        nodes = []
        for original in value['nodes']:
            n = dict(original)
            if 'ssh_hops' not in n or 'upstream_url' not in n or any(key in n for key in ('ssh_ip', 'mode', 'upstream')):
                raise ValueError(tr('配置格式不受支持'))
            n['areas'] = {k: Listen(**v) for k, v in n['areas'].items()}
            nodes.append(Node(**n))
        config = cls([Region(**r) for r in value['regions']], nodes,
                     [Site(**s) for s in value['sites']], value['revision'], value['verify_origin_https'])
        validate_enum_values(config)
        return config

    def find(self, collection, identity):
        return next((x for x in getattr(self, collection) if x.id == identity), None)


def validate_enum_values(config):
    """Unknown protocol values are not editable drafts or translated labels."""
    for node in config.nodes:
        if not isinstance(node.ssh_hops, list) or any(not isinstance(hop, list) or len(hop) != 1 or not isinstance(hop[0], str) for hop in node.ssh_hops):
            raise ValueError(tr('SSH 每一跳必须恰好包含一个 IP'))
        if not isinstance(node.upstream_url, str) or node.platform not in ('', *PLATFORMS):
            raise ValueError(tr('节点配置标识不受支持'))
    for site in config.sites:
        if site.tls_source not in TLS_SOURCES or any(mode not in MODES for mode in site.areas.values()):
            raise ValueError(tr('站点配置标识不受支持'))


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
    if type(config.verify_origin_https) is not bool:
        raise ValueError(tr('源头 HTTPS 校验设置必须为布尔值'))
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
    for region in config.regions:
        if len(region.ports) != 3:
            add('regions', region, 'p0', tr('必须提供三个默认端口')); continue
        for i, port in enumerate(region.ports):
            if not valid_port(port): add('regions', region, f'p{i}', tr('端口必须是 1–65535 的整数'))
    region_ids = {r.id for r in config.regions}
    for node in config.nodes:
        try: ssh_addresses(node.ssh_hops)
        except ValueError as error: add('nodes', node, 'ssh_hops', str(error))
        if node.platform not in PLATFORMS: add('nodes', node, 'platform', tr('请选择目标平台'))
        if node.arch not in ARCHES: add('nodes', node, 'arch', tr('请选择 CPU 架构'))
        if node.upstream_url:
            try: relay_endpoint(node.upstream_url)
            except ValueError as error: add('nodes', node, 'upstream_url', str(error))
        used = {}
        for rid, area in node.areas.items():
            col = 'area:' + rid
            if rid not in region_ids:
                add('nodes', node, col, tr('区域引用不存在')); continue
            if not area.enabled: continue
            try:
                address = ip_address(area.ip)
                if address.is_unspecified: raise ValueError()
                address = str(address)
            except ValueError:
                add('nodes', node, col, tr('必须填写具体 IP，禁止通配地址')); address = area.ip
            region = config.find('regions', rid)
            if len(area.overrides) != 3 or len(region.ports) != 3:
                add('nodes', node, col, tr('端口配置数量无效')); continue
            for i, override in enumerate(area.overrides):
                port = region.ports[i] if override is None else override
                if not valid_port(port): add('nodes', node, col, PORTS[i] + tr(' 端口无效')); continue
                endpoint = address, int(port)
                if endpoint in used:
                    message = tr('监听冲突：{0}:{1}', address, port)
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
        except ValueError: add('sites', site, 'source', tr('源头须为 http/https 地址，可带端口，不带路径或凭据'))
        for rid, mode in site.areas.items():
            if rid not in region_ids or mode not in MODES: add('sites', site, 'area:' + rid, tr('区域服务原则无效'))
    return errors


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
