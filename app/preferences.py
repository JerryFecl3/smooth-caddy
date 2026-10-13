"""Local global preferences, independent of exported network configuration."""
import json
from pathlib import Path
from .i18n import LANGUAGES
from .network.files import atomic

LANGUAGE_OPTIONS = ('auto', *LANGUAGES)


def load_language(directory):
    try:
        value = json.loads((Path(directory) / 'preferences.json').read_text(encoding='utf-8'))
        language = value.get('language', 'auto')
        return language if language in LANGUAGE_OPTIONS else 'auto'
    except (OSError, ValueError, AttributeError, TypeError):
        return 'auto'


def save_language(directory, language):
    if language not in LANGUAGE_OPTIONS:
        raise ValueError('Unsupported language: ' + str(language))
    atomic(Path(directory) / 'preferences.json',
           (json.dumps({'language': language}, ensure_ascii=False) + '\n').encode('utf-8'))
