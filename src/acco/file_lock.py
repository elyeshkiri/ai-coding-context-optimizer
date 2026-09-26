"""Small cross-platform advisory file lock used by ACCO state stores."""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
import os
import time


@contextmanager
def locked_file(path: Path, *, timeout: float = 30.0):
    """Lock one byte of a private lock file on Windows or flock it on POSIX."""
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with path.open("a+b", buffering=0) as handle:
        if os.name == "nt":
            import msvcrt

            handle.seek(0, os.SEEK_END)
            if handle.tell() == 0:
                handle.write(b"0")
            handle.seek(0)
            deadline = time.monotonic() + timeout
            while True:
                try:
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                    break
                except OSError:
                    if time.monotonic() >= deadline:
                        raise TimeoutError(
                            f"timed out acquiring ACCO state lock: {path}"
                        )
                    time.sleep(0.02)
            try:
                yield
            finally:
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle, fcntl.LOCK_UN)
