"""Release identity comes from the exact Git tag and commit, never a version constant."""
import json
from pathlib import Path
import re
import subprocess

ROOT=Path(__file__).resolve().parents[1]

def git_release(root=ROOT, tag=None):
    def git(*args):return subprocess.check_output(['git',*args],cwd=root,text=True,stderr=subprocess.DEVNULL).strip()
    if git('status','--porcelain','--untracked-files=normal'):
        raise ValueError('正式构建要求工作区干净')
    tags=git('tag','--points-at','HEAD').splitlines()
    tags=[value for value in tags if re.fullmatch(r'v(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)',value)]
    if tag is None:
        if len(tags)!=1:raise ValueError('当前提交必须有唯一的 vX.Y.Z 标签')
        tag=tags[0]
    if tag not in tags:raise ValueError('发布标签必须指向当前提交')
    commit=git('rev-parse','HEAD')
    return {'version':tag[1:]+'.'+commit[:8],'tag':tag,'commit':commit}

def display_version():
    embedded=Path(__file__).with_name('build-version.json')
    if embedded.exists():return json.loads(embedded.read_text())['version']
    try:return git_release()['version']
    except (ValueError,OSError,subprocess.CalledProcessError):return 'development'

# Python packaging uses PEP 440; binary filenames use the requested X.Y.Z.commit.
try:
    info=git_release()
    __version__=info['tag'][1:]+'+g'+info['commit'][:8]
except (ValueError,OSError,subprocess.CalledProcessError):
    __version__='0+development'
