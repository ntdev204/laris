"""Dense retrieval and sentence-order objectives."""

import math
from typing import Any


def contrastive_retrieval_loss(
    queries: Any, passages: Any, positives: Any, temperature: float = 0.07
) -> Any:
    """Query-to-passage InfoNCE with a mask for known positives in each row."""
    import torch
    import torch.nn.functional as F

    if not math.isfinite(temperature) or temperature <= 0:
        raise ValueError("temperature must be finite and positive")
    if queries.ndim != 2 or passages.ndim != 2 or queries.shape[1] != passages.shape[1]:
        raise ValueError("query and passage embeddings must have matching feature dimensions")
    if positives.shape != (len(queries), len(passages)) or positives.dtype != torch.bool:
        raise ValueError("positives must be a boolean query-by-passage mask")
    if len(queries) == 0 or not bool(positives.any(dim=1).all()):
        raise ValueError("every query must have at least one positive passage")
    with torch.autocast(device_type=queries.device.type, enabled=False):
        logits = F.normalize(queries.float(), dim=-1) @ F.normalize(passages.float(), dim=-1).T
        logits = logits / temperature
        positive_logits = logits.masked_fill(~positives.to(logits.device), -torch.inf)
        return (logits.logsumexp(dim=1) - positive_logits.logsumexp(dim=1)).mean()


def sentence_order_loss(logits: Any, targets: Any, ignore_index: int = -100) -> Any:
    """Mean cross-entropy over the labelled two-segment rows (T195), computed in fp32.

    Rows with `ignore_index` (single-segment MLM rows) do not count; a batch without a
    labelled row gives a zero that keeps the graph, not a NaN mean over nothing.
    """
    import torch
    import torch.nn.functional as F

    if logits.ndim != 2 or targets.shape != logits.shape[:1]:
        raise ValueError("order logits must be (B, classes) and targets (B,)")
    targets = targets.to(device=logits.device, dtype=torch.long)
    if not bool((targets != ignore_index).any()):
        return logits.sum() * 0.0
    with torch.autocast(device_type=logits.device.type, enabled=False):
        return F.cross_entropy(logits.float(), targets, ignore_index=ignore_index)


def contrastive_similarity_loss(
    anchors: Any,
    candidates: Any,
    known_positives: Any,
    row_weights: Any,
    temperature: float = 0.05,
) -> Any:
    """In-batch InfoNCE for the similarity task (T199), one target per anchor.

    `candidates` holds the B designated positives first (row i is the target of anchor i: a
    second dropout pass of the same sentence for SimCSE rows, the relation partner for positive
    pairs) followed by any hard negatives. Every other candidate is a negative, except those
    `known_positives` (B, C) marks (the same text as the anchor or as its positive), which are
    left out of the denominator. `row_weights` (B,) scales each anchor's loss and the result is
    their weighted mean, so a relation with a smaller weight counts less. Computed in fp32.
    """
    import torch
    import torch.nn.functional as F

    if not math.isfinite(temperature) or temperature <= 0:
        raise ValueError("temperature must be finite and positive")
    rows = len(anchors)
    if anchors.ndim != 2 or candidates.ndim != 2 or anchors.shape[1] != candidates.shape[1]:
        raise ValueError("anchor and candidate embeddings must have matching feature dimensions")
    if rows == 0 or len(candidates) < rows:
        raise ValueError("candidates must start with one designated positive per anchor")
    if known_positives.shape != (rows, len(candidates)) or known_positives.dtype != torch.bool:
        raise ValueError("known_positives must be a boolean anchor-by-candidate mask")
    if row_weights.shape != (rows,):
        raise ValueError("row_weights must hold one weight per anchor")
    with torch.autocast(device_type=anchors.device.type, enabled=False):
        weights = row_weights.to(device=anchors.device, dtype=torch.float32)
        if bool((weights < 0).any()) or not bool(torch.isfinite(weights).all()):
            raise ValueError("row_weights must be finite and non-negative")
        if not float(weights.sum()) > 0:
            return anchors.float().sum() * 0.0
        logits = F.normalize(anchors.float(), dim=-1) @ F.normalize(candidates.float(), dim=-1).T
        logits = logits / temperature
        target = torch.eye(rows, len(candidates), dtype=torch.bool, device=logits.device)
        drop = known_positives.to(logits.device) & ~target
        logits = logits.masked_fill(drop, -torch.inf)
        per_row = logits.logsumexp(dim=1) - logits[torch.arange(rows), torch.arange(rows)]
        return (per_row * weights).sum() / weights.sum()
