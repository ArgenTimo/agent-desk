"""One console per data directory, enforced by the kernel rather than by convention.

Two consoles on one database is every failure at once (_research/04_dogfooding_gaps.md, R1): each
start marks the other's running blocks failed, and each runs the loops that start agents, so one
queued task can become two. docs/adr/0003 says one process; this is the lock that makes it true.

`flock` rather than a pid file: the kernel drops it when the process dies, however it dies, so a
console killed with SIGKILL never leaves a stale lock for a human to delete.
"""

from __future__ import annotations

import fcntl
import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path


class AlreadyRunning(RuntimeError):
    """Another console holds this data directory."""


@contextmanager
def hold(data_dir: Path) -> Iterator[None]:
    data_dir.mkdir(parents=True, exist_ok=True)
    path = data_dir / ".lock"
    fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            holder = os.pread(fd, 32, 0).decode(errors="replace").strip() or "unknown"
            raise AlreadyRunning(
                f"another agent-desk console (pid {holder}) is already running on {data_dir}. "
                "Stop it, or start this one with AGENT_DESK_DATA_DIR pointing somewhere else."
            ) from None
        os.ftruncate(fd, 0)
        os.pwrite(fd, str(os.getpid()).encode(), 0)
        yield
    finally:
        os.close(fd)  # closing the descriptor is what releases the lock
