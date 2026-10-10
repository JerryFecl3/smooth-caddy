"""Generate release notes from the history of the triggering version tag."""
import argparse
from pathlib import Path
import re
import subprocess


def generate(root, tag, repo):
    def git(*args):
        return subprocess.check_output(['git', *args], cwd=root, text=True, encoding='utf-8').strip()

    def version(value):
        if re.fullmatch(r'v(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)', value):
            return tuple(map(int, value[1:].split('.')))
        return None

    current = version(tag)
    if current is None:
        raise ValueError('发布标签必须为 vX.Y.Z')
    if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', repo):
        raise ValueError('仓库必须为 owner/name')
    ref = 'refs/tags/' + tag
    candidates = [t for t in git('tag', '--merged', ref).splitlines()
                  if version(t) is not None and version(t) < current]
    previous = max(candidates, key=version) if candidates else None
    revision = 'refs/tags/' + previous + '..' + ref if previous else ref
    url = 'https://github.com/' + repo
    lines = ['## 本次变更', '']
    for sha in git('rev-list', '--reverse', revision).splitlines():
        title = git('show', '-s', '--format=%s', sha)
        body = git('show', '-s', '--format=%b', sha)
        lines.append(f'- {title} ([{sha[:8]}]({url}/commit/{sha}))')
        if body:
            lines.extend(['', *['    ' + line if line else '' for line in body.splitlines()]])
        lines.append('')
    if len(lines) == 2:
        lines.extend(['此版本没有新增提交。', ''])
    if previous:
        lines.append(f'[完整代码差异]({url}/compare/{previous}...{tag})')
    return '\n'.join(lines) + '\n'


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('tag')
    parser.add_argument('--repo', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output.write_text(generate(Path(__file__).resolve().parents[1], args.tag, args.repo), encoding='utf-8')
