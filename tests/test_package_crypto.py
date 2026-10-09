import re
import subprocess
import tempfile
import unittest
from pathlib import Path
from app.network.application import Application
from app.network.package_crypto import encrypt_payload, encrypt_package
from app.network.releases import build_package
from app.network.models import Node

class PackageCryptoTests(unittest.TestCase):
    def test_openssl_interoperability_and_wrong_password(self):
        payload=b'private material\0'*100
        encrypted,salt=encrypt_payload(payload,'导出 secret')
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'encrypted';path.write_bytes(encrypted)
            cmd=['openssl','enc','-d','-aes-256-cbc','-pbkdf2','-iter','100000','-md','sha256','-S',salt,'-in',str(path),'-pass','stdin']
            result=subprocess.run(cmd,input='导出 secret\n'.encode(),capture_output=True)
            self.assertEqual(result.returncode,0);self.assertEqual(result.stdout,payload)
            wrong=subprocess.run(cmd,input=b'wrong\n',capture_output=True)
            self.assertNotEqual(wrong.returncode,0)
        other,_=encrypt_payload(payload,'导出 secret');self.assertNotEqual(other,encrypted)

    def test_package_header_and_payload(self):
        node=Node('node','Node',platform='Debian 13',arch='amd64')
        original=build_package(node,'20261009-120000','v2.11.7',{'private.key':b'PRIVATE KEY'},b'binary')
        encrypted=encrypt_package(original,'export')
        header,payload=encrypted.split(b'__CADDY_PAYLOAD__\n',1)
        self.assertNotIn(b'export',header)
        self.assertIn(b'openssl enc -d',header)
        self.assertFalse(payload.startswith(b'\x1f\x8b'))
        self.assertEqual(subprocess.run(['sh','-n'],input=header,capture_output=True).returncode,0)

    def test_batch_key_survives_password_change_and_ca_reset(self):
        with tempfile.TemporaryDirectory() as directory:
            app=Application(directory)
            try:
                app.security.setup('old');app.certificates.initialize('Test')
                key=app.security.decrypt(app.security._record('batch-key'))
                material=app.security.batch_cipher().encrypt(b'private')
                app.security.change_password('new');app.certificates.reset()
                self.assertEqual(app.security.decrypt(app.security._record('batch-key')),key)
                app.security.lock();app.security.unlock('new')
                self.assertEqual(app.security.batch_cipher().decrypt(material),b'private')
            finally:app.close()
