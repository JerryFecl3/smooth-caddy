"""Atomic local file writes shared by caches and package generation."""
import os
import tempfile
from pathlib import Path

def atomic(path, data, mode=0o600):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    fd,tmp=tempfile.mkstemp(prefix='.'+path.name+'-',dir=path.parent)
    try:
        with os.fdopen(fd,'wb') as stream:
            if hasattr(os,"fchmod"):os.fchmod(stream.fileno(),mode)
            stream.write(data);stream.flush();os.fsync(stream.fileno())
        os.replace(tmp,path)
    finally:
        if os.path.exists(tmp): os.unlink(tmp)



def publish(path, data, temporary, mode=0o600):
    """Stage generated output before publishing a complete destination file."""
    temporary=Path(temporary);temporary.mkdir(parents=True,exist_ok=True,mode=0o700)
    with tempfile.TemporaryDirectory(dir=temporary, prefix='export-') as directory:
        staged=Path(directory)/'payload'
        atomic(staged,data,mode)
        path=Path(path);path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
        try: os.replace(staged,path)
        except OSError as error:
            import errno
            if error.errno != errno.EXDEV: raise
            atomic(path,staged.read_bytes(),mode)
