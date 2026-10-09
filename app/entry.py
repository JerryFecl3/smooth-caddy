"""Human entry point; business operations live in app.network."""
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
    parser = argparse.ArgumentParser(description='个人网络 Caddy 配置与证书管理')
    parser.add_argument('--data-dir', default=str(default_data_directory()), help='运行数据目录，默认 ~/.smooth-caddy/（数据库 smooth-caddy.db）')
    from .version import display_version
    parser.add_argument('--version', action='version', version='Smooth Caddy '+display_version())
    args = parser.parse_args(argv)
    from .tui.ui import main as run
    run(args.data_dir)
