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


def test_assembles_every_platform_and_keeps_the_executable_bit(tmp_path: Path) -> None:
    for platform in assemble.PLATFORMS:
        _artifact(tmp_path / "in", platform)
    assemble.main(tmp_path / "in", tmp_path / "out")
    exe = tmp_path / "out" / "linux-x64" / "laris" / "laris"
    assert exe.stat().st_mode & stat.S_IXUSR
    manifest = json.loads((tmp_path / "out" / "darwin-arm64" / "package.json").read_text())
    assert manifest["os"] == ["darwin"] and manifest["cpu"] == ["arm64"]
    launcher = json.loads((tmp_path / "out" / "launcher" / "package.json").read_text())
    assert set(launcher["optionalDependencies"]) == {
        f"@ntdev204/laris-cli-{p}" for p in assemble.PLATFORMS
    }
    assert "vendor" not in json.dumps(launcher["files"])


def test_a_missing_platform_stops_the_release(tmp_path: Path) -> None:
    _artifact(tmp_path / "in", "linux-x64")
    with pytest.raises(SystemExit, match="no build for"):
        assemble.main(tmp_path / "in", tmp_path / "out")
