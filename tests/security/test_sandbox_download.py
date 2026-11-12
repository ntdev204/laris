"""A tampered sandbox download (SR-C5, SR-C8): what the client does when the Python or a package
it fetches is not what was promised.

Two layers. The manager must treat any failed fetch as "no sandbox" (never a half-built or
partly trusted one, never a silent fallback). And the real `uv` must refuse an archive whose hash
differs from the one it knows; that is run against a local mirror serving a tampered archive."""

import http.server
import io
import json
import os
import shutil
import subprocess
import tarfile
import threading

import pytest

from laris.client.sandbox import SandboxManager

UV = shutil.which("uv")


def completed(code=0, out="", err=""):
    return subprocess.CompletedProcess([], code, out, err)


class Recorder:
    """A stand-in for `subprocess.run` that fails chosen `uv` commands the way a tampered or
    unreachable download does."""

    def __init__(self, fail_on):
        self.fail_on = fail_on
        self.calls = []

    def __call__(self, cmd, **kwargs):
        self.calls.append((list(cmd), kwargs.get("env") or {}))
        text = " ".join(map(str, cmd))
        for needle in self.fail_on:
            if needle in text:
                return completed(1, "", "Hash mismatch for `cpython-3.12`")
        if "venv" in cmd:
            target = next(c for c in reversed(cmd) if str(c).endswith(".venv.building"))
            (__import__("pathlib").Path(target) / "bin").mkdir(parents=True, exist_ok=True)
        return completed(0, "3.12.0")


def manager(tmp_path, runner, **cfg):
    return SandboxManager(tmp_path / "home", cfg or None, "1", "uv", runner, {"PATH": ""})


def test_a_python_that_fails_its_hash_check_leaves_no_sandbox(tmp_path):
    run = Recorder(["python install"])
    m = manager(tmp_path, run, python="3.12", pythonSource="https://mirror.example")
    state = m.ensure()
    assert state.state == "failed" and "could not fetch Python" in state.detail
    assert not m.venv.exists() and not (m.home / ".venv.building").exists()
    assert not (m.venv / ".laris-sandbox.json").exists()
    assert m.check().state in ("missing", "failed")


def test_a_failed_fetch_from_a_configured_source_does_not_fall_back_to_another_python(tmp_path):
    run = Recorder(["python install"])
    manager(tmp_path, run, python="3.12", pythonSource="https://mirror.example").ensure()
    venv_calls = [c for c, _ in run.calls if "venv" in c]
    assert venv_calls == [], "a venv was made after the configured download failed"


def test_every_uv_call_ignores_configuration_files_and_the_mirror_is_only_the_configured_one(
    tmp_path,
):
    run = Recorder([])
    manager(tmp_path, run, python="3.12", pythonSource="https://mirror.example").ensure()
    assert run.calls
    for command, env in run.calls:
        if command and command[0] == "uv":
            assert env.get("UV_NO_CONFIG") == "1", command
            assert env.get("UV_PYTHON_INSTALL_DIR", "").startswith(str(tmp_path / "home")), command
    install = [env for c, env in run.calls if "install" in c and "python" in c]
    assert install and install[0]["UV_PYTHON_INSTALL_MIRROR"] == "https://mirror.example"


def test_a_package_that_fails_its_check_leaves_no_sandbox_and_no_half_build(tmp_path):
    run = Recorder(["pip install --python"])
    m = manager(tmp_path, run, python="3.12", packages=["rich"])
    state = m.ensure()
    assert state.state == "failed" and "packages" in state.detail
    assert not m.venv.exists() and not (m.home / ".venv.building").exists()
    assert "tampered" not in m.last_failure  # the message is ours, not the attacker's text


def test_a_failed_build_is_retried_not_remembered_as_good(tmp_path):
    run = Recorder(["python install"])
    m = manager(tmp_path, run, python="3.12", pythonSource="https://mirror.example")
    assert m.ensure().state == "failed"
    run.fail_on = []  # the mirror is fixed
    assert m.ensure().state in ("ready", "broken", "outdated", "failed")
    assert any("venv" in c for c, _ in run.calls)  # and a build was tried again


@pytest.mark.skipif(UV is None, reason="uv not installed")
def test_the_real_uv_refuses_a_tampered_python_archive(tmp_path):
    marker = tmp_path / "EXECUTED"
    archive = io.BytesIO()
    with tarfile.open(fileobj=archive, mode="w:gz") as tar:  # a well-formed archive, wrong content
        for name in ("python/bin/python3.12", "python/bin/python3"):
            body = f"#!/bin/sh\ntouch {marker}\nexit 1\n".encode()
            info = tarfile.TarInfo(name)
            info.size, info.mode = len(body), 0o755
            tar.addfile(info, io.BytesIO(body))
    payload, requested = archive.getvalue(), []

    class Mirror(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            requested.append(self.path)
            self.send_response(200)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, *args):
            pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Mirror)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        m = SandboxManager(
            tmp_path / "home",
            {"python": "3.12", "pythonSource": f"http://127.0.0.1:{server.server_port}"},
            "1", UV, environ={**os.environ, "UV_HTTP_RETRIES": "0"},
        )  # fmt: skip
        state = m.ensure()
    finally:
        server.shutdown()
    assert requested, "uv never asked the mirror: the test proves nothing"
    assert state.state == "failed"
    assert not marker.exists(), "the tampered interpreter was executed"
    assert not m.venv.exists()
    installed = list((m.python_dir).glob("cpython-*")) if m.python_dir.exists() else []
    assert installed == [], installed


def test_the_marker_of_a_broken_build_cannot_make_a_sandbox_look_ready(tmp_path):
    m = manager(tmp_path, Recorder([]), python="3.12")
    (m.venv / "bin").mkdir(parents=True)
    (m.venv / ".laris-sandbox.json").write_text(json.dumps({"engine": "1"}), encoding="utf-8")
    assert m.check().state != "ready"  # no interpreter and no matching digest: not ready
