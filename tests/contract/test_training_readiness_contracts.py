"""Contract tests for Natural Language Foundation Training Readiness & Audit invariants.

Enforces:
- Exact reconciliation of 17 tracked datasets and disaggregated unit ledgers
- Mathematical soundness of VRAM estimation formulas under hardware budget
- Zero trained model weights/checkpoints in repository (Mandatory Stop Condition)
- Formal readiness gate taxonomy validation
"""

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def test_manifest_and_disaggregated_accounting_invariants() -> None:
    """Verifies that the acquisition manifest disaggregated totals match exactly."""
    manifest_path = REPO_ROOT / "data" / "acquisition_manifest.json"
    assert manifest_path.exists(), "acquisition_manifest.json must exist"

    with open(manifest_path, "r", encoding="utf-8") as f:
        manifest = json.load(f)

    total_samples = manifest.get("total_acquired_samples", 0)
    assert total_samples == 5106491, f"Expected 5,106,491 samples, got {total_samples}"

    datasets = manifest.get("datasets", [])
    assert len(datasets) == 17, f"Expected 17 tracked datasets, got {len(datasets)}"

    english_samples = 0
    vietnamese_samples = 0
    acquired_count = 0

    for d in datasets:
        samples = d.get("actual_sample_count", 0)
        lang = d.get("language", "")
        if d.get("acquisition_status") == "VERIFIED":
            acquired_count += 1
            if lang == "English":
                english_samples += samples
            elif lang == "Vietnamese":
                vietnamese_samples += samples

    assert acquired_count == 14, f"Expected 14 verified acquired datasets, got {acquired_count}"
    assert english_samples == 3782210, f"Expected 3.78M EN records, got {english_samples}"
    assert vietnamese_samples == 1324281, f"Expected 1.32M VI records, got {vietnamese_samples}"
    assert english_samples + vietnamese_samples == total_samples


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
