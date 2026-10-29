"""Streaming multi-task dataloader with temperature-scaled dynamic sampling.

Adheres to DOC-SPEC-TRAIN-001 Section 4.2:
- Dynamic temperature sampling: p_k = N_k^alpha / sum_j(N_j^alpha) with alpha = 0.7
- Multi-task support: MLM, 3-Way NLI, Paraphrase, Semantic Similarity, and QA
- Streaming batch iteration using PyArrow to enforce bounded RAM
- Pure Python and PyTorch-compatible batch generation
"""

import logging
import math
import random
import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Tuple, Union

import numpy as np
import pyarrow.parquet as pq

logger = logging.getLogger(__name__)

VALID_SPLITS = {"train", "val", "test"}


@dataclass(frozen=True)
class TaskBatch:
    """Canonical batch container for multi-task training and forward verification."""

    task_type: str  # "mlm", "nli", "paraphrase", "similarity", "qa"
    token_ids: Any  # (batch_size, seq_len)
    attention_mask: Any  # (batch_size, seq_len)
    labels: Dict[str, Any]  # Task-specific label tensors or arrays
    batch_size: int
    seq_len: int


class TemperatureSamplingScheduler:
    """Calculates multinomial sampling probabilities across tasks using temperature alpha."""

    def __init__(self, task_counts: Dict[str, int], alpha: float = 0.7) -> None:
        if not task_counts:
            raise ValueError("task_counts dictionary cannot be empty")
        if alpha <= 0.0:
            raise ValueError(f"alpha must be positive, got {alpha}")

        self.task_counts = task_counts
        self.alpha = alpha
        self.tasks = sorted(task_counts.keys())

        # Compute p_k = N_k^alpha / sum(N_j^alpha)
        scaled_counts = [math.pow(max(task_counts[t], 1), alpha) for t in self.tasks]
        total_scaled = sum(scaled_counts)
        self.probabilities = [c / total_scaled for c in scaled_counts]

    def sample_task(self, rng: Optional[random.Random] = None) -> str:
        """Samples a task according to the temperature-scaled distribution."""
        chooser = rng.choices if rng else random.choices
        selected = chooser(self.tasks, weights=self.probabilities, k=1)
        return selected[0]

    def get_task_probability(self, task_name: str) -> float:
        """Returns sampling probability for a given task."""
        if task_name not in self.task_counts:
            raise KeyError(f"Task '{task_name}' not found in scheduler")
        idx = self.tasks.index(task_name)
        return self.probabilities[idx]


class SyntheticMultiTaskDataLoader:
    """Mock/Synthetic multi-task data loader for contract testing and CPU verification.

    Generates properly shaped batches for all Stage 1 tasks without requiring raw disk datasets.
    """

    def __init__(
        self,
        vocab_size: int = 32000,
        seq_len: int = 512,
        batch_size: int = 4,
        alpha: float = 0.7,
        seed: int = 42,
    ) -> None:
        self.vocab_size = vocab_size
        self.seq_len = seq_len
        self.batch_size = batch_size
        self.rng = random.Random(seed)
        self.np_rng = np.random.default_rng(seed)

        # Baseline sample counts matching Stage 1 specifications
        self.task_counts = {
            "mlm": 3320430,  # Wikipedia EN + VI
            "nli": 1150647,  # All-NLI + ANLI
            "paraphrase": 469691,  # Quora + PAWS
            "similarity": 8628,  # STS-B
            "qa": 130447,  # SQuAD + ViQuAD
        }
        self.scheduler = TemperatureSamplingScheduler(self.task_counts, alpha=alpha)

    def generate_batch(self, task_type: Optional[str] = None) -> TaskBatch:
        """Generates a single synthetic batch for testing forward passes and loss calculation."""
        selected_task = task_type or self.scheduler.sample_task(self.rng)
        b, s = self.batch_size, self.seq_len

        # Token IDs and attention mask
        token_ids = self.np_rng.integers(10, self.vocab_size, size=(b, s), dtype=np.int64)
        attention_mask = np.ones((b, s), dtype=np.int64)

        labels: Dict[str, Any] = {}
        if selected_task == "mlm":
            # Masked LM labels: -100 for unmasked, token_id for masked
            mlm_labels = np.full((b, s), -100, dtype=np.int64)
            mask_positions = self.np_rng.random((b, s)) < 0.15
            mlm_labels[mask_positions] = token_ids[mask_positions]
            labels["mlm_labels"] = mlm_labels
        elif selected_task == "nli":
            # 3-way NLI: 0=Entailment, 1=Neutral, 2=Contradiction
            labels["nli_labels"] = self.np_rng.integers(0, 3, size=(b,), dtype=np.int64)
        elif selected_task == "paraphrase":
            # Binary paraphrase equivalence: 0.0 or 1.0
            labels["para_labels"] = self.np_rng.integers(0, 2, size=(b,)).astype(np.float32)
        elif selected_task == "similarity":
            # Continuous similarity score in [0.0, 1.0]
            labels["sim_labels"] = self.np_rng.uniform(0.0, 1.0, size=(b,)).astype(np.float32)
        elif selected_task == "qa":
            # Start and end positions for span extraction
            starts = self.np_rng.integers(0, s // 2, size=(b,), dtype=np.int64)
            ends = starts + self.np_rng.integers(1, 10, size=(b,), dtype=np.int64)
            ends = np.minimum(ends, s - 1)
            labels["qa_start_positions"] = starts
            labels["qa_end_positions"] = ends

        return TaskBatch(
            task_type=selected_task,
            token_ids=token_ids,
            attention_mask=attention_mask,
            labels=labels,
            batch_size=b,
            seq_len=s,
        )

    def __iter__(self) -> Iterator[TaskBatch]:
        """Infinite generator of synthetic batches."""
        while True:
            yield self.generate_batch()


def create_multi_task_sampler(
    task_counts: Dict[str, int],
    alpha: float = 0.7,
) -> TemperatureSamplingScheduler:
    """Helper factory creating temperature-scaled scheduler for multi-task datasets."""
    return TemperatureSamplingScheduler(task_counts, alpha=alpha)


class StreamingParquetMultiTaskDataLoader:
    """True streaming multi-task DataLoader reading physical Parquet shards using PyArrow.

    Enforces:
    - Bounded memory (RAM <= 250 MB) streaming via pyarrow.parquet.ParquetFile.iter_batches.
    - Temperature-scaled task selection with alpha = 0.7.
    - Dynamic MLM masking: 15% rate (80% [MASK], 10% random token, 10% unchanged).
    - Task formatting for MLM, 3-way NLI, Paraphrase, Similarity, and QA.
    - Returns canonical TaskBatch instances compatible with PyTorch and NumPy.
    """

    DEFAULT_TASK_COUNTS = {
        "mlm": 3320430,  # Wikipedia EN + VI
        "nli": 1150647,  # All-NLI + ANLI
        "paraphrase": 469691,  # Quora + PAWS
        "similarity": 8628,  # STS-B
        "qa": 130447,  # SQuAD + ViQuAD
    }

    def __init__(
        self,
        data_dir: Optional[Union[str, Path]] = None,
        task_paths: Optional[Dict[str, List[Union[str, Path]]]] = None,
        task_counts: Optional[Dict[str, int]] = None,
        tokenizer: Optional[Any] = None,
        vocab_size: int = 32000,
        seq_len: int = 512,
        batch_size: int = 4,
        alpha: float = 0.7,
        buffer_size: int = 64,
        mlm_mask_prob: float = 0.15,
        seed: int = 42,
        return_tensors: str = "np",
        fallback_to_synthetic: bool = False,
        split: str = "train",
    ) -> None:
        if split not in VALID_SPLITS:
            raise ValueError(f"split must be one of {sorted(VALID_SPLITS)}, got '{split}'")
        self.split = split
        self.data_dir = Path(data_dir) if data_dir else Path("data/processed")
        self.tokenizer = tokenizer
        self.vocab_size = vocab_size
        self.seq_len = seq_len
        self.batch_size = batch_size
        self.alpha = alpha
        self.buffer_size = buffer_size
        self.mlm_mask_prob = mlm_mask_prob
        self.rng = random.Random(seed)
        self.np_rng = np.random.default_rng(seed)
        self.return_tensors = return_tensors
        self.fallback_to_synthetic = fallback_to_synthetic

        # Discover or assign task file paths
        self.task_paths: Dict[str, List[Path]] = {}
        if task_paths:
            for task, paths in task_paths.items():
                self.task_paths[task] = [Path(p) for p in paths if Path(p).is_file()]
        else:
            self._discover_task_paths()

        # Build task counts for active tasks
        active_counts: Dict[str, int] = {}
        counts_src = task_counts or self.DEFAULT_TASK_COUNTS
        for task in self.task_paths:
            active_counts[task] = counts_src.get(task, 100000)

        self._synthetic_fallback: Optional[SyntheticMultiTaskDataLoader] = None
        if not active_counts:
            if not self.fallback_to_synthetic:
                raise FileNotFoundError(
                    f"No valid Parquet dataset shards found in {self.data_dir} "
                    "and fallback_to_synthetic is False"
                )
            self._synthetic_fallback = SyntheticMultiTaskDataLoader(
                vocab_size=self.vocab_size,
                seq_len=self.seq_len,
                batch_size=self.batch_size,
                alpha=self.alpha,
                seed=seed,
            )
            self.scheduler = self._synthetic_fallback.scheduler
        else:
            self.scheduler = TemperatureSamplingScheduler(active_counts, alpha=self.alpha)

        # Initialize streaming generators for active tasks
        self._task_iterators: Dict[str, Iterator[Dict[str, Any]]] = {}
        for task_name, path_list in self.task_paths.items():
            if path_list:
                self._task_iterators[task_name] = self._create_task_stream(
                    path_list, self.buffer_size
                )

    def _discover_task_paths(self) -> None:
        """Discovers Parquet shards of the configured split within data_dir."""
        if not self.data_dir.is_dir():
            return

        task_dir_map = {
            "mlm": ["wikipedia_en", "wikipedia_vi", "mlm"],
            "nli": ["all_nli", "anli", "nli"],
            "paraphrase": ["quora", "paws", "quora_duplicates", "paraphrase"],
            "similarity": ["stsb", "similarity"],
            "qa": ["squad", "viquad", "qa"],
        }

        for task, subdirs in task_dir_map.items():
            found: List[Path] = []
            for subdir in subdirs:
                candidate_dir = self.data_dir / subdir
                if candidate_dir.is_dir():
                    found.extend(sorted(candidate_dir.glob(f"{self.split}*.parquet")))
            if found:
                self.task_paths[task] = found

    @staticmethod
    def _create_task_stream(
        paths: List[Path],
        buffer_size: int,
    ) -> Iterator[Dict[str, Any]]:
        """Creates an infinite streaming generator yielding records with bounded RAM.

        Unreadable shards are logged once and dropped; when no readable shard remains the
        generator raises instead of spinning.
        """
        usable = list(paths)
        while usable:
            yielded = False
            for p in list(usable):
                try:
                    pq_file = pq.ParquetFile(p)
                    for batch in pq_file.iter_batches(batch_size=buffer_size):
                        for row in batch.to_pylist():
                            yielded = True
                            yield row
                except Exception as exc:
                    logger.warning("Dropping unreadable shard %s: %s", p, exc)
                    usable.remove(p)
            if not yielded and usable:
                raise RuntimeError(f"Shards contain no records: {[str(p) for p in usable]}")
        raise RuntimeError(f"No readable Parquet shards among {[str(p) for p in paths]}")

    def _tokenize(self, text: str) -> List[int]:
        """Encodes text to a list of integer token IDs."""
        if not text:
            return []
        if self.tokenizer is not None:
            if hasattr(self.tokenizer, "encode_as_ids"):
                return list(self.tokenizer.encode_as_ids(text))
            elif hasattr(self.tokenizer, "encode"):
                res = self.tokenizer.encode(text)
                if hasattr(res, "token_ids"):
                    return list(res.token_ids)
                elif isinstance(res, (list, tuple)):
                    return list(res)
            elif callable(self.tokenizer):
                res = self.tokenizer(text)
                if isinstance(res, (list, tuple)):
                    return list(res)

        # Deterministic whitespace/CRC32 fallback (stable across processes; tests only)
        return [
            (zlib.crc32(tok.encode("utf-8")) % (self.vocab_size - 10)) + 10 for tok in text.split()
        ]

    def _prepare_sequence(
        self,
        tok_ids: List[int],
        second_tok_ids: Optional[List[int]] = None,
    ) -> Tuple[List[int], List[int]]:
        """Formats 1 or 2 token sequences with [CLS], [SEP], padding, and attention mask."""
        cls_id, sep_id, pad_id = 2, 3, 0
        s = self.seq_len

        if second_tok_ids is None:
            # Single sequence: [CLS] + toks + [SEP]
            max_inner = max(0, s - 2)
            trimmed = tok_ids[:max_inner]
            full_seq = [cls_id] + trimmed + [sep_id]
        else:
            # Pair sequence: [CLS] + toks1 + [SEP] + toks2 + [SEP]
            max_inner = max(0, s - 3)
            half = max_inner // 2
            trimmed1 = tok_ids[:half]
            trimmed2 = second_tok_ids[: (max_inner - len(trimmed1))]
            full_seq = [cls_id] + trimmed1 + [sep_id] + trimmed2 + [sep_id]

        actual_len = len(full_seq)
        pad_len = max(0, s - actual_len)
        padded_seq = full_seq[:s] + [pad_id] * pad_len
        attention_mask = [1] * min(actual_len, s) + [0] * pad_len
        return padded_seq, attention_mask

    def _format_mlm_batch(self, records: List[Dict[str, Any]]) -> TaskBatch:
        """Formats records for Masked Language Modeling with 15% dynamic masking."""
        s = self.seq_len
        cls_id, sep_id, mask_id, pad_id = 2, 3, 4, 0

        token_ids_list: List[List[int]] = []
        attention_mask_list: List[List[int]] = []
        mlm_labels_list: List[List[int]] = []

        for rec in records:
            text = rec.get("text") or rec.get("content") or rec.get("document") or ""
            tok_ids = self._tokenize(text)
            padded_seq, att_mask = self._prepare_sequence(tok_ids)

            # Apply dynamic MLM masking
            mlm_labels = [-100] * s
            final_tokens = list(padded_seq)

            for idx in range(s):
                tok = padded_seq[idx]
                if tok in (cls_id, sep_id, pad_id):
                    continue
                if self.rng.random() < self.mlm_mask_prob:
                    mlm_labels[idx] = tok
                    r = self.rng.random()
                    if r < 0.8:
                        final_tokens[idx] = mask_id
                    elif r < 0.9:
                        final_tokens[idx] = self.rng.randint(10, self.vocab_size - 1)
                    # 10% remains unchanged

            token_ids_list.append(final_tokens)
            attention_mask_list.append(att_mask)
            mlm_labels_list.append(mlm_labels)

        tok_arr = np.array(token_ids_list, dtype=np.int64)
        att_arr = np.array(attention_mask_list, dtype=np.int64)
        lbl_arr = np.array(mlm_labels_list, dtype=np.int64)

        return self._to_task_batch("mlm", tok_arr, att_arr, {"mlm_labels": lbl_arr})

    def _format_nli_batch(self, records: List[Dict[str, Any]]) -> TaskBatch:
        """Formats premise/hypothesis records for 3-way NLI classification."""
        token_ids_list: List[List[int]] = []
        attention_mask_list: List[List[int]] = []
        nli_labels: List[int] = []

        label_map: Dict[Any, int] = {
            "entailment": 0,
            "0": 0,
            0: 0,
            "neutral": 1,
            "1": 1,
            1: 1,
            "contradiction": 2,
            "2": 2,
            2: 2,
            "-": 1,
        }

        for rec in records:
            p = rec.get("premise") or rec.get("sentence1") or ""
            h = rec.get("hypothesis") or rec.get("sentence2") or ""
            raw_lbl = rec.get("label") if "label" in rec else rec.get("gold_label", 1)
            lbl = label_map.get(raw_lbl, 1)

            p_toks = self._tokenize(p)
            h_toks = self._tokenize(h)
            padded_seq, att_mask = self._prepare_sequence(p_toks, h_toks)

            token_ids_list.append(padded_seq)
            attention_mask_list.append(att_mask)
            nli_labels.append(lbl)

        tok_arr = np.array(token_ids_list, dtype=np.int64)
        att_arr = np.array(attention_mask_list, dtype=np.int64)
        lbl_arr = np.array(nli_labels, dtype=np.int64)

        return self._to_task_batch("nli", tok_arr, att_arr, {"nli_labels": lbl_arr})

    def _format_paraphrase_batch(self, records: List[Dict[str, Any]]) -> TaskBatch:
        """Formats sentence pair records for binary paraphrase classification."""
        token_ids_list: List[List[int]] = []
        attention_mask_list: List[List[int]] = []
        para_labels: List[float] = []

        for rec in records:
            q1 = rec.get("question1") or rec.get("sentence1") or ""
            q2 = rec.get("question2") or rec.get("sentence2") or ""
            raw_lbl = rec.get("is_duplicate") if "is_duplicate" in rec else rec.get("label", 0)
            lbl = 1.0 if raw_lbl in (1, True, "1", "duplicate") else 0.0

            q1_toks = self._tokenize(q1)
            q2_toks = self._tokenize(q2)
            padded_seq, att_mask = self._prepare_sequence(q1_toks, q2_toks)

            token_ids_list.append(padded_seq)
            attention_mask_list.append(att_mask)
            para_labels.append(lbl)

        tok_arr = np.array(token_ids_list, dtype=np.int64)
        att_arr = np.array(attention_mask_list, dtype=np.int64)
        lbl_arr = np.array(para_labels, dtype=np.float32)

        return self._to_task_batch("paraphrase", tok_arr, att_arr, {"para_labels": lbl_arr})

    def _format_similarity_batch(self, records: List[Dict[str, Any]]) -> TaskBatch:
        """Formats sentence pair records for STS semantic similarity regression."""
        token_ids_list: List[List[int]] = []
        attention_mask_list: List[List[int]] = []
        sim_labels: List[float] = []

        for rec in records:
            s1 = rec.get("sentence1") or ""
            s2 = rec.get("sentence2") or ""
            raw_val = (
                rec.get("score") if "score" in rec else rec.get("similarity_score", 0.0)
            )
            raw_score = float(raw_val if raw_val is not None else 0.0)
            # Normalize STS 0-5 scores to [0.0, 1.0]
            if raw_score > 1.0:
                raw_score = raw_score / 5.0
            score = max(0.0, min(1.0, raw_score))

            s1_toks = self._tokenize(s1)
            s2_toks = self._tokenize(s2)
            padded_seq, att_mask = self._prepare_sequence(s1_toks, s2_toks)

            token_ids_list.append(padded_seq)
            attention_mask_list.append(att_mask)
            sim_labels.append(score)

        tok_arr = np.array(token_ids_list, dtype=np.int64)
        att_arr = np.array(attention_mask_list, dtype=np.int64)
        lbl_arr = np.array(sim_labels, dtype=np.float32)

        return self._to_task_batch("similarity", tok_arr, att_arr, {"sim_labels": lbl_arr})

    def _locate_answer_span(
        self, rec: Dict[str, Any], context: str, q_toks: List[int]
    ) -> Tuple[int, int]:
        """Maps the first gold answer (char offset) to token positions in the pair sequence.

        Returns (0, 0) -- the [CLS] position -- when there is no answer or it was truncated.
        """
        answers = rec.get("answers")
        if not isinstance(answers, dict):
            return 0, 0
        texts = answers.get("text") or []
        starts = answers.get("answer_start") or []
        if len(texts) == 0 or len(starts) == 0 or not texts[0]:
            return 0, 0
        char_start = int(starts[0])
        if char_start < 0 or context[char_start : char_start + len(texts[0])] != texts[0]:
            return 0, 0

        max_inner = max(0, self.seq_len - 3)
        question_len = min(len(q_toks), max_inner // 2)
        context_offset = 1 + question_len + 1  # [CLS] question [SEP]
        context_limit = min(self.seq_len - 1, context_offset + (max_inner - question_len))
        prefix_len = len(self._tokenize(context[:char_start]))
        answer_len = len(self._tokenize(texts[0]))
        if answer_len == 0:
            return 0, 0
        start_pos = context_offset + prefix_len
        end_pos = start_pos + answer_len - 1
        if end_pos >= context_limit:
            return 0, 0
        return start_pos, end_pos

    def _format_qa_batch(self, records: List[Dict[str, Any]]) -> TaskBatch:
        """Formats question/context records for extractive QA span prediction."""
        token_ids_list: List[List[int]] = []
        attention_mask_list: List[List[int]] = []
        starts: List[int] = []
        ends: List[int] = []

        for rec in records:
            q = rec.get("question") or ""
            c = rec.get("context") or ""
            q_toks = self._tokenize(q)
            c_toks = self._tokenize(c)

            padded_seq, att_mask = self._prepare_sequence(q_toks, c_toks)
            token_ids_list.append(padded_seq)
            attention_mask_list.append(att_mask)

            start_pos, end_pos = self._locate_answer_span(rec, c, q_toks)
            starts.append(start_pos)
            ends.append(end_pos)

        tok_arr = np.array(token_ids_list, dtype=np.int64)
        att_arr = np.array(attention_mask_list, dtype=np.int64)
        start_arr = np.array(starts, dtype=np.int64)
        end_arr = np.array(ends, dtype=np.int64)

        return self._to_task_batch(
            "qa",
            tok_arr,
            att_arr,
            {"qa_start_positions": start_arr, "qa_end_positions": end_arr},
        )

    def _to_task_batch(
        self,
        task_type: str,
        token_ids: np.ndarray,
        attention_mask: np.ndarray,
        labels: Dict[str, np.ndarray],
    ) -> TaskBatch:
        """Constructs TaskBatch, converting to PyTorch tensors if return_tensors='pt'."""
        if self.return_tensors == "pt":
            try:
                import torch

                pt_token_ids = torch.from_numpy(token_ids)
                pt_attention_mask = torch.from_numpy(attention_mask)
                pt_labels = {k: torch.from_numpy(v) for k, v in labels.items()}
                return TaskBatch(
                    task_type=task_type,
                    token_ids=pt_token_ids,
                    attention_mask=pt_attention_mask,
                    labels=pt_labels,
                    batch_size=len(token_ids),
                    seq_len=self.seq_len,
                )
            except ImportError:
                pass

        return TaskBatch(
            task_type=task_type,
            token_ids=token_ids,
            attention_mask=attention_mask,
            labels=labels,
            batch_size=len(token_ids),
            seq_len=self.seq_len,
        )

    def generate_batch(self, task_type: Optional[str] = None) -> TaskBatch:
        """Generates a batch by streaming records from physical Parquet files."""
        if self._synthetic_fallback is not None:
            return self._synthetic_fallback.generate_batch(task_type=task_type)

        selected_task = task_type or self.scheduler.sample_task(self.rng)
        if selected_task not in self._task_iterators:
            selected_task = next(iter(self._task_iterators.keys()))

        it = self._task_iterators[selected_task]
        records: List[Dict[str, Any]] = []
        for _ in range(self.batch_size):
            try:
                records.append(next(it))
            except StopIteration:
                break

        if not records:
            if self._synthetic_fallback is not None:
                return self._synthetic_fallback.generate_batch(task_type=selected_task)
            raise RuntimeError(f"No records could be read for task '{selected_task}'")

        if selected_task == "mlm":
            return self._format_mlm_batch(records)
        elif selected_task == "nli":
            return self._format_nli_batch(records)
        elif selected_task == "paraphrase":
            return self._format_paraphrase_batch(records)
        elif selected_task == "similarity":
            return self._format_similarity_batch(records)
        elif selected_task == "qa":
            return self._format_qa_batch(records)
        else:
            raise ValueError(f"Unknown task: {selected_task}")

    def __iter__(self) -> Iterator[TaskBatch]:
        """Infinite generator yielding streaming TaskBatch instances."""
        while True:
            yield self.generate_batch()
