"""Small advisory file lock for Linux and Windows."""
import os
import time

class FileLock:
    def __init__(self, path, *, blocking=True):
        self.file=open(path,'a+b')
        try:
            if os.name=='nt':
                import msvcrt
                self.file.seek(0,2)
                if self.file.tell()==0:self.file.write(b'\0');self.file.flush()
                while True:
                    self.file.seek(0)
                    try:msvcrt.locking(self.file.fileno(),msvcrt.LK_NBLCK,1);break
                    except OSError:
                        if not blocking:raise BlockingIOError('lock occupied') from None
                        time.sleep(.05)
            else:
                import fcntl
                fcntl.flock(self.file,fcntl.LOCK_EX|(0 if blocking else fcntl.LOCK_NB))
        except BaseException:
            self.file.close();raise
    def close(self):self.file.close()
    def __enter__(self):return self
    def __exit__(self,*exc):self.close()
