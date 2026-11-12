"""Build, check and repair `~/.laris/.venv` with `uv`, silently and under a file lock.

States: `ready`, `missing`, `broken`, `outdated`, `building`, `failed`. `ensure()` is what a tool
calls before it uses the sandbox: it returns at once when the sandbox is ready, waits when another
session is building it, and builds it otherwise (into `.venv.building`, renamed into place, so a
crash never leaves a half-built sandbox). A failure is a state with a plain message, never an
exception: the rest of `laris` keeps working.
"""

import hashlib
import json
import os
import shutil
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence

MARKER = ".laris-sandbox.json"
SAFE_ENV = (
    "HOME",
    "USER",
    "LOGNAME",
    "LANG",
    "LC_ALL",
    "LC_CTYPE",
    "TERM",
    "TMPDIR",
    "SHELL",
    "TZ",
)


def _lock(handle: Any) -> None:
    """Exclusive lock on an open file, blocking: flock on POSIX, msvcrt on Windows."""
    if sys.platform == "win32":
        import msvcrt

        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)  # retries for about 10 s, then raises
    else:
        import fcntl

        fcntl.flock(handle, fcntl.LOCK_EX)


def _unlock(handle: Any) -> None:
    if sys.platform == "win32":
        import msvcrt

        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
    else:
        import fcntl

        fcntl.flock(handle, fcntl.LOCK_UN)


@dataclass
class SandboxState:
    state: str
    detail: str = ""
    python: str = ""
    packages: List[str] = field(default_factory=list)

    def hint(self) -> str:
        """A few words for the status line; empty when there is nothing to say."""
        return {
            "building": "sandbox: preparing…",
            "failed": f"sandbox: unavailable ({self.detail})",
        }.get(self.state, "")


Runner = Callable[..., "subprocess.CompletedProcess[str]"]


def find_uv(environ: Optional[Mapping[str, str]] = None) -> Optional[str]:
    """The bundled `uv` (the launcher sets LARIS_UV), else one on PATH."""
    env = os.environ if environ is None else environ
    found = env.get("LARIS_UV")
    if found and Path(found).is_file():
        return found
    return shutil.which("uv", path=env.get("PATH"))


def settings_digest(sandbox: Mapping[str, Any]) -> str:
    keys = {k: sandbox.get(k) for k in ("python", "packages", "indexUrl", "pythonSource")}
    return hashlib.sha256(json.dumps(keys, sort_keys=True).encode("utf-8")).hexdigest()[:16]


class SandboxManager:
    def __init__(
        self,
        home: Path,
        sandbox: Optional[Mapping[str, Any]] = None,
        engine_version: str = "0",
        uv: Optional[str] = None,
        runner: Optional[Runner] = None,
        environ: Optional[Mapping[str, str]] = None,
    ) -> None:
        self.home = Path(home)
        self.cfg: Dict[str, Any] = {
            "python": "3.12", "packages": [], "indexUrl": "", "pythonSource": "",
            **(sandbox or {}),
        }  # fmt: skip
        self.engine_version = engine_version
        self.environ = dict(os.environ if environ is None else environ)
        self.uv = uv if uv is not None else find_uv(self.environ)
        self._run: Runner = runner or subprocess.run  # type: ignore[assignment]
        self.venv = self.home / ".venv"
        self.python_dir = self.home / "python"
        self.lock_path = self.home / ".sandbox.lock"
        self._building = threading.Event()
        self._thread_lock = threading.Lock()
        self.last_failure = ""

    # -- paths -----------------------------------------------------------------------------
    @property
    def bin(self) -> Path:
        return self.venv / ("Scripts" if sys.platform == "win32" else "bin")

    @property
    def python(self) -> Path:
        return self.bin / ("python.exe" if sys.platform == "win32" else "python")

    # -- checking --------------------------------------------------------------------------
    def _probe(self, args: Sequence[str], timeout: float = 20.0) -> Optional[str]:
        try:
            done = self._run(
                [str(self.python), *args], capture_output=True, text=True, timeout=timeout,
                env={**self.environ, "PYTHONNOUSERSITE": "1"}, check=False,
            )  # fmt: skip
        except (OSError, subprocess.SubprocessError):
            return None
        return done.stdout.strip() if done.returncode == 0 else None

    def check(self) -> SandboxState:
        """Marker, interpreter and pip, without building anything."""
        if self._building.is_set():
            return SandboxState("building")
        if not self.venv.exists():
            return (
                SandboxState("failed", self.last_failure)
                if self.last_failure
                else SandboxState("missing")
            )
        marker = self._read_marker()
        if self._probe(["-c", "import sys;print(sys.version_info[0])"]) is None:
            return SandboxState("broken", "the interpreter does not run")
        if self._probe(["-m", "pip", "--version"]) is None:
            return SandboxState("broken", "pip is missing")
        if marker is None:
            return SandboxState("broken", "no marker")
        if marker.get("engine") != self.engine_version or marker.get("digest") != settings_digest(
            self.cfg
        ):
            return SandboxState("outdated", "engine version or sandbox settings changed")
        return SandboxState(
            "ready", python=str(marker.get("python", "")), packages=list(self.cfg["packages"])
        )

    def _read_marker(self) -> Optional[Dict[str, Any]]:
        try:
            data = json.loads((self.venv / MARKER).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        return data if isinstance(data, dict) else None

    # -- building --------------------------------------------------------------------------
    def ensure(self) -> SandboxState:
        """Ready sandbox, or the reason there is none. Waits for another session's build."""
        state = self.check()
        if state.state == "ready":
            return state
        with self._thread_lock:  # one build at a time inside this process …
            self.home.mkdir(parents=True, exist_ok=True)
            self._building.set()
            try:
                with open(self.lock_path, "a+") as handle:  # … and across processes
                    _lock(handle)
                    try:
                        self._building.clear()
                        state = self.check()  # another session may have built it meanwhile
                        if state.state == "ready":
                            return state
                        self._building.set()
                        return self._build()
                    finally:
                        _unlock(handle)
            finally:
                self._building.clear()

    def _uv(
        self,
        args: Sequence[str],
        timeout: float = 600.0,
        extra_env: Optional[Dict[str, str]] = None,
    ):
        assert self.uv is not None
        env = {**self.environ, **(extra_env or {})}
        return self._run(
            [self.uv, *args], capture_output=True, text=True, timeout=timeout, env=env, check=False
        )

    def _fail(self, message: str) -> SandboxState:
        shutil.rmtree(self.home / ".venv.building", ignore_errors=True)  # never keep a half build
        self.last_failure = message
        return SandboxState("failed", message)

    def _build(self) -> SandboxState:
        if self.uv is None:
            return self._fail("the uv program was not found; the sandbox needs it")
        building = self.home / ".venv.building"
        shutil.rmtree(building, ignore_errors=True)
        shutil.rmtree(self.venv, ignore_errors=True)  # missing, broken or outdated: start clean
        wanted = str(self.cfg["python"])
        source = str(self.cfg["pythonSource"])
        env = {"UV_PYTHON_INSTALL_DIR": str(self.python_dir), "UV_NO_CONFIG": "1"}
        try:
            if source:  # a configured source: uv downloads and verifies a standalone Python
                env["UV_PYTHON_INSTALL_MIRROR"] = source
                got = self._uv(["python", "install", wanted], extra_env=env)
                if got.returncode != 0:
                    return self._fail(f"could not fetch Python {wanted} from the configured source")
            attempt = self._uv(
                ["venv", "--python", wanted, "--no-python-downloads", str(building)], extra_env=env
            )
            if attempt.returncode != 0 and not source:  # else any suitable system Python
                attempt = self._uv(
                    ["venv", "--python", "3", "--no-python-downloads", str(building)], extra_env=env
                )
            if attempt.returncode != 0:
                return self._fail(
                    f"no Python {wanted} (or any system Python 3) is available, and no "
                    "sandbox.pythonSource is configured; the rest of laris keeps working"
                )
            py = building / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
            if not self._pip_present(py, env):
                return self._fail("pip could not be installed into the sandbox (offline?)")
            packages = [str(p) for p in self.cfg["packages"]]
            if packages:
                index = ["--index-url", str(self.cfg["indexUrl"])] if self.cfg["indexUrl"] else []
                got = self._uv(
                    ["pip", "install", "--python", str(py), *index, *packages], extra_env=env
                )
                if got.returncode != 0:
                    return self._fail("sandbox.packages could not be installed (offline?)")
            version = self._run(
                [str(py), "-c", "import sys;print('.'.join(map(str, sys.version_info[:3])))"],
                capture_output=True, text=True, timeout=20, check=False,
            ).stdout.strip()  # fmt: skip
            (building / MARKER).write_text(
                json.dumps(
                    {"engine": self.engine_version, "digest": settings_digest(self.cfg),
                     "python": version, "built": time.time()}
                ),
                encoding="utf-8",
            )  # fmt: skip
            building.rename(self.venv)
        except (OSError, subprocess.SubprocessError) as exc:
            shutil.rmtree(building, ignore_errors=True)
            return self._fail(f"building the sandbox failed: {type(exc).__name__}")
        self.last_failure = ""
        self._building.clear()
        return self.check()

    def _pip_present(self, py: Path, env: Dict[str, str]) -> bool:
        def has_pip() -> bool:
            done = self._run(
                [str(py), "-m", "pip", "--version"], capture_output=True, text=True, timeout=30,
                env={**self.environ, "PYTHONNOUSERSITE": "1"}, check=False,
            )  # fmt: skip
            return done.returncode == 0

        if has_pip():
            return True
        self._run([str(py), "-m", "ensurepip", "--upgrade"], capture_output=True, text=True,
                  timeout=120, check=False)  # fmt: skip
        if has_pip():
            return True
        self._uv(["pip", "install", "--python", str(py), "pip"], extra_env=env)
        return has_pip()

    def reset(self) -> SandboxState:
        """`/sandbox reset`: throw it away and build again."""
        with self._thread_lock:
            shutil.rmtree(self.venv, ignore_errors=True)
            self.last_failure = ""
        return self.ensure()

    # -- background ------------------------------------------------------------------------
    def start_background(self, on_state: Callable[[SandboxState], None]) -> threading.Thread:
        """Check now and build when needed, off the main thread; `on_state` hears each change."""

        def work() -> None:
            state = self.check()
            on_state(state)
            if state.state != "ready":
                on_state(SandboxState("building"))
                on_state(self.ensure())

        thread = threading.Thread(target=work, daemon=True, name="sandbox")
        thread.start()
        return thread

    def describe(self) -> str:
        state = self.check()
        lines = [f"sandbox: {state.state}" + (f" ({state.detail})" if state.detail else "")]
        lines.append(f"location: {self.venv}")
        if state.python:
            lines.append(f"python: {state.python}")
        if self.cfg["packages"]:
            lines.append("packages: " + ", ".join(map(str, self.cfg["packages"])))
        return "\n".join(lines)


def command_env(
    manager: SandboxManager,
    extra: Optional[Mapping[str, str]] = None,
    inherit: bool = False,
    environ: Optional[Mapping[str, str]] = None,
) -> Dict[str, str]:
    """The environment commands the agent runs see: the sandbox first on PATH, VIRTUAL_ENV set,
    `PIP_REQUIRE_VIRTUALENV=1`, no user site. Without `inherit` only a short safe list of the
    user's variables passes (no tokens, no cloud credentials); `extra` is `settings.env`."""
    source = os.environ if environ is None else environ
    env: Dict[str, str] = (
        dict(source) if inherit else {k: source[k] for k in SAFE_ENV if k in source}
    )
    base_path = source.get("PATH", "/usr/local/bin:/usr/bin:/bin")
    env.update(extra or {})
    env["PATH"] = os.pathsep.join([str(manager.bin), base_path])
    env["VIRTUAL_ENV"] = str(manager.venv)
    env["PIP_REQUIRE_VIRTUALENV"] = "1"
    env["PYTHONNOUSERSITE"] = "1"
    env.pop("PYTHONHOME", None)
    return env


def sandbox_command(manager: SandboxManager, argument: str = "") -> str:
    """The text of `/sandbox` and `/sandbox reset` (the slash registry calls this)."""
    word = argument.strip().lower()
    if word == "reset":
        state = manager.reset()
        return (
            "sandbox rebuilt\n" + manager.describe()
            if state.state == "ready"
            else manager.describe()
        )
    if word:
        return "usage: /sandbox [reset]"
    return manager.describe()


def make_sandbox(home: Path, settings_file: Path, engine_version: str) -> SandboxManager:
    """The manager for this user's settings; an unreadable settings file means the defaults."""
    from laris.shared.config import settings as settings_mod

    try:
        sandbox = settings_mod.validate(settings_mod.read_raw(settings_file)).sandbox.model_dump()
    except settings_mod.SettingsError:
        sandbox = {}
    return SandboxManager(home, sandbox, engine_version)
