"""The no-training guard of scripts/verify_model_block.py catches seeded training calls (T94)."""

import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "verify_model_block.py"
spec = importlib.util.spec_from_file_location("verify_model_block", SCRIPT)
assert spec is not None and spec.loader is not None
guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard)

VAR = "LARIS_" + "TRAINING_AUTHORIZED"  # built in pieces so the guard does not exclude this file
SEEDED = {
    "backward": "def test_x(loss):\n    loss.backward()\n",
    "optimizer_step": "def test_x(optimizer):\n    optimizer" + ".step()\n",
    "trainer": "from laris.research.language.training.trainer import LanguageEncoderTrainer\n",
    "run_training": "def test_x():\n    run_training()\n",
    "authorization": "def test_x(mp):\n    mp.setenv('" + VAR + "', '1')\n",
}


@pytest.mark.parametrize("name", sorted(SEEDED))
def test_seeded_training_call_is_caught(name: str, tmp_path: Path) -> None:
    path = tmp_path / "test_seeded.py"
    path.write_text(SEEDED[name], encoding="utf-8")
    assert guard.guard_findings(path)


def test_clean_and_delenv_are_not_flagged(tmp_path: Path) -> None:
    path = tmp_path / "test_clean.py"
    path.write_text(
        "def test_x(monkeypatch):\n"
        "    monkeypatch.delenv('" + VAR + "', raising=False)\n"
        "    assert 1 + 1 == 2\n",
        encoding="utf-8",
    )
    assert guard.guard_findings(path) == []


def test_authorization_in_environment_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(VAR, "1")
    assert guard.main(["--list"]) == 2
