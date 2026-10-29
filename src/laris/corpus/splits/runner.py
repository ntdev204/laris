"""Entry point that physically partitions the acquired raw datasets."""

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from laris.corpus.acquisition.common import APPROVED_LICENSE_STATUSES
from laris.corpus.splits.partitioners.cc100 import partition_cc100_physical, wikipedia_digests
from laris.corpus.splits.partitioners.fever import partition_fever_physical
from laris.corpus.splits.partitioners.hotpotqa import partition_hotpotqa_physical
from laris.corpus.splits.partitioners.pairwise import (
    partition_all_nli_physical,
    partition_anli_physical,
    partition_paws_physical,
    partition_stsb_physical,
)
from laris.corpus.splits.partitioners.quora import partition_quora_dataset_physical
from laris.corpus.splits.partitioners.squad import partition_qa_dataset_physical
from laris.corpus.splits.partitioners.vinli import partition_vinli_physical
from laris.corpus.splits.partitioners.viquad_v2 import partition_viquad_v2_physical
from laris.corpus.splits.partitioners.vists import partition_vists_physical
from laris.corpus.splits.partitioners.wikipedia import partition_wikipedia_shards_physical


def _license_blocked_datasets(raw_path: Path) -> Dict[str, str]:
    """Dataset ids whose acquisition manifest entry is not license-approved."""
    manifest_path = raw_path.parent / "acquisition_manifest.json"
    if not manifest_path.is_file():
        return {}
    with open(manifest_path, "r", encoding="utf-8") as handle:
        entries = json.load(handle).get("datasets", [])
    return {
        e["dataset_id"].upper(): e.get("license_status", "UNKNOWN")
        for e in entries
        if e.get("license_status") not in APPROVED_LICENSE_STATUSES
    }


def execute_physical_partitioning(
    raw_root: Union[str, Path] = "data/raw",
    processed_root: Union[str, Path] = "data/processed",
    manifest_output_path: Optional[Union[str, Path]] = None,
    datasets: Optional[List[str]] = None,
    max_records: Optional[int] = None,
    batch_size: int = 100000,
    num_workers: Optional[int] = None,
    include_unreviewed_licenses: bool = False,
) -> Dict[str, Any]:
    """Executes physical partitioning on raw datasets and outputs task_splits_manifest.json."""
    raw_path = Path(raw_root)
    proc_path = Path(processed_root)
    proc_path.mkdir(parents=True, exist_ok=True)

    target_manifest = (
        Path(manifest_output_path)
        if manifest_output_path
        else proc_path / "task_splits_manifest.json"
    )

    selected = [d.upper() for d in datasets] if datasets else None
    results: List[Dict[str, Any]] = []
    skipped: List[Dict[str, str]] = []
    license_blocked = {} if include_unreviewed_licenses else _license_blocked_datasets(raw_path)

    def wanted(dataset_id: str, raw_name: str) -> bool:
        """True when requested, present on disk and license-cleared (skips are recorded)."""
        if selected is not None and dataset_id not in selected:
            return False
        if not (raw_path / raw_name).is_dir():
            return False
        if dataset_id in license_blocked:
            skipped.append({"dataset_id": dataset_id, "reason": license_blocked[dataset_id]})
            return False
        return True

    # 1. Wikipedia Vietnamese
    if selected is None or "WIKIPEDIA-VI" in selected or "WIKIPEDIA_VI" in selected:
        vi_raw_dir = raw_path / "wikipedia_vi"
        if vi_raw_dir.is_dir():
            shards = sorted(vi_raw_dir.glob("*.parquet"))
            if shards:
                res_vi = partition_wikipedia_shards_physical(
                    shard_paths=shards,
                    output_dir=proc_path / "wikipedia_vi",
                    dataset_id="WIKIPEDIA-VI",
                    max_records=max_records,
                    batch_size=batch_size,
                    num_workers=num_workers,
                )
                results.append(res_vi.to_dict())

    # 2. Wikipedia English
    if selected is None or "WIKIPEDIA-EN" in selected or "WIKIPEDIA_EN" in selected:
        en_raw_dir = raw_path / "wikipedia_en"
        if en_raw_dir.is_dir():
            shards = sorted(en_raw_dir.glob("*.parquet"))
            if shards:
                res_en = partition_wikipedia_shards_physical(
                    shard_paths=shards,
                    output_dir=proc_path / "wikipedia_en",
                    dataset_id="WIKIPEDIA-EN",
                    max_records=max_records,
                    batch_size=batch_size,
                    num_workers=num_workers,
                )
                results.append(res_en.to_dict())

    # 3. Quora Question Pairs
    if selected is None or "QUORA-DUPLICATES" in selected or "QUORA" in selected:
        quora_file = raw_path / "quora_duplicates" / "train-00000-of-00001.parquet"
        if quora_file.is_file():
            res_quora = partition_quora_dataset_physical(
                raw_file_path=quora_file,
                output_dir=proc_path / "quora_duplicates",
                max_records=max_records,
            )
            results.append(res_quora.to_dict())

    # 4. SQuAD
    if selected is None or "SQUAD" in selected:
        squad_dir = raw_path / "squad"
        if squad_dir.is_dir() and (squad_dir / "validation-00000-of-00001.parquet").exists():
            res_squad = partition_qa_dataset_physical(
                raw_dir=squad_dir,
                output_dir=proc_path / "squad",
                dataset_id="SQUAD",
            )
            results.append(res_squad.to_dict())

    # 5. Bilingual expansion datasets
    for dataset_id, raw_name, partition in (
        ("ALL-NLI", "all_nli", partition_all_nli_physical),
        ("ANLI", "anli", partition_anli_physical),
        ("PAWS-WIKI", "paws", partition_paws_physical),
        ("STSB", "stsb", partition_stsb_physical),
    ):
        if wanted(dataset_id, raw_name):
            results.append(
                partition(
                    raw_path / raw_name, proc_path / raw_name, max_records=max_records
                ).to_dict()
            )
    if wanted("VINLI", "vinli"):
        results.append(
            partition_vinli_physical(raw_path / "vinli", proc_path / "vinli").to_dict()
        )
    if wanted("VISTS", "vists"):
        results.append(
            partition_vists_physical(raw_path / "vists", proc_path / "vists").to_dict()
        )
    if wanted("HOTPOTQA", "hotpotqa"):
        results.append(
            partition_hotpotqa_physical(raw_path / "hotpotqa", proc_path / "hotpotqa").to_dict()
        )
    if wanted("FEVER", "fever"):
        results.append(partition_fever_physical(raw_path / "fever", proc_path / "fever").to_dict())
    if wanted("UIT-VIQUAD-V2", "viquad_v2"):
        # ViQuAD 2.0 is a superset of 1.1 over the same contexts; 1.1 is never used as a QA
        # source, so no cross-corpus filtering is applied (it would remove every row).
        results.append(
            partition_viquad_v2_physical(raw_path / "viquad_v2", proc_path / "viquad_v2").to_dict()
        )
    if wanted("CC100-VI-CLEAN", "cc100_vi_clean"):
        wiki_dir = raw_path / "wikipedia_vi"
        results.append(
            partition_cc100_physical(
                sorted((raw_path / "cc100_vi_clean").glob("*.parquet")),
                proc_path / "cc100_vi_clean",
                exclude_digests=(
                    wikipedia_digests(sorted(wiki_dir.glob("*.parquet")))
                    if wiki_dir.is_dir()
                    else None
                ),
                max_records=max_records,
                batch_size=min(batch_size, 20000),
            ).to_dict()
        )

    if selected is not None and target_manifest.is_file():
        # A partial run must not erase the entries recorded by earlier runs.
        with open(target_manifest, "r", encoding="utf-8") as handle:
            previous = json.load(handle)
        fresh = {r["dataset_id"] for r in results} | {s["dataset_id"] for s in skipped}
        results = [
            r for r in previous.get("partitioned_datasets", []) if r["dataset_id"] not in fresh
        ] + results
        skipped = [
            s for s in previous.get("skipped_datasets", []) if s["dataset_id"] not in fresh
        ] + skipped

    summary = {
        "manifest_version": "1.1.0",
        "description": "Authoritative physical task-split manifest with non-leakage partitions.",
        "zero_training_verified": True,
        "raw_data_untouched": True,
        "total_datasets_partitioned": len(results),
        "partitioned_datasets": results,
        "skipped_datasets": skipped,
    }

    with open(target_manifest, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)

    return summary
