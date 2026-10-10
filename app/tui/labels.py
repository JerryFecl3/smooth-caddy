"""Localized display labels for language-neutral configuration identifiers."""
from ..i18n import tr

LABELS = {
    'direct': '直连源头', 'via_upstream': '经上游转发',
    'private_ca': '私有 CA', 'public_ca': '公共 CA',
    'disabled': '不提供服务', 'http': 'HTTP', 'https': 'HTTPS',
    'https_mtls': 'HTTPS + mTLS',
    'debian_13': 'Debian 13', 'openwrt_25_12': 'OpenWrt 25.12',
}


def label(value):
    return tr(LABELS[value]) if value in LABELS else value


def options(values):
    return [(label(value), value) for value in values]
