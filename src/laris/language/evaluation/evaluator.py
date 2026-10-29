"""Evaluation of a trained language encoder on the held-out val/test splits.

Every task is scored per dataset and per language against a trivial baseline; a task/language
group passes only when it beats its baseline by the margin in the acceptance config (ADR-008).
"""

import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pyarrow.parquet as pq

from laris.language.evaluation import metrics as M
from laris.language.inference.loader import LoadedEncoder
from laris.language.training.dataloader import (
    SEP_ID,
    TASK_DATASET_DIRS,
    StreamingParquetMultiTaskDataLoader,
)

EVAL_SPLITS = ("val", "test")
NLI_CLASSES = 3
DATASET_LANGUAGE = {
    "wikipedia_en": "en", "all_nli": "en", "anli": "en", "quora": "en", "paws": "en",
    "quora_duplicates": "en", "stsb": "en", "squad": "en", "hotpotqa": "en", "fever": "en",
    "wikipedia_vi": "vi", "cc100_vi_clean": "vi", "vinli": "vi", "vists": "vi",
    "viquad": "vi", "viquad_v2": "vi",
}  # fmt: skip
PRIMARY_METRIC = {
    "mlm": "masked_accuracy", "nli": "macro_f1", "paraphrase": "auc",
    "similarity": "spearman", "qa": "f1",
}  # fmt: skip


@dataclass
class DatasetResult:
    task: str
    dataset: str
    language: str
    samples: int
    metrics: Dict[str, float]
    baseline: Dict[str, float]
    baseline_source: str = "train"


@dataclass
class EvaluationReport:
    split: str
    results: List[DatasetResult] = field(default_factory=list)
    groups: List[Dict[str, Any]] = field(default_factory=list)
    passed: bool = False


def _spans(logits: np.ndarray, mask: np.ndarray, max_len: int = 64) -> List[Tuple[int, int]]:
    out = []
    for lg, mk in zip(logits, mask):
        valid = mk.astype(bool)
        start = np.where(valid, lg[:, 0], -np.inf)
        end = np.where(valid, lg[:, 1], -np.inf)
        n = len(valid)
        ones = np.ones((n, n), dtype=bool)
        allowed = np.triu(ones) & ~np.triu(ones, k=max_len)
        score = np.where(allowed, start[:, None] + end[None, :], -np.inf)
        s, e = np.unravel_index(int(np.argmax(score)), score.shape)
        out.append((int(s), int(e)))
    return out


def _jaccard(token_ids: np.ndarray) -> np.ndarray:
    """Token-set overlap between the two [SEP]-delimited segments of each pair."""
    scores = []
    for row in token_ids:
        full = [int(t) for t in row]
        seps = [i for i, t in enumerate(full) if t == SEP_ID]
        if len(seps) < 2:
            scores.append(0.0)
            continue
        first = {t for t in full[1 : seps[0]] if t > 4}
        second = {t for t in full[seps[0] + 1 : seps[1]] if t > 4}
        union = first | second
        scores.append(len(first & second) / len(union) if union else 0.0)
    return np.asarray(scores)


def _mean(values: List[float]) -> float:
    return float(np.mean(values)) if values else 0.0


class LanguageEncoderEvaluator:
    def __init__(
        self,
        encoder: LoadedEncoder,
        data_dir: Path,
        thresholds: Dict[str, Any],
        max_samples: int = 2000,
        batch_size: int = 16,
        seed: int = 42,
    ) -> None:
        self.encoder = encoder
        self.data_dir = Path(data_dir)
        self.thresholds = thresholds
        self.max_samples = max_samples
        self.batch_size = batch_size
        self.seed = seed

    # ------------------------------------------------------------------ data access
    def _loader(self, task: str, files: List[Path]) -> StreamingParquetMultiTaskDataLoader:
        return StreamingParquetMultiTaskDataLoader(
            task_paths={task: list(files)},
            tokenizer=self.encoder.tokenizer,
            vocab_size=self.encoder.config.vocab_size,
            seq_len=self.encoder.seq_len,
            batch_size=self.batch_size,
            return_tensors="pt",
            seed=self.seed,
            fallback_to_synthetic=False,
        )

    @staticmethod
    def _row_count(files: List[Path]) -> int:
        return sum(pq.ParquetFile(f).metadata.num_rows for f in files)

    def _batches(self, task: str, files: List[Path], limit: int):
        loader = self._loader(task, files)
        seen = 0
        while seen < limit:
            batch = loader.generate_batch(task_type=task)
            take = min(batch.batch_size, limit - seen)
            seen += take
            yield batch, take

    # ------------------------------------------------------------------ per-task scoring
    def _forward(self, batch: Any) -> Dict[str, Any]:
        import torch

        device = self.encoder.device
        with torch.no_grad():
            out: Dict[str, Any] = self.encoder.model(
                batch.token_ids.to(device), attention_mask=batch.attention_mask.to(device)
            )
        return out

    def _train_files(self, dataset: str) -> List[Path]:
        return sorted((self.data_dir / dataset).glob("train*.parquet"))

    def _score_mlm(self, files: List[Path], train_files: List[Path], n: int) -> Tuple[Any, Any]:
        vocab = self.encoder.config.vocab_size
        gold_all: List[np.ndarray] = []
        pred_all: List[np.ndarray] = []
        nll = 0.0
        for batch, take in self._batches("mlm", files, n):
            out = self._forward(batch)
            labels = batch.labels["mlm_labels"][:take]
            logits = out["mlm_logits"][:take].float().cpu()
            sel = labels >= 0
            if not bool(sel.any()):
                continue
            masked_logits = logits[sel]
            gold = labels[sel]
            logp = masked_logits.log_softmax(-1)
            nll += float(-logp[np.arange(len(gold)), gold.numpy()].sum())
            gold_all.append(gold.numpy())
            pred_all.append(masked_logits.argmax(-1).numpy())
        gold_v = np.concatenate(gold_all) if gold_all else np.zeros(0, dtype=np.int64)
        pred_v = np.concatenate(pred_all) if pred_all else np.zeros(0, dtype=np.int64)
        count = max(1, len(gold_v))
        metrics = {
            "masked_accuracy": M.accuracy(pred_v, gold_v),
            "perplexity": math.exp(min(50.0, nll / count)),
            "masked_tokens": float(len(gold_v)),
        }
        counts = np.zeros(vocab, dtype=np.float64)
        source = "train"
        if train_files:
            for batch, take in self._batches("mlm", train_files, n):
                lab = batch.labels["mlm_labels"][:take].numpy()
                counts += np.bincount(lab[lab >= 0], minlength=vocab)[:vocab]
        else:
            source = "eval"
            counts += np.bincount(gold_v, minlength=vocab)[:vocab]
        smooth = (counts + 1.0) / (counts.sum() + vocab)
        top1 = float((gold_v == int(np.argmax(counts))).mean()) if len(gold_v) else 0.0
        base = {
            "unigram_top1": top1,
            "masked_accuracy": top1,
            "unigram_perplexity": (
                float(math.exp(-np.log(smooth[gold_v]).mean())) if len(gold_v) else float(vocab)
            ),
        }
        return metrics, (base, source)

    def _score_nli(self, files: List[Path], train_files: List[Path], n: int) -> Tuple[Any, Any]:
        pred: List[int] = []
        gold: List[int] = []
        for batch, take in self._batches("nli", files, n):
            out = self._forward(batch)
            pred.extend(out["nli_logits"][:take].argmax(-1).cpu().tolist())
            gold.extend(batch.labels["nli_labels"][:take].tolist())
        metrics = {
            "accuracy": M.accuracy(pred, gold),
            "macro_f1": M.macro_f1(pred, gold, NLI_CLASSES),
        }
        source, ref = "train", []
        if train_files:
            for batch, take in self._batches("nli", train_files, n):
                ref.extend(batch.labels["nli_labels"][:take].tolist())
        else:
            source, ref = "eval", gold
        majority = int(np.argmax(np.bincount(ref, minlength=NLI_CLASSES)))
        const = [majority] * len(gold)
        base = {
            "accuracy": M.accuracy(const, gold),
            "macro_f1": M.macro_f1(const, gold, NLI_CLASSES),
            "majority_class": M.macro_f1(const, gold, NLI_CLASSES),
        }
        return metrics, (base, source)

    def _score_paraphrase(
        self, files: List[Path], train_files: List[Path], n: int
    ) -> Tuple[Any, Any]:
        prob: List[float] = []
        gold: List[int] = []
        for batch, take in self._batches("paraphrase", files, n):
            out = self._forward(batch)
            prob.extend(out["paraphrase_prob"][:take].float().reshape(-1).cpu().tolist())
            gold.extend(int(v) for v in batch.labels["para_labels"][:take].tolist())
        metrics = {
            "auc": M.auc(prob, gold),
            "f1": M.f1_binary([int(p >= 0.5) for p in prob], gold),
            "accuracy": M.accuracy([int(p >= 0.5) for p in prob], gold),
        }
        base = {"random": 0.5, "auc": 0.5, "f1": M.f1_binary([1] * len(gold), gold)}
        return metrics, (base, "constant")

    def _score_similarity(
        self, files: List[Path], train_files: List[Path], n: int
    ) -> Tuple[Any, Any]:
        pred: List[float] = []
        gold: List[float] = []
        overlap: List[float] = []
        for batch, take in self._batches("similarity", files, n):
            out = self._forward(batch)
            pred.extend(out["similarity_score"][:take].float().reshape(-1).cpu().tolist())
            gold.extend(batch.labels["sim_labels"][:take].tolist())
            overlap.extend(_jaccard(batch.token_ids[:take].numpy()).tolist())
        metrics = {"pearson": M.pearson(pred, gold), "spearman": M.spearman(pred, gold)}
        base = {
            "token_jaccard": M.spearman(overlap, gold),
            "pearson": M.pearson(overlap, gold),
            "spearman": M.spearman(overlap, gold),
        }
        return metrics, (base, "lexical")

    def _score_qa(self, files: List[Path], train_files: List[Path], n: int) -> Tuple[Any, Any]:
        pred: List[Tuple[int, int]] = []
        gold: List[Tuple[int, int]] = []
        for batch, take in self._batches("qa", files, n):
            out = self._forward(batch)
            logits = out["qa_logits"][:take].float().cpu().numpy()
            pred.extend(_spans(logits, batch.attention_mask[:take].numpy()))
            starts = batch.labels["qa_start_positions"][:take].tolist()
            ends = batch.labels["qa_end_positions"][:take].tolist()
            gold.extend(zip(starts, ends))
        metrics = {
            "exact_match": _mean([float(p == g) for p, g in zip(pred, gold)]),
            "f1": _mean([M.span_f1(p, g) for p, g in zip(pred, gold)]),
        }
        no_answer = [(0, 0)] * len(gold)
        baseline_f1 = _mean([M.span_f1(p, g) for p, g in zip(no_answer, gold)])
        base = {
            "no_answer_or_first": baseline_f1,
            "f1": baseline_f1,
            "exact_match": _mean([float(p == g) for p, g in zip(no_answer, gold)]),
        }
        return metrics, (base, "constant")

    # ------------------------------------------------------------------ orchestration
    def evaluate(self, split: str) -> EvaluationReport:
        if split not in EVAL_SPLITS:
            raise ValueError(f"split must be one of {EVAL_SPLITS}; training data is never scored")
        report = EvaluationReport(split=split)
        scorers = {
            "mlm": self._score_mlm,
            "nli": self._score_nli,
            "paraphrase": self._score_paraphrase,
            "similarity": self._score_similarity,
            "qa": self._score_qa,
        }
        self.encoder.model.eval()
        for task, dirs in TASK_DATASET_DIRS.items():
            for dataset in dirs:
                files = sorted((self.data_dir / dataset).glob(f"{split}*.parquet"))
                if not files:
                    continue
                n = min(self._row_count(files), self.max_samples)
                metrics, (baseline, source) = scorers[task](files, self._train_files(dataset), n)
                report.results.append(
                    DatasetResult(
                        task=task,
                        dataset=dataset,
                        language=DATASET_LANGUAGE.get(dataset, "unknown"),
                        samples=n,
                        metrics=metrics,
                        baseline=baseline,
                        baseline_source=source,
                    )
                )
        report.groups = self._aggregate(report.results)
        report.passed = bool(report.groups) and all(g["passed"] for g in report.groups)
        return report

    def _aggregate(self, results: List[DatasetResult]) -> List[Dict[str, Any]]:
        groups: Dict[Tuple[str, str], List[DatasetResult]] = {}
        for r in results:
            groups.setdefault((r.task, r.language), []).append(r)
        out = []
        for (task, language), rows in sorted(groups.items()):
            cfg = self.thresholds["tasks"][task]
            metric = cfg["metric"]
            weights = np.asarray([r.samples for r in rows], dtype=np.float64)
            value = float(np.average([r.metrics[metric] for r in rows], weights=weights))
            base = float(np.average([r.baseline[cfg["baseline"]] for r in rows], weights=weights))
            required = max(base + float(cfg["min_margin"]), float(cfg["min_absolute"]))
            out.append(
                {
                    "task": task,
                    "language": language,
                    "datasets": [r.dataset for r in rows],
                    "samples": int(weights.sum()),
                    "metric": metric,
                    "value": value,
                    "baseline": base,
                    "required": required,
                    "passed": bool(value >= required),
                }
            )
        return out


def load_thresholds(path: Path) -> Dict[str, Any]:
    import yaml

    with open(path, "r", encoding="utf-8") as handle:
        data: Dict[str, Any] = yaml.safe_load(handle)
    missing = set(PRIMARY_METRIC) - set(data.get("tasks", {}))
    if missing:
        raise ValueError(f"Threshold config is missing tasks: {sorted(missing)}")
    return data


def assert_leakage_verified(data_dir: Path) -> None:
    """Refuses to evaluate unless the partition manifest proves splits are leakage-free."""
    manifest = Path(data_dir) / "task_splits_manifest.json"
    if not manifest.is_file():
        raise FileNotFoundError(
            f"{manifest} not found: run `laris data partition` so split isolation is recorded"
        )
    with open(manifest, "r", encoding="utf-8") as handle:
        entries = json.load(handle).get("partitioned_datasets", [])
    bad = [e["dataset_id"] for e in entries if not e.get("leakage_verified", False)]
    if bad:
        raise ValueError(f"Datasets without verified split isolation: {bad}")


def report_to_dict(
    report: EvaluationReport, extra: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    body: Dict[str, Any] = {
        "split": report.split,
        "passed": report.passed,
        "groups": report.groups,
        "datasets": [
            {
                "task": r.task, "dataset": r.dataset, "language": r.language,
                "samples": r.samples, "metrics": r.metrics, "baseline": r.baseline,
                "baseline_source": r.baseline_source,
            }
            for r in report.results
        ],
    }  # fmt: skip
    body.update(extra or {})
    return body
