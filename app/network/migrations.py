"""Versioned decoding and transactional database migration, never UI translation."""
from ..i18n import tr
from copy import deepcopy
import json
import os
from pathlib import Path
import sqlite3
from uuid import uuid4
from .models import Configuration

DATABASE_VERSION = 10


def legacy_configuration(value):
    """Decode database v2 / batch metadata v1 without modifying the input."""
    value = deepcopy(value)
    modes = {'直连源头': 'direct', '经上游转发': 'via_upstream'}
    platforms = {'': '', 'Debian 13': 'debian_13', 'OpenWrt 25.12': 'openwrt_25_12'}
    sources = {'私有 CA': 'private_ca', '公共 CA': 'public_ca'}
    services = {'不提供服务': 'disabled', 'HTTP': 'http', 'HTTPS': 'https', 'HTTPS + mTLS': 'https_mtls'}
    try:
        for node in value['nodes']:
            node['mode'] = modes[node['mode']]
            node['platform'] = platforms[node['platform']]
        for site in value['sites']:
            site['tls_source'] = sources[site['tls_source']]
            site['areas'] = {key: services[mode] for key, mode in site['areas'].items()}
        return configuration_v3(value)
    except (KeyError, TypeError) as error:
        raise ValueError(tr('旧配置格式或枚举值不受支持，未转换数据')) from error


def configuration_v3(value):
    """Expand the old business-derived SSH route; never keep a partial route."""
    value = deepcopy(value)
    nodes = {node['id']: node for node in value['nodes']}
    paths = {}
    from .models import ssh_ip
    for node in value['nodes']:
        path = []; seen = set(); current = node
        try:
            while current is not None:
                if current['id'] in seen: raise ValueError()
                seen.add(current['id'])
                path.append([ssh_ip(current['ssh_ip'])])
                if current['mode'] == 'direct': break
                if current['mode'] != 'via_upstream': raise ValueError()
                current = nodes[current['upstream'][0]]
            paths[node['id']] = list(reversed(path))
        except (KeyError, TypeError, ValueError, IndexError):
            paths[node['id']] = []
    for node in value['nodes']:
        node.pop('ssh_ip', None)
        node['ssh_hops'] = paths[node['id']]
    return configuration_v4(value)


def configuration_v4(value):
    """Resolve former node/region references once; broken references stay invalid."""
    value = deepcopy(value)
    nodes = {n['id']: n for n in value['nodes']}
    regions = {r['id']: r for r in value['regions']}
    urls = {}
    from .models import relay_endpoint
    for node in value['nodes']:
        mode = node['mode']
        if mode == 'direct':
            urls[node['id']] = ''
        elif mode == 'via_upstream':
            try:
                parent_id, region_id = node['upstream']
                area = nodes[parent_id]['areas'][region_id]
                if not area['enabled']: raise ValueError()
                host = area['ip']
                port = area['overrides'][2] if area['overrides'][2] is not None else regions[region_id]['ports'][2]
                url = 'https://' + ('['+host+']' if ':' in host else host) + ':' + port
                relay_endpoint(url)
                urls[node['id']] = url
            except (KeyError, ValueError, TypeError, IndexError):
                # Empty means direct-to-origin, so never use it for a broken relay.
                urls[node['id']] = 'https://'
        else:
            raise ValueError(tr('节点配置标识不受支持'))
    for node in value['nodes']:
        node.pop('mode');node.pop('upstream')
        node['upstream_url'] = urls[node['id']]
    return configuration_v5(value)


def configuration_v5(value):
    """Expand single bind IPs while preserving historical invalid drafts."""
    value = deepcopy(value)
    for node in value['nodes']:
        for area in node['areas'].values():
            ip = area.pop('ip')
            area['ips'] = [ip] if ip else []
    return configuration_v7(value)


def configuration_v7(value):
    """Resolve former ports and copy old service choices into explicit policies."""
    value=deepcopy(value)
    regions={r["id"]:r for r in value["regions"]}
    for node in value["nodes"]:
        for rid,area in node["areas"].items():
            defaults=regions.get(rid,{}).get("ports",["80","443","8443"])
            ports=[p if p is not None else defaults[i] for i,p in enumerate(area.pop("overrides"))]
            area["ports"]=ports
    for site in value["sites"]:
        source=site.pop("tls_source")
        if source not in ("private_ca","public_ca") or any(mode not in ("disabled","http","https","https_mtls") for mode in site["areas"].values()):raise ValueError(tr("站点配置标识不受支持"))
        site["areas"]={rid:{"enabled":mode!="disabled","tls_source":"private_ca" if mode=="http" else source,"mtls":mode=="https_mtls"} for rid,mode in site["areas"].items()}
    for region in value["regions"]:
        region.pop("ports")
        region.update(tls_source="private_ca",mtls=False)
    return configuration_v9(value)


def configuration_v8(value):
    value=deepcopy(value)
    for node in value["nodes"]:
        port=node.pop("http_port")
        for area in node["areas"].values():area["ports"]=[port,*area["ports"]]
    return configuration_v9(value)


def configuration_v9(value):
    """Preserve the global origin verification choice on each existing site."""
    value=deepcopy(value)
    verify=value.pop('verify_origin_https')
    if type(verify) is not bool:
        raise ValueError(tr('源头 HTTPS 校验设置必须为布尔值'))
    for site in value['sites']:
        if 'verify_origin_https' in site:raise ValueError(tr('配置格式不受支持'))
        site['verify_origin_https']=verify
    return Configuration.from_dict(value)


def migrate_database(db, path, version):
    """Caller holds BEGIN IMMEDIATE; back up committed state before any writes."""
    row = db.execute('SELECT revision, payload FROM configuration WHERE id=1').fetchone()
    if row is None:
        raise ValueError(tr('旧数据库缺少配置记录'))
    revision, payload = row
    config = {2: legacy_configuration, 3: configuration_v3, 4: configuration_v4, 5: configuration_v5, 6: configuration_v7, 7: configuration_v7, 8: configuration_v8, 9: configuration_v9}[version](json.loads(payload))
    if config.revision != revision:
        raise ValueError(tr('旧数据库配置修订号不一致'))
    directory = Path(path).parent / 'backups'
    directory.mkdir(mode=0o700, exist_ok=True)
    backup = directory / (f'smooth-caddy-v{version}-' + uuid4().hex + '.db')
    pending = backup.with_suffix('.pending')
    fd = os.open(pending, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    os.close(fd)
    try:
        # A separate read connection avoids backing up the writer's open transaction.
        source = sqlite3.connect(Path(path).resolve().as_uri() + '?mode=ro', uri=True)
        try:
            target = sqlite3.connect(pending)
            try:
                source.backup(target)
                if target.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                    raise ValueError(tr('迁移备份校验失败'))
            finally:
                target.close()
        finally:
            source.close()
        # Windows FlushFileBuffers requires a writable file handle.
        with pending.open('r+b') as stream:
            os.fsync(stream.fileno())
        os.replace(pending, backup)
    except BaseException:
        pending.unlink(missing_ok=True)
        raise
    value = config.to_dict()
    value['revision'] += 1
    db.execute('UPDATE configuration SET payload=?, revision=? WHERE id=1',
               (json.dumps(value, ensure_ascii=False), value['revision']))
    db.execute(f'PRAGMA user_version={DATABASE_VERSION}')
    return backup
