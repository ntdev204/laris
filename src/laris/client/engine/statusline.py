"""The values of the status line (SR-C1) and of `/cost` and `/context`.

One source for all three, so what the front end draws, what `/cost` prints and what the server
account route reports cannot drift apart: model and mode from the session, context use from the
agent's own estimator, tokens left from `/v1/laris/account`, the git branch of the working folder
and the sandbox state. Nothing here raises: a part that cannot be read is `None`.
"""

import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Dict, Optional

ACCOUNT_TTL_S = 30.0


def git_branch(cwd: Path, timeout: float = 2.0) -> Optional[str]:
    """The current branch (or a short commit id when detached); None outside a repository."""
    try:
        done = subprocess.run(
            ["git", "-C", str(cwd), "branch", "--show-current"],  # also right before a first commit
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    name = done.stdout.strip()
    if done.returncode != 0:
        return None
    if name:
        return name
    try:
        short = subprocess.run(
            ["git", "-C", str(cwd), "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            timeout=timeout,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return None
    return short or None


class Account:
    """`/v1/laris/account`, fetched lazily and cached; a failure keeps the last known value."""

    def __init__(self, chat: Any, ttl: float = ACCOUNT_TTL_S) -> None:
        self.chat = chat
        self.ttl = ttl
        self.value: Optional[Dict[str, Any]] = None
        self._at = 0.0
        self._lock = threading.Lock()

    def refresh(self, force: bool = False) -> Optional[Dict[str, Any]]:
        with self._lock:
            if not force and self.value is not None and time.monotonic() - self._at < self.ttl:
                return self.value
            runtime = self.chat.runtime
            if not runtime.config.model_api.base_url:
                return None
            try:
                info = runtime.server_client().get("/laris/account")
            except Exception:  # unreachable, unauthorised, bad answer: the status line goes on
                return self.value
            self.value, self._at = info, time.monotonic()
            return self.value


def context_use(chat: Any, conversation_id: str) -> Dict[str, Any]:
    usage = chat.usage(conversation_id)
    tokens, window = int(usage["tokens"]), int(usage["window"])
    percent = round(100 * tokens / window) if window else None
    return {"tokens": tokens, "window": window, "percent": percent}


def collect(
    chat: Any,
    conversation_id: str,
    cwd: Path,
    sandbox_state: str,
    account: Optional[Dict[str, Any]],
    queued: int = 0,
) -> Dict[str, Any]:
    """The data of one `status` event of kind `line`."""
    try:
        context: Optional[Dict[str, Any]] = context_use(chat, conversation_id)
    except Exception:  # a status line must never break the session
        context = None
    left = account.get("tokens_left") if account else None
    return {
        "model": chat.runtime.config.model_api.model,
        "mode": str(chat.permissions.mode),
        "context": context,
        "tokens_left": left,
        "tokens_used": account.get("tokens_used") if account else None,
        "token_limit": account.get("token_limit") if account else None,
        "unlimited": bool(account) and left is None,
        "branch": git_branch(cwd),
        "sandbox": sandbox_state,
        "queued": queued,
    }
