"""Acquirers for the bilingual expansion datasets (ViNLI, ViSTS, HotpotQA, FEVER, ...)."""

import shutil
from pathlib import Path
from typing import List

from laris.corpus.acquisition.common import (
    CACHE_DIR,
    HF_PARQUET_REV,
    HF_RESOLVE,
    RAW_DIR,
    DatasetEntry,
    _acquire_remote_files,
    _finalize_entry,
    _record_files,
    count_jsonl_lines,
    count_parquet_rows,
    download_file,
)
from laris.corpus.acquisition.fever_evidence import EVIDENCE_FILENAME, build_evidence_table


def acquire_vinli() -> DatasetEntry:
    """Acquires Vietnamese 3-way NLI pairs (community HF mirror; upstream vnlp/vinli is 404)."""
    print("\n--- Acquiring Vietnamese NLI (ViNLI, presencesw/vinli_4_label) ---")
    dest_dir = RAW_DIR / "vinli"
    repo = "presencesw/vinli_4_label"
    files = [
        (HF_RESOLVE.format(repo=repo, rev="main", path=f"data/{s}-00000-of-00001.parquet"),
         f"{s}-00000-of-00001.parquet")
        for s in ("train", "dev", "test")
    ]
    records, size, rows, ok = _acquire_remote_files(dest_dir, files, count_parquet_rows)
    return _finalize_entry(
        dataset_id="VINLI",
        name="Vietnamese Natural Language Inference (ViNLI)",
        version="HF presencesw/vinli_4_label (default)",
        source_url=f"https://huggingface.co/datasets/{repo}",
        license_name="Not declared by uploader (research use only pending review)",
        license_approved=False,
        language="Vietnamese",
        sample_unit="3-Way NLI Hypothesis-Premise Pair (gold_label, sentence1, sentence2)",
        expected=">= 30,000 pairs (24,376 train / 3,009 dev / 2,991 test per dataset card)",
        dest_dir=dest_dir,
        records=records,
        size=size,
        rows=rows,
        complete=ok,
        min_rows=30000,
        notes=(
            "Spec URL github.com/vnlp/vinli returns 404; community mirror used. "
            "Uploader declares no license: NEEDS_LICENSE_REVIEW before any redistribution."
        ),
    )


def acquire_vists() -> DatasetEntry:
    """Acquires Vietnamese STS test suites (MIT) translated from STS12-16, SICK-R and STS-B."""
    print("\n--- Acquiring Vietnamese STS (ViSTS, anti-ai/ViSTS) ---")
    dest_dir = RAW_DIR / "vists"
    repo = "anti-ai/ViSTS"
    names = [
        "sickr_sts/sickr_sts_vi.jsonl",
        "sts12/sts12_vi.jsonl",
        "sts13/sts13_vi.jsonl",
        "sts14/sts14_vi.jsonl",
        "sts15/sts15_vi.jsonl",
        "sts16/sts16_vi.jsonl",
        "stsb/stsbenchmark_vi.jsonl",
    ]
    files = [
        (HF_RESOLVE.format(repo=repo, rev="main", path=f"test/{n}"), n.replace("/", "__"))
        for n in names
    ]
    records, size, rows, ok = _acquire_remote_files(dest_dir, files, count_jsonl_lines)
    return _finalize_entry(
        dataset_id="VISTS",
        name="Vietnamese Semantic Textual Similarity (ViSTS)",
        version="HF anti-ai/ViSTS (7 STS suites)",
        source_url=f"https://huggingface.co/datasets/{repo}",
        license_name="MIT",
        license_approved=True,
        language="Vietnamese",
        sample_unit="Scored Sentence Pair",
        expected="10K-100K pairs (dataset card size category)",
        dest_dir=dest_dir,
        records=records,
        size=size,
        rows=rows,
        complete=ok,
        min_rows=10000,
        notes=(
            "Spec URL github.com/vnlp/vists returns 404; MIT-licensed HF release used. "
            "Contains test suites only (no train split); licensed MIT, "
            "not CC-BY-4.0 as in earlier spec."
        ),
    )


def acquire_hotpotqa() -> DatasetEntry:
    """Acquires HotpotQA distractor-setting multi-hop QA (CC-BY-SA-4.0)."""
    print("\n--- Acquiring HotpotQA (distractor setting) ---")
    dest_dir = RAW_DIR / "hotpotqa"
    repo = "hotpotqa/hotpot_qa"
    names = [
        "distractor/train-00000-of-00002.parquet",
        "distractor/train-00001-of-00002.parquet",
        "distractor/validation-00000-of-00001.parquet",
    ]
    files = [
        (HF_RESOLVE.format(repo=repo, rev="main", path=n), n.replace("/", "__")) for n in names
    ]
    records, size, rows, ok = _acquire_remote_files(dest_dir, files, count_parquet_rows)
    return _finalize_entry(
        dataset_id="HOTPOTQA",
        name="HotpotQA Multi-Hop Reading Comprehension (distractor)",
        version="HF hotpotqa/hotpot_qa distractor",
        source_url=f"https://huggingface.co/datasets/{repo}",
        license_name="CC-BY-SA-4.0",
        license_approved=True,
        language="English",
        sample_unit="Multi-Hop QA Item (question, answer, context, supporting_facts)",
        expected="97,852 items (90,447 train / 7,405 validation)",
        dest_dir=dest_dir,
        records=records,
        size=size,
        rows=rows,
        complete=ok,
        min_rows=97000,
        notes=(
            "Fullwiki setting excluded: it repeats the same questions with retrieval context "
            "and its test split has no answers. Distractor already carries gold supporting facts."
        ),
    )


FEVER_WIKI_PAGES_URL = "https://fever.ai/download/fever/wiki-pages.zip"


def _resolve_fever_evidence(dest_dir: Path, claim_files: List[Path]) -> bool:
    """Builds evidence_sentences.parquet from the FEVER Wikipedia snapshot (cache is removed)."""
    if (dest_dir / EVIDENCE_FILENAME).exists():
        return True
    cache = CACHE_DIR / "fever_wiki_pages"
    archive = cache / "wiki-pages.zip"
    if not download_file(FEVER_WIKI_PAGES_URL, archive):
        return False
    count = build_evidence_table(claim_files, archive, dest_dir / EVIDENCE_FILENAME)
    print(f"  [DONE] {EVIDENCE_FILENAME}: {count} evidence sentences")
    shutil.rmtree(cache, ignore_errors=True)
    return count > 0


def acquire_fever() -> DatasetEntry:
    """Acquires FEVER v1.0 labelled claims via the Hugging Face parquet conversion branch."""
    print("\n--- Acquiring FEVER v1.0 (labelled claims) ---")
    dest_dir = RAW_DIR / "fever"
    repo = "fever/fever"
    names = ["v1.0/train/0000.parquet", "v1.0/labelled_dev/0000.parquet"]
    files = [
        (HF_RESOLVE.format(repo=repo, rev=HF_PARQUET_REV, path=n), n.replace("/", "__"))
        for n in names
    ]
    records, size, rows, ok = _acquire_remote_files(dest_dir, files, count_parquet_rows)
    if ok:
        ok = _resolve_fever_evidence(dest_dir, [dest_dir / n for _, n in files])
    evidence_records, evidence_size, _ = _record_files(
        dest_dir, [EVIDENCE_FILENAME], count_parquet_rows
    )
    records, size = records + evidence_records, size + evidence_size
    return _finalize_entry(
        dataset_id="FEVER",
        name="Fact Extraction and VERification (FEVER) v1.0",
        version="v1.0 (train + labelled_dev)",
        source_url="https://fever.ai/dataset/fever.html",
        license_name="CC-BY-SA-3.0",
        license_approved=True,
        language="English",
        sample_unit="Claim with SUPPORTS/REFUTES/NOT ENOUGH INFO label and Wikipedia evidence ids",
        expected="348,997 claims (311,431 train + 37,566 labelled_dev)",
        dest_dir=dest_dir,
        records=records,
        size=size,
        rows=rows,
        complete=ok,
        min_rows=348997,
        notes=(
            "License is CC-BY-SA-3.0 (Wikipedia-derived), not MIT as in earlier spec. "
            "paper_dev/paper_test are subsets of labelled_dev and unlabelled_* carry no labels, "
            "so both are excluded. Evidence references are resolved against the FEVER Wikipedia "
            "snapshot into evidence_sentences.parquet (page, sentence_id, text)."
        ),
    )


def acquire_viquad_v2() -> DatasetEntry:
    """Acquires UIT-ViQuAD 2.0 (Vietnamese QA with unanswerable questions)."""
    print("\n--- Acquiring UIT-ViQuAD 2.0 (taidng/UIT-ViQuAD2.0) ---")
    dest_dir = RAW_DIR / "viquad_v2"
    repo = "taidng/UIT-ViQuAD2.0"
    files = [
        (HF_RESOLVE.format(repo=repo, rev="main", path=f"data/{s}-00000-of-00001.parquet"),
         f"{s}-00000-of-00001.parquet")
        for s in ("train", "validation", "test")
    ]
    records, size, rows, ok = _acquire_remote_files(dest_dir, files, count_parquet_rows)
    return _finalize_entry(
        dataset_id="UIT-VIQUAD-V2",
        name="UIT-ViQuAD 2.0 (Unanswerable Vietnamese QA)",
        version="HF taidng/UIT-ViQuAD2.0",
        source_url=f"https://huggingface.co/datasets/{repo}",
        license_name="Academic research use (UIT-NLP; HF card declares no SPDX license)",
        license_approved=False,
        language="Vietnamese",
        sample_unit="Context-Question-Answer Item (incl. unanswerable)",
        expected="~39K items (train/validation/test)",
        dest_dir=dest_dir,
        records=records,
        size=size,
        rows=rows,
        complete=ok,
        min_rows=30000,
        notes=(
            "Upstream license is non-commercial academic; the mirror declares no license, "
            "so NEEDS_LICENSE_REVIEW. v1.1 answerable items in UIT-VIQUAD overlap: "
            "dedupe at partition time."
        ),
    )

