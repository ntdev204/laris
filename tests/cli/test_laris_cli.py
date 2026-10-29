"""Tests for the `laris` command-line interface."""

import subprocess
import sys
from pathlib import Path

import pytest

from laris.cli.main import COMMANDS, build_parser, main

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_every_command_module_exposes_the_command_contract() -> None:
    for commands in COMMANDS.values():
        for _, module in commands.values():
            assert callable(module.add_arguments)
            assert callable(module.run)


def test_parser_resolves_every_leaf_command() -> None:
    parser = build_parser()
    for group, commands in COMMANDS.items():
        for name, (_, module) in commands.items():
            args = parser.parse_args([group, name])
            assert args.handler is module.run


def test_unknown_command_exits_with_usage_error() -> None:
    with pytest.raises(SystemExit) as exc:
        main(["train", "does-not-exist"])
    assert exc.value.code == 2


def test_profile_only_runs_without_authorization(capsys: pytest.CaptureFixture[str]) -> None:
    code = main(["train", "language-encoder", "--model-size", "compact", "--profile-only"])
    assert code == 0
    assert "Bounded profiling complete" in capsys.readouterr().out


def test_training_refuses_without_authorization_flag(capsys: pytest.CaptureFixture[str]) -> None:
    code = main(["train", "language-encoder", "--model-size", "compact"])
    assert code == 1
    assert "--authorized" in capsys.readouterr().out


def test_acquire_rejects_unknown_dataset_id() -> None:
    assert main(["data", "acquire", "--only", "NOT-A-DATASET"]) == 2


@pytest.mark.parametrize(
    "script",
    ["acquire_datasets", "partition_datasets", "train_tokenizer", "train_language_encoder"],
)
def test_compatibility_wrappers_delegate_to_cli(script: str) -> None:
    result = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / f"{script}.py"), "--help"],
        capture_output=True,
        text=True,
        env={"PYTHONPATH": str(REPO_ROOT / "src"), "PATH": ""},
    )
    assert result.returncode == 0
    assert "usage: laris" in result.stdout
