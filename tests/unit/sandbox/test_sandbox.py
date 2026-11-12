import shutil
import sys
import threading
from pathlib import Path

import pytest

from laris.client.sandbox import SandboxManager, classify_install, command_env

UV = shutil.which("uv")


def test_command_env_puts_the_sandbox_first_and_drops_secrets(tmp_path):
    manager = SandboxManager(tmp_path, uv="uv", environ={})
    env = command_env(
        manager,
        {"X": "1"},
        environ={"PATH": "/usr/bin", "HOME": "/h", "AWS_SECRET_ACCESS_KEY": "s"},
    )
    assert env["PATH"].startswith(str(manager.bin)) and env["VIRTUAL_ENV"] == str(manager.venv)
    assert (
        env["PIP_REQUIRE_VIRTUALENV"] == "1"
        and env["X"] == "1"
        and "AWS_SECRET_ACCESS_KEY" not in env
    )
    inherited = command_env(manager, inherit=True, environ={"PATH": "/usr/bin", "FOO": "bar"})
    assert inherited["FOO"] == "bar"


@pytest.mark.parametrize(
    "command,kind",
    [
        ("pip install requests", "sandbox"),
        ("python -m pip install numpy && echo ok", "sandbox"),
        ("uv pip install rich", "sandbox"),
        ("pip install --user requests", "outside"),
        ("pip install --break-system-packages x", "outside"),
        ("pip install -t /tmp/x y", "outside"),
        ("pip install -e .", "outside"),
        ("/usr/bin/pip install x", "outside"),
        ("sudo pip install x", "outside"),
        ("apt-get install -y gcc", "outside"),
        ("pipx install black", "outside"),
        ("ls -la", "none"),
        ("echo pip install", "none"),
    ],
)
def test_install_classification(tmp_path, command, kind):
    assert classify_install(command, tmp_path / ".venv" / "bin").kind == kind


def test_missing_uv_is_a_state_not_an_exception(tmp_path):
    manager = SandboxManager(tmp_path, uv=None, environ={"PATH": ""})
    assert manager.check().state == "missing"
    state = manager.ensure()
    assert state.state == "failed" and "uv" in state.detail
    assert manager.check().state == "failed" and "unavailable" in manager.check().hint()


@pytest.mark.skipif(UV is None, reason="uv not installed")
def test_build_probe_repair_and_reset_with_a_temporary_home(tmp_path):
    manager = SandboxManager(
        tmp_path, {"python": f"{sys.version_info[0]}.{sys.version_info[1]}"}, "1", UV
    )
    state = manager.ensure()
    assert state.state == "ready", state
    assert manager.python.exists() and (tmp_path / ".venv" / ".laris-sandbox.json").exists()
    assert manager.check().state == "ready"
    # nothing leaks into the system or user site-packages
    assert not (Path(sys.prefix) / "lib").joinpath("laris-sandbox-marker").exists()
    # damaged: the interpreter disappears, the next ensure repairs it
    manager.python.unlink()
    assert manager.check().state == "broken"
    assert manager.ensure().state == "ready"
    # a new engine version or new settings means rebuild
    newer = SandboxManager(tmp_path, manager.cfg, "2", UV)
    assert newer.check().state == "outdated"
    assert newer.ensure().state == "ready"
    marker = (tmp_path / ".venv" / ".laris-sandbox.json").read_text()
    assert '"engine": "2"' in marker
    (tmp_path / ".venv" / "junk").write_text("x")
    assert newer.reset().state == "ready" and not (tmp_path / ".venv" / "junk").exists()


@pytest.mark.skipif(UV is None, reason="uv not installed")
def test_two_sessions_build_once(tmp_path):
    cfg = {"python": f"{sys.version_info[0]}.{sys.version_info[1]}"}
    calls = []
    import subprocess

    def counting(cmd, **kw):
        if "venv" in cmd:
            calls.append(cmd)
        return subprocess.run(cmd, **kw)

    managers = [SandboxManager(tmp_path, cfg, "1", UV, runner=counting) for _ in range(2)]
    results = []
    threads = [
        threading.Thread(target=lambda m=m: results.append(m.ensure().state)) for m in managers
    ]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert results == ["ready", "ready"] and len(calls) == 1


def test_offline_without_python_reports_clearly(tmp_path):
    import subprocess

    def refuse(cmd, **kw):
        return subprocess.CompletedProcess(cmd, 1, "", "no python")

    manager = SandboxManager(tmp_path, {"python": "3.99"}, "1", "uv", runner=refuse)
    state = manager.ensure()
    assert state.state == "failed" and "keeps working" in state.detail
    assert not (tmp_path / ".venv").exists() and not (tmp_path / ".venv.building").exists()


def test_sandbox_command_text(tmp_path):
    from laris.client.sandbox import sandbox_command

    manager = SandboxManager(tmp_path, uv=None, environ={"PATH": ""})
    assert "sandbox: missing" in sandbox_command(manager)
    assert sandbox_command(manager, "bogus").startswith("usage")
    assert "failed" in sandbox_command(manager, "reset")
