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


def test_every_leaf_command_has_working_help() -> None:
    parser = build_parser()
    for group, commands in COMMANDS.items():
        for name in commands:
            with pytest.raises(SystemExit) as exc:
                parser.parse_args([group, name, "--help"])
            assert exc.value.code == 0


def test_commands_without_required_flags_resolve_to_their_handler() -> None:
    parser = build_parser()
    for group in ("data", "train"):
        for name, (_, module) in COMMANDS[group].items():
            assert parser.parse_args([group, name]).handler is module.run


def test_unknown_command_exits_with_usage_error() -> None:
    with pytest.raises(SystemExit) as exc:
        main(["train", "does-not-exist"])
    assert exc.value.code == 2


def test_profile_only_refuses_without_a_real_tokenizer(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Profiling runs on real tokenized batches, never on random ids."""
    import torch

    monkeypatch.delenv("LARIS_TRAINING_AUTHORIZED", raising=False)
    args = ["train", "language-encoder", "--model-size", "compact", "--profile-only"]
    code = main(args + ["--tokenizer-model", str(tmp_path / "missing.model")])
    out = capsys.readouterr().out
    assert code == 1
    expected = "--tokenizer-model" if torch.cuda.is_available() else "No CUDA device"
    assert expected in out


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


def test_evaluate_and_infer_commands_are_registered() -> None:
    parser = build_parser()
    args = parser.parse_args(
        ["evaluate", "language-encoder", "--checkpoint", "c", "--tokenizer-model", "t"]
    )
    assert args.split == "test" and args.handler is not None
    for task in ("fill-mask", "nli", "paraphrase", "similarity", "qa", "embed"):
        assert task in COMMANDS["infer"]


def test_evaluate_reports_usage_error_for_missing_checkpoint(tmp_path: Path) -> None:
    code = main(
        ["evaluate", "language-encoder", "--checkpoint", str(tmp_path / "nope"),
         "--tokenizer-model", str(tmp_path / "tok.model"), "--data-dir", str(tmp_path)]
    )  # fmt: skip
    assert code == 2


def test_evaluate_rejects_the_training_split() -> None:
    with pytest.raises(SystemExit) as exc:
        main(
            ["evaluate", "language-encoder", "--checkpoint", "c", "--tokenizer-model", "t",
             "--split", "train"]
        )  # fmt: skip
    assert exc.value.code == 2


def test_infer_reports_error_for_missing_checkpoint(tmp_path: Path) -> None:
    code = main(
        ["infer", "nli", "--checkpoint", str(tmp_path / "nope"),
         "--tokenizer-model", str(tmp_path / "t.model"), "--premise", "a", "--hypothesis", "b"]
    )  # fmt: skip
    assert code == 2


@pytest.mark.parametrize(
    ("size", "extra", "expected"),
    [("compact", [], 512), ("compact", ["--max-seq-len", "1024"], 1024), ("large", [], 1024)],
)
def test_sequence_length_default_per_size_and_honored_for_compact(
    size: str,
    extra: list,
    expected: int,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """The header shows the length the model and the dataloader will really use."""
    monkeypatch.delenv("LARIS_TRAINING_AUTHORIZED", raising=False)
    main(["train", "language-encoder", "--model-size", size, "--profile-only",
          "--tokenizer-model", str(tmp_path / "missing.model"), *extra])
    assert f"Sequence Length:           {expected}" in capsys.readouterr().out
