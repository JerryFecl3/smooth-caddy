"""Plan and publish a fixed main-branch commit using the workflow's GitHub token."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import urllib.error
import urllib.parse
import urllib.request

VERSION = re.compile(r'v(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)')


def git(root, *args):
    return subprocess.check_output(['git', *args], cwd=root, text=True, encoding='utf-8', timeout=30).strip()


def version(tag):
    match = VERSION.fullmatch(tag)
    return tuple(map(int, match.groups())) if match else None


def plan(root):
    """Reuse a tag on this commit; otherwise allocate one greater than all tags."""
    commit = git(root, 'rev-parse', 'HEAD')
    tags = [t for t in git(root, 'tag').splitlines() if version(t) is not None]
    current = [t for t in git(root, 'tag', '--points-at', 'HEAD').splitlines() if version(t) is not None]
    requested = [line.partition(':')[2].strip() for line in git(root, 'show', '-s', '--format=%B', 'HEAD').splitlines()
                 if line.startswith('Release-Version:')]
    if len(requested) > 1 or (requested and version('v' + requested[0]) is None):
        raise ValueError('Use a single Release-Version: X.Y.Z line')
    if len(current) > 1:
        raise ValueError('Multiple release tags point to this commit')
    if current and tags and version(current[0]) < max(map(version, tags)):
        raise ValueError('A newer release tag already exists; do not republish an older commit')
    if current:
        if requested and current[0] != 'v' + requested[0]:
            raise ValueError('Requested version conflicts with existing tag')
        return current[0], commit
    latest = max(tags, key=version) if tags else None
    if latest:
        # A rerun of an older commit must not release on top of a newer version.
        git(root, 'merge-base', '--is-ancestor', 'refs/tags/' + latest, commit)
    if requested:
        tag = 'v' + requested[0]
        if latest and version(tag) <= version(latest):
            raise ValueError('Requested version must exceed the latest release tag')
    elif latest:
        major, minor, patch = version(latest)
        tag = f'v{major}.{minor}.{patch + 1}'
    else:
        tag = 'v0.1.0'
    return tag, commit


class GitHub:
    def __init__(self, repository, token):
        if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', repository):
            raise ValueError('Expected owner/repository')
        self.base = 'https://api.github.com/repos/' + repository
        self.token = token

    def request(self, method, path, data=None, *, missing=False, upload=False):
        url = ('https://uploads.github.com' + urllib.parse.urlsplit(self.base).path + path) if upload else self.base + path
        body = data if upload else (json.dumps(data).encode() if data is not None else None)
        request = urllib.request.Request(url, data=body, method=method, headers={
            'Authorization': 'Bearer ' + self.token, 'Accept': 'application/vnd.github+json',
            'X-GitHub-Api-Version': '2022-11-28', 'User-Agent': 'smooth-caddy-release',
            'Content-Type': 'application/octet-stream' if upload else 'application/json',
        })
        try:
            with urllib.request.urlopen(request, timeout=180) as response:
                raw = response.read()
                return json.loads(raw) if raw else None
        except urllib.error.HTTPError as error:
            if missing and error.code == 404:
                return None
            # Do not log tokens or full request/response bodies.
            raise RuntimeError(f'GitHub {method} {path}: HTTP {error.code}') from None

    def tag_commit(self, tag):
        ref = self.request('GET', '/git/ref/tags/' + tag, missing=True)
        if ref is None:
            return None
        obj = ref['object']
        for _ in range(8):
            if obj['type'] == 'commit':
                return obj['sha']
            if obj['type'] != 'tag':
                break
            obj = self.request('GET', '/git/tags/' + obj['sha'])['object']
        raise ValueError('Release tag does not resolve to a commit')


def packages(directory, tag, commit):
    """Require exactly the two fixed-commit archives and their matching checksums."""
    prefix = f'smooth-caddy-{tag[1:]}.{commit[:8]}'
    archives = [prefix + '-linux-amd64.tar.gz', prefix + '-windows-amd64.zip']
    expected = set(archives + [name + '.sha256' for name in archives])
    if {p.name for p in directory.iterdir()} != expected:
        raise ValueError('Expected exactly Linux/Windows archives and SHA-256 files for this commit')
    for name in archives:
        digest = hashlib.sha256((directory / name).read_bytes()).hexdigest()
        if (directory / (name + '.sha256')).read_text().split() != [digest, name]:
            raise ValueError('Checksum mismatch: ' + name)
    return [directory / name for name in sorted(expected)]


def publish(api, root, directory, tag, commit, repository):
    from tools.release_notes import generate
    if version(tag) is None or git(root, 'rev-parse', 'HEAD') != commit:
        raise ValueError('Release identity must match the checked-out commit')
    files = packages(directory, tag, commit)
    existing = api.tag_commit(tag)
    if existing is not None and existing != commit:
        raise ValueError('Refusing to move an existing tag')
    # A local tag is created by the workflow for notes and tagged build identity.
    if git(root, 'rev-parse', 'refs/tags/' + tag + '^{}') != commit:
        raise ValueError('Local release tag must match the checked-out commit')
    notes = generate(root, tag, repository)
    release = api.request('GET', '/releases/tags/' + tag, missing=True)
    if release and not release['draft']:
        if existing != commit:
            raise ValueError('Published release has no matching tag')
        return release['html_url']  # Never overwrite a published asset.
    if existing is None:
        api.request('POST', '/git/refs', {'ref': 'refs/tags/' + tag, 'sha': commit})
    if release is None:
        release = api.request('POST', '/releases', {
            'tag_name': tag, 'target_commitish': commit, 'name': 'Smooth Caddy ' + tag,
            'body': notes, 'draft': True, 'prerelease': False,
        })
    assets = api.request('GET', f"/releases/{release['id']}/assets?per_page=100")
    by_name = {asset['name']: asset for asset in assets}
    for file in files:
        digest = 'sha256:' + hashlib.sha256(file.read_bytes()).hexdigest()
        if file.name in by_name:
            if by_name[file.name].get('digest') != digest:
                raise ValueError('Existing draft asset differs: ' + file.name)
            continue
        api.request('POST', f"/releases/{release['id']}/assets?name=" + urllib.parse.quote(file.name), file.read_bytes(), upload=True)
    result = api.request('PATCH', f"/releases/{release['id']}", {'draft': False, 'make_latest': 'true'})
    return result['html_url']


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('plan', 'publish'))
    parser.add_argument('--tag')
    parser.add_argument('--directory', type=Path, default=Path('dist'))
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    repository = os.environ['GITHUB_REPOSITORY']
    api = GitHub(repository, os.environ['GITHUB_TOKEN'])
    if args.action == 'plan':
        tag, commit = plan(root)
        release = api.request('GET', '/releases/tags/' + tag, missing=True)
        published = bool(release and not release['draft'])
        if published and api.tag_commit(tag) != commit:
            raise ValueError('Published release tag does not match this commit')
        with open(os.environ['GITHUB_OUTPUT'], 'a', encoding='utf-8') as output:
            output.write(f'tag={tag}\ncommit={commit}\npublished={str(published).lower()}\n')
        print(f'{tag} / {commit} / already published: {published}')
    else:
        if not args.tag:
            parser.error('--tag is required for publish')
        print(publish(api, root, args.directory, args.tag, os.environ['GITHUB_SHA'], repository))


if __name__ == '__main__':
    # Direct script execution must also resolve tools.release_notes.
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    main()
