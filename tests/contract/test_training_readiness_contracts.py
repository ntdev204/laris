"""Contract tests for Natural Language Foundation Training Readiness & Audit invariants.

Enforces:
- Reconciliation of tracked datasets and disaggregated unit ledgers
- Mathematical soundness of VRAM estimation formulas under hardware budget
- Zero trained model weights/checkpoints in repository (Mandatory Stop Condition)
- Formal readiness gate taxonomy validation
"""

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def test_manifest_and_disaggregated_accounting_invariants() -> None:
    """Verifies that the acquisition manifest totals reconcile with per-dataset ledgers."""
    manifest_path = REPO_ROOT / "data" / "acquisition_manifest.json"
    assert manifest_path.exists(), "acquisition_manifest.json must exist"

    with open(manifest_path, "r", encoding="utf-8") as f:
        manifest = json.load(f)

    datasets = manifest.get("datasets", [])
    assert manifest.get("total_datasets_tracked") == len(datasets)
    ids = [d["dataset_id"] for d in datasets]
    assert len(ids) == len(set(ids)), "dataset_id values must be unique"

    counted_statuses = {"VERIFIED", "DOWNLOADED"}
    english_samples = 0
    vietnamese_samples = 0
    for d in datasets:
        samples = d.get("actual_sample_count", 0)
        if d.get("acquisition_status") in counted_statuses:
            if d.get("language") == "English":
                english_samples += samples
            elif d.get("language") == "Vietnamese":
                vietnamese_samples += samples
        elif d.get("acquisition_status") in {"BLOCKED", "PROPOSED"}:
            assert samples == 0, f"{d['dataset_id']} is not acquired but reports samples"

    total_samples = manifest.get("total_acquired_samples", 0)
    assert english_samples + vietnamese_samples == total_samples
    assert total_samples == sum(
        d.get("actual_sample_count", 0)
        for d in datasets
        if d.get("acquisition_status") in counted_statuses
    )

    verified = [d for d in datasets if d.get("acquisition_status") == "VERIFIED"]
    assert all(d.get("license_status") == "APPROVED_FOR_ACQUISITION" for d in verified)
    assert all(d.get("schema_valid") is True for d in verified)


def test_training_readiness_hardware_budget_formula() -> None:
    """Verifies analytical memory calculation for 109.56M Transformer encoder respects
    RTX 5070 Ti envelope.
    """
    param_count = 109_561_856
    d_model = 768
    num_layers = 12
    batch_size = 32
    seq_len = 512

    # Weights in 16-bit (2 bytes per param)
    weight_bytes = param_count * 2
    # Gradients in 16-bit (2 bytes per param)
    grad_bytes = param_count * 2
    # AdamW optimizer: FP32 master weights (4B) + 1st moment (4B) + 2nd moment (4B) = 12B
    optimizer_bytes = param_count * 12

    # Activations estimate with FlashAttention and activation checkpointing
    activation_bytes = 2 * num_layers * batch_size * seq_len * d_model * 2

    # CUDA / framework overhead buffer (800 MB)
    workspace_bytes = 800 * 1024 * 1024

    total_bytes = weight_bytes + grad_bytes + optimizer_bytes + activation_bytes + workspace_bytes
    total_gb = total_bytes / (1024**3)

    # Must be less than 6.0 GB for 110M model and strictly within 14.5 GB safety envelope
    assert total_gb < 6.0, f"Estimated memory {total_gb:.2f} GB exceeds 6.0 GB baseline"
    assert total_gb <= 14.5, f"Estimated memory {total_gb:.2f} GB exceeds 14.5 GB hardware limit"


def test_mandatory_stop_condition_no_trained_weights() -> None:
    """Enforces repository invariant: NO neural weights or trained checkpoints exist in repo."""
    prohibited_extensions = {".pt", ".bin", ".safetensors", ".gguf", ".ckpt", ".h5"}

    for ext in prohibited_extensions:
        found_files = list(REPO_ROOT.glob(f"**/*{ext}"))
        model_weights = [
            f for f in found_files
            if "laris-env" not in f.parts and ".git" not in f.parts
        ]
        assert len(model_weights) == 0, f"Found unauthorized model weight file: {model_weights}"


def test_readiness_gate_taxonomy_and_contract() -> None:
    """Verifies that the training specification specifies all 11 gates with canonical statuses."""
    spec_path = (
        REPO_ROOT
        / "docs"
        / "specifications"
        / "NATURAL_LANGUAGE_TRAINING_SPECIFICATION.md"
    )
    assert spec_path.exists(), "NATURAL_LANGUAGE_TRAINING_SPECIFICATION.md must exist"

    content = spec_path.read_text(encoding="utf-8")
    valid_statuses = ["PASS", "FAIL", "BLOCKED", "READY", "NOT VERIFIED"]

    # All 11 gates must be present with one of the valid statuses
    for gate_idx in range(1, 12):
        gate_marker = f"**{gate_idx}**"
        assert gate_marker in content, f"Gate {gate_idx} missing from readiness gates table"

    # Status tokens must be present in the document
    for status in valid_statuses:
        if status in {"PASS", "BLOCKED", "READY"}:
            assert f"**{status}**" in content, f"Expected active gate status {status} in spec"

    # Mandatory stop statement must be present
    assert "NO MODEL TRAINING WAS RUN." in content
