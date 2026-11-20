"""Tests for the `laris-model` command-line entry point (the model block's only Python CLI)."""

import subprocess
import sys
from pathlib import Path

import pytest

from cli.main import main
from cli.model import _serve_parser

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_no_command_prints_usage_and_exits_with_usage_error(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main([]) == 2
    assert "laris-model serve" in capsys.readouterr().out


def test_removed_research_commands_are_gone(capsys: pytest.CaptureFixture[str]) -> None:
    """T233 (D48): train, evaluate, infer and data commands left with the self-trained model."""
    for group in ("train", "evaluate", "infer", "data"):
        assert main([group, "anything"]) == 2


def test_serve_parser_knows_only_service_flags() -> None:
    args = _serve_parser().parse_args(["--port", "9000", "--backend", "pkg.mod:Cls"])
    assert (args.port, args.backend) == (9000, "pkg.mod:Cls")
    with pytest.raises(SystemExit):
        _serve_parser().parse_args(["--checkpoint", "x.pt"])


def test_module_entry_point_runs() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "cli"],
        cwd=REPO_ROOT,
        env={"PYTHONPATH": str(REPO_ROOT / "src"), "PATH": ""},
        capture_output=True,
        text=True,
    )
    assert result.returncode == 2
    assert "laris-model serve" in result.stdout
