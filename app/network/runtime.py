"""Single-instance ownership and temporary workspace lifetime."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from .file_lock import FileLock
import shutil

class Runtime:
    def __init__(self, directory):
        self.directory = Path(directory).resolve()
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        try:
            self.lock = FileLock(self.directory / '.lock',blocking=False)
        except BlockingIOError:
            raise ValueError('此 data 目录已有程序运行') from None
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='temp-cleanup')
        self.ready = self.executor.submit(self.clean)

    def clean(self):
        path = self.directory / '.tmp'
        if path.is_symlink(): path.unlink()
        elif path.exists(): shutil.rmtree(path)
        path.mkdir(mode=0o700)

    def close(self):
        try:
            self.executor.submit(self.clean).result()
        finally:
            self.executor.shutdown(wait=True)
            self.lock.close()
