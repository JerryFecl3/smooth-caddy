"""Verified binary cache and atomic release index; no UI dependencies."""
from ..i18n import tr
from contextlib import contextmanager
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError
from .file_lock import FileLock
import hashlib
import io
import json
import os
import re
import shutil
import tarfile
import tempfile
import time
from .generator import generate
from .files import atomic, publish
from .downloads import fetch
from .task_progress import TaskCancelled
from .plans import generation_plan, assembly_plan
from .models import ARCHES

HERE = Path(__file__).parent / 'templates'


def sha(data): return hashlib.sha256(data).hexdigest()




class BinaryCache:
    def __init__(self,directory):
        self.root=Path(directory)/'tool_caddy'
        self.catalog=self.root/'releases.json'

    def versions(self):
        if not self.root.exists(): return {}
        return {p.name:sorted(a.name for a in p.iterdir() if a.is_dir() and (a/'caddy').is_file() and (a/'sha256').is_file())
                for p in self.root.iterdir() if p.is_dir() and re.fullmatch(r'v\d+\.\d+\.\d+',p.name)}

    @staticmethod
    def catalog_versions(values):
        if not isinstance(values, list): raise ValueError(tr('官方版本列表格式无效'))
        return [r['tag_name'] for r in values if not r['draft'] and not r['prerelease'] and re.fullmatch(r'v\d+\.\d+\.\d+',r['tag_name'])]

    def cached_versions(self):
        try: return self.catalog_versions(json.loads(self.catalog.read_bytes()))
        except (OSError, ValueError, KeyError, TypeError): return []

    def online_versions(self):
        headers={'User-Agent':'smooth-caddy','Accept':'application/vnd.github+json'}
        metadata_path=self.catalog.with_suffix('.http.json')
        cached=None
        try:
            payload=self.catalog.read_bytes()
            cached=self.catalog_versions(json.loads(payload))
            metadata=json.loads(metadata_path.read_bytes())
            if metadata.get('sha256') == sha(payload):
                for key, header in [('etag','If-None-Match'), ('last_modified','If-Modified-Since')]:
                    if isinstance(metadata.get(key),str) and metadata[key]: headers[header]=metadata[key]
        except (OSError, ValueError, KeyError, TypeError): pass
        request=Request('https://api.github.com/repos/caddyserver/caddy/releases?per_page=30',headers=headers)
        try:
            with urlopen(request,timeout=10) as response:
                payload=response.read(16*1024*1024+1)
                response_headers=response.headers
        except HTTPError as error:
            if error.code == 304 and cached is not None:
                error.close()
                return cached
            raise
        if len(payload)>16*1024*1024: raise ValueError(tr('官方版本列表超过大小限制'))
        versions=self.catalog_versions(json.loads(payload))
        metadata={'sha256':sha(payload),'etag':response_headers.get('ETag'),
                  'last_modified':response_headers.get('Last-Modified')}
        atomic(self.catalog,payload)
        atomic(metadata_path,json.dumps(metadata).encode())
        return versions

    def path(self,version,arch):
        if not re.fullmatch(r'v\d+\.\d+\.\d+',version) or arch not in ARCHES: raise ValueError(tr('版本或架构格式无效'))
        return self.root/version/arch/'caddy'

    def get(self,version,arch):
        path=self.path(version,arch)
        data=path.read_bytes()
        if sha(data)!=path.with_name('sha256').read_text(encoding='utf-8').strip(): raise ValueError(tr('本地 Caddy 缓存校验失败'))
        return data

    def ensure(self,version,arch,progress=lambda _:None,*,cancel=None):
        path=self.path(version,arch)
        try:
            cached=self.get(version,arch)
            progress(tr('使用本地缓存 {0} / {1}', version, arch))
            return cached
        except (OSError,ValueError):pass
        progress(tr('获取校验清单 {0} / {1}', version, arch))
        base=f'https://github.com/caddyserver/caddy/releases/download/{version}/'
        filename=f'caddy_{version[1:]}_linux_{arch}.tar.gz'
        checksums=fetch(base+f'caddy_{version[1:]}_checksums.txt',1024*1024,cancel=cancel).decode()
        match=[line.split()[0] for line in checksums.splitlines() if line.split() and line.split()[-1].lstrip('*')==filename]
        if len(match)!=1: raise ValueError(tr('官方校验清单缺少所需架构'))
        progress(tr('连接下载服务器 {0} / {1}', version, arch))
        payload=fetch(base+filename,progress=progress,cancel=cancel,label=f'Caddy {version} / {arch}',temporary=self.root.parent/'.tmp')
        progress(tr('校验并解压 {0} / {1}', version, arch))
        if hashlib.sha512(payload).hexdigest()!=match[0]: raise ValueError(tr('官方发行文件校验失败'))
        with tarfile.open(fileobj=io.BytesIO(payload),mode='r:gz') as archive:
            entry=archive.getmember('caddy')
            if not entry.isfile() or entry.size>150*1024*1024: raise ValueError(tr('Caddy 发行包格式无效'))
            data=archive.extractfile(entry).read()
        publish(path,data,self.root.parent/'.tmp',0o700);atomic(path.with_name('sha256'),sha(data).encode())
        return data

@dataclass
class Package:
    node_id: str
    name: str
    platform: str
    arch: str
    filename: str
    size: int
    digest: str

@dataclass
class Release:
    version: str
    directory: str
    created_at: str
    summary: dict
    metadata_sha256: str


@dataclass
class PackageSet:
    version: str
    caddy: str
    directory: str
    packages: list[Package]
    configuration: dict



def build_package(node, version, caddy, materials, binary=None):
    platform='debian' if node.platform=='debian_13' else 'openwrt'
    manifest=(f'format=1\nnode_id={node.id}\nplatform={platform}\nrelease={version}\ncaddy_version={caddy}\narch={node.arch}\nbinary_sha256={sha(binary) if binary else ""}\n').encode()
    files={'release/'+name:data for name,data in materials.items()}
    files['release/manifest']=manifest
    files['manage.sh']=HERE.joinpath('manage.sh').read_text(encoding='utf-8').replace('@PLATFORM@',platform).encode()
    files['service']=HERE.joinpath('smooth-caddy.service' if platform=='debian' else 'procd-service.sh').read_bytes()
    if binary is not None:
        files['caddy']=binary
        for notice in ('CADDY-LICENSE','GO-LICENSE'):
            files['release/licenses/'+notice]=HERE.joinpath(notice).read_bytes()
    files['release/SHA256SUMS']=''.join(f'{sha(data)}  {name[8:]}\n' for name,data in sorted(files.items()) if name.startswith('release/')).encode()
    files['SHA256SUMS']=''.join(f'{sha(data)}  {name}\n' for name,data in sorted(files.items())).encode()
    buf=io.BytesIO()
    with tarfile.open(fileobj=buf,mode='w:gz') as archive:
        for name,data in sorted(files.items()):
            entry=tarfile.TarInfo(name);entry.size=len(data);entry.mode=0o600
            archive.addfile(entry,io.BytesIO(data))
    payload=buf.getvalue()
    return HERE.joinpath('header.sh').read_text(encoding='utf-8').replace('@PAYLOAD_HASH@',sha(payload)).encode()+payload


class Releases:
    def __init__(self,application):
        self.app=application
        self.root=application.store.directory/'releases'
        self.cache=BinaryCache(application.store.directory)

    @contextmanager
    def lock(self):
        self.root.mkdir(parents=True,exist_ok=True,mode=0o700)
        with FileLock(self.root/'.lock'):
            yield

    def directory(self, item):
        relative=Path(item.directory)
        allowed=('releases',) if isinstance(item,Release) else ('tasks','packages')
        if len(relative.parts)!=2 or relative.parts[0] not in allowed or relative.parts[1] in ('.','..'):
            raise ValueError(tr('批次目录无效'))
        base = self.app.store.directory if isinstance(item,Release) else (self.app.store.temporary if relative.parts[0]=='tasks' else self.app.store.exports)
        path=base/relative
        if not path.resolve().is_relative_to(base.resolve()):raise ValueError(tr('批次目录超出数据目录'))
        if isinstance(item,Release) and relative.parts[1]!=item.version:raise ValueError(tr('批次目录与标识不符'))
        return path

    def list(self):
        path=self.root/'index.json'
        if not path.exists():return []
        value=json.loads(path.read_text(encoding='utf-8'))
        if value['format']!=3:raise ValueError(tr('配置批次索引格式不受支持'))
        result=[Release(**entry) for entry in value['releases']]
        for batch in result:self.directory(batch)
        return result

    def _index(self, batches):
        atomic(self.root/'index.json',json.dumps({'format':3,'releases':[asdict(b) for b in batches]},ensure_ascii=False,indent=2).encode())

    def load(self,batch):
        from .models import Configuration
        directory=self.directory(batch)
        payload=(directory/'metadata.json').read_bytes()
        if sha(payload)!=batch.metadata_sha256:raise ValueError(tr('配置批次 metadata 校验失败'))
        metadata=json.loads(payload)
        if type(metadata['format']) is not int or metadata['format'] not in (1,2,3,4) or metadata['version']!=batch.version:raise ValueError(tr('配置批次格式无效'))
        if metadata['format'] == 1:
            from .migrations import legacy_configuration
            config = legacy_configuration(metadata['configuration'])
        elif metadata['format'] == 2:
            from .migrations import configuration_v3
            config = configuration_v3(metadata['configuration'])
        elif metadata['format'] == 3:
            from .migrations import configuration_v4
            config = configuration_v4(metadata['configuration'])
        else:
            config = Configuration.from_dict(metadata['configuration'])
        materials={node.id:{} for node in config.nodes}
        for entry in metadata['files']:
            relative=Path(entry['path'])
            if relative.is_absolute() or '..' in relative.parts or len(relative.parts)<2:raise ValueError(tr('配置文件路径无效'))
            path=directory/relative
            if not path.resolve().is_relative_to(directory.resolve()):raise ValueError(tr('配置文件超出批次目录'))
            from cryptography.fernet import InvalidToken
            try:content=self.app.security.batch_cipher().decrypt(path.read_bytes())
            except InvalidToken:raise ValueError(tr('配置文件解密失败或已损坏：')+entry['path']) from None
            if len(content)!=entry['size'] or sha(content)!=entry['sha256']:raise ValueError(tr('配置文件缺失或损坏：')+entry['path'])
            materials[relative.parts[0]][Path(*relative.parts[1:]).as_posix()]=content
        return config,materials

    def check(self,batch):
        self.load(batch)
        return batch

    def create(self,progress=lambda _:None,*,task_progress=lambda _:None,cancel=None,config=None,public_materials=None):
        self.app.security.require()
        from .models import configuration_errors
        config=config or self.app.snapshot()
        if configuration_errors(config) or not config.nodes:raise ValueError(tr('请添加节点并修正配置错误'))
        plan=generation_plan(config);steps=plan.steps
        def step(index):
            if cancel is not None and cancel.is_set():raise TaskCancelled(tr('已停止生成配置批次'))
            task_progress(plan.event(plan.ids[index]));progress(steps[index])
        with self.lock():
            previous=self.list()
            while True:
                stamp=datetime.now().astimezone().strftime('%Y%m%d-%H%M%S')
                if not (self.root/stamp).exists():break
                if cancel is not None and cancel.is_set():raise TaskCancelled(tr('已停止'))
                time.sleep(.1)
            step(0)
            materials=generate(config,self.app.certificates,stamp,public_materials)
            work=Path(tempfile.mkdtemp(prefix='.prepare-',dir=self.app.store.temporary))
            try:
                files=[]
                for i,node in enumerate(config.nodes,1):
                    step(i)
                    for name,content in materials[node.id].items():
                        relative=(Path(node.id)/name).as_posix()
                        atomic(work/relative,self.app.security.batch_cipher().encrypt(content))
                        files.append({'path':relative,'size':len(content),'sha256':sha(content)})
                step(len(steps)-1)
                created=datetime.now().astimezone().isoformat(timespec='seconds')
                summary={key:[obj.name for obj in getattr(config,key)] for key in ('nodes','sites','regions')}
                metadata={'format':4,'version':stamp,'created_at':created,'configuration':config.to_dict(),'files':files}
                payload=json.dumps(metadata,ensure_ascii=False,indent=2).encode()
                atomic(work/'metadata.json',payload)
                batch=Release(stamp,'releases/'+stamp,created,summary,sha(payload))
                if cancel is not None and cancel.is_set():raise TaskCancelled(tr('已停止'))
                os.rename(work,self.root/stamp)
                try:self._index([batch]+previous)
                except BaseException:
                    shutil.rmtree(self.root/stamp);raise
                task_progress(plan.event('metadata',stamp,'success'))
                return batch
            finally:
                if work.exists():shutil.rmtree(work)

    def assemble(self,batch,version,include_binary=None,*,destination='packages',progress=lambda _:None,task_progress=lambda _:None,cancel=None,password=None):
        """Build from immutable batch materials. None means all nodes (offline export)."""
        from uuid import uuid4
        self.app.security.require()
        if destination not in ('packages','tasks'):raise ValueError(tr('输出类型无效'))
        if destination=='packages' and not password:raise ValueError(tr('请输入部署包导出口令'))
        if not re.fullmatch(r'v\d+\.\d+\.\d+',version):raise ValueError(tr('版本须为 vX.Y.Z'))
        config,materials=self.load(batch)
        included={n.id for n in config.nodes} if include_binary is None else set(include_binary)
        if not included.issubset({n.id for n in config.nodes}):raise ValueError(tr('节点集合无效'))
        plan=assembly_plan(config);steps=plan.steps
        def checkpoint():
            if cancel is not None and cancel.is_set():raise TaskCancelled(tr('已停止打包'))
        def report(value):checkpoint();progress(value)
        def step(i,note=''):checkpoint();task_progress(plan.event(plan.ids[i],note,'success' if note else ''))
        step(0,tr('无需下载') if not included else '')
        binaries={}
        for arch in sorted({n.arch for n in config.nodes if n.id in included}):
            binaries[arch]=self.cache.ensure(version,arch,report,cancel=cancel)
        step(0,tr('已就绪') if included else tr('无需下载'))
        folder=self.app.store.temporary/destination
        folder.mkdir(parents=True,exist_ok=True,mode=0o700)
        name=datetime.now().astimezone().strftime('%Y%m%d-%H%M%S')+'-'+uuid4().hex[:8]
        work=folder/name;work.mkdir(mode=0o700)
        try:
            packages=[]
            for i,node in enumerate(config.nodes,1):
                step(i)
                report(tr('打包 / ')+node.name)
                payload=build_package(node,batch.version,version,materials[node.id],binaries.get(node.arch) if node.id in included else None)
                if destination=='packages':
                    from .package_crypto import encrypt_package
                    payload=encrypt_package(payload,password)
                filename=node.id+'.run';atomic(work/filename,payload,0o700)
                packages.append(Package(node.id,node.name,node.platform,node.arch,filename,len(payload),sha(payload)))
                step(i,tr('已打包'))
            checkpoint()
            if destination == 'packages':
                target=self.app.store.exports/'packages'/name
                target.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
                try: os.replace(work,target)
                except OSError as error:
                    import errno
                    if error.errno != errno.EXDEV: raise
                    staged=target.with_name('.'+target.name)
                    try:
                        shutil.copytree(work,staged)
                        os.replace(staged,target)
                    finally: shutil.rmtree(staged,ignore_errors=True)
                    shutil.rmtree(work)
            return PackageSet(batch.version,version,(Path(destination)/name).as_posix(),packages,config.to_dict())
        except BaseException:
            shutil.rmtree(work,ignore_errors=True)
            raise

    def check_packages(self,packages):
        for package in packages.packages:
            if Path(package.filename).name!=package.filename:raise ValueError(tr('部署文件名无效'))
            data=(self.directory(packages)/package.filename).read_bytes()
            if len(data)!=package.size or sha(data)!=package.digest:raise ValueError(tr('部署文件损坏：')+package.filename)

    def cleanup(self,packages):
        if not packages.directory.startswith('tasks/'):raise ValueError(tr('只允许清理临时部署文件'))
        shutil.rmtree(self.directory(packages))

    def delete(self,version):
        self.app.security.require()
        with self.lock():
            batches=self.list();batch=next((b for b in batches if b.version==version),None)
            if batch is None:raise ValueError(tr('配置批次不存在'))
            path=self.directory(batch)
            if path.exists():shutil.rmtree(path)
            self._index([b for b in batches if b.version!=version])
