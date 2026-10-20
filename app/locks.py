"""Verrou d'écriture : threads du processus et autres processus."""

import threading
from contextlib import contextmanager

try:
    import fcntl
except ImportError:  # Windows
    fcntl = None

try:
    import msvcrt
except ImportError:
    msvcrt = None

from .errors import AppError


class OpLock:
    def __init__(self, path):
        self.path = path
        self._thread = threading.Lock()

    @contextmanager
    def acquire(self, wait=5):
        if not self._thread.acquire(timeout=wait):
            raise AppError(409, "conflict", "Une opération de maintenance est en cours.")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle = open(self.path, "a+")
        held = False
        try:
            try:
                if fcntl is not None:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    held = True
                elif msvcrt is not None:
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                    held = True
            except (BlockingIOError, OSError):
                raise AppError(409, "conflict", "Une opération de maintenance est en cours.")
            yield
        finally:
            if held and fcntl is not None:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            elif held and msvcrt is not None:
                try:
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                except OSError:
                    pass
            handle.close()
            self._thread.release()
