"""Bounded streaming HTTP downloads with uniform cancellation and progress."""
from ..i18n import tr
import time
import tempfile
from pathlib import Path
from urllib.request import Request, urlopen
from .task_progress import DownloadProgress, TaskCancelled


def fetch(url, limit=100*1024*1024, progress=lambda _:None, *, cancel=None, label='', timeout=25, temporary=None):
    def checkpoint():
        if cancel is not None and cancel.is_set():raise TaskCancelled(tr('已停止下载'))
    checkpoint()
    headers={'User-Agent':'smooth-caddy','Accept':'application/vnd.github+json' if 'api.github.com/' in url else 'application/octet-stream'}
    if temporary is not None: Path(temporary).mkdir(parents=True,exist_ok=True,mode=0o700)
    with tempfile.SpooledTemporaryFile(max_size=0 if temporary else limit, dir=temporary) as staged, urlopen(Request(url,headers=headers),timeout=timeout) as response:
        if temporary is not None: staged.rollover()
        length=response.headers.get('Content-Length')
        total=int(length) if length and length.isdigit() and int(length)>0 else None
        if total is not None and total>limit:raise ValueError(tr('下载文件超过大小限制'))
        size=0;started=time.monotonic();last=started
        progress(DownloadProgress(label,0,total,0))
        while True:
            checkpoint()
            chunk=response.read(min(256*1024,limit+1-size))
            if not chunk:break
            staged.write(chunk);size+=len(chunk)
            if size>limit:raise ValueError(tr('下载文件超过大小限制'))
            now=time.monotonic()
            if now-last>=.1:
                progress(DownloadProgress(label,size,total,size/max(now-started,.001)));last=now
        checkpoint()
        if total is not None and size!=total:raise ValueError(tr('下载不完整，请重试'))
        progress(DownloadProgress(label,size,total,size/max(time.monotonic()-started,.001)))
        staged.seek(0)
        return staged.read()
