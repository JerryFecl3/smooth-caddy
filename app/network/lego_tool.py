"""Local, verified lego v5 tool management; no target-node installation."""
from ..i18n import tr
import hashlib
import io
import json
import os
from pathlib import Path
import platform
import re
import subprocess
import tarfile
import zipfile
import threading
from .files import atomic
from .downloads import fetch
from .task_progress import TaskStep, TaskCancelled

class LegoTool:
    def __init__(self,directory):
        self.root=Path(directory)/'tool_lego';self.binary=self.root/('lego.exe' if platform.system()=='Windows' else 'lego')
        self.lock=threading.Lock()

    def version(self,required=False):
        if not self.binary.is_file():
            if required:raise ValueError(tr('请先在 lego 管理中下载工具'))
            return tr('未安装')
        result=subprocess.run([str(self.binary),'--version'],capture_output=True,text=True,timeout=10)
        match=re.search(r'\bv?(5\.\d+\.\d+)\b',result.stdout)
        if result.returncode or not match:raise ValueError(tr('lego 不可用，需要兼容的 v5 版本'))
        return 'v'+match[1]

    def latest(self):
        value=json.loads(fetch('https://api.github.com/repos/go-acme/lego/releases/latest',limit=4*1024*1024))
        if not re.fullmatch(r'v5\.\d+\.\d+',value['tag_name']):raise ValueError(tr('最新版本不属于兼容的 lego v5 系列'))
        return value

    def install(self,release,progress=lambda _:None,task_progress=lambda _:None,cancel=None):
        if not self.lock.acquire(blocking=False):raise ValueError(tr('lego 更新正在执行'))
        try:
            steps=(tr('下载 lego'),tr('校验文件'),tr('更新工具'))
            def step(index,note=''):
                if cancel is not None and cancel.is_set():raise TaskCancelled(tr('已停止下载'))
                task_progress(TaskStep(steps,index,note,state='success' if note else ''))
            version=release['tag_name']
            if not re.fullmatch(r'v5\.\d+\.\d+',version):raise ValueError(tr('不支持的 lego 版本'))
            system=platform.system().lower();machine=platform.machine().lower()
            arch={'x86_64':'amd64','amd64':'amd64','aarch64':'arm64','arm64':'arm64','i386':'386','i686':'386','armv7l':'armv7'}.get(machine,machine)
            if system not in ('linux','darwin','windows'):raise ValueError(tr('当前平台不受支持'))
            name=f'lego_{version}_{system}_{arch}.'+('zip' if system=='windows' else 'tar.gz')
            assets={a['name']:a['browser_download_url'] for a in release['assets']}
            sums=next((key for key in assets if key.endswith('_checksums.txt')),None)
            if name not in assets or not sums:raise ValueError(tr('官方版本缺少当前平台文件或校验清单'))
            def url(key):
                value=assets[key]
                prefix=f'https://github.com/go-acme/lego/releases/download/{version}/'
                if not value.startswith(prefix):raise ValueError(tr('非官方 lego 下载地址'))
                return value
            step(0)
            checksums=fetch(url(sums),cancel=cancel,limit=1024*1024).decode()
            data=fetch(url(name),limit=256*1024*1024,progress=progress,cancel=cancel,label='lego',temporary=self.root.parent/'.tmp')
            step(0,tr('已下载'));step(1)
            entries={p[1].lstrip('*'):p[0] for line in checksums.splitlines() if len(p:=line.split())==2}
            if entries.get(name)!=hashlib.sha256(data).hexdigest():raise ValueError(tr('lego 文件校验失败'))
            if system=='windows':
                with zipfile.ZipFile(io.BytesIO(data)) as archive:
                    members=[m for m in archive.infolist() if Path(m.filename).name=='lego.exe' and not m.is_dir()]
                    if len(members)!=1 or members[0].file_size>256*1024*1024:raise ValueError(tr('lego 压缩包格式无效'))
                    payload=archive.read(members[0])
            else:
                with tarfile.open(fileobj=io.BytesIO(data),mode='r:gz') as archive:
                    members=[m for m in archive.getmembers() if Path(m.name).name=='lego' and m.isfile()]
                    if len(members)!=1 or members[0].size>256*1024*1024:raise ValueError(tr('lego 压缩包格式无效'))
                    payload=archive.extractfile(members[0]).read()
            step(1,tr('已通过'));step(2)
            self.root.mkdir(parents=True,exist_ok=True,mode=0o700)
            temporary=self.root.parent/'.tmp'
            temporary.mkdir(parents=True,exist_ok=True,mode=0o700)
            candidate=temporary/('lego-candidate.exe' if system=='windows' else 'lego-candidate')
            try:
                atomic(candidate,payload,0o700)
                result=subprocess.run([str(candidate),'--version'],capture_output=True,text=True,timeout=10)
                if result.returncode or not re.search(r'\bv?'+re.escape(version[1:])+r'\b',result.stdout):raise ValueError(tr('lego 版本校验失败'))
                if cancel is not None and cancel.is_set():raise TaskCancelled(tr('已停止更新'))
                os.replace(candidate,self.binary)
            finally:candidate.unlink(missing_ok=True)
            task_progress(TaskStep(steps,2,version,state='success'));return version
        finally:self.lock.release()
