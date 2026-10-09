"""Process-wide passphrase session and authenticated private-key storage."""
import base64
import os
import threading
import asyncssh
from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

# Persistent format marker, independent of the product's display name.
VERIFIER = b'caddy-lite/private-storage/v2'

class LockedError(ValueError):
    pass


def cipher(password, salt):
    if not isinstance(password, str) or not password:
        raise ValueError('程序口令不能为空')
    key = Scrypt(salt=salt, length=32, n=2**15, r=8, p=1).derive(password.encode())
    return Fernet(base64.urlsafe_b64encode(key))


class Security:
    def __init__(self, store):
        self.store = store
        self._password = None
        self._cipher = None
        self._verifier = None
        self._mutex = threading.RLock()

    def _record(self, name):
        row = self.store.db.execute('SELECT value FROM secrets WHERE name=?', (name,)).fetchone()
        return row[0] if row else None

    @property
    def initialized(self): return self._record('passphrase-verifier') is not None

    @property
    def unlocked(self): return self._cipher is not None

    def require(self):
        if not self.unlocked: raise LockedError('请先解锁程序')
        if self._record('passphrase-verifier') != self._verifier:
            self.lock()
            raise LockedError('程序口令已被其他进程修改，请重新解锁')

    def setup(self, password):
        with self._mutex:
            salt = os.urandom(16)
            protector = cipher(password, salt)
            verifier = protector.encrypt(VERIFIER)
            ssh = asyncssh.generate_private_key('ssh-ed25519')
            records = [('passphrase-salt', salt), ('passphrase-verifier', verifier),
                       ('ssh-key', protector.encrypt(ssh.export_private_key())),
                       ('ssh-public', ssh.export_public_key()), ('batch-key', protector.encrypt(Fernet.generate_key()))]
            with self.store.transaction():
                if self.initialized: raise ValueError('程序口令已设置')
                self.store.db.executemany('INSERT INTO secrets VALUES (?,?)', records)
            self._password, self._cipher, self._verifier = password, protector, verifier

    def unlock(self, password):
        with self._mutex:
            if not self.initialized: raise ValueError('请先设置程序口令')
            try:
                protector = cipher(password, self._record('passphrase-salt'))
                verifier = self._record('passphrase-verifier')
                if protector.decrypt(verifier) != VERIFIER: raise InvalidToken()
            except InvalidToken: raise ValueError('程序口令错误') from None
            self._password, self._cipher, self._verifier = password, protector, verifier

    def verify_password(self, password):
        """Revalidate explicit input without changing the process unlock session."""
        with self._mutex:
            if not self.initialized: raise ValueError('请先设置程序口令')
            try:
                protector = cipher(password, self._record('passphrase-salt'))
                if protector.decrypt(self._record('passphrase-verifier')) != VERIFIER:
                    raise InvalidToken()
            except InvalidToken:
                raise ValueError('程序口令错误') from None

    def lock(self):
        self._password = self._cipher = self._verifier = None

    def encrypt(self, material):
        with self._mutex:
            self.require()
            return self._cipher.encrypt(material)

    def decrypt(self, material):
        with self._mutex:
            self.require()
            try: return self._cipher.decrypt(material)
            except InvalidToken: raise ValueError('私钥数据损坏，无法解密') from None

    def batch_cipher(self):
        self.require()
        value=self._record('batch-key')
        if value is None:raise ValueError('缺少批次加密密钥')
        return Fernet(self.decrypt(value))

    def change_password(self, password):
        with self._mutex:
            self.require()
            salt = os.urandom(16)
            replacement = cipher(password, salt)
            verifier = replacement.encrypt(VERIFIER)
            # All key rows and password metadata commit together. Any failure
            # leaves the old password, persisted keys and process session intact.
            with self.store.transaction():
                self.require()
                for table, identity in [('authorities', 'role'), ('clients', 'id')]:
                    rows = self.store.db.execute(f'SELECT {identity},key FROM {table}').fetchall()
                    converted = [(replacement.encrypt(self.decrypt(data)), key) for key, data in rows]
                    self.store.db.executemany(f'UPDATE {table} SET key=? WHERE {identity}=?', converted)
                for name, data in self.store.db.execute("SELECT name,value FROM secrets WHERE name LIKE 'public-tls-secret/%'").fetchall():
                    self.store.db.execute('UPDATE secrets SET value=? WHERE name=?', (replacement.encrypt(self.decrypt(data)), name))
                batch_key = replacement.encrypt(self.decrypt(self._record('batch-key')))
                self.store.db.execute('UPDATE secrets SET value=? WHERE name=?',(batch_key,'batch-key'))
                ssh = replacement.encrypt(self.decrypt(self._record('ssh-key')))
                self.store.db.executemany('UPDATE secrets SET value=? WHERE name=?',
                    [(ssh, 'ssh-key'), (salt, 'passphrase-salt'), (verifier, 'passphrase-verifier')])
            self._password, self._cipher, self._verifier = password, replacement, verifier
