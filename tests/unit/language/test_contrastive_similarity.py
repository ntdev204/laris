"""Contrastive similarity objective (T199): loss, row sampler, loader batch, dropout, trainer.

Fixture-sized and CPU only. Forward passes and loss values only: no backward step runs here. The
one test that would train a toy encoder is skipped unless the owner authorises training.
"""

import random
import zlib
from pathlib import Path
from typing import List

import pyarrow as pa
import pyarrow.parquet as pq
import pytest
import torch

from laris.research.language.training.objectives import contrastive_similarity_loss
from laris.research.language.training.trainer import LanguageEncoderTrainer
from laris.shared.config.schemas import (
    CONTRASTIVE_ROW_KINDS,
    DEFAULT_CONTRASTIVE_ROW_WEIGHTS,
    TrainingConfig,
)
from laris.shared.core.authorization import is_training_authorized
from laris.shared.language.encoder.transformer import (
    LanguageEncoderConfig,
    PyTorchTransformerEncoder,
)
from laris.shared.language.loading.dataloader import (
    CONTRASTIVE_SIM_TASK,
    StreamingParquetMultiTaskDataLoader,
)
from laris.shared.language.loading.relations import (
    RelationRowSampler,
    relation_stream,
    shuffled,
)

VOCAB = 200
RELATIONS = (*CONTRASTIVE_ROW_KINDS[1:], "order_swapped")


class _Tok:
    def encode_as_ids(self, text: str) -> List[int]:
        return [10 + zlib.crc32(w.encode()) % (VOCAB - 10) for w in text.split()]


def _model(dropout: float = 0.1) -> PyTorchTransformerEncoder:
    return PyTorchTransformerEncoder(
        LanguageEncoderConfig(
            d_model=384, num_layers=2, num_heads=6, d_ff=1536, vocab_size=VOCAB,
            max_sequence_length=64, similarity_head="bi_encoder", dropout=dropout,
        )  # fmt: skip
    )


def _pairs(tmp_path: Path, per_relation: int = 40) -> Path:
    directory = tmp_path / "relation_pairs_en"
    if directory.exists():
        return tmp_path
    directory.mkdir(parents=True)
    rows = [
        {"sentence1": f"the {relation} first sentence {i}",
         "sentence2": f"the {relation} second sentence {i}",
         "relation": relation, "polarity": "negative" if "contra" in relation else "positive",
         "source": "fixture", "label_source": "derived", "symmetric": True}
        for i in range(per_relation) for relation in RELATIONS
    ]  # fmt: skip
    random.Random(0).shuffle(rows)
    pq.write_table(pa.Table.from_pylist(rows), directory / "train.parquet")
    return tmp_path


def _loader(tmp_path: Path, **extra) -> StreamingParquetMultiTaskDataLoader:
    return StreamingParquetMultiTaskDataLoader(
        data_dir=_pairs(tmp_path), tokenizer=_Tok(), vocab_size=VOCAB, seq_len=48, batch_size=8,
        seed=5, return_tensors="pt", include_contrastive_sim_task=True, buffer_size=16,
        **{"contrastive_sim_batch_size": 12, **extra},
    )  # fmt: skip


# ---------------------------------------------------------------- loss
def _emb(rows: int, dim: int = 8, seed: int = 0) -> torch.Tensor:
    return torch.randn(rows, dim, generator=torch.Generator().manual_seed(seed))


def _loss(anchors, candidates, known=None, weights=None, temperature=0.05):
    rows = len(anchors)
    known = torch.zeros(rows, len(candidates), dtype=torch.bool) if known is None else known
    weights = torch.ones(rows) if weights is None else weights
    return contrastive_similarity_loss(anchors, candidates, known, weights, temperature)


def test_loss_is_log_batch_size_for_identical_candidates_and_near_zero_when_aligned() -> None:
    anchors = _emb(4)
    same = anchors[:1].expand(4, -1).contiguous()
    assert _loss(same, same).item() == pytest.approx(torch.log(torch.tensor(4.0)).item(), abs=1e-5)
    assert _loss(anchors, anchors.clone()).item() < 0.05  # far below log 4 = 1.39


def test_loss_matches_a_direct_cross_entropy() -> None:
    anchors, candidates = _emb(3, seed=1), _emb(5, seed=2)  # 3 positives + 2 hard negatives
    logits = torch.nn.functional.normalize(anchors, dim=-1) @ torch.nn.functional.normalize(
        candidates, dim=-1
    ).T
    expected = torch.nn.functional.cross_entropy(logits / 0.05, torch.arange(3))
    assert _loss(anchors, candidates).item() == pytest.approx(expected.item(), abs=1e-5)


def test_known_positives_leave_the_denominator_but_the_target_stays() -> None:
    anchors, candidates = _emb(3, seed=3), _emb(3, seed=4)
    known = torch.zeros(3, 3, dtype=torch.bool)
    known[0, 1] = True  # candidate 1 has the same text as anchor 0's positive
    base, masked = _loss(anchors, candidates), _loss(anchors, candidates, known)
    assert masked.item() < base.item()
    known[0, 0] = True  # the target itself is never dropped
    assert _loss(anchors, candidates, known).item() == pytest.approx(masked.item(), abs=1e-6)


def test_hard_negative_close_to_the_anchor_raises_the_loss() -> None:
    anchors = _emb(2, seed=5)
    positives = anchors + 0.05 * _emb(2, seed=6)
    easy = torch.cat([positives, -anchors[:1]])
    hard = torch.cat([positives, anchors[:1] + 0.01 * _emb(1, seed=7)])
    assert _loss(anchors, hard).item() > _loss(anchors, easy).item()


def test_row_weights_give_a_weighted_mean_and_all_zero_weights_a_zero() -> None:
    anchors, candidates = _emb(4, seed=8), _emb(4, seed=9)
    w = torch.tensor([1.0, 0.0, 0.0, 0.0])
    only_first = contrastive_similarity_loss(
        anchors, candidates, torch.zeros(4, 4, dtype=torch.bool), w, 0.05
    )
    logits = torch.nn.functional.normalize(anchors, dim=-1) @ torch.nn.functional.normalize(
        candidates, dim=-1
    ).T
    assert only_first.item() == pytest.approx(
        torch.nn.functional.cross_entropy(logits[:1] / 0.05, torch.tensor([0])).item(), abs=1e-5
    )
    zero = _loss(anchors, candidates, weights=torch.zeros(4))
    assert zero.item() == 0.0


def test_loss_validates_its_inputs() -> None:
    anchors, candidates = _emb(3), _emb(3)
    with pytest.raises(ValueError, match="temperature"):
        _loss(anchors, candidates, temperature=0.0)
    with pytest.raises(ValueError, match="designated positive"):
        _loss(_emb(3), _emb(2))
    with pytest.raises(ValueError, match="boolean"):
        _loss(anchors, candidates, known=torch.zeros(3, 3))
    with pytest.raises(ValueError, match="non-negative"):
        _loss(anchors, candidates, weights=torch.tensor([1.0, -1.0, 1.0]))
    with pytest.raises(ValueError, match="one weight"):
        _loss(anchors, candidates, weights=torch.ones(2))
    with pytest.raises(ValueError, match="feature"):
        _loss(anchors, _emb(3, dim=4))


def test_loss_gradient_reaches_the_anchors_when_asked() -> None:
    # autograd bookkeeping only: requires_grad inputs, no backward call
    anchors = _emb(3).requires_grad_(True)
    assert _loss(anchors, _emb(3, seed=1)).requires_grad


# ---------------------------------------------------------------- configuration
def test_defaults_keep_the_task_off() -> None:
    cfg = TrainingConfig()
    assert not cfg.contrastive_sim_task and cfg.loss_lambda_contrastive_sim == 0.0
    assert not cfg.similarity_calibration_only
    assert set(cfg.contrastive_sim_row_shares) == set(CONTRASTIVE_ROW_KINDS)
    assert cfg.contrastive_sim_row_weights["adjacent_sentences"] < 1.0
    assert "order_swapped" not in cfg.contrastive_sim_row_shares


def test_task_flag_and_weight_go_together_and_need_the_bi_encoder() -> None:
    ok = dict(similarity_head="bi_encoder")
    TrainingConfig(contrastive_sim_task=True, loss_lambda_contrastive_sim=0.5, **ok)
    with pytest.raises(ValueError, match="go together"):
        TrainingConfig(contrastive_sim_task=True, **ok)
    with pytest.raises(ValueError, match="go together"):
        TrainingConfig(loss_lambda_contrastive_sim=0.5, **ok)
    with pytest.raises(ValueError, match="bi-encoder"):
        TrainingConfig(contrastive_sim_task=True, loss_lambda_contrastive_sim=0.5)
    with pytest.raises(ValueError, match="bi_encoder"):
        TrainingConfig(similarity_calibration_only=True)


def test_row_share_and_weight_maps_are_validated() -> None:
    with pytest.raises(ValueError, match="contrastive_sim_row_shares"):
        TrainingConfig(contrastive_sim_row_shares={"order_swapped": 1.0})
    with pytest.raises(ValueError, match="contrastive_sim_row_weights"):
        TrainingConfig(contrastive_sim_row_weights={"simcse": -1.0})
    with pytest.raises(ValueError, match="positive share"):
        TrainingConfig(contrastive_sim_row_shares={"simcse": 0.0})


# ---------------------------------------------------------------- row sampler
def _sampler(tmp_path: Path, shares, seed: int = 1) -> RelationRowSampler:
    path = _pairs(tmp_path) / "relation_pairs_en" / "train.parquet"
    streams = {
        kind: shuffled(
            relation_stream([path], None if kind == "simcse" else kind, chunk_rows=16),
            8, random.Random(f"{seed}{kind}"),
        )
        for kind in shares
    }  # fmt: skip
    return RelationRowSampler(streams, shares, random.Random(seed))


def test_sampler_follows_the_shares_and_builds_each_row_kind(tmp_path: Path) -> None:
    shares = {"simcse": 0.4, "entailment": 0.2, "contradiction": 0.4}
    sampler = _sampler(tmp_path, shares)
    rows = [r for _ in range(40) for r in sampler.draw_batch(10)]
    count = {k: sum(r["kind"] == k for r in rows) for k in shares}
    assert all(abs(count[k] / len(rows) - w) < 0.08 for k, w in shares.items())
    for row in rows:
        if row["kind"] == "simcse":
            assert row["positive"] is None and row["negative"] is None
        elif row["kind"] == "entailment":
            assert "second" in row["positive"] and row["negative"] is None
        else:
            assert row["positive"] is None and "second" in row["negative"]
        assert row["anchor"]


def test_streams_hold_only_their_relation_and_cycle(tmp_path: Path) -> None:
    path = _pairs(tmp_path) / "relation_pairs_en" / "train.parquet"
    rows = [r for _, r in zip(range(130), relation_stream([path], "entailment", chunk_rows=16))]
    assert {r["relation"] for r in rows} == {"entailment"}  # 40 rows in the file, so it wrapped
    assert len({r["sentence1"] for r in rows}) == 40
    assert {r["relation"] for _, r in zip(range(300), relation_stream([path], None))} == set(
        RELATIONS
    )
    with pytest.raises(RuntimeError, match="no pair rows"):
        next(relation_stream([path], "no_such_relation"))


def test_shuffle_keeps_every_item_and_changes_the_order() -> None:
    out = list(shuffled(iter(range(100)), 10, random.Random(0)))
    assert len(out) == 90 and len(set(out)) == 90 and out != sorted(out)  # buffer keeps 10


def test_sampler_needs_a_stream_per_drawn_kind() -> None:
    with pytest.raises(ValueError, match="no stream"):
        RelationRowSampler({}, {"simcse": 1.0}, random.Random(0))


def test_sampler_is_seed_stable_and_rejects_empty_shares(tmp_path: Path) -> None:
    shares = {"simcse": 1.0, "paws_non_paraphrase": 1.0}
    first = _sampler(tmp_path, shares).draw_batch(16)
    assert first == _sampler(tmp_path, shares).draw_batch(16)
    with pytest.raises(ValueError, match="positive share"):
        RelationRowSampler({}, {"simcse": 0.0}, random.Random(0))


# ---------------------------------------------------------------- loader batch
def test_loader_batch_has_aligned_anchors_positives_negatives_and_weights(tmp_path: Path) -> None:
    loader = _loader(tmp_path)
    batch = loader.generate_batch(CONTRASTIVE_SIM_TASK)
    labels = batch.labels
    rows = batch.batch_size
    assert batch.task_type == CONTRASTIVE_SIM_TASK and rows == 12
    assert labels["contrastive_sim_anchor_ids"].shape[0] == rows
    assert labels["contrastive_sim_positive_ids"].shape[0] == rows
    hard = labels["contrastive_sim_negative_ids"].shape[0]
    assert 0 < hard < rows
    assert labels["contrastive_sim_known_positives"].shape == (rows, rows + hard)
    assert labels["contrastive_sim_known_positives"].dtype == torch.bool
    weights = labels["contrastive_sim_weights"]
    assert weights.shape == (rows,) and set(weights.tolist()) <= set(
        DEFAULT_CONTRASTIVE_ROW_WEIGHTS.values()
    )
    assert torch.equal(batch.token_ids, labels["contrastive_sim_anchor_ids"])
    for name in ("anchor", "positive", "negative"):  # mask matches ids, CLS first
        ids, mask = labels[f"contrastive_sim_{name}_ids"], labels[f"contrastive_sim_{name}_mask"]
        assert ids.shape == mask.shape and (mask[:, 0] == 1).all()


def test_simcse_positive_is_the_anchor_tokens_and_marks_known_positives(tmp_path: Path) -> None:
    loader = _loader(tmp_path, contrastive_sim_row_shares={"simcse": 1.0})
    labels = loader.generate_batch(CONTRASTIVE_SIM_TASK).labels
    assert torch.equal(labels["contrastive_sim_anchor_ids"], labels["contrastive_sim_positive_ids"])
    assert "contrastive_sim_negative_ids" not in labels
    known = labels["contrastive_sim_known_positives"]
    assert known.diagonal().all()  # each anchor's own positive


def test_equal_texts_are_marked_as_known_positives(tmp_path: Path) -> None:
    loader = _loader(tmp_path)
    rows = [
        {"kind": "entailment", "anchor": "a b c", "positive": "d e f", "negative": None},
        {"kind": "simcse", "anchor": "d e f", "positive": None, "negative": None},
        {"kind": "contradiction", "anchor": "x y z", "positive": None, "negative": "a b c"},
    ]
    known = loader._format_contrastive_sim_batch(rows).labels["contrastive_sim_known_positives"]
    # candidates: positives [d e f, d e f, x y z] then the hard negative [a b c]
    assert known[0].tolist() == [True, True, False, True]  # anchor a b c equals the hard negative
    assert known[1].tolist() == [True, True, False, False]
    assert known[2].tolist() == [False, False, True, False]


def test_loader_task_is_train_only_and_validates_sizes(tmp_path: Path) -> None:
    data = _pairs(tmp_path)
    with pytest.raises(ValueError, match="train split"):
        StreamingParquetMultiTaskDataLoader(
            data_dir=data, tokenizer=_Tok(), vocab_size=VOCAB, seq_len=48, split="val",
            include_contrastive_sim_task=True,
        )  # fmt: skip
    for bad in ({"contrastive_sim_batch_size": 1}, {"contrastive_sim_max_sequence_length": 4}):
        with pytest.raises(ValueError):
            _loader(tmp_path / "x", **bad)


def test_task_is_absent_unless_enabled(tmp_path: Path) -> None:
    loader = StreamingParquetMultiTaskDataLoader(
        data_dir=_pairs(tmp_path), tokenizer=_Tok(), vocab_size=VOCAB, seq_len=48,
        fallback_to_synthetic=True,
    )  # fmt: skip
    assert CONTRASTIVE_SIM_TASK not in loader.task_paths


# ---------------------------------------------------------------- dropout (forward only)
def _ids() -> tuple:
    ids = torch.randint(5, VOCAB, (4, 12))
    return ids, torch.ones_like(ids)


def test_two_stochastic_passes_differ_in_training_mode_and_match_otherwise() -> None:
    model = _model().train()
    ids, mask = _ids()

    def run(stochastic: bool) -> torch.Tensor:
        return model(ids, attention_mask=mask, task="embedding", stochastic=stochastic)[
            "cls_embedding"
        ]

    assert not torch.allclose(run(True), run(True))  # independent dropout masks
    assert torch.equal(run(False), run(False))  # the default pass is deterministic
    model.eval()
    assert torch.equal(run(True), run(True))  # eval mode: no dropout even when requested


def test_zero_dropout_and_the_default_pass_are_unchanged() -> None:
    ids, mask = _ids()
    with_p = _model(0.1).eval()(ids, attention_mask=mask, task="embedding")["cls_embedding"]
    without = _model(0.0).eval()(ids, attention_mask=mask, task="embedding")["cls_embedding"]
    assert torch.equal(with_p, without)  # dropout adds no parameter and no eval-time effect
    model = _model(0.0).train()
    a = model(ids, attention_mask=mask, task="embedding", stochastic=True)["cls_embedding"]
    assert torch.equal(a, model(ids, attention_mask=mask, task="embedding")["cls_embedding"])


# ---------------------------------------------------------------- trainer
def _trainer(model, **extra) -> LanguageEncoderTrainer:
    return LanguageEncoderTrainer(
        model, config=None, dataloader=None, use_8bit_adam=False, device="cpu", **extra
    )


def test_trainer_needs_a_positive_weight_and_training_mode(tmp_path: Path) -> None:
    labels = _loader(tmp_path).generate_batch(CONTRASTIVE_SIM_TASK).labels
    model = _model()
    with pytest.raises(ValueError, match="contrastive_sim_weight"):
        _trainer(model)._forward(CONTRASTIVE_SIM_TASK, None, None, labels)
    trainer = _trainer(model, contrastive_sim_weight=1.0)
    model.eval()
    with pytest.raises(ValueError, match="training mode"):
        trainer._forward(CONTRASTIVE_SIM_TASK, None, None, labels, training_pass=True)
    for bad in ({"contrastive_sim_temperature": 0.0}, {"contrastive_sim_weight": -1.0}):
        with pytest.raises(ValueError):
            _trainer(model, **bad)


def test_trainer_loss_is_finite_with_the_expected_scale_at_initialisation(tmp_path: Path) -> None:
    loader = _loader(tmp_path, contrastive_sim_row_shares={"simcse": 0.5, "contradiction": 0.5})
    model = _model().train()
    trainer = _trainer(model, contrastive_sim_weight=0.5)
    batch = loader.generate_batch(CONTRASTIVE_SIM_TASK)
    outputs = trainer._forward(CONTRASTIVE_SIM_TASK, None, None, batch.labels)  # no gradient
    loss = trainer._compute_torch_loss(CONTRASTIVE_SIM_TASK, outputs, batch.labels, None)
    raw = outputs["contrastive_sim_loss"].item()
    assert torch.isfinite(loss) and loss.item() == pytest.approx(0.5 * raw, rel=1e-5)
    assert 0.0 <= raw < 20.0


def test_calibration_only_runs_the_two_passes_without_gradient(tmp_path: Path) -> None:
    model = _model()
    ids = torch.randint(5, VOCAB, (3, 10))
    mask = torch.ones_like(ids)
    on = model.bi_encoder_similarity(ids, mask, ids, mask, detach_embeddings=True)
    off = model.bi_encoder_similarity(ids, mask, ids, mask)
    assert torch.equal(on["similarity_score"], off["similarity_score"])
    model.train()
    # the scale and bias still carry gradient, the body embeddings do not (no backward call)
    on = model.bi_encoder_similarity(ids, mask, ids, mask, detach_embeddings=True)
    assert on["similarity_score"].requires_grad and not on["similarity_cosine"].requires_grad


@pytest.mark.skipif(
    not is_training_authorized(), reason="runs optimizer steps: needs owner-authorised training"
)
def test_loss_falls_on_a_toy_encoder_when_training_is_authorised(tmp_path: Path) -> None:
    loader = _loader(tmp_path, contrastive_sim_row_shares={"simcse": 0.5, "entailment": 0.5})
    model = _model()
    trainer = LanguageEncoderTrainer(
        model, config=None, dataloader=loader, use_8bit_adam=False, device="cpu",
        learning_rate=1e-3, grad_accum_steps=1, contrastive_sim_weight=1.0,
    )  # fmt: skip
    losses = [trainer.train_step(loader.generate_batch(CONTRASTIVE_SIM_TASK)).loss_value
              for _ in range(30)]  # fmt: skip
    assert sum(losses[-5:]) / 5 < sum(losses[:5]) / 5
