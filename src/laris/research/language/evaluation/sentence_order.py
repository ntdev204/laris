"""Sentence-order diagnostic (T195): forward-only accuracy of the order head on held-out MLM text.

Every MLM row of the split is cut into two consecutive segments of one passage and labelled in
order, swapped, or second segment from another document of the same split (T194). The inputs
are not masked. The task has no gate: it reports whether the encoder separates the three
classes, with the majority-class share as the trivial baseline and ln 3 as the loss at chance.
"""

import math
from pathlib import Path
from typing import Any, Dict, List, Sequence, Tuple

import numpy as np

from laris.research.language.evaluation import metrics as M
from laris.shared.language.encoder.transformer import ORDER_CLASS_COUNT
from laris.shared.language.loading.dataloader import StreamingParquetMultiTaskDataLoader
from laris.shared.language.loading.segments import IGNORE_INDEX, ORDER_CLASSES

CHANCE_LOSS = math.log(ORDER_CLASS_COUNT)


def order_loader(
    encoder: Any,
    files: Sequence[Path],
    batch_size: int,
    seed: int,
    class_shares: Tuple[float, float, float] = (1 / 3, 1 / 3, 1 / 3),
) -> StreamingParquetMultiTaskDataLoader:
    """Every row two-segment and order-labelled; masking off, so the text is intact."""
    return StreamingParquetMultiTaskDataLoader(
        task_paths={"mlm": list(files)},
        tokenizer=encoder.tokenizer,
        vocab_size=encoder.config.vocab_size,
        seq_len=encoder.seq_len,
        batch_size=batch_size,
        return_tensors="pt",
        seed=seed,
        fallback_to_synthetic=False,
        require_real_data=True,
        mlm_mask_prob=0.0,
        mlm_pair_fraction=1.0,
        order_task=True,
        order_class_shares=class_shares,
    )


def order_metrics(logits: np.ndarray, gold: np.ndarray) -> Dict[str, Any]:
    """Accuracy, macro F1, per-class recall, predicted shares and mean loss of labelled rows."""
    keep = gold != IGNORE_INDEX
    logits, gold = np.asarray(logits, dtype=np.float64)[keep], np.asarray(gold)[keep]
    if len(gold) == 0:
        raise ValueError("no order-labelled rows to score")
    shifted = logits - logits.max(axis=1, keepdims=True)
    log_probs = shifted - np.log(np.exp(shifted).sum(axis=1, keepdims=True))
    pred = logits.argmax(axis=1)
    gold_counts = np.bincount(gold, minlength=ORDER_CLASS_COUNT)
    pred_counts = np.bincount(pred, minlength=ORDER_CLASS_COUNT)
    return {
        "rows": int(len(gold)),
        "accuracy": M.accuracy(pred, gold),
        "macro_f1": M.macro_f1(pred.tolist(), gold.tolist(), ORDER_CLASS_COUNT),
        "loss": float(-log_probs[np.arange(len(gold)), gold].mean()),
        "chance_loss": CHANCE_LOSS,
        "majority_baseline_accuracy": float(gold_counts.max() / len(gold)),
        "recall": {
            name: float(((pred == c) & (gold == c)).sum() / max(1, gold_counts[c]))
            for c, name in enumerate(ORDER_CLASSES)
        },
        "gold_shares": {n: float(gold_counts[c] / len(gold)) for c, n in enumerate(ORDER_CLASSES)},
        "predicted_shares": {
            n: float(pred_counts[c] / len(gold)) for c, n in enumerate(ORDER_CLASSES)
        },
        "mean_top_probability": float(np.exp(log_probs.max(axis=1)).mean()),
    }


def score_sentence_order(
    encoder: Any, files: Sequence[Path], rows: int, batch_size: int = 16, seed: int = 42
) -> Dict[str, Any]:
    """Forward passes only (no gradient): order metrics over the first `rows` drawn rows."""
    import torch

    loader = order_loader(encoder, files, batch_size, seed)
    logits: List[np.ndarray] = []
    gold: List[np.ndarray] = []
    seen = 0
    encoder.model.eval()
    while seen < rows:
        batch = loader.generate_batch(task_type="mlm")
        take = min(batch.batch_size, rows - seen)
        seen += take
        with torch.no_grad():
            out = encoder.model(
                batch.token_ids.to(encoder.device),
                attention_mask=batch.attention_mask.to(encoder.device),
                task="order",
            )
        logits.append(out["order_logits"][:take].float().cpu().numpy())
        gold.append(np.asarray(batch.labels["order_labels"][:take]))
    result = order_metrics(np.concatenate(logits), np.concatenate(gold))
    result.update(
        drawn_rows=seen,
        rows_without_boundary=int(loader.stats["mlm_pair_without_boundary"]),
        other_document_unavailable=int(loader.stats["order_other_document_unavailable"]),
        masked_inputs=False,
    )
    return result
