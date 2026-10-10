"""Shared public-certificate coverage and renewal policy."""
from ..i18n import tr
from datetime import datetime, timedelta, timezone
from cryptography import x509

RENEW_DAYS = 13


def requested_domains(item):
    return [item['domain']] + (['*.'+item['domain']] if item['wildcard'] else [])


def certificate_expiry(pem):
    return x509.load_pem_x509_certificate(pem.encode() if isinstance(pem,str) else pem).not_valid_after_utc


def renewal_status(pem, now=None):
    if not pem:return tr('待申请')
    now = now or datetime.now(timezone.utc)
    return tr('待续签') if certificate_expiry(pem) <= now+timedelta(days=RENEW_DAYS) else ''
