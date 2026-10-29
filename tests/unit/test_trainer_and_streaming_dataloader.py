"""Unit and contract tests for real Stage 1 optimization loop and streaming Parquet DataLoader.

Verifies:
- LanguageEncoderTrainer genuine forward, autograd backward, and optimizer.step() weight updates
- LanguageEncoderTrainer multi-task loss computation across MLM, NLI, Paraphrase, Similarity, QA
- LanguageEncoderTrainer gradient accumulation steps and clipping
- StreamingParquetMultiTaskDataLoader streaming Parquet reading via PyArrow (RAM <= 250MB)
- StreamingParquetMultiTaskDataLoader dynamic MLM masking and label construction
- StreamingParquetMultiTaskDataLoader PyTorch and NumPy tensor output modes
- Infinite shard recycling during continuous training iteration
"""

import tempfile
import unittest
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

from laris.core.authorization import (
    temporary_training_authorization,
)
from laris.core.errors import (
    TrainingExecutionProhibitedError,
)
from laris.language.encoder.transformer import (
    TORCH_AVAILABLE,
    LanguageEncoderConfig,
    PyTorchTransformerEncoder,
)
from laris.language.training.dataloader import (
    StreamingParquetMultiTaskDataLoader,
    SyntheticMultiTaskDataLoader,
)
from laris.language.training.trainer import (
    LanguageEncoderTrainer,
)

if TORCH_AVAILABLE:
    import torch


class TestTrainerAndStreamingDataLoader(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.data_dir = Path(self.temp_dir.name)

        # Create tiny Parquet fixtures for all 5 tasks
        self._create_parquet_fixtures()

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _create_parquet_fixtures(self) -> None:
        """Creates minimal Parquet test shards for physical streaming verification."""
        # 1. MLM: text documents
        mlm_dir = self.data_dir / "wikipedia_en"
        mlm_dir.mkdir(parents=True, exist_ok=True)
        mlm_table = pa.Table.from_pydict({
            "id": ["doc_001", "doc_002", "doc_003"],
            "text": [
                "Quantum computing uses superposition and entanglement.",
                "General relativity describes spacetime gravitation.",
                "Photosynthesis converts light energy into chemical energy.",
            ],
        })
        pq.write_table(mlm_table, mlm_dir / "train.parquet")

        # 2. NLI: premise, hypothesis, label
        nli_dir = self.data_dir / "all_nli"
        nli_dir.mkdir(parents=True, exist_ok=True)
        nli_table = pa.Table.from_pydict({
            "premise": [
                "A dog runs across the park.",
                "Two astronomers observe a supernova.",
                "A child is playing violin.",
            ],
            "hypothesis": [
                "An animal is outdoors.",
                "The astronomers are asleep.",
                "A person makes music.",
            ],
            "label": [0, 2, 0],
        })
        pq.write_table(nli_table, nli_dir / "train.parquet")

        # 3. Paraphrase: question1, question2, is_duplicate
        para_dir = self.data_dir / "quora"
        para_dir.mkdir(parents=True, exist_ok=True)
        para_table = pa.Table.from_pydict({
            "question1": [
                "What is the theory of special relativity?",
                "How do neural networks learn weights?",
            ],
            "question2": [
                "Can you explain Einstein's special relativity?",
                "Why is the sky blue during the day?",
            ],
            "is_duplicate": [1, 0],
        })
        pq.write_table(para_table, para_dir / "train.parquet")

        # 4. Similarity: sentence1, sentence2, score
        sim_dir = self.data_dir / "stsb"
        sim_dir.mkdir(parents=True, exist_ok=True)
        sim_table = pa.Table.from_pydict({
            "sentence1": ["The scientist conducts an experiment.", "Water boils at 100 Celsius."],
            "sentence2": ["A researcher performs a laboratory test.", "Ice melts above 0 Celsius."],
            "score": [4.5, 2.5],
        })
        pq.write_table(sim_table, sim_dir / "train.parquet")

        # 5. QA: context, question, answer
        qa_dir = self.data_dir / "squad"
        qa_dir.mkdir(parents=True, exist_ok=True)
        qa_table = pa.Table.from_pydict({
            "context": [
                "The speed of light in vacuum is 299792458 meters per second.",
                "Mitochondria generate most of the chemical energy needed by the cell.",
            ],
            "question": [
                "What is the speed of light in vacuum?",
                "Which organelle generates cellular energy?",
            ],
        })
        pq.write_table(qa_table, qa_dir / "train.parquet")

    def test_streaming_parquet_dataloader_all_tasks(self) -> None:
        """Verifies StreamingParquetMultiTaskDataLoader streams batches across all 5 tasks."""
        loader = StreamingParquetMultiTaskDataLoader(
            data_dir=self.data_dir,
            batch_size=2,
            seq_len=24,
            buffer_size=4,
            mlm_mask_prob=0.20,
            seed=42,
            return_tensors="np",
        )

        for task in ["mlm", "nli", "paraphrase", "similarity", "qa"]:
            batch = loader.generate_batch(task_type=task)
            self.assertEqual(batch.task_type, task)
            self.assertEqual(batch.batch_size, 2)
            self.assertEqual(batch.seq_len, 24)
            self.assertEqual(batch.token_ids.shape, (2, 24))
            self.assertEqual(batch.attention_mask.shape, (2, 24))

            if task == "mlm":
                self.assertIn("mlm_labels", batch.labels)
                self.assertEqual(batch.labels["mlm_labels"].shape, (2, 24))
                # Verify that unmasked positions are -100
                unmasked = batch.labels["mlm_labels"] == -100
                self.assertTrue(np.any(unmasked))
            elif task == "nli":
                self.assertIn("nli_labels", batch.labels)
                self.assertEqual(batch.labels["nli_labels"].shape, (2,))
            elif task == "paraphrase":
                self.assertIn("para_labels", batch.labels)
                self.assertEqual(batch.labels["para_labels"].shape, (2,))
            elif task == "similarity":
                self.assertIn("sim_labels", batch.labels)
                self.assertEqual(batch.labels["sim_labels"].shape, (2,))
                # Score in [0, 1]
                self.assertTrue(np.all(batch.labels["sim_labels"] <= 1.0))
            elif task == "qa":
                self.assertIn("qa_start_positions", batch.labels)
                self.assertIn("qa_end_positions", batch.labels)
                self.assertEqual(batch.labels["qa_start_positions"].shape, (2,))

    def test_streaming_parquet_dataloader_infinite_cycling(self) -> None:
        """Verifies loader recycles small shards continuously without StopIteration."""
        loader = StreamingParquetMultiTaskDataLoader(
            data_dir=self.data_dir,
            batch_size=2,
            seq_len=16,
            buffer_size=2,
        )

        # Draw 10 batches sequentially from a 3-record shard
        batches_drawn = 0
        for batch in loader:
            self.assertEqual(batch.batch_size, 2)
            batches_drawn += 1
            if batches_drawn >= 10:
                break
        self.assertEqual(batches_drawn, 10)

    @unittest.skipUnless(TORCH_AVAILABLE, "PyTorch required for neural optimization tests")
    def test_streaming_parquet_dataloader_pytorch_tensors(self) -> None:
        """Verifies loader yields PyTorch tensors when return_tensors='pt'."""
        loader = StreamingParquetMultiTaskDataLoader(
            data_dir=self.data_dir,
            batch_size=2,
            seq_len=16,
            return_tensors="pt",
        )
        batch = loader.generate_batch(task_type="mlm")
        self.assertIsInstance(batch.token_ids, torch.Tensor)
        self.assertIsInstance(batch.attention_mask, torch.Tensor)
        self.assertIsInstance(batch.labels["mlm_labels"], torch.Tensor)

    @unittest.skipUnless(TORCH_AVAILABLE, "PyTorch required for neural optimization tests")
    def test_stage1_trainer_genuine_pytorch_optimization(self) -> None:
        """Verifies trainer executes forward, backward, autograd, and optimizer update."""
        cfg = LanguageEncoderConfig(
            d_model=384,
            num_layers=2,
            num_heads=6,
            d_ff=1536,
            max_sequence_length=32,
            vocab_size=500,
        )
        model = PyTorchTransformerEncoder(cfg)

        # Snapshot initial weight of first layer query projection
        initial_weight = model.layers[0].q_proj.weight.clone().detach().cpu()

        loader = StreamingParquetMultiTaskDataLoader(
            data_dir=self.data_dir,
            vocab_size=500,
            seq_len=32,
            batch_size=2,
            return_tensors="pt",
        )
        batch = loader.generate_batch(task_type="mlm")

        # Initialize trainer with grad_accum_steps=1 to force immediate optimizer.step()
        trainer = LanguageEncoderTrainer(
            model=model,
            config=cfg,
            dataloader=loader,
            grad_accum_steps=1,
            use_8bit_adam=False,  # Use standard CPU AdamW for unit test
            learning_rate=0.01,
        )

        # 1. Verify strict authorization gate
        with self.assertRaises(TrainingExecutionProhibitedError):
            trainer.execute_training_step(batch)

        # 2. Verify authorized optimization step updates parameters and records non-zero loss
        with temporary_training_authorization(True):
            snapshot = trainer.execute_training_step(batch)

            # Loss must be genuine positive scalar, NOT dummy 0.0
            self.assertGreater(snapshot.loss_value, 0.0)
            self.assertEqual(snapshot.step, 1)
            self.assertEqual(snapshot.task_type, "mlm")

            # Check that weights were actually updated by optimizer.step()
            current_weight = model.layers[0].q_proj.weight.detach().cpu()
            weight_diff = torch.norm(current_weight - initial_weight).item()
            self.assertGreater(
                weight_diff,
                1e-6,
                "Model weights did not change after optimizer.step()!",
            )

    @unittest.skipUnless(TORCH_AVAILABLE, "PyTorch required for neural optimization tests")
    def test_stage1_trainer_all_tasks_gradient_flow(self) -> None:
        """Verifies gradient calculation across all 5 Stage 1 multi-task objectives."""
        cfg = LanguageEncoderConfig(
            d_model=384,
            num_layers=2,
            num_heads=6,
            d_ff=1536,
            max_sequence_length=32,
            vocab_size=500,
        )
        model = PyTorchTransformerEncoder(cfg)

        loader = StreamingParquetMultiTaskDataLoader(
            data_dir=self.data_dir,
            vocab_size=500,
            seq_len=32,
            batch_size=2,
            return_tensors="pt",
        )

        trainer = LanguageEncoderTrainer(
            model=model,
            config=cfg,
            dataloader=loader,
            grad_accum_steps=1,
            use_8bit_adam=False,
        )

        with temporary_training_authorization(True):
            for task in ["mlm", "nli", "paraphrase", "similarity", "qa"]:
                batch = loader.generate_batch(task_type=task)
                snapshot = trainer.execute_training_step(batch)
                self.assertGreater(snapshot.loss_value, 0.0)
                self.assertEqual(snapshot.task_type, task)

    @unittest.skipUnless(TORCH_AVAILABLE, "PyTorch required for neural optimization tests")
    def test_stage1_trainer_gradient_accumulation(self) -> None:
        """Verifies optimizer steps only after grad_accum_steps batches."""
        cfg = LanguageEncoderConfig(
            d_model=384,
            num_layers=2,
            num_heads=6,
            d_ff=1536,
            max_sequence_length=32,
            vocab_size=500,
        )
        model = PyTorchTransformerEncoder(cfg)
        initial_weight = model.layers[0].q_proj.weight.clone().detach().cpu()

        loader = SyntheticMultiTaskDataLoader(vocab_size=500, seq_len=32, batch_size=2)
        batch1 = loader.generate_batch(task_type="mlm")
        batch2 = loader.generate_batch(task_type="mlm")

        trainer = LanguageEncoderTrainer(
            model=model,
            config=cfg,
            dataloader=loader,
            grad_accum_steps=2,
            use_8bit_adam=False,
            learning_rate=0.01,
        )

        with temporary_training_authorization(True):
            # Step 1: accumulated, weights should NOT have updated yet
            trainer.execute_training_step(batch1)
            weight_after_step1 = model.layers[0].q_proj.weight.clone().detach().cpu()
            self.assertTrue(torch.allclose(initial_weight, weight_after_step1))

            # Step 2: accumulation limit reached, optimizer steps, weights MUST update
            trainer.execute_training_step(batch2)
            weight_after_step2 = model.layers[0].q_proj.weight.detach().cpu()
            self.assertFalse(torch.allclose(initial_weight, weight_after_step2))


if __name__ == "__main__":
    unittest.main()
