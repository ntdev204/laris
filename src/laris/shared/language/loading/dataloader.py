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
from typing import Any, Dict, Iterator, List, Mapping, Optional, Sequence, Tuple, Union

import numpy as np
import pyarrow.parquet as pq

from laris.shared.config.schemas import (
    DEFAULT_CONTRASTIVE_ROW_SHARES,
    DEFAULT_CONTRASTIVE_ROW_WEIGHTS,
)
from laris.shared.language.loading.balanced import (
    BALANCEABLE_TASKS,
    LabelBalancedSampler,
    label_counts,
    nli_label,
    paraphrase_label,
)
from laris.shared.language.loading.relations import (
    RelationRowSampler,
    relation_stream,
    shuffled,
)
from laris.shared.language.loading.segments import (
    IGNORE_INDEX,
    ORDER_CLASSES,
    ORDER_OTHER_DOCUMENT,
    ORDER_SWAPPED,
    build_pair_sequence,
    cut_two_segments,
    document_id,
    draw_order_class,
    validate_shares,
)

logger = logging.getLogger(__name__)

VALID_SPLITS = {"train", "val", "test"}


CLS_ID, SEP_ID, MASK_ID, PAD_ID = 2, 3, 4, 0

# Processed-data directories (under data/processed) that feed each task.
TASK_DATASET_DIRS: Dict[str, List[str]] = {
    # English only since D46 / ADR-022; the Vietnamese directories were withdrawn and deleted.
    "mlm": [
        "wikipedia_en", "fineweb_edu_en", "openwebtext_en", "c4_en", "gutenberg_en",
        "cc_news_en", "cnn_dailymail_en", "xsum_en", "wikipedia_simple_en", "mlm",
    ],
    "nli": ["all_nli", "anli", "fever", "wanli_en", "scitail_en", "vitaminc_en", "nli"],
    # paws_swap_en and paws_unlabeled_en (T200) are word-order sources with a train split only; the
    # unlabeled labels are model-assigned (`label_source: model`).
    "paraphrase": [
        "quora", "paws", "quora_duplicates", "mrpc_en", "paws_swap_en", "paws_unlabeled_en",
        "paraphrase",
    ],
    "similarity": ["stsb", "sts_extra_en", "similarity_llm_en", "similarity"],
    # duorc_en, ropes_en, quoref_en and drop_en (T200) have a train split only.
    "qa": [
        "squad", "hotpotqa", "squad_v2_en", "adversarial_qa_en", "duorc_en", "ropes_en",
        "quoref_en", "drop_en", "qa",
    ],
}

# Dense-retrieval pairs (T178). Kept out of TASK_DATASET_DIRS on purpose: the task exists only when
# a run enables it (`include_retrieval_task`) and it has no per-dataset scorer in the evaluator.
RETRIEVAL_TASK = "retrieval"
# Contrastive similarity rows (T199): the relation pairs of T197, train split only; like retrieval,
# the task exists only when a run enables it and has no per-dataset scorer.
CONTRASTIVE_SIM_TASK = "contrastive_sim"
CONTRASTIVE_SIM_DATASET_DIR = "relation_pairs_en"
RETRIEVAL_DATASET_DIRS: List[str] = [
    "gooaq_en", "natural_questions_pairs_en", "msmarco_en", "eli5_en", "yahoo_answers_en",
    "stackexchange_duplicates_en", "specter_triplets_en", "altlex_en", "simple_wiki_en",
    "coco_captions_en",
]


def _text_length(record: Dict[str, Any]) -> int:
    """Characters of text in a record: a cheap proxy for its token length."""
    return sum(len(v) for v in record.values() if isinstance(v, str))


def build_sequence(
    tok_ids: List[int],
    second_tok_ids: Optional[List[int]],
    seq_len: int,
) -> Tuple[List[int], List[int]]:
    """[CLS] a [SEP] (b [SEP]) padded to `seq_len`, with its attention mask.

    Shared by training batches and inference so both format inputs identically.
    """
    if second_tok_ids is None:
        trimmed = tok_ids[: max(0, seq_len - 2)]
        full_seq = [CLS_ID] + trimmed + [SEP_ID]
    else:
        max_inner = max(0, seq_len - 3)
        trimmed1 = tok_ids[: max_inner // 2]
        trimmed2 = second_tok_ids[: (max_inner - len(trimmed1))]
        full_seq = [CLS_ID] + trimmed1 + [SEP_ID] + trimmed2 + [SEP_ID]
    actual_len = len(full_seq)
    pad_len = max(0, seq_len - actual_len)
    padded_seq = full_seq[:seq_len] + [PAD_ID] * pad_len
    attention_mask = [1] * min(actual_len, seq_len) + [0] * pad_len
    return padded_seq, attention_mask


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
    """Calculates multinomial sampling probabilities across tasks using temperature alpha.

    `floors` (task -> minimum share of the steps) lifts a small task above its temperature share
    (a 20 k-row task gets 0.5 % of the steps at alpha 0.7, too few for its head to learn); the
    other tasks keep their relative proportions and give up the difference. Floors of tasks that
    are not active are ignored.
    """

    def __init__(
        self,
        task_counts: Dict[str, int],
        alpha: float = 0.7,
        floors: Optional[Dict[str, float]] = None,
    ) -> None:
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
        self.floors = {t: f for t, f in (floors or {}).items() if t in task_counts}
        if self.floors:
            self.probabilities = self._apply_floors(self.probabilities, self.floors)

    def _apply_floors(self, probabilities: List[float], floors: Dict[str, float]) -> List[float]:
        for task, floor in floors.items():
            if not math.isfinite(floor) or not 0.0 <= floor < 1.0:
                raise ValueError(f"floor for '{task}' must be in [0, 1), got {floor}")
        if sum(floors.values()) >= 1.0:
            raise ValueError(f"floors must sum to less than 1, got {sum(floors.values())}")
        fixed: Dict[str, float] = {}
        while True:
            free = [t for t in self.tasks if t not in fixed]
            budget = 1.0 - sum(fixed.values())
            mass = sum(probabilities[self.tasks.index(t)] for t in free)
            share = {t: probabilities[self.tasks.index(t)] / mass * budget for t in free}
            below = [t for t in free if t in floors and share[t] < floors[t]]
            if not below:
                break
            for t in below:
                fixed[t] = floors[t]
        share.update(fixed)
        return [share[t] for t in self.tasks]

    def sample_task(self, rng: Optional[random.Random] = None) -> str:
        """Samples a task according to the temperature-scaled distribution."""
        chooser = rng.choices if rng else random.choices
        selected = chooser(self.tasks, weights=self.probabilities, k=1)
        return selected[0]

    def sample_tasks(self, rng: Optional[random.Random], count: int) -> List[str]:
        """`count` different tasks for one mixed step (T201), drawn without replacement.

        Each draw follows the usual distribution renormalised over the tasks not yet drawn.
        `count == 1` is exactly `sample_task` (same RNG use), so the default path is unchanged.
        """
        if count < 1:
            raise ValueError(f"tasks per step must be >= 1, got {count}")
        if count > len(self.tasks):
            raise ValueError(
                f"tasks per step ({count}) exceeds the {len(self.tasks)} active tasks "
                f"{self.tasks}"
            )
        if count == 1:
            return [self.sample_task(rng)]
        chooser = rng.choices if rng else random.choices
        remaining = list(zip(self.tasks, self.probabilities))
        drawn: List[str] = []
        for _ in range(count):
            names = [name for name, _ in remaining]
            weights = [max(weight, 1e-12) for _, weight in remaining]
            pick = chooser(names, weights=weights, k=1)[0]
            drawn.append(pick)
            remaining = [item for item in remaining if item[0] != pick]
        return drawn

    def get_task_probability(self, task_name: str) -> float:
        """Returns sampling probability for a given task."""
        if task_name not in self.task_counts:
            raise KeyError(f"Task '{task_name}' not found in scheduler")
        idx = self.tasks.index(task_name)
        return self.probabilities[idx]


def task_inclusion_probabilities(
    tasks: List[str], probabilities: List[float], count: int
) -> Dict[str, float]:
    """Chance that each task is in one mixed step of `count` different tasks (T203).

    Mirrors `TemperatureSamplingScheduler.sample_tasks` (successive draws without replacement,
    each renormalised over the tasks left), computed exactly by enumeration; the values sum to
    `count`. With `count == 1` they are the scheduler probabilities. Dividing by `count` gives
    the share of the batch draws a task receives, which is not its scheduler probability once
    `count > 1`: a large task is limited to one place in each step.
    """
    if len(tasks) != len(probabilities):
        raise ValueError("tasks and probabilities differ in length")
    if not 1 <= count <= len(tasks):
        raise ValueError(f"count must be between 1 and {len(tasks)}, got {count}")
    weights = [max(p, 1e-12) for p in probabilities]
    included = {task: 0.0 for task in tasks}

    def walk(left: List[int], chosen: List[int], mass: float) -> None:
        if len(chosen) == count:
            for index in chosen:
                included[tasks[index]] += mass
            return
        total = sum(weights[i] for i in left)
        for index in left:
            rest = [i for i in left if i != index]
            walk(rest, chosen + [index], mass * weights[index] / total)

    walk(list(range(len(tasks))), [], 1.0)
    return included


class SyntheticMultiTaskDataLoader:
    """Mock/Synthetic multi-task data loader for contract testing and CPU verification.

    Generates properly shaped batches for all language encoder tasks without raw disk datasets.
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
        self._seed = seed
        self.rng = random.Random(seed)
        self.np_rng = np.random.default_rng(seed)

        # Baseline sample counts matching the language encoder training specification
        self.task_counts = {
            "mlm": 3320430,  # Wikipedia EN (generation-1 figure)
            "nli": 1150647,  # All-NLI + ANLI
            "paraphrase": 469691,  # Quora + PAWS
            "similarity": 8628,  # STS-B
            "qa": 130447,  # SQuAD (generation-1 figure)
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

    def generate_step_batches(self, tasks_per_step: int = 1) -> List[TaskBatch]:
        """One micro-step of `tasks_per_step` batches of different tasks (T201)."""
        tasks = self.scheduler.sample_tasks(self.rng, tasks_per_step)
        return [self.generate_batch(task_type=task) for task in tasks]

    def __iter__(self) -> Iterator[TaskBatch]:
        """Infinite generator of synthetic batches."""
        while True:
            yield self.generate_batch()


def create_multi_task_sampler(
    task_counts: Dict[str, int],
    alpha: float = 0.7,
    floors: Optional[Dict[str, float]] = None,
) -> TemperatureSamplingScheduler:
    """Helper factory creating temperature-scaled scheduler for multi-task datasets."""
    return TemperatureSamplingScheduler(task_counts, alpha=alpha, floors=floors)


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
        "mlm": 3320430,  # Wikipedia EN (generation-1 figure)
        "nli": 1150647,  # All-NLI + ANLI
        "paraphrase": 469691,  # Quora + PAWS
        "similarity": 8628,  # STS-B
        "qa": 130447,  # SQuAD (generation-1 figure)
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
        task_sampling_floor: Optional[Dict[str, float]] = None,
        buffer_size: int = 64,
        mlm_mask_prob: float = 0.15,
        seed: int = 42,
        return_tensors: str = "np",
        fallback_to_synthetic: bool = False,
        split: str = "train",
        require_real_data: bool = False,
        trim_padding: bool = False,
        length_pool_batches: int = 1,
        dataset_sampling_exponents: Optional[Dict[str, float]] = None,
        dataset_sampling_weights: Optional[Dict[str, Dict[str, float]]] = None,
        include_retrieval_pairs: bool = False,
        include_retrieval_task: bool = False,
        retrieval_batch_size: Optional[int] = None,
        retrieval_max_sequence_length: Optional[int] = None,
        mlm_pair_fraction: float = 0.0,
        order_task: bool = False,
        order_class_shares: Tuple[float, float, float] = (1 / 3, 1 / 3, 1 / 3),
        label_balanced_tasks: Sequence[str] = (),
        include_contrastive_sim_task: bool = False,
        contrastive_sim_batch_size: Optional[int] = None,
        contrastive_sim_max_sequence_length: Optional[int] = None,
        contrastive_sim_row_shares: Optional[Mapping[str, float]] = None,
        contrastive_sim_row_weights: Optional[Mapping[str, float]] = None,
    ) -> None:
        if length_pool_batches < 1:
            raise ValueError("length_pool_batches must be >= 1")
        if retrieval_batch_size is not None and retrieval_batch_size < 2:
            raise ValueError("retrieval_batch_size must be >= 2 (in-batch negatives need a batch)")
        max_len = retrieval_max_sequence_length
        if max_len is not None and not 8 <= max_len <= seq_len:
            raise ValueError("retrieval_max_sequence_length must be between 8 and seq_len")
        if contrastive_sim_batch_size is not None and contrastive_sim_batch_size < 2:
            raise ValueError("contrastive_sim_batch_size must be >= 2 (in-batch negatives)")
        sim_len = contrastive_sim_max_sequence_length
        if sim_len is not None and not 8 <= sim_len <= seq_len:
            raise ValueError("contrastive_sim_max_sequence_length must be between 8 and seq_len")
        if include_contrastive_sim_task and split != "train":
            raise ValueError("the contrastive similarity task requires the train split")
        self.include_contrastive_sim_task = include_contrastive_sim_task
        self.contrastive_sim_batch_size = contrastive_sim_batch_size or batch_size
        self.contrastive_sim_seq_len = sim_len or seq_len
        self.contrastive_sim_row_shares = dict(
            contrastive_sim_row_shares or DEFAULT_CONTRASTIVE_ROW_SHARES
        )
        self.contrastive_sim_row_weights = {
            **DEFAULT_CONTRASTIVE_ROW_WEIGHTS, **dict(contrastive_sim_row_weights or {})
        }
        self._relation_samplers: Dict[str, RelationRowSampler] = {}
        if require_real_data and (tokenizer is None or fallback_to_synthetic):
            raise ValueError(
                "require_real_data needs a fitted tokenizer and forbids the synthetic fallback"
            )
        if not 0.0 <= mlm_pair_fraction <= 1.0:
            raise ValueError("mlm_pair_fraction must be between 0 and 1")
        if order_task and mlm_pair_fraction <= 0.0:
            raise ValueError(
                "order_task labels two-segment MLM rows: it needs mlm_pair_fraction > 0"
            )
        self.mlm_pair_fraction = float(mlm_pair_fraction)
        self.order_task = order_task
        self.order_class_shares = validate_shares(order_class_shares)
        # Second segments of earlier rows, the source of the other-document class; they come
        # from this loader's split only, so no segment crosses train and validation.
        self._other_segments: List[Tuple[str, List[int]]] = []
        self.stats = {"qa_total": 0, "qa_unanswerable": 0, "qa_answer_outside_window": 0}
        self.stats.update(
            {
                "mlm_sequences": 0,
                "mlm_pair_sequences": 0,
                "mlm_pair_without_boundary": 0,
                "order_other_document_unavailable": 0,
                **{f"order_{name}": 0 for name in ORDER_CLASSES},
            }
        )
        if split not in VALID_SPLITS:
            raise ValueError(f"split must be one of {sorted(VALID_SPLITS)}, got '{split}'")
        self.split = split
        self.data_dir = Path(data_dir) if data_dir else Path("data/processed")
        self.tokenizer = tokenizer
        self.vocab_size = vocab_size
        self.seq_len = seq_len
        self.batch_size = batch_size
        self.alpha = alpha
        self.task_sampling_floor = dict(task_sampling_floor or {})
        self.buffer_size = buffer_size
        self.mlm_mask_prob = mlm_mask_prob
        self._seed = seed
        self.rng = random.Random(seed)
        self.np_rng = np.random.default_rng(seed)
        self.return_tensors = return_tensors
        self.fallback_to_synthetic = fallback_to_synthetic
        self.trim_padding = trim_padding
        self.length_pool_batches = length_pool_batches
        self.dataset_sampling_exponents = dict(dataset_sampling_exponents or {})
        if any(
            (task not in TASK_DATASET_DIRS and task != RETRIEVAL_TASK)
            or not math.isfinite(power)
            or power <= 0
            for task, power in self.dataset_sampling_exponents.items()
        ):
            raise ValueError("dataset sampling exponents require known tasks and positive powers")
        # Per-source multipliers (T207): task -> {dataset directory -> factor on rows ** exponent}.
        self.dataset_sampling_weights = {
            task: dict(weights) for task, weights in (dataset_sampling_weights or {}).items()
        }
        for task, weights in self.dataset_sampling_weights.items():
            known = set(TASK_DATASET_DIRS.get(task, [])) | (
                set(RETRIEVAL_DATASET_DIRS) if task == RETRIEVAL_TASK else set()
            )
            if not known or any(
                name not in known or not math.isfinite(w) or w <= 0 for name, w in weights.items()
            ):
                raise ValueError(
                    "dataset sampling weights require a known task, its dataset directories "
                    "and positive finite factors"
                )
        if split != "train" and (
            self.dataset_sampling_exponents
            or self.dataset_sampling_weights
            or include_retrieval_pairs
        ):
            raise ValueError("dataset resampling and retrieval pairs require the train split")
        unknown = sorted(set(label_balanced_tasks) - set(BALANCEABLE_TASKS))
        if unknown:
            raise ValueError(f"label balancing supports {list(BALANCEABLE_TASKS)}, not {unknown}")
        if label_balanced_tasks and split != "train":
            raise ValueError("label balancing requires the train split (held-out keeps its prior)")
        # Source- and label-balanced tasks (T196): a source per row, then a label of that source.
        self.label_balanced_tasks = tuple(sorted(set(label_balanced_tasks)))
        self._balanced: Dict[str, LabelBalancedSampler] = {}
        self._label_counts: Dict[str, Dict[str, Dict[int, int]]] = {}
        self.include_retrieval_pairs = include_retrieval_pairs
        self.include_retrieval_task = include_retrieval_task
        self.retrieval_batch_size = retrieval_batch_size or batch_size
        self.retrieval_seq_len = retrieval_max_sequence_length or seq_len
        self._pending: Dict[str, List[List[Dict[str, Any]]]] = {}

        # Discover or assign task file paths
        self.task_paths: Dict[str, List[Path]] = {}
        if task_paths:
            for task, paths in task_paths.items():
                self.task_paths[task] = [Path(p) for p in paths if Path(p).is_file()]
        else:
            self._discover_task_paths()

        # Build task counts for active tasks
        active_counts: Dict[str, int] = {}
        if require_real_data:
            counts_src = task_counts or self._count_rows()
            unknown = sorted(t for t in self.task_paths if not counts_src.get(t))
            if unknown:
                raise ValueError(f"Cannot count real rows for tasks {unknown} in {self.data_dir}")
        else:
            counts_src = task_counts or self._count_rows() or self.DEFAULT_TASK_COUNTS
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
            self.scheduler = TemperatureSamplingScheduler(
                active_counts, alpha=self.alpha, floors=self.task_sampling_floor
            )

        self._build_streams()

    def _build_streams(self) -> None:
        """Recreate per-task streams using the configured dataset count exponents."""
        self._task_iterators: Dict[str, Iterator[Dict[str, Any]]] = {}
        self._balanced = {}
        self._relation_samplers = {}
        for task_name, path_list in self.task_paths.items():
            if path_list and task_name == CONTRASTIVE_SIM_TASK:
                buffer = max(self.buffer_size, self.contrastive_sim_batch_size) * 4
                kinds = [k for k, w in self.contrastive_sim_row_shares.items() if w > 0]
                self._relation_samplers[task_name] = RelationRowSampler(
                    {
                        kind: shuffled(
                            relation_stream(path_list, None if kind == "simcse" else kind),
                            buffer,
                            random.Random(f"{self._seed}:{task_name}:{kind}"),
                        )
                        for kind in kinds
                    },
                    self.contrastive_sim_row_shares,
                    random.Random(f"{self._seed}:{task_name}"),
                )
                self._task_iterators[task_name] = iter(())  # marks the task as available
            elif path_list and task_name in self.label_balanced_tasks:
                self._balanced[task_name] = self._balanced_sampler(task_name, path_list)
                self._task_iterators[task_name] = iter(())  # marks the task as available
            elif path_list:
                self._task_iterators[task_name] = self._interleaved_stream(
                    path_list,
                    self.buffer_size,
                    random.Random(f"{self._seed}:{task_name}"),
                    self.dataset_sampling_exponents.get(task_name, 1.0),
                    self.dataset_sampling_weights.get(task_name),
                )

    def _balanced_sampler(self, task: str, paths: List[Path]) -> LabelBalancedSampler:
        """A source- and label-balanced sampler; a source is a dataset directory."""
        sources: Dict[str, List[Path]] = {}
        for path in paths:
            sources.setdefault(path.parent.name, []).append(path)
        if task not in self._label_counts:
            counts: Dict[str, Dict[int, int]] = {}
            for name, shard_paths in sources.items():
                merged: Dict[int, int] = {}
                for shard in shard_paths:
                    for label, n in label_counts(shard, task).items():
                        merged[label] = merged.get(label, 0) + n
                counts[name] = merged
            self._label_counts[task] = counts
        return LabelBalancedSampler(
            task,
            sources,
            lambda shard_paths: self._create_task_stream(shard_paths, self.buffer_size),
            random.Random(f"{self._seed}:{task}:balanced"),
            dataset_exponent=self.dataset_sampling_exponents.get(task, 1.0),
            source_weights=self.dataset_sampling_weights.get(task),
            queue_limit=max(self.buffer_size, self.batch_size) * 4,
            label_counts_by_source=self._label_counts[task],
        )

    def label_balance_report(self) -> Dict[str, Any]:
        """Per balanced task: label share per source and per batch among the rows drawn so far."""
        return {task: sampler.report() for task, sampler in sorted(self._balanced.items())}

    def reset(self) -> None:
        """Rewinds streams and random state so the next batches repeat from the start.

        Validation calls this before every evaluation, so each one scores the same records.
        """
        self.rng = random.Random(self._seed)
        self.np_rng = np.random.default_rng(self._seed)
        self._pending.clear()
        self._other_segments.clear()
        self._build_streams()

    def _count_rows(self) -> Dict[str, int]:
        """Row counts per task from Parquet footers (no data is read)."""
        counts: Dict[str, int] = {}
        for task, paths in self.task_paths.items():
            total = 0
            for path in paths:
                try:
                    total += pq.ParquetFile(path).metadata.num_rows
                except Exception as exc:
                    logger.warning("Cannot read row count of %s: %s", path, exc)
            if total > 0:
                counts[task] = total
        return counts

    def _discover_task_paths(self) -> None:
        """Discovers Parquet shards of the configured split within data_dir."""
        if not self.data_dir.is_dir():
            return

        task_dir_map = TASK_DATASET_DIRS

        for task, subdirs in task_dir_map.items():
            found: List[Path] = []
            for subdir in subdirs:
                candidate_dir = self.data_dir / subdir
                if candidate_dir.is_dir():
                    found.extend(sorted(candidate_dir.glob(f"{self.split}*.parquet")))
            if found:
                self.task_paths[task] = found
        if self.include_retrieval_task:
            retrieval = [
                path
                for subdir in RETRIEVAL_DATASET_DIRS
                if (self.data_dir / subdir).is_dir()
                for path in sorted((self.data_dir / subdir).glob(f"{self.split}*.parquet"))
            ]
            if retrieval:
                self.task_paths[RETRIEVAL_TASK] = retrieval
        if self.include_contrastive_sim_task:
            pairs = sorted(
                (self.data_dir / CONTRASTIVE_SIM_DATASET_DIR).glob(f"{self.split}*.parquet")
            )
            if pairs:
                self.task_paths[CONTRASTIVE_SIM_TASK] = pairs

    @classmethod
    def _interleaved_stream(
        cls,
        paths: List[Path],
        buffer_size: int,
        rng: random.Random,
        dataset_exponent: float = 1.0,
        dataset_weights: Optional[Dict[str, float]] = None,
    ) -> Iterator[Dict[str, Any]]:
        """Draw a dataset by count exponent and a shard within it by row count.

        Reading the files one after another would show a bilingual task its first dataset for
        most of a run (all English, then all Vietnamese).
        """
        if len(paths) == 1:
            return cls._create_task_stream(paths, buffer_size)
        row_counts = []
        for p in paths:
            try:
                row_counts.append(max(1, pq.ParquetFile(p).metadata.num_rows))
            except Exception:
                row_counts.append(1)  # the stream itself reports an unreadable shard
        dataset_counts: Dict[Path, int] = {}
        for path, count in zip(paths, row_counts):
            dataset_counts[path.parent] = dataset_counts.get(path.parent, 0) + count
        multipliers = dataset_weights or {}
        weights = [
            count
            * dataset_counts[path.parent] ** (dataset_exponent - 1)
            * multipliers.get(path.parent.name, 1.0)
            for path, count in zip(paths, row_counts)
        ]
        streams = [cls._create_task_stream([p], buffer_size) for p in paths]

        def draw() -> Iterator[Dict[str, Any]]:
            while streams:
                i = rng.choices(range(len(streams)), weights=weights)[0]
                try:
                    yield next(streams[i])
                except RuntimeError:  # unreadable shard, already logged: keep using the others
                    del streams[i], weights[i]
            raise RuntimeError(f"No readable Parquet shards among {[str(p) for p in paths]}")

        return draw()

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
        return build_sequence(tok_ids, second_tok_ids, self.seq_len)

    def _mask_tokens(self, padded_seq: List[int]) -> Tuple[List[int], List[int]]:
        """Dynamic MLM masking (80 % [MASK], 10 % random, 10 % unchanged); special ids stay."""
        mlm_labels = [IGNORE_INDEX] * len(padded_seq)
        final_tokens = list(padded_seq)
        for idx, tok in enumerate(padded_seq):
            if tok in (CLS_ID, SEP_ID, PAD_ID):
                continue
            if self.rng.random() < self.mlm_mask_prob:
                mlm_labels[idx] = tok
                r = self.rng.random()
                if r < 0.8:
                    final_tokens[idx] = MASK_ID
                elif r < 0.9:
                    final_tokens[idx] = self.rng.randint(10, self.vocab_size - 1)
                # 10% remains unchanged
        return final_tokens, mlm_labels

    def _two_segment_rows(
        self, records: List[Dict[str, Any]]
    ) -> List[Optional[Tuple[str, List[int], List[int]]]]:
        """Per record (document, a, b) when it becomes a two-segment row, else None."""
        rows: List[Optional[Tuple[str, List[int], List[int]]]] = []
        for rec in records:
            if self.mlm_pair_fraction <= 0.0 or self.rng.random() >= self.mlm_pair_fraction:
                rows.append(None)
                continue
            text = rec.get("text") or rec.get("content") or rec.get("document") or ""
            cut = cut_two_segments(text, self.rng)
            if cut is None:
                self.stats["mlm_pair_without_boundary"] += 1
                rows.append(None)
                continue
            rows.append((document_id(rec), self._tokenize(cut[0]), self._tokenize(cut[1])))
        return rows

    def _other_segment(
        self, doc: str, rows: List[Optional[Tuple[str, List[int], List[int]]]]
    ) -> Optional[List[int]]:
        """A second segment of another document: from this batch first, then earlier rows."""
        in_batch = [row[2] for row in rows if row is not None and row[0] != doc]
        if in_batch:
            return in_batch[self.rng.randrange(len(in_batch))]
        earlier = [seg for other, seg in self._other_segments if other != doc]
        return earlier[self.rng.randrange(len(earlier))] if earlier else None

    def _format_mlm_batch(self, records: List[Dict[str, Any]]) -> TaskBatch:
        """Formats records for Masked Language Modeling with 15% dynamic masking.

        With `mlm_pair_fraction` a share of the rows becomes `[CLS] a [SEP] b [SEP]` from two
        consecutive segments of one passage; with `order_task` those rows carry an order label
        (in order, swapped, other document) and the other rows carry the ignore index.
        """
        token_ids_list: List[List[int]] = []
        attention_mask_list: List[List[int]] = []
        mlm_labels_list: List[List[int]] = []
        order_labels: List[int] = []

        rows = self._two_segment_rows(records)
        for rec, row in zip(records, rows):
            order = IGNORE_INDEX
            if row is None:
                text = rec.get("text") or rec.get("content") or rec.get("document") or ""
                padded_seq, att_mask = self._prepare_sequence(self._tokenize(text))
            else:
                doc, first, second = row
                if self.order_task:
                    order = draw_order_class(self.rng, self.order_class_shares)
                    if order == ORDER_SWAPPED:
                        first, second = second, first
                    elif order == ORDER_OTHER_DOCUMENT:
                        other = self._other_segment(doc, rows)
                        if other is None:
                            self.stats["order_other_document_unavailable"] += 1
                            order = draw_order_class(self.rng, self.order_class_shares[:2] + (0.0,))
                            if order == ORDER_SWAPPED:
                                first, second = second, first
                        else:
                            second = other
                    self.stats[f"order_{ORDER_CLASSES[order]}"] += 1
                padded_seq, att_mask = build_pair_sequence(
                    first, second, self.seq_len, CLS_ID, SEP_ID, PAD_ID
                )
                self.stats["mlm_pair_sequences"] += 1
            final_tokens, mlm_labels = self._mask_tokens(padded_seq)
            token_ids_list.append(final_tokens)
            attention_mask_list.append(att_mask)
            mlm_labels_list.append(mlm_labels)
            order_labels.append(order)
        self.stats["mlm_sequences"] += len(records)

        for row in rows:
            if row is not None:
                self._other_segments.append((row[0], row[2]))
        del self._other_segments[: max(0, len(self._other_segments) - self.buffer_size)]

        labels = {"mlm_labels": np.array(mlm_labels_list, dtype=np.int64)}
        if self.order_task:
            labels["order_labels"] = np.array(order_labels, dtype=np.int64)
        tok_arr = np.array(token_ids_list, dtype=np.int64)
        att_arr = np.array(attention_mask_list, dtype=np.int64)
        return self._to_task_batch("mlm", tok_arr, att_arr, labels)

    def two_segment_report(self) -> Dict[str, Any]:
        """Share of two-segment MLM rows and order-class shares among the rows drawn so far."""
        total = self.stats["mlm_sequences"]
        pairs = self.stats["mlm_pair_sequences"]
        ordered = sum(self.stats[f"order_{name}"] for name in ORDER_CLASSES)
        return {
            "mlm_pair_fraction": self.mlm_pair_fraction,
            "order_task": self.order_task,
            "order_class_shares": list(self.order_class_shares),
            "mlm_sequences": total,
            "mlm_pair_sequences": pairs,
            "mlm_pair_share": pairs / total if total else 0.0,
            "mlm_pair_without_boundary": self.stats["mlm_pair_without_boundary"],
            "order_other_document_unavailable": self.stats["order_other_document_unavailable"],
            "order_counts": {name: self.stats[f"order_{name}"] for name in ORDER_CLASSES},
            "order_shares": {
                name: (self.stats[f"order_{name}"] / ordered if ordered else 0.0)
                for name in ORDER_CLASSES
            },
        }

    def _format_nli_batch(self, records: List[Dict[str, Any]]) -> TaskBatch:
        """Formats premise/hypothesis records for 3-way NLI classification."""
        token_ids_list: List[List[int]] = []
        attention_mask_list: List[List[int]] = []
        nli_labels: List[int] = []

        for rec in records:
            p = rec.get("premise") or rec.get("sentence1") or ""
            h = rec.get("hypothesis") or rec.get("sentence2") or ""
            lbl = nli_label(rec)

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
            lbl = float(paraphrase_label(rec))

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
        singles: Dict[str, List[List[int]]] = {
            f"sim_{side}_{kind}": [] for side in ("a", "b") for kind in ("ids", "mask")
        }

        for rec in records:
            s1 = rec.get("sentence1") or ""
            s2 = rec.get("sentence2") or ""
            raw_val = rec.get("score") if "score" in rec else rec.get("similarity_score")
            if raw_val is None:
                raise ValueError("Similarity record without a score; refusing to use 0.0")
            raw_score = float(raw_val)
            # Raw STS scores on the 0-5 scale are normalised to [0.0, 1.0]
            if raw_score > 1.0:
                raw_score = raw_score / 5.0
            if not 0.0 <= raw_score <= 1.0:
                raise ValueError(f"Similarity score {raw_val!r} is outside the 0-5 STS scale")
            score = raw_score

            s1_toks = self._tokenize(s1)
            s2_toks = self._tokenize(s2)
            padded_seq, att_mask = self._prepare_sequence(s1_toks, s2_toks)

            token_ids_list.append(padded_seq)
            attention_mask_list.append(att_mask)
            sim_labels.append(score)
            # single-sentence inputs for the bi-encoder similarity head (T198)
            for side, toks in (("a", s1_toks), ("b", s2_toks)):
                single_seq, single_mask = self._prepare_sequence(toks, None)
                singles[f"sim_{side}_ids"].append(single_seq)
                singles[f"sim_{side}_mask"].append(single_mask)

        tok_arr = np.array(token_ids_list, dtype=np.int64)
        att_arr = np.array(attention_mask_list, dtype=np.int64)
        lbl_arr = np.array(sim_labels, dtype=np.float32)
        labels: Dict[str, Any] = {"sim_labels": lbl_arr}
        for side in ("a", "b"):
            ids = np.array(singles[f"sim_{side}_ids"], dtype=np.int64)
            mask = np.array(singles[f"sim_{side}_mask"], dtype=np.int64)
            if self.trim_padding and len(mask):
                # each side trims to its own longest sequence (it can exceed the pair's)
                width = min(self.seq_len, max(8, -(-int(mask.sum(axis=1).max()) // 8) * 8))
                ids, mask = ids[:, :width], mask[:, :width]
            labels[f"sim_{side}_ids"], labels[f"sim_{side}_mask"] = ids, mask

        return self._to_task_batch("similarity", tok_arr, att_arr, labels)

    def _locate_answer_span(
        self, rec: Dict[str, Any], context: str, q_toks: List[int]
    ) -> Tuple[int, int]:
        """Maps the first gold answer (char offset) to token positions in the pair sequence.

        Returns (0, 0) -- the [CLS] position -- when there is no answer or it lies outside the
        sequence window (counted separately in `self.stats`).
        """
        self.stats["qa_total"] += 1
        answers = rec.get("answers")
        texts = answers.get("text") if isinstance(answers, dict) else None
        starts = answers.get("answer_start") if isinstance(answers, dict) else None
        if not texts or not texts[0]:
            self.stats["qa_unanswerable"] += 1  # a real "no answer" label (SQuAD 2.0 style)
            return 0, 0
        if not starts:
            raise ValueError(
                f"Answer {texts[0]!r} has no answer_start; refusing to relabel it 'no answer'"
            )
        char_start = int(starts[0])
        if char_start < 0 or context[char_start : char_start + len(texts[0])] != texts[0]:
            raise ValueError(
                f"Answer offset {char_start} does not point at {texts[0]!r}; "
                "refusing to relabel it 'no answer'"
            )

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
            self.stats["qa_answer_outside_window"] += 1  # span cut off by the sequence window
            return 0, 0
        return start_pos, end_pos

    def _format_qa_batch(self, records: List[Dict[str, Any]]) -> TaskBatch:
        """Formats question/context records for extractive QA span prediction."""
        token_ids_list: List[List[int]] = []
        attention_mask_list: List[List[int]] = []
        starts: List[int] = []
        ends: List[int] = []
        retrieval_pairs: List[Tuple[List[int], List[int]]] = []

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
            if self.include_retrieval_pairs and start_pos > 0 and q_toks and c_toks:
                retrieval_pairs.append((q_toks, c_toks))

        tok_arr = np.array(token_ids_list, dtype=np.int64)
        att_arr = np.array(attention_mask_list, dtype=np.int64)
        start_arr = np.array(starts, dtype=np.int64)
        end_arr = np.array(ends, dtype=np.int64)

        labels = {"qa_start_positions": start_arr, "qa_end_positions": end_arr}
        if len(retrieval_pairs) >= 2:
            labels.update(self._retrieval_labels(retrieval_pairs))
        return self._to_task_batch(
            "qa",
            tok_arr,
            att_arr,
            labels,
        )

    def _format_retrieval_batch(self, records: List[Dict[str, Any]]) -> TaskBatch:
        """Query/positive pairs for in-batch-negative contrastive training (T178).

        Every other pair's passage is a negative for a query, except passages known to be positives
        (the same passage, or another pair with the same query), which the mask excludes.
        """
        pairs: List[Tuple[List[int], List[int]]] = []
        for rec in records:
            q_toks = self._tokenize(rec.get("query") or "")
            p_toks = self._tokenize(rec.get("positive") or "")
            if q_toks and p_toks:
                pairs.append((q_toks, p_toks))
        if len(pairs) < 2:
            raise RuntimeError("A retrieval batch needs two or more non-empty query/positive pairs")
        labels = self._retrieval_labels(pairs)
        # The trainer reads the query side as the batch input; the labels carry both sides.
        return self._to_task_batch(
            RETRIEVAL_TASK,
            labels["retrieval_query_ids"],
            labels["retrieval_query_mask"],
            labels,
        )

    def _format_contrastive_sim_batch(self, rows: List[Dict[str, Any]]) -> TaskBatch:
        """Anchors, designated positives and hard negatives for in-batch InfoNCE (T199).

        Candidate i (i < B) is the positive of anchor i: the partner sentence of a positive
        relation, else the anchor itself (the trainer runs it as a second, independently dropped
        pass). Hard negatives follow. `contrastive_sim_known_positives` marks every candidate
        whose text equals the anchor's or its positive's, which the loss keeps out of the
        denominator; `contrastive_sim_weights` carries the loss weight of each row's kind.
        """
        anchors, positives, negatives = [], [], []
        for row in rows:
            anchors.append(row["anchor"])
            positives.append(row["positive"] if row["positive"] is not None else row["anchor"])
            if row["negative"] is not None:
                negatives.append(row["negative"])
        encoded = []
        for group in (anchors, positives, negatives):
            tokens = [self._tokenize(text) for text in group]
            if not all(tokens):
                raise RuntimeError("A contrastive similarity row tokenized to nothing")
            encoded.append([build_sequence(t, None, self.contrastive_sim_seq_len) for t in tokens])
        labels: Dict[str, np.ndarray] = {}
        for name, group in zip(("anchor", "positive", "negative"), encoded):
            if group:
                ids, masks = zip(*group)
                width = max(map(sum, masks))
                labels[f"contrastive_sim_{name}_ids"] = np.asarray(ids, dtype=np.int64)[:, :width]
                labels[f"contrastive_sim_{name}_mask"] = np.asarray(masks, dtype=np.int64)[
                    :, :width
                ]
        candidates = positives + negatives
        labels["contrastive_sim_known_positives"] = np.asarray(
            [[c == a or c == p for c in candidates] for a, p in zip(anchors, positives)],
            dtype=np.bool_,
        )
        labels["contrastive_sim_weights"] = np.asarray(
            [self.contrastive_sim_row_weights[row["kind"]] for row in rows], dtype=np.float32
        )
        return self._to_task_batch(
            CONTRASTIVE_SIM_TASK,
            labels["contrastive_sim_anchor_ids"],
            labels["contrastive_sim_anchor_mask"],
            labels,
        )

    def contrastive_sim_report(self) -> Dict[str, Any]:
        """Row kinds drawn so far against their target shares (empty when the task is off)."""
        return {t: sampler.report() for t, sampler in sorted(self._relation_samplers.items())}

    def _retrieval_labels(
        self, pairs: List[Tuple[List[int], List[int]]]
    ) -> Dict[str, np.ndarray]:
        """Encode standalone QA queries and passages as in dense inference."""
        result: Dict[str, np.ndarray] = {}
        encoded = []
        for column, name in enumerate(("query", "passage")):
            sequences, masks = zip(
                *(build_sequence(pair[column], None, self.retrieval_seq_len) for pair in pairs)
            )
            length = max(map(sum, masks))
            result[f"retrieval_{name}_ids"] = np.asarray(sequences, dtype=np.int64)[:, :length]
            result[f"retrieval_{name}_mask"] = np.asarray(masks, dtype=np.int64)[:, :length]
            encoded.append(sequences)
        queries, passages = encoded
        result["retrieval_positives"] = np.asarray(
            [
                [q1 == q2 or p1 == p2 for q2, p2 in zip(queries, passages)]
                for q1, p1 in zip(queries, passages)
            ],
            dtype=np.bool_,
        )
        return result

    def _to_task_batch(
        self,
        task_type: str,
        token_ids: np.ndarray,
        attention_mask: np.ndarray,
        labels: Dict[str, np.ndarray],
    ) -> TaskBatch:
        """Constructs TaskBatch, converting to PyTorch tensors if return_tensors='pt'.

        With `trim_padding` the columns past the longest real sequence (rounded up to a
        multiple of 8) are dropped: they are masked out, so the result is unchanged.
        """
        seq_len = self.seq_len
        if self.trim_padding:
            longest = int(attention_mask.sum(axis=1).max()) if len(attention_mask) else 1
            seq_len = min(self.seq_len, max(8, -(-longest // 8) * 8))
            token_ids = np.ascontiguousarray(token_ids[:, :seq_len])
            attention_mask = np.ascontiguousarray(attention_mask[:, :seq_len])
            labels = {
                k: np.ascontiguousarray(v[:, :seq_len])
                if not k.startswith(("retrieval_", "sim_a_", "sim_b_", "contrastive_sim_"))
                and v.ndim == 2 and v.shape[1] == self.seq_len
                else v
                for k, v in labels.items()
            }
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
                    seq_len=seq_len,
                )
            except ImportError:
                pass

        return TaskBatch(
            task_type=task_type,
            token_ids=token_ids,
            attention_mask=attention_mask,
            labels=labels,
            batch_size=len(token_ids),
            seq_len=seq_len,
        )

    def _next_records(self, task: str) -> List[Dict[str, Any]]:
        """Next micro-batch of raw records; with a length pool, similar lengths share a batch.

        A label-balanced task draws its batch directly: sorting a pool by length would mix the
        balanced batches, so it does not use the length pool.
        """
        if task in self._balanced:
            return self._balanced[task].draw_batch(self.batch_size)
        if task in self._relation_samplers:
            return self._relation_samplers[task].draw_batch(self.contrastive_sim_batch_size)
        pending = self._pending.setdefault(task, [])
        if not pending:
            it = self._task_iterators[task]
            pool: List[Dict[str, Any]] = []
            size = self.retrieval_batch_size if task == RETRIEVAL_TASK else self.batch_size
            for _ in range(size * self.length_pool_batches):
                try:
                    pool.append(next(it))
                except StopIteration:
                    break
            if self.length_pool_batches > 1:
                pool.sort(key=_text_length)
            batches = [pool[i : i + size] for i in range(0, len(pool), size)]
            self.rng.shuffle(batches)
            pending.extend(batches)
        return pending.pop() if pending else []

    def generate_batch(self, task_type: Optional[str] = None) -> TaskBatch:
        """Generates a batch by streaming records from physical Parquet files."""
        if self._synthetic_fallback is not None:
            return self._synthetic_fallback.generate_batch(task_type=task_type)

        selected_task = task_type or self.scheduler.sample_task(self.rng)
        if selected_task not in self._task_iterators:
            raise KeyError(
                f"Task '{selected_task}' has no data shards; available: "
                f"{sorted(self._task_iterators)}"
            )

        records = self._next_records(selected_task)

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
        elif selected_task == RETRIEVAL_TASK:
            return self._format_retrieval_batch(records)
        elif selected_task == CONTRASTIVE_SIM_TASK:
            return self._format_contrastive_sim_batch(records)
        else:
            raise ValueError(f"Unknown task: {selected_task}")

    def generate_step_batches(self, tasks_per_step: int = 1) -> List[TaskBatch]:
        """One micro-step of `tasks_per_step` batches of different tasks (T201).

        With 1 this is exactly `[generate_batch()]` (same RNG draws). With more, the tasks are
        drawn without replacement from the scheduler distribution, so a step never carries the
        same task twice; each batch keeps its own size and sequence length.
        """
        if self._synthetic_fallback is not None:
            return self._synthetic_fallback.generate_step_batches(tasks_per_step)
        tasks = self.scheduler.sample_tasks(self.rng, tasks_per_step)
        return [self.generate_batch(task_type=task) for task in tasks]

    def __iter__(self) -> Iterator[TaskBatch]:
        """Infinite generator yielding streaming TaskBatch instances."""
        while True:
            yield self.generate_batch()
