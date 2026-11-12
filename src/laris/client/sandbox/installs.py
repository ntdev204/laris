"""Which package installs are allowed (SR-C5, SR-C8).

An install into the sandbox is allowed without a prompt. Any other install is denied by a
built-in rule that settings cannot widen: system Python, `pip --user`, `--target`/`--prefix`/
`--root`, `--break-system-packages`, another interpreter named by path, `pipx`, `conda`, a system
package manager, or the program's own files. `classify_install` reads one shell command line
(simple pipelines and `&&` lists are split) and says what each install would do.
"""

import re
import shlex
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

_SPLIT = re.compile(r"\s*(?:&&|\|\||;|\|)\s*")
_PIP_FLAGS_OUTSIDE = (
    "--user", "--target", "-t", "--prefix", "--root", "--break-system-packages",
    "--no-require-virtualenv", "--system",
)  # fmt: skip
_SYSTEM_MANAGERS = ("apt", "apt-get", "dnf", "yum", "pacman", "brew", "apk", "zypper", "snap")
_OTHER_INSTALLERS = ("pipx", "conda", "mamba", "micromamba", "poetry", "pdm", "npm", "gem", "cargo")


@dataclass
class InstallCheck:
    """`kind`: `none` (not an install), `sandbox` (allowed), `outside` (denied)."""

    kind: str
    reason: str = ""
    command: str = ""


def _words(segment: str) -> List[str]:
    try:
        return shlex.split(segment)
    except ValueError:
        return segment.split()


def _is_pip(words: List[str]) -> Optional[int]:
    """Index of the `install` word when this is a pip or uv-pip install, else None."""
    if not words:
        return None
    head = Path(words[0]).name
    if head in ("pip", "pip3") or re.fullmatch(r"pip3?\.\d+", head):
        rest = words[1:]
        return 1 + rest.index("install") if "install" in rest else None
    if head == "uv" and words[1:3] == ["pip", "install"]:
        return 3
    if re.fullmatch(r"python[\d.]*", head) and words[1:4] == ["-m", "pip", "install"]:
        return 4
    if head == "uv" and words[1:2] in (["add"], ["sync"]) and False:
        return None
    return None


def classify_install(command: str, sandbox_bin: Path) -> InstallCheck:
    """What `command` would install and where. `sandbox_bin` is the sandbox's `bin/` folder."""
    sandbox = str(sandbox_bin)
    for segment in _SPLIT.split(command.strip()):
        words = _words(segment)
        while words and (words[0] in ("sudo", "env", "time", "nohup") or "=" in words[0]):
            if words[0] == "sudo":
                return InstallCheck("outside", "sudo is never allowed for installs", segment)
            words = words[1:]
        if not words:
            continue
        head = Path(words[0]).name
        if head in _SYSTEM_MANAGERS and "install" in words:
            return InstallCheck("outside", f"{head} installs outside the sandbox", segment)
        if head in _OTHER_INSTALLERS and any(w in words for w in ("install", "add", "global")):
            return InstallCheck("outside", f"{head} does not install into the sandbox", segment)
        if (
            head == "uv"
            and words[1:2] in (["add"], ["tool"])
            or head == "uv"
            and "sync" in words[1:2]
        ):
            return InstallCheck(
                "outside", "uv project/tool installs are outside the sandbox", segment
            )
        install_at = _is_pip(words)
        if install_at is None:
            continue
        if "/" in words[0] and not words[0].startswith(sandbox):
            return InstallCheck("outside", "another interpreter or pip is named by path", segment)
        flags = words[install_at:]
        for flag in flags:
            bare = flag.split("=", 1)[0]
            if bare in _PIP_FLAGS_OUTSIDE:
                return InstallCheck("outside", f"{bare} installs outside the sandbox", segment)
            if bare == "--python" and not flag.split("=", 1)[-1].startswith(sandbox):
                return InstallCheck("outside", "--python points outside the sandbox", segment)
        if any(w in ("-e", "--editable") for w in flags):
            return InstallCheck(
                "outside", "editable installs link to files outside the sandbox", segment
            )
        return InstallCheck("sandbox", "installs into the sandbox", segment)
    return InstallCheck("none")
