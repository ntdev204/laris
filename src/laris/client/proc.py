"""Process helpers that behave the same on POSIX and Windows."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
from typing import Any, Dict


def new_group_options() -> Dict[str, Any]:
    """`Popen` options that give the child its own process group, so a timeout can end its tree."""
    if sys.platform == "win32":
        return {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
    return {"start_new_session": True}


def kill_tree(proc: "subprocess.Popen[Any]") -> None:
    """Kill the child and everything it started. Never raises for a process that is already gone."""
    try:
        if sys.platform == "win32":
            subprocess.run(
                ["taskkill", "/T", "/F", "/PID", str(proc.pid)], capture_output=True, check=False
            )
        else:
            os.killpg(proc.pid, signal.SIGKILL)
    except (ProcessLookupError, OSError):
        pass
