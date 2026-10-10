"""Process-wide startup language; translation never touches configuration values."""
import json
from pathlib import Path
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


def saved_language(directory):
    path = Path(directory) / 'ui.json'
    if not path.exists():
        return 'zh-CN'
    value = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(value, dict):
        raise ValueError(tr('语言设置无效，请使用 zh-CN 或 en'))
    language = value.get('language', 'zh-CN')
    if language not in LANGUAGES:
        raise ValueError(tr('语言设置无效，请使用 zh-CN 或 en'))
    return language


def save_language(directory, language):
    if language not in LANGUAGES:
        raise ValueError(tr('语言设置无效，请使用 zh-CN 或 en'))
    from .network.files import atomic
    path = Path(directory) / 'ui.json'
    value = json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
    if not isinstance(value, dict):
        raise ValueError(tr('语言设置无效，请使用 zh-CN 或 en'))
    value['language'] = language
    atomic(path, (json.dumps(value, ensure_ascii=False, indent=2) + '\n').encode('utf-8'))
