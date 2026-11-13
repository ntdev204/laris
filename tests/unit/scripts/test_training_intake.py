import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location(
    "training_intake", Path(__file__).resolve().parents[3] / "scripts/training_intake.py"
)
assert SPEC and SPEC.loader
intake = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(intake)

TASKS = {"mlm": 1.0, "nli": 0.2, "paraphrase": 0.1, "qa": 0.5, "similarity": 0.01}


def write_run(root: Path, run_id: str, init_sha=None, steps=100, weight=0.0, tok="tok", bad=False):
    for which in ("best", "last"):
        d = root / run_id / which
        d.mkdir(parents=True)
        (d / "model.pt").write_bytes(b"weights-" + run_id.encode())
        sha = hashlib.sha256(b"weights-" + run_id.encode()).hexdigest()
        manifest = {
            "model_sha256": "0" * 64 if bad else sha,
            "counters": {
                "trainer": {"optimizer_steps": steps, "skipped_steps": 0},
                "loop": {"stale_evals": 0, "evaluations": [{**TASKS, "mean": 0.3}]},
            },
            "provenance": {
                "training": {"loss_lambda_retrieval": weight},
                "tokenizer_sha256": hashlib.sha256(tok.encode()).hexdigest(),
                "initial_checkpoint": None if init_sha is None else "x",
                "initial_model_sha256": init_sha,
                "run_config": {"patience": 6},
            },
        }
        (d / "manifest.json").write_text(json.dumps(manifest))


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(intake, "RUNS", tmp_path)
    tokenizer = tmp_path / "tok.model"
    tokenizer.write_bytes(b"tok")
    for var in intake.AUTH_VARS:
        monkeypatch.delenv(var, raising=False)
    return tmp_path, tokenizer


def args(tokenizer, **extra):
    base = ["--run-id", "r2", "--expect-steps", "100", "--expect-retrieval-weight", "0.0"]
    out = base + ["--tokenizer-model", str(tokenizer)]
    for key, value in extra.items():
        out += [f"--{key.replace('_', '-')}", str(value)]
    return out


def test_clean_run_passes(env):
    root, tok = env
    write_run(root, "r2")
    assert intake.main(args(tok, reference_run="r2")) == 0


def test_tampered_weights_fail(env):
    root, tok = env
    write_run(root, "r2", bad=True)
    assert intake.main(args(tok)) == 1


def test_wrong_step_count_fails(env):
    root, tok = env
    write_run(root, "r2", steps=90)
    assert intake.main(args(tok)) == 1


def test_lineage_must_match_init_run(env):
    root, tok = env
    write_run(root, "r1")
    write_run(root, "r2", init_sha="f" * 64)
    assert intake.main(args(tok, init_run="r1")) == 1


def test_missing_run_is_unusable_input(env):
    _, tok = env
    assert intake.main(args(tok)) == 2


def test_refuses_when_training_is_authorized(env, monkeypatch):
    root, tok = env
    write_run(root, "r2")
    monkeypatch.setenv("LARIS_TRAINING_AUTHORIZED", "1")
    assert intake.main(args(tok)) == 2
