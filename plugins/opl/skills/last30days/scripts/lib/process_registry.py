"""Track helper subprocesses so an interrupted research run can stop them."""

from __future__ import annotations

import os
import signal
import threading

_child_pids: set[int] = set()
_lock = threading.Lock()


def register_child_pid(pid: int) -> None:
    with _lock:
        _child_pids.add(pid)


def unregister_child_pid(pid: int) -> None:
    with _lock:
        _child_pids.discard(pid)


def cleanup_children() -> None:
    with _lock:
        pids = list(_child_pids)
    for pid in pids:
        try:
            if hasattr(os, "killpg"):
                os.killpg(os.getpgid(pid), signal.SIGTERM)
            else:
                os.kill(pid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError, OSError):
            continue
