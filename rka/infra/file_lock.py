"""Small cross-platform advisory file-lock primitives."""

from __future__ import annotations

import errno
import os

if os.name == "nt":
    import msvcrt
else:
    import fcntl


def try_acquire_exclusive(lock_fd: int) -> bool:
    """Try to acquire an exclusive lock without waiting.

    Return ``False`` only when another process or file descriptor currently
    owns the lock. Unexpected filesystem errors still propagate to the caller.
    """
    if os.name == "nt":
        # ``msvcrt.locking`` locks a byte range from the current file position
        # and permits that range to extend beyond the end of an empty lock file.
        os.lseek(lock_fd, 0, os.SEEK_SET)
        try:
            msvcrt.locking(lock_fd, msvcrt.LK_NBLCK, 1)
        except OSError as exc:
            contended_errnos = {errno.EACCES, errno.EAGAIN}
            if hasattr(errno, "EDEADLK"):
                contended_errnos.add(errno.EDEADLK)
            # CPython normally maps ERROR_LOCK_VIOLATION to EACCES. Retain the
            # native code as a fallback for Windows runtime variations.
            if exc.errno in contended_errnos or getattr(exc, "winerror", None) == 33:
                return False
            raise
        return True

    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        return False
    return True


def release_exclusive(lock_fd: int) -> None:
    """Release a lock previously acquired by :func:`try_acquire_exclusive`."""
    if os.name == "nt":
        os.lseek(lock_fd, 0, os.SEEK_SET)
        msvcrt.locking(lock_fd, msvcrt.LK_UNLCK, 1)
        return
    fcntl.flock(lock_fd, fcntl.LOCK_UN)
