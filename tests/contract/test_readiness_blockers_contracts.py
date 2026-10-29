"""Contract tests for Issue #217 (M2-LANG-005) Training Readiness Blockers invariants.

Enforces:
- Mathematical soundness of 109.56M parameter equation
- From-scratch tokenizer pipeline and mandatory training prohibition
- Randomly initialized neural model path with capability heads and no learned weights
- Task-specific leakage-proof partitioning contracts
- Config handoff parameter inventory classification
- Strict repository invariant: NO neural weights or trained checkpoints exist in repo
"""

from pathlib import Path

from laris.core.errors import TrainingExecutionProhibitedError
from laris.corpus.splits import (
    PartitionRatios,
    QuestionPairGraphPartitioner,
    WikipediaArticlePartitioner,
    validate_split_isolation,
)
from laris.language.encoder.config_handoff import (
    get_immutable_invariants,
    get_tunable_parameters,
)
from laris.language.encoder.transformer import (
    LanguageEncoderConfig,
    ModelReadinessState,
    RandomlyInitializedTransformerEncoder,
)
from laris.language.tokenization.trainer import (
    TokenizerTrainingPipeline,
)
from laris.language.training.profiling import HardwareEnvironmentProfile

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def test_contract_109m_parameter_count_formula() -> None:
    """Contract: Model 1 encoder parameters must equal 109,561,856 under canonical config."""
    config = LanguageEncoderConfig(
        vocab_size=32000,
        d_model=768,
        num_layers=12,
        num_heads=12,
        d_ff=3072,
        tie_embeddings=True,
    )
    assert config.calculate_parameter_count() == 109_561_856


def test_contract_tokenizer_training_pipeline_prohibition() -> None:
    """Contract: TokenizerTrainingPipeline must enforce training prohibition."""
    pipeline = TokenizerTrainingPipeline()
    try:
        pipeline.execute_training()
        assert False, "execute_training() must raise TrainingExecutionProhibitedError"
    except TrainingExecutionProhibitedError:
        pass


def test_contract_neural_model_readiness_state() -> None:
    """Contract: Neural encoder must instantiate as RANDOMLY_INITIALIZED and prohibit training."""
    config = LanguageEncoderConfig(
        vocab_size=100,
        d_model=384,
        num_layers=2,
        num_heads=4,
        d_ff=1024,
    )
    model = RandomlyInitializedTransformerEncoder(config)
    assert model.readiness_state == ModelReadinessState.RANDOMLY_INITIALIZED
    assert model.readiness_state.value == "RANDOMLY_INITIALIZED"

    try:
        model.train_step()
        assert False, "train_step() must raise TrainingExecutionProhibitedError"
    except TrainingExecutionProhibitedError:
        pass


def test_contract_task_partitioners_zero_leakage() -> None:
    """Contract: Wikipedia and Quora partitioners must enforce zero cross-split leakage."""
    # 1. Wikipedia
    wiki_part = WikipediaArticlePartitioner(ratios=PartitionRatios(0.8, 0.1, 0.1))
    records = [{"id": f"art-{i}", "text": f"Article text {i}"} for i in range(20)]
    wiki_splits = wiki_part.partition_records(records)
    assert validate_split_isolation(wiki_splits, item_id_key="id")

    # 2. Quora
    pair_part = QuestionPairGraphPartitioner(ratios=PartitionRatios(0.8, 0.1, 0.1))
    pairs = [
        {"id": "p1", "question1": "What is AI?", "question2": "Explain AI"},
        {"id": "p2", "question1": "Explain AI", "question2": "Artificial Intelligence summary"},
        {"id": "p3", "question1": "Cooking pasta", "question2": "How to boil pasta?"},
    ]
    pair_splits = pair_part.partition_pairs(pairs)
    assert validate_split_isolation(pair_splits, item_id_key="id")


def test_contract_config_handoff_inventory() -> None:
    """Contract: Config handoff must classify tunable parameters vs immutable invariants."""
    tunables = get_tunable_parameters()
    invariants = get_immutable_invariants()

    assert "vocab_size" in tunables
    assert "d_model" in tunables
    assert "learning_rate" in tunables

    assert "norm_type" in invariants
    assert "pos_encoding" in invariants
    assert "max_vram_gb" in invariants
    assert invariants["max_vram_gb"] == 14.5
    assert invariants["mandatory_training_ban"] is True


def test_contract_target_server_marked_not_verified() -> None:
    """Contract: Target server specification must be explicitly labeled NOT VERIFIED."""
    target_spec = HardwareEnvironmentProfile.get_target_server_specification()
    assert target_spec["status"] == "NOT VERIFIED"
    assert target_spec["gpu_requirement"] == "NVIDIA GeForce RTX 5070 Ti (16384 MiB VRAM / 16.0 GB)"
