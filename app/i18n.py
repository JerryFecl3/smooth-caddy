"""Process-wide startup language; translation never touches configuration values."""
import locale
import os
import sys
from .messages import EN

LANGUAGES = ('zh-CN', 'en')
_language = 'zh-CN'


def set_language(language):
    global _language
    if language not in LANGUAGES:
        raise ValueError('Unsupported language: ' + str(language))
    _language = language


def get_language():
    return _language


def tr(message, *values):
    text = EN.get(message, message) if _language == 'en' else message
    return text.format(*values) if values else text


def system_language():
    """Windows display language, or POSIX message locale; English fallback."""
    if sys.platform == 'win32':
        try:
            import ctypes
            language_id = ctypes.windll.kernel32.GetUserDefaultUILanguage()
            return 'zh-CN' if language_id & 0x3ff == 0x04 else 'en'
        except (AttributeError, OSError):
            return 'en'
    for name in ('LC_ALL', 'LC_MESSAGES', 'LANG'):
        value = os.environ.get(name)
        if value:
            break
    else:
        try:
            value = locale.getlocale(locale.LC_MESSAGES)[0] or ''
        except (AttributeError, ValueError, locale.Error):
            value = ''
    language = value.lower().replace('-', '_').split('.')[0].split('@')[0]
    return 'zh-CN' if language == 'zh' or language.startswith('zh_') else 'en'
