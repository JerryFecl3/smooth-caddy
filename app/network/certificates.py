"""Private PKI entirely through cryptography APIs; no subprocesses."""
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from ipaddress import ip_address
from uuid import uuid4
import re
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.serialization import pkcs12
from cryptography.x509.oid import NameOID, ExtendedKeyUsageOID

END = datetime(2099, 12, 31, 23, 59, 59, tzinfo=timezone.utc)
PEM = serialization.Encoding.PEM
ROLES = ('root', 'tls', 'client', 'relay')
CA_SUFFIXES = {'root': 'Root CA', 'tls': 'TLS CA', 'client': 'mTLS CA', 'relay': 'Relay CA'}

def validate_certificate_name(name):
    name = name.strip()
    if not name: raise ValueError('名称不能为空')
    if not re.fullmatch(r'[A-Za-z0-9 ._-]+', name):
        raise ValueError('仅允许英文字母、数字、空格及 - _ .')
    if len(name.encode('ascii')) > 64: raise ValueError('名称不能超过 64 个字符')
    return name

@dataclass(frozen=True)
class Client:
    id: str
    name: str
    enabled: bool

@dataclass(frozen=True)
class Material:
    certificate: bytes
    private_key: bytes


def key_bytes(key, password=None):
    encryption = serialization.BestAvailableEncryption(password) if password else serialization.NoEncryption()
    return key.private_bytes(PEM, serialization.PrivateFormat.PKCS8, encryption)


def issue(name, key, issuer_cert=None, issuer_key=None, *, ca=False, root=False, usages=(), sans=(), until=END):
    now = datetime.now(timezone.utc)
    if until <= now: raise ValueError('证书有效期已经结束')
    if issuer_cert is not None and until > issuer_cert.not_valid_after_utc:
        raise ValueError('签发有效期超出 CA 有效期')
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, name)])
    issuer_key = issuer_key or key
    builder = (x509.CertificateBuilder().subject_name(subject)
               .issuer_name(issuer_cert.subject if issuer_cert else subject)
               .public_key(key.public_key()).serial_number(x509.random_serial_number())
               .not_valid_before(now-timedelta(minutes=5)).not_valid_after(until)
               .add_extension(x509.BasicConstraints(ca=ca, path_length=1 if root else 0 if ca else None), critical=True)
               .add_extension(x509.KeyUsage(digital_signature=True, content_commitment=False,
                    key_encipherment=False, data_encipherment=False, key_agreement=False,
                    key_cert_sign=ca, crl_sign=ca, encipher_only=False, decipher_only=False), critical=True)
               .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False)
               .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(issuer_key.public_key()), critical=False))
    if usages: builder = builder.add_extension(x509.ExtendedKeyUsage(list(usages)), critical=True)
    if sans: builder = builder.add_extension(x509.SubjectAlternativeName(list(sans)), critical=False)
    return builder.sign(issuer_key, hashes.SHA256())


class Certificates:
    def __init__(self, store, security):
        self.store = store
        self.security = security

    @property
    def initialized(self):
        return self.store.db.execute('SELECT count(*) FROM authorities').fetchone()[0] == 4

    @property
    def unlocked(self): return self.security.unlocked and self.initialized

    @property
    def name(self):
        row = self.store.db.execute("SELECT name FROM authorities WHERE role='root'").fetchone()
        return row[0] if row else ''

    @property
    def names(self):
        return dict(self.store.db.execute('SELECT role,name FROM authorities'))

    def overview(self):
        """Public certificate subjects and actual expiry; never decrypt keys."""
        def describe(pem):
            cert=x509.load_pem_x509_certificate(pem)
            return (cert.subject.get_attributes_for_oid(NameOID.COMMON_NAME)[0].value,
                    cert.not_valid_after_utc.strftime('%Y-%m-%d'))
        authorities={role:describe(cert) for role,cert in self.store.db.execute('SELECT role,cert FROM authorities')}
        clients=[(*describe(cert),bool(enabled)) for cert,enabled in
                 self.store.db.execute('SELECT cert,enabled FROM clients ORDER BY rowid')]
        return authorities,clients

    def public(self, role):
        row = self.store.db.execute('SELECT cert FROM authorities WHERE role=?', (role,)).fetchone()
        if row is None: raise ValueError('CA 尚未初始化')
        return row[0]

    def export_trust_ca(self):
        """Public root certificate in DER format for device trust installation."""
        return x509.load_pem_x509_certificate(self.public('root')).public_bytes(serialization.Encoding.DER)

    def initialize(self, name, *, replace=False):
        self.security.require()
        name = validate_certificate_name(name)
        if self.initialized and not replace: raise ValueError('CA 已初始化；重新初始化需要明确确认')
        keyset = {r: ec.generate_private_key(ec.SECP256R1()) for r in ROLES}
        names = {role: name+' '+CA_SUFFIXES[role] for role in ROLES}
        if any(len(value.encode('utf-8')) > 64 for value in names.values()):
            raise ValueError('CA 名称过长，请缩短名称前缀')
        root = issue(names['root'], keyset['root'], ca=True, root=True)
        certs = {'root': root}
        for role, usage in [('tls', [ExtendedKeyUsageOID.SERVER_AUTH]),
                            ('client', [ExtendedKeyUsageOID.CLIENT_AUTH]),
                            ('relay', [ExtendedKeyUsageOID.SERVER_AUTH, ExtendedKeyUsageOID.CLIENT_AUTH])]:
            certs[role] = issue(names[role], keyset[role], root, keyset['root'], ca=True, usages=usage)
        records = [(r, names[r], certs[r].public_bytes(PEM), self.security.encrypt(key_bytes(keyset[r]))) for r in ROLES]
        with self.store.transaction():
            self.store.db.execute('DELETE FROM clients')
            self.store.db.execute('DELETE FROM authorities')
            self.store.db.executemany('INSERT INTO authorities VALUES (?,?,?,?)', records)
    def reset(self):
        self.security.require()
        with self.store.transaction():
            self.store.db.execute('DELETE FROM clients')
            self.store.db.execute('DELETE FROM authorities')

    def clients(self):
        return [Client(i,n,bool(e)) for i,n,e in self.store.db.execute('SELECT id,name,enabled FROM clients ORDER BY rowid')]

    def sign_client(self, name):
        name = validate_certificate_name(name)
        if any(c.name.casefold() == name.casefold() for c in self.clients()): raise ValueError('Client 名称已存在')
        material = self.leaf('client', name, client=True, until=END)
        encrypted = self.security.encrypt(material.private_key)
        identity = uuid4().hex
        with self.store.transaction():
            self.store.db.execute('INSERT INTO clients VALUES (?,?,?,1,?,?)',
                                  (identity, name, name.casefold(), material.certificate, encrypted))
        return identity

    def set_enabled(self, identity, enabled):
        self.security.require()
        if type(enabled) is not bool: raise ValueError('启用状态必须为布尔值')
        with self.store.transaction():
            if self.store.db.execute('UPDATE clients SET enabled=? WHERE id=?', (enabled,identity)).rowcount != 1:
                raise ValueError('Client 不存在')

    def export_p12(self, identity, password):
        self.security.require()
        if not password: raise ValueError('导出密码不能为空')
        row = self.store.db.execute('SELECT name,cert,key FROM clients WHERE id=?', (identity,)).fetchone()
        if row is None: raise ValueError('Client 不存在')
        name, cert, private = row
        return pkcs12.serialize_key_and_certificates(name.encode(),
                 serialization.load_pem_private_key(self.security.decrypt(private), None),
                 x509.load_pem_x509_certificate(cert),
                 [x509.load_pem_x509_certificate(self.public('client')), x509.load_pem_x509_certificate(self.public('root'))],
                 serialization.BestAvailableEncryption(password.encode()))

    def enabled_certificates(self):
        return [row[0] for row in self.store.db.execute('SELECT cert FROM clients WHERE enabled=1 ORDER BY id')]

    def leaf(self, role, name, *, client=False, dns=None, ip=None, until=None):
        if role not in ('tls','client','relay'): raise ValueError('叶子用途无效')
        self.security.require()
        if not self.initialized: raise ValueError('CA 尚未初始化')
        if role == 'tls' and client or role == 'client' and not client: raise ValueError('证书用途不匹配')
        key = ec.generate_private_key(ec.SECP256R1())
        sans = []
        if dns: sans.append(x509.DNSName(dns))
        if ip: sans.append(x509.IPAddress(ip_address(ip)))
        cert = issue(name, key, x509.load_pem_x509_certificate(self.public(role)), serialization.load_pem_private_key(self.security.decrypt(self.store.db.execute('SELECT key FROM authorities WHERE role=?', (role,)).fetchone()[0]), None),
                     usages=[ExtendedKeyUsageOID.CLIENT_AUTH if client else ExtendedKeyUsageOID.SERVER_AUTH],
                     sans=sans, until=until or datetime.now(timezone.utc)+timedelta(days=365))
        return Material(cert.public_bytes(PEM), key_bytes(key))
