"""Offline tests for assembling the npm packages from frozen per-platform programs."""

import importlib.util
import io
import json
import stat
import tarfile
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location(
    "assemble_npm", Path(__file__).resolve().parents[3] / "packaging" / "assemble_npm.py"
)
assert SPEC and SPEC.loader
assemble = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(assemble)


def _artifact(root: Path, platform: str) -> None:
    folder = root / f"binary-{platform}"
    folder.mkdir(parents=True)
    exe = "laris.exe" if platform.startswith("win32") else "laris"
    with tarfile.open(folder / "laris.tar.gz", "w:gz") as tar:
        info = tarfile.TarInfo(f"laris/{exe}")
        info.mode = 0o755
        data = b"#!/bin/sh\n"
        info.size = len(data)
        tar.addfile(info, io.BytesIO(data))


def _front_end(root: Path) -> Path:
    folder = root / "ui" / "src"
    folder.mkdir(parents=True)
    (folder / "main.js").write_text("export {};\n", encoding="utf-8")
    return folder


def test_assembles_every_platform_and_keeps_the_executable_bit(tmp_path: Path) -> None:
    for platform in assemble.PLATFORMS:
        _artifact(tmp_path / "in", platform)
    assemble.main(tmp_path / "in", tmp_path / "out", _front_end(tmp_path))
    exe = tmp_path / "out" / "linux-x64" / "laris" / "laris"
    assert exe.stat().st_mode & stat.S_IXUSR
    manifest = json.loads((tmp_path / "out" / "darwin-arm64" / "package.json").read_text())
    assert manifest["os"] == ["darwin"] and manifest["cpu"] == ["arm64"]
    launcher = json.loads((tmp_path / "out" / "launcher" / "package.json").read_text())
    assert set(launcher["optionalDependencies"]) == {
        f"@ntdev204/laris-cli-{p}" for p in assemble.PLATFORMS
    }
    assert "vendor" not in json.dumps(launcher["files"])
    # the launcher ships the compiled Ink front end and its two runtime dependencies, no dev tools
    out = tmp_path / "out" / "launcher"
    assert (out / "build" / "src" / "main.js").is_file() and (out / "bin" / "laris.js").is_file()
    assert launcher["files"] == ["bin", "scripts", "build/src", "README.md"]
    assert set(launcher["dependencies"]) == {"ink", "react"} and "devDependencies" not in launcher
    assert launcher["type"] == "module" and launcher["engines"] == {"node": ">=22"}
    assert set(launcher["scripts"]) == {"postinstall"}
    assert not (out / "node_modules").exists() and not (out / "test").exists()


def test_a_missing_front_end_build_stops_the_release(tmp_path: Path) -> None:
    for platform in assemble.PLATFORMS:
        _artifact(tmp_path / "in", platform)
    with pytest.raises(SystemExit, match="no compiled front end"):
        assemble.main(tmp_path / "in", tmp_path / "out", tmp_path / "nothing")


def test_a_missing_platform_stops_the_release(tmp_path: Path) -> None:
    _artifact(tmp_path / "in", "linux-x64")
    with pytest.raises(SystemExit, match="no build for"):
        assemble.main(tmp_path / "in", tmp_path / "out", _front_end(tmp_path))
