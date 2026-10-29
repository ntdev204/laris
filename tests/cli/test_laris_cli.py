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


def test_training_hyperparameters_come_from_yaml_and_flags_override() -> None:
    from laris.cli.commands.language_encoder import _resolve_hyperparameters

    parser = build_parser()
    args = parser.parse_args(["train", "language-encoder", "--model-size", "compact"])
    hyper = _resolve_hyperparameters(args)
    assert hyper.learning_rate == 1e-4 and hyper.warmup_steps == 2000  # compact.yaml
    args = parser.parse_args(
        ["train", "language-encoder", "--model-size", "large", "--learning-rate", "3e-4",
         "--steps", "50"]
    )
    hyper = _resolve_hyperparameters(args)
    assert hyper.learning_rate == 3e-4 and hyper.max_steps == 50
    assert hyper.micro_batch_size == 16 and hyper.gradient_accumulation_steps == 4  # large.yaml


def test_training_needs_environment_authorization(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("LARIS_TRAINING_AUTHORIZED", raising=False)
    code = main(["train", "language-encoder", "--model-size", "compact", "--authorized"])
    assert code == 1
    assert "LARIS_TRAINING_AUTHORIZED" in capsys.readouterr().out


def test_training_requires_a_tokenizer(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LARIS_TRAINING_AUTHORIZED", "1")
    code = main(["train", "language-encoder", "--model-size", "compact", "--authorized"])
    assert code == 1
    assert "--tokenizer-model" in capsys.readouterr().out


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
