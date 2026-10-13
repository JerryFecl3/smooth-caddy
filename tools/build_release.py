"""Build a native portable sample; run on each target OS/architecture."""
import ast
import argparse
import os
import hashlib
import importlib.metadata as metadata
import json
import platform
from pathlib import Path
import shutil
import subprocess
import sys
import sysconfig
import tarfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    identity = parser.add_mutually_exclusive_group()
    identity.add_argument("--preview", action="store_true", help="Build a clean commit without a release tag")
    identity.add_argument("--tag", help="Explicit release tag for main-branch CI builds")
    args = parser.parse_args()
    system = {'Linux': 'linux', 'Windows': 'windows'}.get(platform.system())
    arch = {'x86_64': 'amd64', 'AMD64': 'amd64', 'aarch64': 'arm64', 'ARM64': 'arm64'}.get(platform.machine())
    if not system or arch != 'amd64':
        raise SystemExit('Unsupported build platform')
    sys.path.insert(0,str(ROOT))
    from app.version import git_release, git_preview
    release=git_preview(ROOT) if args.preview else git_release(ROOT,args.tag or os.environ.get('GITHUB_REF_NAME'))
    version=release['version']
    name = f'smooth-caddy-{version}-{system}-{arch}'
    work = ROOT / 'build' / 'portable'
    output = ROOT / 'dist'
    stage = output / name
    if work.exists(): shutil.rmtree(work)
    if stage.exists(): shutil.rmtree(stage)
    work.mkdir(parents=True); stage.mkdir(parents=True)
    version_file=work/'build-version.json'
    version_file.write_text(json.dumps(release),encoding='utf-8')
    cmd = [sys.executable, '-m', 'PyInstaller', '--noconfirm', '--clean', '--onefile', '--python-option', 'X utf8',
           '--name', 'smooth-caddy', '--distpath', str(stage), '--workpath', str(work),
           '--specpath', str(work), '--collect-all', 'textual',
           '--add-data', f'{version_file}{os.pathsep}app',
           '--add-data', f'{ROOT / "app/tui/tui.tcss"}{os.pathsep}app/tui',
           '--add-data', f'{ROOT / "app/network/templates"}{os.pathsep}app/network/templates',
           str(ROOT / 'smooth_caddy.py')]
    subprocess.run(cmd, cwd=ROOT, check=True)
    licenses = stage / 'licenses'; licenses.mkdir()
    for license_name in ('LICENSE','THIRD_PARTY_NOTICES.md'):
        shutil.copy2(ROOT/license_name,stage/license_name)
    inventory = []
    # Conservative inventory: includes build-environment packages, a superset
    # of bundled Python dependencies. It is not a claim of a complete SBOM.
    seen = set()
    for dist in metadata.distributions():
        package = dist.metadata['Name']
        if package.lower() in seen or package in ('app', 'smooth-caddy'): continue
        seen.add(package.lower())
        copied = []
        for entry in dist.files or []:
            if not any(word in str(entry).lower() for word in ('license', 'copying', 'notice')): continue
            source = Path(dist.locate_file(entry))
            if not source.is_file() or source.suffix == '.pyc': continue
            target = licenses / package / str(len(copied)) / source.name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target); copied.append(target.relative_to(stage).as_posix())
        inventory.append({'name': package, 'version': dist.version, 'license_files': copied})
    python_license = Path(sysconfig.get_path('stdlib')) / 'LICENSE.txt'
    if not python_license.exists(): python_license = Path(sys.base_prefix) / 'LICENSE.txt'
    if not python_license.exists(): raise SystemExit('Python LICENSE.txt missing')
    shutil.copy2(python_license, licenses / 'PYTHON-LICENSE.txt')
    # On Debian, collect copyright files for system libraries present in Analysis.
    missing = []
    toc = ast.literal_eval((work / 'smooth-caddy' / 'Analysis-00.toc').read_text(encoding='utf-8'))
    def walk(value):
        if isinstance(value, (tuple, list)):
            if len(value) == 3 and value[-1] in ('BINARY', 'EXTENSION') and isinstance(value[1], str):
                yield value[1]
            else:
                for child in value: yield from walk(child)
    if shutil.which('dpkg-query'):
        for library in sorted(set(walk(toc))):
            if 'site-packages' in library: continue
            owners=[]
            for candidate in (library,str(Path(library).resolve())):
                result = subprocess.run(['dpkg-query', '-S', candidate], capture_output=True, text=True)
                owners=[line for line in result.stdout.splitlines() if ': ' in line and not line.startswith('diversion ')]
                if owners:break
            if not owners:missing.append(Path(library).name);continue
            package = owners[-1].split(': ')[0].split(':')[0]
            source = Path('/usr/share/doc') / package / 'copyright'
            if source.is_file(): shutil.copy2(source, licenses / (package + '-copyright'))
            else: missing.append(package)
        common=Path('/usr/share/common-licenses')
        if common.is_dir():shutil.copytree(common,licenses/'common-licenses')
    else:
        missing.append('Native library license collection needs target-platform review')
    executable=stage/('smooth-caddy.exe' if system=='windows' else 'smooth-caddy')
    for arguments in (('--help',), ('--version',), ('--language', 'en', '--help')):
        subprocess.run([str(executable), *arguments],check=True)
    report = {'version': version, 'platform': system, 'architecture': arch,
              'python': platform.python_version(), 'libc': platform.libc_ver(),
              'tag': release['tag'], 'commit': release['commit'],
              'native_license_gaps': missing, 'build_environment_packages': inventory}
    (stage / 'build-info.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    (stage / 'README.txt').write_text(
        'Smooth Caddy\n\n'
        'Run smooth-caddy (Windows: smooth-caddy.exe).\n'
        'Data is created in ~/.smooth-caddy/. --data-dir overrides it. Exports always go to ~/smooth-caddy-export/.\n'
        'Exit before copying data or replacing the executable.\n'
        'Caddy and lego are downloaded separately through the application.\n'
        'See README.md in the source repository for usage and platform requirements.\n'
        'build-info.json records the native build environment; older Linux libc is not guaranteed.\n'
        'licenses/ includes Python package and available system-library notices.\n', encoding='utf-8')
    if system == 'windows':
        archive = output / (name + '.zip')
        with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as bundle:
            for file in stage.rglob('*'):
                if file.is_file(): bundle.write(file, file.relative_to(output))
    else:
        archive = output / (name + '.tar.gz')
        with tarfile.open(archive, 'w:gz') as bundle: bundle.add(stage, arcname=name)
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    archive.with_name(archive.name + '.sha256').write_text(f'{digest}  {archive.name}\n')
    print(f'Built {archive} ({archive.stat().st_size / 1024**2:.1f} MiB)')

if __name__ == '__main__': main()
