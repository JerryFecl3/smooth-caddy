"""Versioned decoding and transactional database migration, never UI translation."""
from ..i18n import tr
from copy import deepcopy
import json
import os
from pathlib import Path
import sqlite3
from uuid import uuid4
from .models import Configuration

DATABASE_VERSION = 3


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
        return Configuration.from_dict(value)
    except (KeyError, TypeError) as error:
        raise ValueError(tr('旧配置格式或枚举值不受支持，未转换数据')) from error


def migrate_v2(db, path):
    """Caller holds BEGIN IMMEDIATE; back up committed state before any writes."""
    row = db.execute('SELECT revision, payload FROM configuration WHERE id=1').fetchone()
    if row is None:
        raise ValueError(tr('旧数据库缺少配置记录'))
    revision, payload = row
    config = legacy_configuration(json.loads(payload))
    if config.revision != revision:
        raise ValueError(tr('旧数据库配置修订号不一致'))
    directory = Path(path).parent / 'backups'
    directory.mkdir(mode=0o700, exist_ok=True)
    backup = directory / ('smooth-caddy-v2-' + uuid4().hex + '.db')
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
