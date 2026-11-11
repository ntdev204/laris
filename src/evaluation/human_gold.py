"""Human-gold workflow for retrieval relevance (D05-a): pooling, blind sheets, agreement, seal.

This module never creates labels. It prepares blind annotation sheets for two independent human
annotators, validates what they return, measures their agreement and merges the labels, using
an adjudicator's decisions only where the annotators disagree. Model rankings are accepted as
plain data (produced elsewhere by inference); nothing here trains, fits or scores a model.
"""

import hashlib
import json
import random
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence

RELEVANCE_LABELS = (0, 1, 2)  # 0 not relevant, 1 partially relevant, 2 answers the query
DEFAULT_KAPPA_THRESHOLD = 0.85  # LARIS-GOLD s4; proposal pending owner confirmation (D05 s4)
UNRESOLVED = "UNRESOLVED_CONFLICT"


class GoldError(ValueError):
    """Raised when annotation data violates the protocol."""


def cohen_kappa(
    a: Sequence[int],
    b: Sequence[int],
    labels: Sequence[int] = RELEVANCE_LABELS,
    weights: Optional[str] = None,
) -> float:
    """Cohen's kappa; weights is None (nominal), 'linear' or 'quadratic' (ordinal)."""
    if len(a) != len(b) or not a:
        raise GoldError("kappa needs two equally long, non-empty label sequences")
    index = {label: i for i, label in enumerate(labels)}
    if any(x not in index for x in a) or any(x not in index for x in b):
        raise GoldError("label outside the declared label set")
    if weights not in (None, "linear", "quadratic"):
        raise GoldError(f"unknown weights: {weights}")
    n, k = len(a), len(labels)
    observed = [[0.0] * k for _ in range(k)]
    for x, y in zip(a, b):
        observed[index[x]][index[y]] += 1.0 / n
    row = [sum(observed[i]) for i in range(k)]
    col = [sum(observed[i][j] for i in range(k)) for j in range(k)]

    def disagreement(i: int, j: int) -> float:
        if weights is None:
            return 0.0 if i == j else 1.0
        distance = abs(i - j) / (k - 1)
        return distance if weights == "linear" else distance**2

    observed_cost = sum(disagreement(i, j) * observed[i][j] for i in range(k) for j in range(k))
    expected_cost = sum(disagreement(i, j) * row[i] * col[j] for i in range(k) for j in range(k))
    if expected_cost == 0.0:  # both annotators used a single identical label
        return 1.0 if observed_cost == 0.0 else 0.0
    return 1.0 - observed_cost / expected_cost


def build_pool(
    rankings: Mapping[str, Mapping[str, Sequence[str]]],
    top_k: int,
    seed: int,
) -> Dict[str, List[str]]:
    """Union of each system's top-k documents per query, in a seeded order, system names dropped.

    `rankings` maps system -> query_id -> ranked doc ids. Judging the union (pooling) keeps the
    gold from favouring one system; shuffling hides the rank each system gave a document.
    """
    if top_k < 1:
        raise GoldError("top_k must be positive")
    queries = sorted({q for per_system in rankings.values() for q in per_system})
    pool: Dict[str, List[str]] = {}
    for query_id in queries:
        docs = {
            doc for system in sorted(rankings) for doc in rankings[system].get(query_id, [])[:top_k]
        }
        ordered = sorted(docs)
        random.Random(f"{seed}:{query_id}").shuffle(ordered)
        pool[query_id] = ordered
    return pool


def item_id(query_id: str, doc_id: str) -> str:
    return hashlib.sha256(f"{query_id}\x00{doc_id}".encode("utf-8")).hexdigest()[:16]


def build_items(
    pool: Mapping[str, Sequence[str]],
    queries: Mapping[str, str],
    docs: Mapping[str, str],
) -> List[Dict[str, Any]]:
    """Annotation items (query, passage) in a stable order; raises if text is missing."""
    items = []
    for query_id in sorted(pool):
        if query_id not in queries:
            raise GoldError(f"query text missing: {query_id}")
        for doc_id in pool[query_id]:
            if doc_id not in docs:
                raise GoldError(f"document text missing: {doc_id}")
            items.append(
                {
                    "item_id": item_id(query_id, doc_id),
                    "query_id": query_id,
                    "doc_id": doc_id,
                    "query": queries[query_id],
                    "passage": docs[doc_id],
                }
            )
    return items


def write_blind_sheet(items: Sequence[Mapping[str, Any]], path: Path) -> None:
    """One JSON line per item with `label` empty; carries no system, rank or annotator hints."""
    with open(path, "w", encoding="utf-8") as handle:
        for entry in items:
            row = {k: entry[k] for k in ("item_id", "query", "passage")}
            row["label"] = None
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def read_labels(path: Path, expected_ids: Sequence[str]) -> Dict[str, int]:
    """Return item_id -> label; every expected item must be labelled exactly once."""
    labels: Dict[str, int] = {}
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            row = json.loads(line)
            key, label = row.get("item_id"), row.get("label")
            if key in labels:
                raise GoldError(f"duplicate item: {key}")
            if label not in RELEVANCE_LABELS or isinstance(label, bool):
                raise GoldError(f"invalid label for {key}: {label!r}")
            labels[key] = label
    missing = set(expected_ids) - set(labels)
    extra = set(labels) - set(expected_ids)
    if missing or extra:
        raise GoldError(f"label set mismatch: {len(missing)} missing, {len(extra)} unexpected")
    return labels


def reconcile(
    a: Mapping[str, int],
    b: Mapping[str, int],
    adjudication: Optional[Mapping[str, Any]] = None,
    threshold: float = DEFAULT_KAPPA_THRESHOLD,
) -> Dict[str, Any]:
    """Measure agreement and merge labels.

    The batch is accepted only if weighted kappa reaches `threshold` and every disagreement has
    an adjudicator decision (a label, or UNRESOLVED_CONFLICT, which is excluded from the gold).
    A batch under threshold is returned for guideline revision, not adjudicated into acceptance.
    """
    if set(a) != set(b):
        raise GoldError("annotators labelled different items")
    adjudication = adjudication or {}
    ids = sorted(a)
    kappa = cohen_kappa([a[i] for i in ids], [b[i] for i in ids], weights="quadratic")
    disagreements = [i for i in ids if a[i] != b[i]]
    unadjudicated = [i for i in disagreements if i not in adjudication]
    for key in adjudication:
        if key not in disagreements:
            raise GoldError(f"adjudication for a non-disagreement item: {key}")
        if adjudication[key] not in (*RELEVANCE_LABELS, UNRESOLVED):
            raise GoldError(f"invalid adjudication for {key}: {adjudication[key]!r}")
    gold = {i: a[i] for i in ids if a[i] == b[i]}
    gold.update({i: adjudication[i] for i in adjudication if adjudication[i] != UNRESOLVED})
    status = "returned_for_guideline_revision"
    if kappa >= threshold:
        status = "needs_adjudication" if unadjudicated else "accepted"
    return {
        "items": len(ids),
        "weighted_kappa_quadratic": kappa,
        "nominal_kappa": cohen_kappa([a[i] for i in ids], [b[i] for i in ids]),
        "threshold": threshold,
        "disagreements": len(disagreements),
        "unadjudicated": unadjudicated,
        "unresolved": sorted(i for i in adjudication if adjudication[i] == UNRESOLVED),
        "status": status,
        "gold": gold if status == "accepted" else {},
    }


def seal_digest(gold: Mapping[str, int], guideline_sha256: str) -> str:
    """Digest binding the final labels to the frozen guideline, for the evaluation config."""
    payload = json.dumps(
        {"guideline": guideline_sha256, "labels": dict(sorted(gold.items()))}, sort_keys=True
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
