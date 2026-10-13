import unittest
from datetime import timedelta
from app.network.certificate_policy import certificate_expiry, RENEW_DAYS, renewal_status
from app.tui.public_tls import display_validity
from tests.test_public_tls import materials


class CertificateValidityTests(unittest.TestCase):
    def test_certificate_lifetime_and_shared_renewal_boundary(self):
        certificate, _ = materials('example.com', 30)
        pem = certificate.decode()
        item = {'certificate': pem, 'error': 'previous renewal failed'}
        expires = certificate_expiry(pem)
        boundary = expires - timedelta(days=RENEW_DAYS)
        normal = display_validity(item, boundary - timedelta(seconds=1))
        self.assertEqual(normal.plain, expires.strftime('%Y-%m-%d'))
        self.assertFalse(normal.spans)
        for now, days in ((boundary, RENEW_DAYS), (expires-timedelta(seconds=1), 1)):
            self.assertTrue(renewal_status(pem, now))
            result = display_validity(item, now)
            self.assertTrue(result.plain.endswith(f'仅剩{days}天'))
            self.assertEqual(result.spans[-1].style, '#ffa500')
        for now in (expires, expires+timedelta(days=1)):
            result = display_validity(item, now)
            self.assertTrue(result.plain.endswith('已过期'))
            self.assertEqual(result.spans[-1].style, '#ff6b6b')

    def test_missing_certificate_with_or_without_error(self):
        for error in ('', 'failed'):
            result = display_validity({'certificate': '', 'error': error})
            self.assertEqual(result.plain, '无证书')
            self.assertEqual(result.style, '#ff6b6b')
