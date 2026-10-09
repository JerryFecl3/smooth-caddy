"""Password encryption interoperable with openssl enc on deployment hosts."""
import os
from cryptography.hazmat.primitives import hashes, padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

def encrypt_payload(payload, password):
    if not password or '\n' in password or '\r' in password or '\0' in password:
        raise ValueError('导出口令不能为空或包含换行及空字符')
    salt=os.urandom(8)
    material=PBKDF2HMAC(algorithm=hashes.SHA256(),length=48,salt=salt,iterations=100000).derive(password.encode())
    padder=padding.PKCS7(128).padder();padded=padder.update(payload)+padder.finalize()
    enc=Cipher(algorithms.AES(material[:32]),modes.CBC(material[32:])).encryptor()
    return enc.update(padded)+enc.finalize(),salt.hex()

def encrypt_package(package,password):
    header,payload=package.split(b'__CADDY_PAYLOAD__\n',1)
    encrypted,salt=encrypt_payload(payload,password)
    import hashlib
    header=header.decode().replace(hashlib.sha256(payload).hexdigest(),hashlib.sha256(encrypted).hexdigest())
    decrypt='''command -v openssl >/dev/null 2>&1 || { echo 'Missing tool: openssl' >&2; exit 1; }
openssl enc -d -aes-256-cbc -pbkdf2 -iter 100000 -md sha256 -S SALT -in "$work/payload.tar.gz" -out "$work/decrypted.tar.gz" || { echo 'Decryption failed' >&2; exit 1; }
mv "$work/decrypted.tar.gz" "$work/payload.tar.gz"
'''.replace('SALT',salt)
    return header.replace('mkdir "$work/payload"',decrypt+'mkdir "$work/payload"').encode()+b'__CADDY_PAYLOAD__\n'+encrypted
