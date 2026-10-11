"""Localized display labels for language-neutral configuration identifiers."""
from ..i18n import tr

LABELS = {
    'private_ca': '私有 CA', 'public_ca': '公共 CA',
    'disabled': '未启用', 'http': 'HTTP', 'https': 'HTTPS',
    'https_mtls': 'HTTPS + mTLS',
    'debian_13': 'Debian', 'openwrt_25_12': 'OpenWrt',
}


def label(value):
    return tr(LABELS[value]) if value in LABELS else value


def options(values):
    return [(label(value), value) for value in values]
