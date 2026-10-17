"""Unit tests for bounded profiling and hardware environment distinction.

Addresses Issue #217 (WP5).
Validates:
- Single forward pass bounded profiling on synthetic tensor
- Zero optimizer steps or weight updates
- Finite output validation and memory safety governor
- Hardware telemetry: development host (MEASURED) vs target workstation (NOT VERIFIED)
- Exact shell script generation for physical target server verification
"""

import unittest

from laris.core.errors import TrainingExecutionProhibitedError
from laris.language.neural import (
    RandomlyInitializedTransformerEncoder,
    TransformerEncoderConfig,
)
from laris.language.profiling import (
    BoundedProfilingResult,
    BoundedResourceProfiler,
    HardwareEnvironmentProfile,
)


class TestBoundedProfilingAndHardwareTelemetry(unittest.TestCase):
    """Test suite for bounded profiling and hardware telemetry."""

    def setUp(self) -> None:
        self.config = TransformerEncoderConfig(
            vocab_size=500,
            max_sequence_length=64,
            d_model=384,
            num_layers=2,
            num_heads=6,
            d_ff=1536,
            seed=42,
        )
        self.model = RandomlyInitializedTransformerEncoder(self.config)

    def test_profile_forward_pass_bounded(self) -> None:
        """Bounded profiling executes single forward pass without optimizer steps."""
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
        self.assertTrue(result.outputs_finite)
        self.assertTrue(result.safety_governor_passed)
        self.assertIn("Development Host", result.measured_device)

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

    def test_target_verification_script_generation(self) -> None:
        """Target verification script must include required inspection commands."""
        script = HardwareEnvironmentProfile.generate_target_verification_script()
        self.assertIn("uname -a", script)
        self.assertIn("free -h", script)
        self.assertIn("lscpu", script)
        self.assertIn("nvidia-smi", script)
        self.assertIn("torch.cuda.is_available()", script)
