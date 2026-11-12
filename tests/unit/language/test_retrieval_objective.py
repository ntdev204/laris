"""Forward-only checks for the auxiliary retrieval objective and training inputs."""

import math
import random

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from laris.research.language.training.objectives import contrastive_retrieval_loss
from laris.shared.language.loading.dataloader import StreamingParquetMultiTaskDataLoader


def test_aligned_embeddings_have_expected_cosine_loss():
    torch = pytest.importorskip("torch")
    with torch.inference_mode():
        embeddings = torch.eye(2)
        positives = torch.eye(2, dtype=torch.bool)
        aligned = contrastive_retrieval_loss(embeddings, embeddings, positives, 1.0)
        swapped = contrastive_retrieval_loss(embeddings, embeddings.flip(0), positives, 1.0)
    assert aligned.item() == pytest.approx(math.log1p(math.exp(-1)))
    assert swapped.item() > aligned.item()


def test_duplicate_positive_passages_are_not_penalized():
    torch = pytest.importorskip("torch")
    with torch.inference_mode():
        query = torch.tensor([[1.0, 0.0]])
        passages = torch.tensor([[1.0, 0.0], [1.0, 0.0], [0.0, 1.0]])
        positives = torch.tensor([[True, True, False]])
        loss = contrastive_retrieval_loss(query, passages, positives, 1.0)
    assert loss.item() == pytest.approx(math.log1p(math.exp(-1) / 2))


def test_missing_positive_is_rejected():
    torch = pytest.importorskip("torch")
    with torch.inference_mode(), pytest.raises(ValueError, match="positive passage"):
        contrastive_retrieval_loss(torch.eye(2), torch.eye(2), torch.zeros(2, 2, dtype=torch.bool))


def test_qa_train_pairs_reuse_answerable_rows_and_mask_shared_context(tmp_path):
    records = [
        {"context": "same context", "question": question, "answers": answers}
        for question, answers in [
            ("what one", {"text": ["same"], "answer_start": [0]}),
            ("what two", {"text": ["context"], "answer_start": [5]}),
            ("what three", {"text": [], "answer_start": []}),
        ]
    ]
    path = tmp_path / "train.parquet"
    pq.write_table(pa.Table.from_pylist(records), path)
    loader = StreamingParquetMultiTaskDataLoader(
        task_paths={"qa": [path]}, seq_len=16, batch_size=3,
        trim_padding=True, include_retrieval_pairs=True,
    )
    batch = loader.generate_batch("qa")
    assert batch.labels["retrieval_query_ids"].shape[0] == 2
    assert batch.labels["retrieval_positives"].tolist() == [[True, True], [True, True]]
    assert batch.labels["qa_start_positions"].tolist()[-1] == 0
    with pytest.raises(ValueError, match="train split"):
        StreamingParquetMultiTaskDataLoader(split="val", include_retrieval_pairs=True)


def test_resampling_counts_dataset_before_shard(tmp_path):
    class CaptureWeights(random.Random):
        def choices(self, population, weights=None, *, cum_weights=None, k=1):
            self.observed = weights
            return [0]

    paths = []
    for name, shard, rows in [("a", 0, 3), ("a", 1, 6), ("b", 0, 4)]:
        path = tmp_path / name / f"train{shard}.parquet"
        path.parent.mkdir(exist_ok=True)
        pq.write_table(pa.table({"text": [name] * rows}), path)
        paths.append(path)
    rng = CaptureWeights()
    stream = StreamingParquetMultiTaskDataLoader._interleaved_stream(paths, 4, rng, 0.5)
    assert next(stream) == {"text": "a"}
    assert rng.observed == pytest.approx([1.0, 2.0, 2.0])
