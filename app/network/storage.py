"""SQLite ownership, atomic transactions and optimistic configuration revisions."""
from ..i18n import tr
from contextlib import contextmanager
import json
from pathlib import Path
import os
import sqlite3
from .models import Configuration
from .migrations import DATABASE_VERSION, migrate_database

APPLICATION_ID = 0x434C4E31

class ConflictError(ValueError):
    pass

class Store:
    def __init__(self, directory):
        self.directory = Path(directory).resolve()
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.temporary = self.directory / '.tmp'
        self.temporary.mkdir(exist_ok=True, mode=0o700)
        self.exports = Path.home() / 'smooth-caddy-export'
        self.path = self.directory / 'smooth-caddy.db'
        existed = self.path.exists()
        if not existed:
            fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600); os.close(fd)
        self.db = sqlite3.connect(self.path, isolation_level=None, timeout=10, check_same_thread=False)
        try:
            identity = self.db.execute('PRAGMA application_id').fetchone()[0]
            tables = self.db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
            if identity != APPLICATION_ID and (tables or existed):
                raise ValueError(tr('此数据库不属于新实现；不会修改旧数据库'))
            self.db.execute('PRAGMA foreign_keys=ON')
            with self.transaction():
                version = self.db.execute('PRAGMA user_version').fetchone()[0]
                if identity == APPLICATION_ID:
                    if version in (2, 3, 4, 5, 6, 7, 8, 9, 10):
                        migrate_database(self.db, self.path, version)
                    elif version > DATABASE_VERSION:
                        raise ValueError(tr('数据库版本较新，请升级程序；不会写入'))
                    elif version != DATABASE_VERSION:
                        raise ValueError(tr('数据库版本不受支持；开发阶段需在程序外一次性转换'))
                self.db.execute(f'PRAGMA application_id={APPLICATION_ID}')
                self.db.execute(f'PRAGMA user_version={DATABASE_VERSION}')
                self.db.execute('CREATE TABLE IF NOT EXISTS configuration (id INTEGER PRIMARY KEY CHECK(id=1), revision INTEGER NOT NULL, payload TEXT NOT NULL)')
                self.db.execute('CREATE TABLE IF NOT EXISTS archive_sources (source TEXT PRIMARY KEY)')
                self.db.execute('CREATE TABLE IF NOT EXISTS settings_archives (id TEXT PRIMARY KEY, payload TEXT NOT NULL, source TEXT UNIQUE)')
                self.db.execute('CREATE TABLE IF NOT EXISTS authorities (role TEXT PRIMARY KEY, name TEXT NOT NULL, cert BLOB NOT NULL, key BLOB NOT NULL)')
                self.db.execute('CREATE TABLE IF NOT EXISTS clients (id TEXT PRIMARY KEY, name TEXT NOT NULL, name_key TEXT NOT NULL UNIQUE, enabled INTEGER NOT NULL, cert BLOB NOT NULL, key BLOB NOT NULL)')
                self.db.execute('CREATE TABLE IF NOT EXISTS secrets (name TEXT PRIMARY KEY, value BLOB NOT NULL)')
                self.db.execute('CREATE TABLE IF NOT EXISTS ssh_hosts (route_id TEXT PRIMARY KEY, key BLOB NOT NULL)')
                self.db.execute('CREATE TABLE IF NOT EXISTS hosts (node_id TEXT PRIMARY KEY, key BLOB NOT NULL)')
                self.db.execute('INSERT OR IGNORE INTO configuration VALUES (1, 0, ?)', (json.dumps(Configuration().to_dict()),))
        except BaseException:
            self.db.close(); raise

    @contextmanager
    def transaction(self):
        self.db.execute('BEGIN IMMEDIATE')
        try:
            yield
            self.db.execute('COMMIT')
        except BaseException:
            self.db.execute('ROLLBACK'); raise

    def load(self):
        payload = self.db.execute('SELECT payload FROM configuration WHERE id=1').fetchone()[0]
        return Configuration.from_dict(json.loads(payload))

    def save(self, config):
        value = config.to_dict(); value['revision'] += 1
        with self.transaction():
            result = self.db.execute('UPDATE configuration SET payload=?, revision=? WHERE id=1 AND revision=?',
                                     (json.dumps(value, ensure_ascii=False), value['revision'], config.revision))
            if result.rowcount != 1: raise ConflictError(tr('配置已被其他操作修改，请重新加载'))
        return Configuration.from_dict(value)

    def close(self): self.db.close()
