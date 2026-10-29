"""Tests for metrics, checkpoint loading, evaluation against baselines and inference."""

import json
import zlib
from dataclasses import asdict
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

torch = pytest.importorskip("torch")

from laris.language.encoder.transformer import (  # noqa: E402
    LanguageEncoderConfig,
    PyTorchTransformerEncoder,
)
from laris.language.evaluation import metrics as M  # noqa: E402
from laris.language.evaluation.evaluator import (  # noqa: E402
    LanguageEncoderEvaluator,
    load_thresholds,
)
from laris.language.evaluation.runner import (  # noqa: E402
    EXIT_BELOW_THRESHOLD,
    EXIT_PASSED,
    evaluate_checkpoint,
)
from laris.language.inference.loader import load_encoder  # noqa: E402
from laris.language.inference.predictor import LanguageEncoderPredictor  # noqa: E402
from laris.language.training.checkpoint import save_checkpoint  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[3]
THRESHOLDS = REPO_ROOT / "configs" / "evaluation" / "language_encoder.yaml"
TEXT = "Quantum computing uses superposition and entanglement for computation."


class FakeTokenizer:
    """Deterministic word-level stand-in for SentencePiece."""

    def encode_as_ids(self, text: str):
        return [10 + zlib.crc32(w.encode()) % 480 for w in text.split()]

    def decode_ids(self, ids):
        return " ".join(f"<{i}>" for i in ids)

    def id_to_piece(self, i: int) -> str:
        return f"piece{i}"


def _config() -> LanguageEncoderConfig:
    return LanguageEncoderConfig(
        d_model=384, num_layers=2, num_heads=6, d_ff=1536, max_sequence_length=48, vocab_size=500
    )


def _write(root: Path, name: str, split: str, table: pa.Table) -> None:
    (root / name).mkdir(parents=True, exist_ok=True)
    pq.write_table(table, root / name / f"{split}.parquet")


@pytest.fixture()
def data_dir(tmp_path: Path) -> Path:
    root = tmp_path / "processed"
    for split in ("train", "val", "test"):
        _write(root, "wikipedia_en", split, pa.table({"id": list("abcd"), "text": [TEXT] * 4}))
        _write(root, "wikipedia_vi", split, pa.table({"id": list("abcd"), "text": [TEXT] * 4}))
        _write(
            root, "all_nli", split,
            pa.table({"premise": [TEXT] * 6, "hypothesis": ["Computers."] * 6,
                      "label": ["entailment", "neutral", "contradiction"] * 2}),
        )  # fmt: skip
        _write(
            root, "quora", split,
            pa.table({"question1": [TEXT] * 6, "question2": ["What is a qubit?"] * 6,
                      "is_duplicate": [1, 0, 1, 0, 1, 0]}),
        )  # fmt: skip
        _write(
            root, "vists", split,
            pa.table({"sentence1": [TEXT] * 6, "sentence2": ["Qubits compute."] * 6,
                      "score": [0.1, 0.5, 0.9, 0.3, 0.7, 0.2]}),
        )  # fmt: skip
        answers = {"text": ["superposition"], "answer_start": [TEXT.index("superposition")]}
        _write(
            root, "squad", split,
            pa.table({"context": [TEXT] * 4, "question": ["What does it use?"] * 4,
                      "answers": [answers, answers, {"text": [], "answer_start": []}, answers]}),
        )  # fmt: skip
    (root / "task_splits_manifest.json").write_text(
        json.dumps({"partitioned_datasets": [{"dataset_id": "X", "leakage_verified": True}]})
    )
    return root


@pytest.fixture()
def checkpoint(tmp_path: Path) -> Path:
    torch.manual_seed(0)
    cfg = _config()
    model = PyTorchTransformerEncoder(cfg)
    out = tmp_path / "run" / "best"
    save_checkpoint(
        out,
        model=model,
        optimizer=None,
        scheduler=None,
        scaler=None,
        counters={"trainer": {}, "loop": {}},
        provenance={"model_size": "compact", "model_config": asdict(cfg)},
    )
    return out


def test_metric_functions_on_known_values() -> None:
    assert M.accuracy([1, 0, 1, 1], [1, 1, 1, 0]) == 0.5
    assert M.auc([0.1, 0.4, 0.35, 0.8], [0, 0, 1, 1]) == 0.75
    assert M.auc([0.5, 0.5], [0, 1]) == 0.5
    assert M.spearman([1, 2, 3, 4], [10, 20, 25, 90]) == pytest.approx(1.0)
    assert M.pearson([1, 2, 3], [3, 2, 1]) == pytest.approx(-1.0)
    assert M.macro_f1([0, 1, 2, 0], [0, 1, 2, 0], 3) == 1.0
    assert M.f1_binary([1, 1, 0, 0], [1, 0, 1, 0]) == pytest.approx(0.5)
    assert M.span_f1((3, 5), (3, 5)) == 1.0
    assert M.span_f1((0, 0), (3, 5)) == 0.0
    assert M.span_f1((0, 0), (0, 0)) == 1.0
    assert M.span_f1((3, 4), (4, 5)) == pytest.approx(0.5)


def test_evaluator_scores_every_task_per_language(data_dir: Path, checkpoint: Path) -> None:
    encoder = load_encoder(checkpoint, tokenizer=FakeTokenizer(), device="cpu")
    evaluator = LanguageEncoderEvaluator(
        encoder, data_dir, load_thresholds(THRESHOLDS), max_samples=6, batch_size=3
    )
    report = evaluator.evaluate("test")
    groups = {(g["task"], g["language"]) for g in report.groups}
    assert groups == {
        ("mlm", "en"), ("mlm", "vi"), ("nli", "en"), ("paraphrase", "en"),
        ("similarity", "vi"), ("qa", "en"),
    }  # fmt: skip
    for g in report.groups:
        assert np.isfinite(g["value"]) and np.isfinite(g["baseline"])
    mlm = next(r for r in report.results if r.dataset == "wikipedia_en")
    assert mlm.metrics["perplexity"] > 1.0 and mlm.baseline_source == "train"


def test_evaluator_refuses_training_split(data_dir: Path, checkpoint: Path) -> None:
    encoder = load_encoder(checkpoint, tokenizer=FakeTokenizer(), device="cpu")
    evaluator = LanguageEncoderEvaluator(encoder, data_dir, load_thresholds(THRESHOLDS))
    with pytest.raises(ValueError, match="never scored"):
        evaluator.evaluate("train")


def _thresholds(tmp_path: Path, margin: float) -> Path:
    config = {
        "tasks": {
            t: {"metric": m, "baseline": b, "min_margin": margin, "min_absolute": -1.0}
            for t, m, b in [
                ("mlm", "masked_accuracy", "unigram_top1"),
                ("nli", "macro_f1", "majority_class"),
                ("paraphrase", "auc", "random"),
                ("similarity", "spearman", "token_jaccard"),
                ("qa", "f1", "no_answer_or_first"),
            ]
        }
    }
    path = tmp_path / f"thr{margin}.yaml"
    import yaml

    path.write_text(yaml.safe_dump(config))
    return path


def test_exit_code_reflects_thresholds_and_report_is_written(
    data_dir: Path, checkpoint: Path, tmp_path: Path
) -> None:
    out = tmp_path / "report.json"
    code, body = evaluate_checkpoint(
        checkpoint, data_dir, "test", _thresholds(tmp_path, -10.0), output=out,
        tokenizer=FakeTokenizer(), max_samples=6, batch_size=3, device="cpu", log=lambda _: None,
    )  # fmt: skip
    assert code == EXIT_PASSED and body["passed"] is True
    saved = json.loads(out.read_text())
    assert saved["split"] == "test" and saved["model_sha256"] and saved["datasets"]
    code, body = evaluate_checkpoint(
        checkpoint, data_dir, "test", _thresholds(tmp_path, 10.0),
        tokenizer=FakeTokenizer(), max_samples=6, batch_size=3, device="cpu", log=lambda _: None,
    )  # fmt: skip
    assert code == EXIT_BELOW_THRESHOLD and body["passed"] is False


def test_evaluation_requires_a_verified_split_manifest(
    data_dir: Path, checkpoint: Path, tmp_path: Path
) -> None:
    manifest = data_dir / "task_splits_manifest.json"
    manifest.write_text(
        json.dumps({"partitioned_datasets": [{"dataset_id": "X", "leakage_verified": False}]})
    )
    with pytest.raises(ValueError, match="split isolation"):
        evaluate_checkpoint(
            checkpoint, data_dir, "test", THRESHOLDS, tokenizer=FakeTokenizer(),
            device="cpu", log=lambda _: None,
        )  # fmt: skip
    manifest.unlink()
    with pytest.raises(FileNotFoundError):
        evaluate_checkpoint(
            checkpoint, data_dir, "test", THRESHOLDS, tokenizer=FakeTokenizer(),
            device="cpu", log=lambda _: None,
        )  # fmt: skip


def test_loader_rejects_a_tokenizer_that_differs_from_training(tmp_path: Path) -> None:
    cfg = _config()
    out = tmp_path / "ck"
    save_checkpoint(
        out, model=PyTorchTransformerEncoder(cfg), optimizer=None, scheduler=None, scaler=None,
        counters={}, provenance={"model_config": asdict(cfg), "tokenizer_sha256": "0" * 64},
    )  # fmt: skip
    tokenizer_file = tmp_path / "tok.model"
    tokenizer_file.write_bytes(b"not the training tokenizer")
    with pytest.raises(ValueError, match="Tokenizer does not match"):
        load_encoder(out, tokenizer_file, device="cpu")


def test_predictor_tasks(checkpoint: Path) -> None:
    predictor = LanguageEncoderPredictor(
        load_encoder(checkpoint, tokenizer=FakeTokenizer(), device="cpu")
    )
    filled = predictor.fill_mask("quantum [MASK] uses entanglement", top_k=3)
    assert len(filled) == 1 and len(filled[0]["candidates"]) == 3
    assert sum(c["probability"] for c in filled[0]["candidates"]) <= 1.0 + 1e-6
    with pytest.raises(ValueError, match="MASK"):
        predictor.fill_mask("no mask here")

    nli = predictor.nli(TEXT, "Computers exist.")
    assert nli["label"] in nli["probabilities"]
    assert sum(nli["probabilities"].values()) == pytest.approx(1.0, abs=1e-5)
    assert 0.0 <= predictor.paraphrase("a b c", "a b d")["probability"] <= 1.0
    assert predictor.similarity("a b c", "a b d")["score_0_to_5"] == pytest.approx(
        predictor.similarity("a b c", "a b d")["score"] * 5.0
    )
    answer = predictor.qa(TEXT, "What does it use?")
    assert answer["start"] <= answer["end"] and isinstance(answer["no_answer"], bool)
    emb = predictor.embed(["one text", "another text"])
    assert emb.shape == (2, 384) and np.allclose(np.linalg.norm(emb, axis=1), 1.0, atol=1e-5)
    assert np.allclose(emb, predictor.embed(["one text", "another text"]))  # deterministic
