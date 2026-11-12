"""The automatic sandbox `~/.laris/.venv` (SR-C8)."""

from laris.client.sandbox.installs import InstallCheck, classify_install
from laris.client.sandbox.manager import (
    SandboxManager,
    SandboxState,
    command_env,
    make_sandbox,
    sandbox_command,
)

__all__ = [
    "InstallCheck",
    "SandboxManager",
    "SandboxState",
    "classify_install",
    "command_env",
    "make_sandbox",
    "sandbox_command",
]
