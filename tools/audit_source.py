"""Audit the Git index before publishing; never print credential contents."""
from pathlib import Path
import re
import subprocess

ROOT=Path(__file__).resolve().parents[1]
ROOT_FILES={'.gitignore','.gitattributes','AGENTS.md','LICENSE','README.md','README.en.md','THIRD_PARTY_NOTICES.md','Makefile','pyproject.toml','requirements.txt','requirements-build.txt','smooth_caddy.py'}
ROOTS={'app','tests','docs','tools','.github'}
FORBIDDEN={'.db','.sqlite','.p12','.pfx','.key','.pem','.cer','.crt','.log','.pyc','.exe','.run','.zip','.gz'}
PATTERNS=[re.compile(rb'-----BEGIN (?:RSA |EC |OPENSSH |ENCRYPTED )?PRIVATE KEY-----[\r\n]+[A-Za-z0-9+/=]{40}'),re.compile(rb'gh[pousr]_[A-Za-z0-9]{30,}'),re.compile(rb'github_pat_[A-Za-z0-9_]{30,}'),re.compile(rb'AKIA[A-Z0-9]{16}')]

def audit(root=ROOT):
    names=subprocess.check_output(['git','ls-files','-z'],cwd=root).decode().split('\0')
    errors=[]
    for name in filter(None,names):
        relative=Path(name);path=root/relative
        if name not in ROOT_FILES and relative.parts[0] not in ROOTS:errors.append(name+': outside source scope')
        if relative.suffix.lower() in FORBIDDEN or '__pycache__' in relative.parts:errors.append(name+': generated/private file type')
        if not path.is_file() or path.is_symlink():errors.append(name+': missing file or symbolic link');continue
        raw=path.read_bytes()
        if any(pattern.search(raw) for pattern in PATTERNS):errors.append(name+': possible credential material')
    if errors:raise ValueError('\n'.join(errors))
    return len(list(filter(None,names)))

if __name__=='__main__':print(f'Audited {audit()} source files')
