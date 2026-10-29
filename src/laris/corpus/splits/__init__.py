"""Task-specific leakage-proof dataset splitting (partitioners, coverage audit, runner)."""

from laris.corpus.splits.coverage import (
    audit_dataset_inventory,
    generate_leakage_safe_manifest,
    validate_record_quality,
    validate_split_isolation,
)
from laris.corpus.splits.partitioners.quora import (
    QuestionPairGraphPartitioner,
    partition_quora_dataset_physical,
)
from laris.corpus.splits.partitioners.squad import (
    QADatasetPartitioner,
    partition_qa_dataset_physical,
)
from laris.corpus.splits.partitioners.wikipedia import (
    WikipediaArticlePartitioner,
    _partition_single_shard_worker,
    partition_wikipedia_shards_physical,
)
from laris.corpus.splits.physical import (
    PhysicalSplitResult,
    _compute_file_sha256,
    _merge_parquet_parts_streaming,
)
from laris.corpus.splits.ratios import PartitionRatios
from laris.corpus.splits.runner import execute_physical_partitioning

__all__ = [
    "_compute_file_sha256",
    "_merge_parquet_parts_streaming",
    "_partition_single_shard_worker",
    "PartitionRatios",
    "WikipediaArticlePartitioner",
    "QuestionPairGraphPartitioner",
    "QADatasetPartitioner",
    "validate_split_isolation",
    "validate_record_quality",
    "audit_dataset_inventory",
    "generate_leakage_safe_manifest",
    "PhysicalSplitResult",
    "partition_wikipedia_shards_physical",
    "partition_quora_dataset_physical",
    "partition_qa_dataset_physical",
    "execute_physical_partitioning",
]
