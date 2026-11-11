"""Dense retrieval objectives for independently encoded query and passage pairs."""

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
