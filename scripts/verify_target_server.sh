#!/usr/bin/env bash
# LARIS Target Server Telemetry & Verification Script (Issue #224)
# ZERO TRAINING PERMITTED - EXECUTES BOUNDED FORWARD-ONLY PASS ONLY
set -euo pipefail

# Resolve the Python interpreter: explicit override, active virtualenv, then python3
PYTHON_BIN="${PYTHON_EXEC:-python3}"
if [ -z "${PYTHON_EXEC:-}" ] && [ -n "${VIRTUAL_ENV:-}" ] && [ -x "${VIRTUAL_ENV}/bin/python" ]; then
    PYTHON_BIN="${VIRTUAL_ENV}/bin/python"
fi

echo "=================================================="
echo "LARIS TARGET SERVER HARDWARE & SOFTWARE AUDIT"
echo "=================================================="

echo "=== 1. OS & KERNEL ==="
uname -a
if [ -f /etc/os-release ]; then
    grep -E 'NAME|VERSION' /etc/os-release || true
fi

echo ""
echo "=== 2. CPU & HOST MEMORY ==="
lscpu | grep -E 'Model name|CPU\(s\):|Thread\(s\) per core' || true
free -h

echo ""
echo "=== 3. GPU ACCELERATOR & DRIVER ==="
if command -v nvidia-smi &> /dev/null; then
    nvidia-smi --query-gpu=name,driver_version,memory.total,memory.free --format=csv,noheader || true
else
    echo "nvidia-smi not found in PATH."
fi

echo ""
echo "=== 4. PYTHON & PYTORCH CUDA INSPECTION ==="
"$PYTHON_BIN" -c '
import sys
print(f"Python: {sys.version}")
try:
    import torch
    print(f"PyTorch: {torch.__version__}")
    print(f"CUDA Available: {torch.cuda.is_available()}")
    if torch.cuda.is_available():
        print(f"Device 0: {torch.cuda.get_device_name(0)}")
        print(f"VRAM Total: {torch.cuda.get_device_properties(0).total_memory / (1024**3):.2f} GB")
        print(f"CUDA Arch List: {torch.cuda.get_arch_list()}")
        is_blackwell = any(a in ("sm_100", "sm_120") for a in torch.cuda.get_arch_list())
        print(f"Blackwell (sm_100/sm_120) Supported: {is_blackwell}")
    else:
        print("CUDA is NOT available in this PyTorch installation.")
except ImportError:
    print("PyTorch is not installed in current Python environment.")
'

echo ""
echo "=== 5. BOUNDED FORWARD-ONLY SMOKE TEST (NO TRAINING) ==="
"$PYTHON_BIN" -c '
import os, sys
sys.path.insert(0, os.path.abspath("src"))
from laris.language.encoder.transformer import LanguageEncoderConfig, RandomlyInitializedTransformerEncoder
from laris.language.training.profiling import BoundedResourceProfiler

cfg = LanguageEncoderConfig(vocab_size=500, max_sequence_length=64, d_model=384, num_layers=2, num_heads=6, d_ff=1536, seed=42)
model = RandomlyInitializedTransformerEncoder(cfg)
res = BoundedResourceProfiler.profile_forward_pass(model, batch_size=2, seq_len=32)
print(f"Forward pass latency: {res.forward_latency_ms:.2f} ms")
print(f"Peak RAM: {res.peak_ram_mb:.2f} MB")
print(f"Peak VRAM: {res.peak_vram_mb}")
print(f"Analytical VRAM Estimate: {res.analytical_vram_estimate_mb} MB")
print(f"Device: {res.measured_device}")
print(f"Governor Passed: {res.safety_governor_passed}")
'

echo ""
echo "=================================================="
echo "AUDIT COMPLETE. NO TRAINING OF ANY KIND WAS RUN."
echo "NO OPTIMIZER STEPS OR WEIGHT UPDATES OCCURRED."
echo "=================================================="
