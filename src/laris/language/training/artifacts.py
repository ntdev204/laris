"""Language foundation training reproducibility and artifact lifecycle manager.

Adheres to DOC-SPEC-MOD-001 (Boundary B / MOD-LANG-003) and ADR-002:
- Immutable serialization and bundling of vocabulary, checkpoint, weights, and run manifests
- Cryptographic SHA-256 verification of all bundle components
- Strict training/validation/test split isolation and leakage prevention
"""

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Union

from laris.core.errors import (
    DataIntegrityError,
    DataLeakageError,
    ModuleContractViolationError,
)
from laris.language.schemas import (
    EncoderCheckpointMetadata,
    LanguageTrainingRunManifest,
    VocabularyContract,
)
from laris.language.tokenization.tokenizer import StemFertilityReport
from laris.retrieval.baseline_comparison import RetrievalComparisonReport

BUNDLE_MANIFEST_FILENAME = "bundle_manifest.json"


@dataclass(frozen=True)
class LanguageArtifactBundle:
    """Complete serialized model artifact bundle for Layer 1 language representations."""

    vocab_contract: VocabularyContract
    checkpoint_metadata: EncoderCheckpointMetadata
    weights: List[List[float]]
    run_manifest: LanguageTrainingRunManifest
    fertility_report: Optional[StemFertilityReport] = None
    retrieval_report: Optional[RetrievalComparisonReport] = None


class LanguageArtifactManager:
    """Manages serialization, cryptographic verification, and lifecycle of language artifacts."""

    @staticmethod
    def verify_split_isolation(
        train_doc_ids: List[str],
        val_doc_ids: List[str],
        test_doc_ids: List[str],
    ) -> None:
        """Verifies zero overlap between train, validation, and test document splits."""
        train_set = set(train_doc_ids)
        val_set = set(val_doc_ids)
        test_set = set(test_doc_ids)

        train_val_overlap = train_set.intersection(val_set)
        if train_val_overlap:
            raise DataLeakageError(
                f"Data leakage detected: {len(train_val_overlap)} documents overlap between "
                f"TRAIN and VAL splits: {sorted(train_val_overlap)[:5]}"
            )

        train_test_overlap = train_set.intersection(test_set)
        if train_test_overlap:
            raise DataLeakageError(
                f"Critical evaluation leakage detected: {len(train_test_overlap)} "
                f"documents overlap between TRAIN and TEST splits: {sorted(train_test_overlap)[:5]}"
            )

        val_test_overlap = val_set.intersection(test_set)
        if val_test_overlap:
            raise DataLeakageError(
                f"Evaluation contamination: {len(val_test_overlap)} documents overlap between "
                f"VAL and TEST splits: {sorted(val_test_overlap)[:5]}"
            )

    @staticmethod
    def _compute_file_sha256(path: Path) -> str:
        """Computes SHA-256 of file contents."""
        hasher = hashlib.sha256()
        with open(path, "rb") as f:
            while chunk := f.read(65536):
                hasher.update(chunk)
        return hasher.hexdigest()

    def save_bundle(
        self,
        bundle: LanguageArtifactBundle,
        target_dir: Union[str, Path],
    ) -> Path:
        """Saves artifact bundle to target directory and generates bundle manifest."""
        dest = Path(target_dir)
        dest.mkdir(parents=True, exist_ok=True)

        files_written: Dict[str, str] = {}

        # 1. Save vocabulary
        vocab_path = dest / "vocabulary.json"
        bundle.vocab_contract.save_to_file(vocab_path)
        files_written["vocabulary.json"] = self._compute_file_sha256(vocab_path)

        # 2. Save checkpoint metadata
        chk_path = dest / "checkpoint.json"
        bundle.checkpoint_metadata.save_to_file(chk_path)
        files_written["checkpoint.json"] = self._compute_file_sha256(chk_path)

        # 3. Save weights
        weights_path = dest / "weights.json"
        with open(weights_path, "w", encoding="utf-8") as f:
            json.dump(bundle.weights, f)
        files_written["weights.json"] = self._compute_file_sha256(weights_path)

        # 4. Save run manifest
        manifest_path = dest / "run_manifest.json"
        with open(manifest_path, "w", encoding="utf-8") as f:
            f.write(bundle.run_manifest.to_json())
        files_written["run_manifest.json"] = self._compute_file_sha256(manifest_path)

        # 5. Save optional fertility report
        if bundle.fertility_report is not None:
            fert_path = dest / "fertility_report.json"
            with open(fert_path, "w", encoding="utf-8") as f:
                f.write(bundle.fertility_report.to_json())
            files_written["fertility_report.json"] = self._compute_file_sha256(fert_path)

        # 6. Save optional retrieval report
        if bundle.retrieval_report is not None:
            ret_path = dest / "retrieval_report.json"
            with open(ret_path, "w", encoding="utf-8") as f:
                f.write(bundle.retrieval_report.to_json())
            files_written["retrieval_report.json"] = self._compute_file_sha256(ret_path)

        # 7. Write bundle manifest
        bundle_manifest_path = dest / BUNDLE_MANIFEST_FILENAME
        bundle_manifest = {
            "version": "1.0.0",
            "model_id": bundle.checkpoint_metadata.model_id,
            "files": files_written,
        }
        with open(bundle_manifest_path, "w", encoding="utf-8") as f:
            json.dump(bundle_manifest, f, indent=2, sort_keys=True)

        return dest

    def load_bundle(
        self,
        source_dir: Union[str, Path],
        verify_integrity: bool = True,
    ) -> LanguageArtifactBundle:
        """Loads and cryptographically verifies an artifact bundle from a directory."""
        src = Path(source_dir)
        bundle_manifest_path = src / BUNDLE_MANIFEST_FILENAME
        if not bundle_manifest_path.exists():
            raise ModuleContractViolationError(
                f"Missing bundle manifest '{BUNDLE_MANIFEST_FILENAME}' in '{source_dir}'"
            )

        with open(bundle_manifest_path, "r", encoding="utf-8") as f:
            manifest = json.load(f)

        expected_files: Dict[str, str] = manifest.get("files", {})

        if verify_integrity:
            for filename, expected_hash in expected_files.items():
                file_path = src / filename
                if not file_path.exists():
                    raise DataIntegrityError(f"Artifact bundle is missing file '{filename}'")
                actual_hash = self._compute_file_sha256(file_path)
                if actual_hash != expected_hash:
                    raise DataIntegrityError(
                        f"Integrity check failed for '{filename}'. Expected hash {expected_hash}, "
                        f"got {actual_hash}"
                    )

        # Load vocabulary
        vocab_contract = VocabularyContract.load_from_file(src / "vocabulary.json")

        # Load checkpoint metadata
        chk_meta = EncoderCheckpointMetadata.load_from_file(src / "checkpoint.json")

        # Load weights
        with open(src / "weights.json", "r", encoding="utf-8") as f:
            weights = json.load(f)

        # Load run manifest
        with open(src / "run_manifest.json", "r", encoding="utf-8") as f:
            run_manifest = LanguageTrainingRunManifest.from_json(f.read())

        # Load optional reports
        fertility_report = None
        fert_path = src / "fertility_report.json"
        if fert_path.exists():
            with open(fert_path, "r", encoding="utf-8") as f:
                fert_data = json.load(f)
                fertility_report = StemFertilityReport(
                    benchmark_version=fert_data["benchmark_version"],
                    vocab_size=fert_data["vocab_size"],
                    vocab_sha256=fert_data["vocab_sha256"],
                    num_samples=fert_data["num_samples"],
                    total_words=fert_data["total_words"],
                    total_tokens=fert_data["total_tokens"],
                    average_fertility=fert_data["average_fertility"],
                    max_fertility=fert_data["max_fertility"],
                    min_fertility=fert_data["min_fertility"],
                    domain_fertility=fert_data["domain_fertility"],
                    baseline_fertility=fert_data.get("baseline_fertility"),
                    fertility_reduction_pct=fert_data.get("fertility_reduction_pct"),
                    report_sha256=fert_data["report_sha256"],
                    metadata=fert_data.get("metadata", {}),
                )

        retrieval_report = None
        ret_path = src / "retrieval_report.json"
        if ret_path.exists():
            with open(ret_path, "r", encoding="utf-8") as f:
                ret_data = json.load(f)
                retrieval_report = RetrievalComparisonReport(
                    benchmark_version=ret_data["benchmark_version"],
                    num_queries=ret_data["num_queries"],
                    num_documents=ret_data["num_documents"],
                    dense_mrr=ret_data["dense_mrr"],
                    dense_hits_at_1=ret_data["dense_hits_at_1"],
                    dense_hits_at_5=ret_data["dense_hits_at_5"],
                    bm25_mrr=ret_data["bm25_mrr"],
                    bm25_hits_at_1=ret_data["bm25_hits_at_1"],
                    bm25_hits_at_5=ret_data["bm25_hits_at_5"],
                    avg_dense_latency_ms=ret_data["avg_dense_latency_ms"],
                    peak_memory_mb=ret_data["peak_memory_mb"],
                    report_sha256=ret_data["report_sha256"],
                    metadata=ret_data.get("metadata", {}),
                )

        return LanguageArtifactBundle(
            vocab_contract=vocab_contract,
            checkpoint_metadata=chk_meta,
            weights=weights,
            run_manifest=run_manifest,
            fertility_report=fertility_report,
            retrieval_report=retrieval_report,
        )
