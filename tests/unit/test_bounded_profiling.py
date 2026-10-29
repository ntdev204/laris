"""Unit tests for bounded profiling and hardware environment distinction.

Addresses Issue #217 (WP5) and Issue #224 (M2-LANG-006-SUB-04).
Validates:
- Single forward pass bounded profiling on synthetic tensor
- Zero optimizer steps or weight updates
- Finite output validation and memory safety governor
- Hardware telemetry: development host (MEASURED) vs target workstation (NOT VERIFIED)
- Real GPU VRAM reporting on CUDA vs strict None reporting on CPU (no fabricated VRAM)
- Analytical VRAM formula estimation
- Blackwell architecture compatibility check (sm_100/sm_120)
- Exact shell script generation for physical target server verification
"""

import importlib.util
import unittest

from laris.core.errors import TrainingExecutionProhibitedError
from laris.language.encoder.transformer import (
    LanguageEncoderConfig,
    PyTorchTransformerEncoder,
    RandomlyInitializedTransformerEncoder,
)
from laris.language.training.profiling import (
    BoundedProfilingResult,
    BoundedResourceProfiler,
    HardwareEnvironmentProfile,
    estimate_forward_vram_mb,
)


class TestBoundedProfilingAndHardwareTelemetry(unittest.TestCase):
    """Test suite for bounded profiling and hardware telemetry."""

    def setUp(self) -> None:
        self.config = LanguageEncoderConfig(
            vocab_size=500,
            max_sequence_length=64,
            d_model=384,
            num_layers=2,
            num_heads=6,
            d_ff=1536,
            seed=42,
        )
        self.model = RandomlyInitializedTransformerEncoder(self.config)

    def test_profile_forward_pass_bounded_cpu(self) -> None:
        """Bounded profiling executes single forward pass on CPU without optimizer steps."""
        result = BoundedResourceProfiler.profile_forward_pass(
            self.model,
            batch_size=2,
            seq_len=32,
        )

        self.assertIsInstance(result, BoundedProfilingResult)
        self.assertEqual(result.batch_size, 2)
        self.assertEqual(result.seq_len, 32)
        self.assertGreater(result.forward_latency_ms, 0.0)
        self.assertGreater(result.peak_ram_mb, 0.0)
        # Strict CPU verification: VRAM must NOT be fabricated
        self.assertIsNone(result.peak_vram_mb)
        self.assertIsNone(result.peak_allocated_vram_mb)
        self.assertIsNone(result.peak_reserved_vram_mb)
        self.assertIsNone(result.process_vram_mb)
        self.assertFalse(result.cuda_available)
        self.assertIsNotNone(result.analytical_vram_estimate_mb)
        self.assertGreater(result.analytical_vram_estimate_mb or 0.0, 0.0)
        self.assertTrue(result.outputs_finite)
        self.assertTrue(result.safety_governor_passed)
        self.assertIn("Development Host", result.measured_device)

    def test_profile_forward_pass_pytorch_model(self) -> None:
        """Bounded profiling supports PyTorchTransformerEncoder without weight updates."""
        if importlib.util.find_spec("torch") is None:
            self.skipTest("PyTorch is not installed in the current environment.")

        pt_model = PyTorchTransformerEncoder(self.config)
        result = BoundedResourceProfiler.profile_forward_pass(
            pt_model,
            batch_size=2,
            seq_len=32,
            device="cpu",
        )

        self.assertIsInstance(result, BoundedProfilingResult)
        self.assertTrue(result.outputs_finite)
        self.assertTrue(result.safety_governor_passed)
        self.assertIsNone(result.peak_vram_mb)
        self.assertFalse(result.cuda_available)

    def test_profile_forward_pass_cuda_if_available(self) -> None:
        """Bounded profiling measures real allocated/reserved VRAM when CUDA is available."""
        if importlib.util.find_spec("torch") is None:
            self.skipTest("PyTorch is not installed.")
        import torch

        if not torch.cuda.is_available():
            self.skipTest("CUDA GPU is not available on this host.")

        pt_model = PyTorchTransformerEncoder(self.config)
        result = BoundedResourceProfiler.profile_forward_pass(
            pt_model,
            batch_size=2,
            seq_len=32,
            device="cuda",
        )

        self.assertIsInstance(result, BoundedProfilingResult)
        self.assertTrue(result.cuda_available)
        self.assertIsNotNone(result.peak_vram_mb)
        self.assertIsNotNone(result.peak_allocated_vram_mb)
        self.assertIsNotNone(result.peak_reserved_vram_mb)
        self.assertGreater(result.peak_allocated_vram_mb or 0.0, 0.0)
        self.assertIn("CUDA", result.measured_device)

    def test_analytical_vram_estimation(self) -> None:
        """Analytical VRAM estimation computes realistic forward pass bounds."""
        est_mb = estimate_forward_vram_mb(self.config, batch_size=2, seq_len=32)
        self.assertGreater(est_mb, 32.0)  # Must exceed base buffer
        # A 2-layer 384-dim model should take ~40-60 MB in FP32
        self.assertLess(est_mb, 500.0)

    def test_execute_training_benchmark_prohibited(self) -> None:
        """Training benchmark jobs must be strictly prohibited."""
        with self.assertRaises(TrainingExecutionProhibitedError):
            BoundedResourceProfiler.execute_training_benchmark()

    def test_hardware_environment_profiles_distinction(self) -> None:
        """Development machine must be MEASURED and Target server must be NOT VERIFIED."""
        dev_profile = HardwareEnvironmentProfile.get_development_host_telemetry()
        self.assertEqual(dev_profile["status"], "MEASURED")
        self.assertEqual(dev_profile["vram_capacity_gb"], 4.0)

        target_profile = HardwareEnvironmentProfile.get_target_server_specification()
        self.assertEqual(target_profile["status"], "NOT VERIFIED")
        self.assertEqual(target_profile["ram_requirement_gb"], 32.0)
        self.assertEqual(target_profile["safety_vram_ceiling_gb"], 14.5)
        self.assertIn("RTX 5070 Ti", target_profile["gpu_requirement"])
        self.assertIn("Blackwell", target_profile["gpu_architecture"])

    def test_target_gpu_compatibility_audit(self) -> None:
        """Auditing target GPU compatibility flags Blackwell sm_100/sm_120 requirements."""
        audit = HardwareEnvironmentProfile.verify_target_gpu_compatibility()
        self.assertEqual(audit["target_status"], "NOT VERIFIED")
        self.assertIn("RTX 5070 Ti", audit["target_gpu"])
        self.assertIn("torch>=2.6.0", audit["remediation"])

    def test_target_verification_script_generation(self) -> None:
        """Target verification script must include required inspection commands."""
        script = HardwareEnvironmentProfile.generate_target_verification_script()
        self.assertIn("uname -a", script)
        self.assertIn("free -h", script)
        self.assertIn("lscpu", script)
        self.assertIn("nvidia-smi", script)
        self.assertIn("torch.cuda.is_available()", script)
        self.assertIn("BoundedResourceProfiler", script)
        self.assertIn("NO TRAINING OCCURRED", script)
