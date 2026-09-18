"""A cross-platform single-instance lock.

Two copies of the program would fight over the serial port, and the loser would
report the chamber as dead.
"""

from __future__ import annotations

import atexit
from pathlib import Path

_handle = None


def lock_path() -> Path:
    folder = Path.home() / ".espec-burn-in"
    folder.mkdir(parents=True, exist_ok=True)
    return folder / "instance.lock"


def acquire_lock() -> bool:
    global _handle
    path = lock_path()
    try:
        _handle = path.open("w")
    except OSError:
        return True  # cannot lock; do not block the user over it

    try:
        if hasattr(__import__("os"), "name") and __import__("os").name == "nt":
            import msvcrt

            msvcrt.locking(_handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(_handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        _handle.close()
        _handle = None
        return False

    atexit.register(release_lock)
    return True


def release_lock() -> None:
    global _handle
    if _handle is not None:
        try:
            _handle.close()
        except OSError:
            pass
        _handle = None
