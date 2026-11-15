"""Bi-encoder similarity head (T198): shapes, range, one path for trainer, evaluator, predictor.

Forward passes only: no backward step, no optimizer step, no training authorization.
"""

import zlib
from pathlib import Path
from types import SimpleNamespace
from typing import List

import pyarrow as pa
import pyarrow.parquet as pq
import pytest
import torch

from cli.commands.language_encoder import same_model_config
from laris.model.inference.predictor import LanguageEncoderPredictor
from laris.research.language.training.trainer import LanguageEncoderTrainer
from laris.shared.config.schemas import TrainingConfig
from laris.shared.language.encoder.transformer import (
    LanguageEncoderConfig,
    PyTorchTransformerEncoder,
)
from laris.shared.language.loading.checkpoint import load_model_weights
from laris.shared.language.loading.dataloader import (
    CLS_ID,
    SEP_ID,
    StreamingParquetMultiTaskDataLoader,
)

VOCAB = 200


def _config(**extra) -> LanguageEncoderConfig:
    return LanguageEncoderConfig(
        d_model=384, num_layers=2, num_heads=6, d_ff=1536, vocab_size=VOCAB,
        max_sequence_length=64, **extra,
    )  # fmt: skip


def _bi(**extra) -> PyTorchTransformerEncoder:
    return PyTorchTransformerEncoder(_config(similarity_head="bi_encoder", **extra))


class _Tok:
    def encode_as_ids(self, text: str) -> List[int]:
        return [10 + zlib.crc32(w.encode()) % (VOCAB - 10) for w in text.split()]


def _sts(tmp_path: Path) -> Path:
    path = tmp_path / "val.parquet"
    rows = [
        {"sentence1": f"a man plays guitar {i}", "sentence2": f"someone plays music {i} now",
         "score": float(i % 6)}
        for i in range(12)
    ]  # fmt: skip
    pq.write_table(pa.Table.from_pylist(rows), path)
    return path


def _batch(tmp_path: Path, trim: bool = False):
    loader = StreamingParquetMultiTaskDataLoader(
        task_paths={"similarity": [_sts(tmp_path)]}, tokenizer=_Tok(), vocab_size=VOCAB,
        seq_len=64, batch_size=6, seed=3, return_tensors="pt", trim_padding=trim,
    )  # fmt: skip
    return loader.generate_batch("similarity")


def _trainer(model: PyTorchTransformerEncoder) -> LanguageEncoderTrainer:
    return LanguageEncoderTrainer(
        model, config=None, dataloader=None, use_8bit_adam=False, device="cpu"
    )


# ---------------------------------------------------------------- configuration
def test_default_head_is_cross_and_the_parameter_count_is_unchanged() -> None:
    cfg = _config()
    assert cfg.similarity_head == "cross"
    model = PyTorchTransformerEncoder(cfg)
    assert not hasattr(model, "sim_scale")
    assert sum(p.numel() for p in model.parameters()) == cfg.calculate_parameter_count(True)


def test_bi_encoder_adds_a_scale_and_a_bias_and_the_count_matches() -> None:
    cfg = _config(similarity_head="bi_encoder")
    model = PyTorchTransformerEncoder(cfg)
    cross = _config().calculate_parameter_count(True)
    assert cfg.calculate_parameter_count(True) == cross + 2
    assert sum(p.numel() for p in model.parameters()) == cross + 2
    assert model.sim_scale.item() == pytest.approx(10.0)
    assert model.sim_bias.item() == pytest.approx(-7.5)


def test_config_rejects_unknown_head_and_bad_scale() -> None:
    with pytest.raises(ValueError, match="similarity_head"):
        _config(similarity_head="late")
    for scale in (0.0, -1.0, float("inf"), float("nan")):
        with pytest.raises(ValueError, match="scale"):
            _config(similarity_head="bi_encoder", similarity_initial_scale=scale)
    with pytest.raises(ValueError, match="bias"):
        _config(similarity_head="bi_encoder", similarity_initial_bias=float("nan"))


def test_training_config_validates_the_head_and_defaults_to_cross() -> None:
    assert TrainingConfig().similarity_head == "cross"
    assert TrainingConfig(similarity_head="bi_encoder").similarity_initial_scale == 10.0
    with pytest.raises(ValueError, match="similarity_head"):
        TrainingConfig(similarity_head="late")
    with pytest.raises(ValueError):
        TrainingConfig(similarity_initial_scale=0.0)


def test_same_seed_bodies_match_between_the_two_heads() -> None:
    cross, bi = PyTorchTransformerEncoder(_config()).state_dict(), _bi().state_dict()
    assert set(bi) - set(cross) == {"sim_scale", "sim_bias"}
    assert all(torch.equal(cross[k], bi[k]) for k in cross)


# ---------------------------------------------------------------- forward: shapes and range
def test_scores_are_in_unit_range_with_cosine_in_minus_one_to_one() -> None:
    model = _bi()
    a, b = torch.randint(5, VOCAB, (5, 12)), torch.randint(5, VOCAB, (5, 9))
    out = model.bi_encoder_similarity(a, torch.ones_like(a), b, torch.ones_like(b))
    assert out["similarity_score"].shape == (5, 1) and out["similarity_cosine"].shape == (5,)
    assert ((out["similarity_score"] > 0) & (out["similarity_score"] < 1)).all()
    assert (out["similarity_cosine"].abs() <= 1 + 1e-6).all()


def test_identical_inputs_give_cosine_one_and_the_initial_score() -> None:
    model = _bi()
    ids = torch.randint(5, VOCAB, (3, 10))
    mask = torch.ones_like(ids)
    out = model.bi_encoder_similarity(ids, mask, ids, mask)
    assert torch.allclose(out["similarity_cosine"], torch.ones(3), atol=1e-5)
    expected = torch.sigmoid(torch.tensor(10.0 - 7.5))
    assert torch.allclose(out["similarity_score"].squeeze(-1), expected.expand(3), atol=1e-5)


def test_score_is_symmetric_in_its_two_inputs() -> None:
    model = _bi()
    a, b = torch.randint(5, VOCAB, (4, 11)), torch.randint(5, VOCAB, (4, 11))
    m = torch.ones_like(a)
    ab = model.bi_encoder_similarity(a, m, b, m)["similarity_score"]
    ba = model.bi_encoder_similarity(b, m, a, m)["similarity_score"]
    assert torch.allclose(ab, ba, atol=1e-6)


def test_padding_does_not_change_a_score() -> None:
    model = _bi()
    a, b = torch.randint(5, VOCAB, (2, 8)), torch.randint(5, VOCAB, (2, 8))
    m = torch.ones_like(a)
    pad = torch.zeros(2, 5, dtype=torch.long)
    padded = lambda x: torch.cat([x, pad], dim=1)  # noqa: E731
    mp = torch.cat([m, pad], dim=1)
    plain = model.bi_encoder_similarity(a, m, b, m)["similarity_score"]
    wide = model.bi_encoder_similarity(padded(a), mp, padded(b), mp)["similarity_score"]
    assert torch.allclose(plain, wide, atol=1e-5)


def test_heads_refuse_the_other_mode() -> None:
    ids = torch.randint(5, VOCAB, (2, 8))
    cross = PyTorchTransformerEncoder(_config())
    with pytest.raises(ValueError, match="bi_encoder"):
        cross.bi_encoder_similarity(ids, torch.ones_like(ids), ids, torch.ones_like(ids))
    bi = _bi()
    with pytest.raises(ValueError, match="bi_encoder_similarity"):
        bi(ids, task="similarity")
    assert "similarity_score" not in bi(ids)  # a pair-input pass without a task omits it
    assert "similarity_score" in cross(ids, task="similarity")


def test_training_pass_still_needs_authorization() -> None:
    model = _bi()
    ids = torch.randint(5, VOCAB, (2, 8))
    with pytest.raises(Exception):
        model.bi_encoder_similarity(
            ids, torch.ones_like(ids), ids, torch.ones_like(ids), training_pass=True
        )


# ---------------------------------------------------------------- loader and trainer
def test_loader_adds_single_sentence_inputs_to_every_similarity_batch(tmp_path: Path) -> None:
    batch = _batch(tmp_path)
    labels = batch.labels
    for side in ("a", "b"):
        ids, mask = labels[f"sim_{side}_ids"], labels[f"sim_{side}_mask"]
        assert ids.shape == mask.shape == (6, 64)
        assert (ids[:, 0] == CLS_ID).all()
        last = mask.sum(dim=1) - 1
        assert (ids[torch.arange(6), last] == SEP_ID).all()
        assert (ids == SEP_ID).sum(dim=1).eq(1).all()  # one segment only
    assert batch.token_ids.shape == (6, 64)  # the pair input stays for the cross head


def test_trim_padding_trims_each_side_to_its_own_longest(tmp_path: Path) -> None:
    batch = _batch(tmp_path, trim=True)
    for side in ("a", "b"):
        width = batch.labels[f"sim_{side}_ids"].shape[1]
        assert width % 8 == 0 and width == batch.labels[f"sim_{side}_mask"].shape[1]
        assert batch.labels[f"sim_{side}_mask"].sum(dim=1).max() <= width < 64


def test_trainer_scores_the_two_sentences_and_the_loss_is_the_weighted_mse(
    tmp_path: Path,
) -> None:
    batch = _batch(tmp_path)
    model = _bi()
    trainer = _trainer(model)
    with torch.no_grad():
        out = trainer._forward("similarity", batch.token_ids, batch.attention_mask, batch.labels)
        loss = trainer._compute_torch_loss(
            "similarity", out, batch.labels, batch.attention_mask
        ).item()
    sides = [batch.labels[f"sim_{s}_{k}"] for s in ("a", "b") for k in ("ids", "mask")]
    direct = model.bi_encoder_similarity(*sides)["similarity_score"].squeeze(-1)
    assert torch.allclose(out["similarity_score"].squeeze(-1), direct)
    expected = torch.nn.functional.mse_loss(direct, batch.labels["sim_labels"].float())
    assert loss == pytest.approx(0.10 * expected.item(), rel=1e-5)


def test_trainer_keeps_the_cross_path_for_a_cross_model(tmp_path: Path) -> None:
    batch = _batch(tmp_path)
    trainer = _trainer(PyTorchTransformerEncoder(_config()))
    out = trainer._forward("similarity", batch.token_ids, batch.attention_mask, batch.labels)
    assert out["similarity_score"].shape == (6, 1) and "similarity_cosine" not in out


# ---------------------------------------------------------------- predictor
def test_predictor_uses_the_same_single_sentence_path() -> None:
    model = _bi()
    encoder = SimpleNamespace(
        model=model, tokenizer=_Tok(), config=model.config, device="cpu", seq_len=64
    )
    result = LanguageEncoderPredictor(encoder).similarity("a man plays", "a man plays")
    assert result["score"] == pytest.approx(torch.sigmoid(torch.tensor(2.5)).item(), abs=1e-5)
    assert result["score_0_to_5"] == pytest.approx(result["score"] * 5.0)
    different = LanguageEncoderPredictor(encoder).similarity("a man plays", "rain falls hard")
    assert 0.0 < different["score"] < result["score"]


# ---------------------------------------------------------------- checkpoint loading
def test_a_cross_checkpoint_loads_into_a_bi_encoder_and_keeps_the_initial_scale() -> None:
    source = PyTorchTransformerEncoder(_config())
    with torch.no_grad():
        source.layers[0].q_proj.weight.add_(1.0)
    target = _bi()
    missing = load_model_weights(target, source.state_dict())
    assert sorted(missing) == ["sim_bias", "sim_scale"]
    assert torch.equal(target.layers[0].q_proj.weight, source.layers[0].q_proj.weight)
    assert target.sim_scale.item() == pytest.approx(10.0)


def test_a_bi_encoder_checkpoint_round_trips_with_a_changed_scale() -> None:
    source = _bi()
    with torch.no_grad():
        source.sim_scale.fill_(3.0)
        source.sim_bias.fill_(-1.0)
    target = _bi()
    assert load_model_weights(target, source.state_dict()) == []
    assert target.sim_scale.item() == 3.0 and target.sim_bias.item() == -1.0


def test_a_bi_encoder_checkpoint_does_not_load_into_a_cross_model() -> None:
    with pytest.raises(RuntimeError, match="unexpected"):
        load_model_weights(PyTorchTransformerEncoder(_config()), _bi().state_dict())


def test_a_config_recorded_before_the_head_option_still_builds_a_cross_model() -> None:
    recorded = {k: v for k, v in _config().__dict__.items() if not k.startswith("similarity")}
    assert LanguageEncoderConfig(**recorded).similarity_head == "cross"


def test_init_from_accepts_a_changed_similarity_head_but_not_a_changed_body() -> None:
    from dataclasses import asdict

    recorded = {k: v for k, v in asdict(_config()).items() if not k.startswith("similarity")}
    assert same_model_config(recorded, asdict(_config(similarity_head="bi_encoder")))
    assert not same_model_config(recorded, {**asdict(_config()), "num_layers": 3})
