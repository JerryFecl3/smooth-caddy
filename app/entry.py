"""Human entry point; business operations live in app.network."""
from .i18n import tr, LANGUAGES, set_language, system_language
import argparse
import sys
from pathlib import Path

def default_data_directory():
    return Path.home() / ".smooth-caddy"

def main(argv=None):
    # Redirected Windows streams otherwise inherit an ANSI code page.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    bootstrap = argparse.ArgumentParser(add_help=False)
    bootstrap.add_argument('--data-dir', default=str(default_data_directory()))
    bootstrap.add_argument('--language', choices=LANGUAGES)
    initial, _ = bootstrap.parse_known_args(argv)
    from .preferences import load_language
    preference = load_language(initial.data_dir)
    set_language(initial.language or (system_language() if preference == "auto" else preference))
    parser = argparse.ArgumentParser(description=tr('个人网络 Caddy 配置与证书管理'))
    parser.add_argument('--data-dir', default=str(default_data_directory()), help=tr('运行数据目录，默认 ~/.smooth-caddy/（数据库 smooth-caddy.db）'))
    parser.add_argument('--language', choices=LANGUAGES, help=tr('界面语言；覆盖全局配置，仅本次启动生效'))
    from .version import display_version
    parser.add_argument('--version', action='version', version='Smooth Caddy '+display_version())
    args = parser.parse_args(argv)
    from .tui.ui import main as run
    run(args.data_dir)
