"""Unit tests for 512M Model 1 architecture scaling, VRAM calculations, and Stage 1 training engine.

Verifies:
- TransformerEncoder500MConfig parameter formulas (512.91M backbone, 513.25M with heads)
- Analytical VRAM budget for 500M model respects 14.5 GB RTX 5070 Ti safety envelope
- TemperatureSamplingScheduler mathematical distribution (alpha=0.7)
- SyntheticMultiTaskDataLoader batch generation across MLM, NLI, Paraphrase, Similarity, QA
- Stage1LossCalculator composite loss and individual task formulation
- Stage1LanguageTrainer strict authorization barrier
"""

import unittest

import numpy as np

from laris.core.authorization import (
    temporary_training_authorization,
)
from laris.core.errors import (
    TrainingExecutionProhibitedError,
)
from laris.language.dataloader import (
    SyntheticMultiTaskDataLoader,
    TemperatureSamplingScheduler,
)
from laris.language.neural import (
    TransformerEncoder500MConfig,
)
from laris.language.profiling import (
    compute_analytical_training_memory_gb,
)
from laris.language.schemas import ALLOWED_EMBEDDING_DIMENSIONS
from laris.language.trainer import (
    Stage1LanguageTrainer,
    Stage1LossCalculator,
)


class Test500MScalingAndTraining(unittest.TestCase):
    def test_allowed_embedding_dimensions_expanded(self) -> None:
        """Verifies ALLOWED_EMBEDDING_DIMENSIONS contains 384, 768, 1024, 1280."""
        self.assertIn(384, ALLOWED_EMBEDDING_DIMENSIONS)
        self.assertIn(768, ALLOWED_EMBEDDING_DIMENSIONS)
        self.assertIn(1024, ALLOWED_EMBEDDING_DIMENSIONS)
        self.assertIn(1280, ALLOWED_EMBEDDING_DIMENSIONS)

    def test_transformer_500m_parameter_formula_exact(self) -> None:
        """Verifies exact parameter calculations for 512.9M model."""
        cfg = TransformerEncoder500MConfig()
        self.assertEqual(cfg.d_model, 1280)
        self.assertEqual(cfg.num_layers, 24)
        self.assertEqual(cfg.num_heads, 20)
        self.assertEqual(cfg.d_ff, 5120)
        self.assertEqual(cfg.max_sequence_length, 1024)

        # Backbone: V*d + L*(4*d^2 + 2*d*d_ff + 2*d) + d + V
        backbone_count = cfg.calculate_backbone_parameter_count()
        self.assertEqual(backbone_count, 512_913_920)

        # Total with heads
        total_count = cfg.calculate_parameter_count(include_heads=True)
        self.assertEqual(total_count, 513_247_751)

    def test_analytical_training_vram_under_safety_envelope(self) -> None:
        """Verifies analytical VRAM calculation for 500M model respects 14.5 GB limit."""
        cfg = TransformerEncoder500MConfig()

        # Config 1: 8-bit AdamW with batch_size=16, seq_len=1024
        vram_8bit = compute_analytical_training_memory_gb(
            config=cfg,
            batch_size=16,
            seq_len=1024,
            use_8bit_adam=True,
            use_activation_checkpointing=True,
        )
        self.assertLess(vram_8bit, 14.5)
        self.assertGreater(vram_8bit, 7.0)

        # Config 2: 32-bit AdamW with batch_size=32, seq_len=1024
        vram_32bit = compute_analytical_training_memory_gb(
            config=cfg,
            batch_size=32,
            seq_len=1024,
            use_8bit_adam=False,
            use_activation_checkpointing=True,
        )
        self.assertLessEqual(vram_32bit, 14.5)
        self.assertGreater(vram_32bit, 12.0)

    def test_temperature_sampling_scheduler(self) -> None:
        """Verifies temperature sampling probabilities are smoothed and sum to 1.0."""
        task_counts = {
            "mlm": 3320430,
            "nli": 1150647,
            "paraphrase": 469691,
            "similarity": 8628,
            "qa": 130447,
        }
        scheduler = TemperatureSamplingScheduler(task_counts, alpha=0.7)
        self.assertAlmostEqual(sum(scheduler.probabilities), 1.0, places=5)

        # Similarity (8.6k) should have higher relative share under alpha=0.7 than raw ratio
        raw_sim_ratio = 8628 / sum(task_counts.values())
        smooth_sim_ratio = scheduler.get_task_probability("similarity")
        self.assertGreater(smooth_sim_ratio, raw_sim_ratio)

    def test_synthetic_dataloader_all_tasks(self) -> None:
        """Verifies synthetic dataloader produces valid batches for all Stage 1 tasks."""
        loader = SyntheticMultiTaskDataLoader(
            vocab_size=32000,
            seq_len=64,
            batch_size=4,
            seed=123,
        )
        for task in ["mlm", "nli", "paraphrase", "similarity", "qa"]:
            batch = loader.generate_batch(task_type=task)
            self.assertEqual(batch.task_type, task)
            self.assertEqual(batch.token_ids.shape, (4, 64))
            self.assertEqual(batch.attention_mask.shape, (4, 64))
            self.assertIn("labels", dir(batch))

    def test_stage1_loss_calculator_numpy(self) -> None:
        """Verifies multi-task loss calculator across all 5 tasks."""
        calc = Stage1LossCalculator()
        b, s, v = 2, 16, 100

        # MLM Loss
        mlm_preds = {"mlm_logits": np.random.randn(b, s, v).astype(np.float32)}
        mlm_labels = {"mlm_labels": np.random.choice([-100, 5, 10], size=(b, s))}
        mlm_loss = calc.compute_loss_numpy("mlm", mlm_preds, mlm_labels)
        self.assertGreaterEqual(mlm_loss, 0.0)

        # NLI Loss
        nli_preds = {"nli_logits": np.array([[2.0, 0.5, 0.1], [0.1, 3.0, 0.2]])}
        nli_labels = {"nli_labels": np.array([0, 1])}
        nli_loss = calc.compute_loss_numpy("nli", nli_preds, nli_labels)
        self.assertGreater(nli_loss, 0.0)

        # Paraphrase Loss
        para_preds = {"paraphrase_prob": np.array([[0.8], [0.2]])}
        para_labels = {"para_labels": np.array([1, 0])}
        para_loss = calc.compute_loss_numpy("paraphrase", para_preds, para_labels)
        self.assertGreater(para_loss, 0.0)

        # Similarity Loss
        sim_preds = {"similarity_score": np.array([[0.7], [0.3]])}
        sim_labels = {"sim_labels": np.array([0.75, 0.25])}
        sim_loss = calc.compute_loss_numpy("similarity", sim_preds, sim_labels)
        self.assertGreater(sim_loss, 0.0)

        # QA Loss
        qa_preds = {"qa_logits": np.random.randn(b, s, 2).astype(np.float32)}
        qa_labels = {
            "qa_start_positions": np.array([2, 5]),
            "qa_end_positions": np.array([4, 8]),
        }
        qa_loss = calc.compute_loss_numpy("qa", qa_preds, qa_labels)
        self.assertGreater(qa_loss, 0.0)

    def test_stage1_trainer_authorization_barrier(self) -> None:
        """Verifies trainer strictly raises TrainingExecutionProhibitedError when unauthorized."""
        cfg = TransformerEncoder500MConfig()
        loader = SyntheticMultiTaskDataLoader(seq_len=32, batch_size=2)
        batch = loader.generate_batch()
        trainer = Stage1LanguageTrainer(model=None, config=cfg, dataloader=loader)

        # When unauthorized, must raise TrainingExecutionProhibitedError
        with self.assertRaises(TrainingExecutionProhibitedError):
            trainer.execute_training_step(batch)

        # When authorized, executes step cleanly
        with temporary_training_authorization(True):
            step_metrics = trainer.execute_training_step(batch)
            self.assertEqual(step_metrics.step, 1)
            self.assertEqual(step_metrics.task_type, batch.task_type)


if __name__ == "__main__":
    unittest.main()
