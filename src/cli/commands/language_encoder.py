"""`laris train language-encoder`: multi-task language encoder training and bounded profiling.

Supports compact/large models and memory profiling. Authorized --profile-only
includes real optimizer steps on a discarded model; it is not a no-training mode."""

import argparse
import random
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import numpy as np

from laris.research.language.evaluation.runner import EXIT_USAGE, evaluate_checkpoint
from laris.research.language.training.loop import TrainingRunConfig, run_training
from laris.research.language.training.memory_profile import profile_training_memory
from laris.research.language.training.progress import TrainingProgress
from laris.research.language.training.trainer import (
    LanguageEncoderTrainer,
    MultiTaskLossCalculator,
    MultiTaskLossWeights,
)
from laris.research.language.training.vram_ceiling import (
    DEFAULT_CEILING_GIB,
    vram_ceiling_from_environment,
)
from laris.shared.config.loader import load_config
from laris.shared.config.schemas import TrainingConfig
from laris.shared.core.authorization import (
    assert_training_authorized,
    is_training_authorized,
)
from laris.shared.core.errors import TrainingExecutionProhibitedError
from laris.shared.language.encoder.transformer import (
    TORCH_AVAILABLE,
    LanguageEncoderConfig,
    LargeLanguageEncoderConfig,
    PyTorchTransformerEncoder,
)
from laris.shared.language.loading.checkpoint import (
    MODEL_FILE,
    current_git_commit,
    file_sha256,
    load_model_weights,
    read_manifest,
)
from laris.shared.language.loading.dataloader import (
    CONTRASTIVE_SIM_TASK,
    TASK_DATASET_DIRS,
    StreamingParquetMultiTaskDataLoader,
)
from laris.shared.language.tokenization.normalized import (
    NORMALIZATION_ID,
    NormalizedSentencePiece,
)

# Default ceiling; `LARIS_VRAM_CEILING_GB` may raise it on a 24 GB+ card (ADR-023).
MAX_VRAM_GB = DEFAULT_CEILING_GIB


def _vram_ceiling_or_exit() -> Optional[float]:
    """Ceiling from the environment and the visible GPU; None after printing an error."""
    total: Optional[float] = None
    if TORCH_AVAILABLE:
        import torch

        if torch.cuda.is_available():
            total = torch.cuda.get_device_properties(0).total_memory / (1024**3)
    try:
        return vram_ceiling_from_environment(total)
    except ValueError as exc:
        print(f"[ERROR] {exc}")
        return None


def seed_everything(seed: int) -> None:
    random.seed(seed)
    np.random.seed(seed)
    if TORCH_AVAILABLE:
        import torch

        torch.manual_seed(seed)
        if torch.cuda.is_available():
            torch.cuda.manual_seed_all(seed)


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--model-size",
        type=str,
        choices=["compact", "large"],
        default="large",
        help="Language encoder size preset (compact ~110M or large ~513M parameters)",
    )
    parser.add_argument(
        "--micro-batch-size",
        type=int,
        default=None,
        help="Micro-batch size per device forward step (default: from --training-config)",
    )
    parser.add_argument(
        "--grad-accum-steps",
        type=int,
        default=None,
        help="Gradient accumulation steps per optimizer update (default: from --training-config)",
    )
    parser.add_argument(
        "--tasks-per-step",
        type=int,
        default=None,
        help="Different tasks whose losses are added in each micro-step (T201; default: from "
        "--training-config, 1 = one task per micro-batch). Memory grows with this number",
    )
    parser.add_argument(
        "--max-seq-len",
        type=int,
        default=None,
        help="Maximum sequence length in tokens (default: 1024 for large, 512 for compact)",
    )
    parser.add_argument(
        "--precision",
        type=str,
        choices=["bf16", "fp16", "fp32"],
        default="bf16",
        help="Mixed-precision computation mode (default: bf16)",
    )
    parser.add_argument(
        "--no-8bit-adam",
        action="store_true",
        help="Disable 8-bit AdamW and fallback to standard 32-bit AdamW",
    )
    parser.add_argument(
        "--gradient-checkpointing",
        action="store_true",
        help="Recompute activations in the backward pass (compact only): less memory, slower, "
        "same numbers; use it to fit a small VRAM budget",
    )
    parser.add_argument(
        "--profile-only",
        action="store_true",
        help="Measure forward memory; with LARIS_TRAINING_AUTHORIZED=1 runs real optimizer steps",
    )
    parser.add_argument(
        "--authorized",
        action="store_true",
        help="Assert explicit operator authorization to run training steps",
    )
    parser.add_argument(
        "--data-dir",
        type=str,
        default="data/processed",
        help="Directory containing processed Parquet datasets (default: data/processed)",
    )
    parser.add_argument(
        "--tokenizer-model",
        type=str,
        default=None,
        help="Path to the fitted SentencePiece .model file (required for training)",
    )
    parser.add_argument(
        "--vocab-size",
        type=int,
        default=None,
        help="Model vocabulary size; must equal the tokenizer's (default: 32000)",
    )
    parser.add_argument(
        "--normalize-input",
        action="store_true",
        help="Apply the tokenizer-fitting text normalisation before encoding, so training sees "
        "the same text as the fit corpus (recorded in the checkpoint provenance)",
    )
    parser.add_argument(
        "--training-config",
        type=str,
        default=None,
        help="YAML with learning rate, warmup, steps and loss weights "
        "(default: configs/language_encoder/<model-size>.yaml)",
    )
    parser.add_argument(
        "--steps",
        type=int,
        default=None,
        help="Total optimizer steps (default: training.max_steps from the training config)",
    )
    parser.add_argument("--learning-rate", type=float, default=None, help="Peak learning rate")
    parser.add_argument("--warmup-steps", type=int, default=None, help="LR warmup optimizer steps")
    parser.add_argument(
        "--dataset-sampling-ablation",
        action="store_true",
        help="Apply the YAML dataset exponents and per-dataset weights to the train loader",
    )
    parser.add_argument(
        "--retrieval-loss-weight", type=float, default=None,
        help="Weight of the query-to-passage contrastive loss (train QA auxiliary; the "
        "retrieval task when the YAML sets retrieval_task: true)",
    )
    parser.add_argument("--eval-interval", type=int, default=200, help="Validate every N steps")
    parser.add_argument(
        "--eval-batches", type=int, default=16, help="Validation batches per task (default: 16)"
    )
    parser.add_argument("--save-interval", type=int, default=500, help="Checkpoint every N steps")
    parser.add_argument(
        "--patience",
        type=int,
        default=5,
        help="Stop after N validations without improvement; 0 disables (default: 5)",
    )
    parser.add_argument(
        "--evaluate-after",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="After training, score the best checkpoint on the test split (default: on)",
    )
    parser.add_argument(
        "--evaluation-config",
        default="configs/evaluation/language_encoder.yaml",
        help="Acceptance thresholds used by --evaluate-after",
    )
    parser.add_argument("--seed", type=int, default=42, help="Random seed (default: 42)")
    parser.add_argument("--run-id", type=str, default=None, help="Run directory name")
    initialization = parser.add_mutually_exclusive_group()
    initialization.add_argument(
        "--resume",
        type=str,
        default=None,
        help="Checkpoint directory (e.g. <run>/last) to resume from",
    )
    initialization.add_argument(
        "--init-from",
        help="Load checkpoint weights with a fresh optimizer, scheduler and counters",
    )
    parser.add_argument(
        "--log-interval",
        type=int,
        default=10,
        help="Log every N optimizer steps (default: 10)",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default="artifacts/checkpoints/language_encoder",
        help="Directory to save model checkpoints and training manifests",
    )


def _resolve_hyperparameters(args: argparse.Namespace) -> TrainingConfig:
    """CLI flags override the training YAML, which overrides schema defaults."""
    config_path = Path(args.training_config or f"configs/language_encoder/{args.model_size}.yaml")
    training = load_config(config_path).training if config_path.is_file() else TrainingConfig()
    overrides = {
        "micro_batch_size": args.micro_batch_size,
        "gradient_accumulation_steps": args.grad_accum_steps,
        "learning_rate": args.learning_rate,
        "warmup_steps": args.warmup_steps,
        "max_steps": args.steps,
        "loss_lambda_retrieval": args.retrieval_loss_weight,
        "tasks_per_step": args.tasks_per_step,
    }
    merged = {**training.model_dump(), **{k: v for k, v in overrides.items() if v is not None}}
    merged["batch_size"] = max(
        merged["batch_size"], merged["micro_batch_size"] * merged["gradient_accumulation_steps"]
    )
    if not args.dataset_sampling_ablation:
        merged["dataset_sampling_exponents"] = {}
        merged["dataset_sampling_weights"] = {}
    elif not merged["dataset_sampling_exponents"]:
        raise ValueError("--dataset-sampling-ablation requires dataset exponents in the YAML")
    return TrainingConfig(**merged)


def same_model_config(recorded: Optional[dict], requested: dict) -> bool:
    """Model configs match; activation checkpointing only changes memory, not the weights."""
    if recorded is None:
        return False
    # the similarity head settings (T198) change a head, never the body weights
    skip = {
        "gradient_checkpointing", "similarity_head", "similarity_initial_scale",
        "similarity_initial_bias",
    }
    return {k: v for k, v in recorded.items() if k not in skip} == {
        k: v for k, v in requested.items() if k not in skip
    }


def _load_initial_weights(
    model: PyTorchTransformerEncoder,
    checkpoint: Path,
    tokenizer_sha256: str,
    config: LanguageEncoderConfig,
) -> str:
    """Verify initialization lineage and load weights independently of training state."""
    import torch

    manifest = read_manifest(checkpoint)
    provenance = manifest["provenance"]
    if provenance.get("tokenizer_sha256") != tokenizer_sha256:
        raise ValueError("initial checkpoint tokenizer differs from the supplied tokenizer")
    if not same_model_config(provenance.get("model_config"), asdict(config)):
        raise ValueError("initial checkpoint model config differs from the requested config")
    weights = checkpoint / MODEL_FILE
    digest = file_sha256(weights)
    if manifest.get("model_sha256") != digest:
        raise ValueError("initial checkpoint weights failed the manifest SHA-256 check")
    # a stage-1 checkpoint has no order head (T195): it keeps its fixed initial values
    load_model_weights(model, torch.load(weights, map_location="cpu", weights_only=True))
    return digest


def _run_memory_profile(
    args: argparse.Namespace,
    config: LanguageEncoderConfig,
    use_8bit_adam: bool,
    hyper: TrainingConfig,
) -> int:
    """Measures real GPU memory on real tokenized train batches (see memory_profile)."""
    if not TORCH_AVAILABLE:
        print("[ERROR] PyTorch is required: pip install -e '.[training]'")
        return 1
    import torch

    if not torch.cuda.is_available():
        print("[ERROR] No CUDA device: GPU memory cannot be measured, so feasibility is unknown.")
        return 1
    if not args.tokenizer_model or not Path(args.tokenizer_model).is_file():
        print("[ERROR] --tokenizer-model must point to the fitted SentencePiece .model file:")
        print("profiling runs on real tokenized batches. Fit it with `laris train tokenizer`.")
        return 1
    try:
        import sentencepiece as spm
    except ImportError:
        print("[ERROR] sentencepiece is required: pip install -e '.[training]'")
        return 1
    tokenizer: Any = spm.SentencePieceProcessor(model_file=args.tokenizer_model)
    if args.normalize_input:
        tokenizer = NormalizedSentencePiece(tokenizer)
    if tokenizer.get_piece_size() != config.vocab_size:
        print(f"[ERROR] Tokenizer vocab {tokenizer.get_piece_size()} != model {config.vocab_size}")
        return 1
    with_step = is_training_authorized()
    seed_everything(args.seed)
    loader = StreamingParquetMultiTaskDataLoader(
        data_dir=args.data_dir,
        tokenizer=tokenizer,
        vocab_size=config.vocab_size,
        seq_len=args.max_seq_len,
        batch_size=args.micro_batch_size,
        return_tensors="pt",
        seed=args.seed,
        split="train",
        require_real_data=True,
        dataset_sampling_exponents=hyper.dataset_sampling_exponents,
        dataset_sampling_weights=hyper.dataset_sampling_weights,
        alpha=hyper.task_sampling_alpha,
        task_sampling_floor=hyper.task_sampling_floor,
        include_retrieval_pairs=hyper.loss_lambda_retrieval > 0,
        include_retrieval_task=hyper.retrieval_task,
        retrieval_batch_size=hyper.retrieval_batch_size,
        retrieval_max_sequence_length=hyper.retrieval_max_sequence_length,
        mlm_pair_fraction=hyper.mlm_pair_fraction,
        order_task=hyper.order_task,
        order_class_shares=hyper.order_class_shares,
        label_balanced_tasks=hyper.label_balanced_tasks,
        include_contrastive_sim_task=hyper.contrastive_sim_task,
        contrastive_sim_batch_size=hyper.contrastive_sim_batch_size,
        contrastive_sim_max_sequence_length=hyper.contrastive_sim_max_sequence_length,
        contrastive_sim_row_shares=hyper.contrastive_sim_row_shares,
        contrastive_sim_row_weights=hyper.contrastive_sim_row_weights,
    )
    expected = (
        set(TASK_DATASET_DIRS)
        | ({"retrieval"} if hyper.retrieval_task else set())
        | ({CONTRASTIVE_SIM_TASK} if hyper.contrastive_sim_task else set())
    )
    missing = sorted(expected - set(loader.task_paths))
    if missing:
        print(f"[ERROR] No real train data for tasks {missing}. Run `laris data partition`.")
        return 1
    stage = "forward+backward with a real optimizer step" if with_step else "forward only"
    print(f"\n[PROFILING MODE] Real model, real train batches, {stage}.")
    print("The model is randomly initialised and discarded; nothing is saved.")
    ceiling_gb = _vram_ceiling_or_exit()
    if ceiling_gb is None:
        return 1
    model = PyTorchTransformerEncoder(config).to("cuda")
    trainer = LanguageEncoderTrainer(
        model=model,
        max_vram_ceiling_gb=ceiling_gb,
        config=config,
        dataloader=loader,
        use_8bit_adam=use_8bit_adam,
        learning_rate=hyper.learning_rate,
        grad_accum_steps=hyper.gradient_accumulation_steps,
        device="cuda",
        precision=args.precision,
        retrieval_loss_weight=hyper.loss_lambda_retrieval,
        retrieval_temperature=hyper.retrieval_temperature,
        order_loss_weight=hyper.loss_lambda_order,
        contrastive_sim_weight=hyper.loss_lambda_contrastive_sim,
        contrastive_sim_temperature=hyper.contrastive_sim_temperature,
        similarity_calibration_only=hyper.similarity_calibration_only,
    )
    if hyper.tasks_per_step > len(loader.task_paths):
        print(f"[ERROR] --tasks-per-step {hyper.tasks_per_step} exceeds the "
              f"{len(loader.task_paths)} active tasks.")
        return 1
    profile = profile_training_memory(
        trainer, loader, ceiling_gb, with_training_step=with_step,
        tasks_per_step=hyper.tasks_per_step,
    )
    print(f"GPU:                       {profile.gpu_name} ({profile.total_vram_gb:.2f} GB)")
    for t in profile.tasks:
        print(
            f"  {t.task_type:<11} peak {t.peak_allocated_gb:6.2f} GB, "
            f"loss {'finite' if t.loss_finite else 'NOT FINITE'}"
        )
    for g in profile.groups:
        print(
            f"  step of {'+'.join(g.tasks):<32} peak {g.peak_allocated_gb:6.2f} GB, "
            f"loss {'finite' if g.loss_finite else 'NOT FINITE'}"
        )
    if profile.error:
        print(f"[FAIL] {profile.error}")
        print("Lower --micro-batch-size (raise --grad-accum-steps to keep the effective batch).")
        return 1
    if profile.groups:
        worst = max(profile.groups, key=lambda g: g.peak_allocated_gb)
        print(f"Worst mixed step:          {'+'.join(worst.tasks)} at "
              f"{worst.peak_allocated_gb:.2f} GB ({hyper.tasks_per_step} tasks per step)")
        if profile.seconds_per_group_step is not None:
            print(f"Latency per mixed step:    {profile.seconds_per_group_step:.2f} s "
                  "(one micro-step with that many tasks)")
    print(f"Measured peak:             {profile.peak_gb:.2f} GB (limit {ceiling_gb:g} GB)")
    per_update = profile.seconds_per_micro_batch * hyper.gradient_accumulation_steps
    print(
        f"Latency:                   {profile.seconds_per_micro_batch:.2f} s/micro-batch incl. "
        f"real data loading, ~{per_update:.1f} s/optimizer step"
    )
    qa = loader.stats
    if qa["qa_total"]:
        print(
            f"QA labels in this sample:  {qa['qa_total']} rows, "
            f"{qa['qa_unanswerable']} unanswerable, "
            f"{qa['qa_answer_outside_window']} answer outside the {args.max_seq_len}-token window"
        )
    if not with_step:
        print("[PARTIAL] Forward only: training memory is NOT certified. Gradients, activations")
        print("for backward and optimizer state were not measured. Gradient computation counts as")
        print("training; the owner must set LARIS_TRAINING_AUTHORIZED=1 to measure them.")
        return 0 if profile.fits else 1
    if not profile.certified:
        print("[FAIL] Peak exceeds the limit or a loss was not finite.")
        print("Lower --micro-batch-size (raise --grad-accum-steps to keep the effective batch).")
        return 1
    print("[SUCCESS] Measured steady-state training peak on this GPU; the configuration fits.")
    return 0


def run(args: argparse.Namespace) -> int:
    try:
        hyper = _resolve_hyperparameters(args)
    except ValueError as exc:
        print(f"[ERROR] {exc}")
        return 1
    args.micro_batch_size = hyper.micro_batch_size
    args.grad_accum_steps = hyper.gradient_accumulation_steps

    if args.max_seq_len is None:
        args.max_seq_len = 1024 if args.model_size == "large" else 512

    # 1. Instantiate Configuration
    config: LanguageEncoderConfig
    vocab_override = {"vocab_size": args.vocab_size} if args.vocab_size else {}
    if args.model_size == "large":
        config = LargeLanguageEncoderConfig(
            **vocab_override,
            max_sequence_length=args.max_seq_len,
            precision=args.precision,
            gradient_checkpointing=True,
            similarity_head=hyper.similarity_head,
            similarity_initial_scale=hyper.similarity_initial_scale,
            similarity_initial_bias=hyper.similarity_initial_bias,
        )
    else:
        config = LanguageEncoderConfig(
            **vocab_override,
            max_sequence_length=args.max_seq_len,
            precision=args.precision,
            gradient_checkpointing=bool(getattr(args, "gradient_checkpointing", False)),
            similarity_head=hyper.similarity_head,
            similarity_initial_scale=hyper.similarity_initial_scale,
            similarity_initial_bias=hyper.similarity_initial_bias,
        )

    param_count = config.calculate_parameter_count(include_heads=True)
    use_8bit_adam = not args.no_8bit_adam

    print("=" * 65)
    print("LARIS Language Encoder Training Runner")
    print("=" * 65)
    print(f"Model Size:                {args.model_size.upper()}")
    print(f"Total Parameters:          {param_count:,} (~{param_count / 1e6:.2f}M)")
    print(f"Hidden Dimension (d):      {config.d_model}")
    print(f"Layers (L) / Heads (H):    {config.num_layers} / {config.num_heads}")
    print(f"Sequence Length:           {args.max_seq_len}")
    print(f"Micro-Batch / Accum:       {args.micro_batch_size} / {args.grad_accum_steps}")
    print(f"Effective Batch Size:      {args.micro_batch_size * args.grad_accum_steps}")
    print(f"8-bit AdamW Optimizer:     {'ENABLED' if use_8bit_adam else 'DISABLED'}")
    ckpt_enabled = 'ENABLED' if config.gradient_checkpointing else 'DISABLED'
    print(f"Activation Checkpointing:  {ckpt_enabled}")
    print("=" * 65)

    # 3. Handle Profiling Mode
    if args.profile_only:
        return _run_memory_profile(args, config, use_8bit_adam, hyper)

    # 4. Handle Training Mode
    if not args.authorized:
        print(
            "\n[ERROR] Training execution requires '--authorized' flag "
            "and environment authorization."
        )
        print("Run with '--profile-only' to inspect memory feasibility without training.")
        return 1

    try:
        assert_training_authorized("language encoder pretraining")
    except TrainingExecutionProhibitedError as exc:
        print(f"[ERROR] {exc}")
        return 1
    print("\n[TRAINING AUTHORIZED] Initializing language encoder training engine...")

    if not args.tokenizer_model or not Path(args.tokenizer_model).is_file():
        print(
            "[ERROR] --tokenizer-model must point to a fitted SentencePiece .model file. "
            "Fit one with `laris train tokenizer` first."
        )
        return 1
    try:
        import sentencepiece as spm
    except ImportError:
        print("[ERROR] sentencepiece is required: pip install -e '.[training]'")
        return 1
    tokenizer: Any = spm.SentencePieceProcessor(model_file=args.tokenizer_model)
    if args.normalize_input:
        tokenizer = NormalizedSentencePiece(tokenizer)
    if tokenizer.get_piece_size() != config.vocab_size:
        print(
            f"[ERROR] Tokenizer vocab {tokenizer.get_piece_size()} != "
            f"model vocab {config.vocab_size}"
        )
        return 1

    seed_everything(args.seed)
    common = dict(
        data_dir=args.data_dir,
        tokenizer=tokenizer,
        fallback_to_synthetic=False,
        require_real_data=True,
        vocab_size=config.vocab_size,
        seq_len=args.max_seq_len,
        batch_size=args.micro_batch_size,
        return_tensors="pt" if TORCH_AVAILABLE else "np",
        seed=args.seed,
    )
    # train split only; validation uses the held-out val split, never test
    # training and validation drop padding and group similar lengths (results are unchanged)
    common.update(trim_padding=True, length_pool_batches=8)
    loader = StreamingParquetMultiTaskDataLoader(
        split="train",
        dataset_sampling_exponents=hyper.dataset_sampling_exponents,
        dataset_sampling_weights=hyper.dataset_sampling_weights,
        alpha=hyper.task_sampling_alpha,
        task_sampling_floor=hyper.task_sampling_floor,
        include_retrieval_pairs=hyper.loss_lambda_retrieval > 0,
        include_retrieval_task=hyper.retrieval_task,
        retrieval_batch_size=hyper.retrieval_batch_size,
        retrieval_max_sequence_length=hyper.retrieval_max_sequence_length,
        mlm_pair_fraction=hyper.mlm_pair_fraction,
        order_task=hyper.order_task,
        order_class_shares=hyper.order_class_shares,
        label_balanced_tasks=hyper.label_balanced_tasks,
        include_contrastive_sim_task=hyper.contrastive_sim_task,
        contrastive_sim_batch_size=hyper.contrastive_sim_batch_size,
        contrastive_sim_max_sequence_length=hyper.contrastive_sim_max_sequence_length,
        contrastive_sim_row_shares=hyper.contrastive_sim_row_shares,
        contrastive_sim_row_weights=hyper.contrastive_sim_row_weights,
        **common,  # type: ignore[arg-type]
    )
    eval_loader = StreamingParquetMultiTaskDataLoader(
        split="val",
        include_retrieval_task=hyper.retrieval_task,
        retrieval_batch_size=hyper.retrieval_batch_size,
        retrieval_max_sequence_length=hyper.retrieval_max_sequence_length,
        **common,  # type: ignore[arg-type]
    )

    for task_name, shard_paths in sorted(loader.task_paths.items()):
        print(f"Data shards [train] {task_name:<11}: {len(shard_paths)}")
    # the contrastive similarity task is train-only (relation pairs have no validation split)
    missing_val = sorted(
        set(loader.task_paths) - set(eval_loader.task_paths) - {CONTRASTIVE_SIM_TASK}
    )
    if hyper.tasks_per_step > len(loader.task_paths):
        print(f"[ERROR] tasks_per_step {hyper.tasks_per_step} exceeds the "
              f"{len(loader.task_paths)} active tasks {sorted(loader.task_paths)}.")
        return 1
    if missing_val:
        print(f"[ERROR] Tasks without validation shards: {missing_val}.")
        print("Run `laris data partition` first.")
        return 1

    if not TORCH_AVAILABLE:
        print("[ERROR] PyTorch is required for training: pip install -e '.[training]'")
        return 1
    import torch

    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"Target Compute Device:     {device.upper()}")
    run_id = args.run_id or datetime.now(timezone.utc).strftime("run-%Y%m%dT%H%M%SZ")
    run_dir = Path(args.output_dir) / run_id
    if args.init_from and run_dir.exists():
        print(f"[ERROR] Choose an unused run directory for --init-from: {run_dir}")
        return 1
    tokenizer_digest = file_sha256(Path(args.tokenizer_model))
    model = PyTorchTransformerEncoder(config)
    initialization_sha256 = None
    if args.init_from:
        try:
            initialization_sha256 = _load_initial_weights(
                model, Path(args.init_from), tokenizer_digest, config
            )
        except (OSError, ValueError, KeyError, RuntimeError) as exc:
            print(f"[ERROR] Cannot initialize from {args.init_from}: {exc}")
            return 1
    model.to(device)
    ceiling_gb = _vram_ceiling_or_exit()
    if ceiling_gb is None:
        return 1
    if ceiling_gb != DEFAULT_CEILING_GIB:
        print(f"VRAM ceiling:              {ceiling_gb:g} GB (LARIS_VRAM_CEILING_GB, ADR-023)")

    trainer = LanguageEncoderTrainer(
        model=model,
        max_vram_ceiling_gb=ceiling_gb,
        config=config,
        dataloader=loader,
        use_8bit_adam=use_8bit_adam,
        learning_rate=hyper.learning_rate,
        grad_accum_steps=args.grad_accum_steps,
        device=device,
        precision=args.precision,
        warmup_steps=hyper.warmup_steps,
        total_optimizer_steps=hyper.max_steps,
        retrieval_loss_weight=hyper.loss_lambda_retrieval,
        retrieval_temperature=hyper.retrieval_temperature,
        order_loss_weight=hyper.loss_lambda_order,
        contrastive_sim_weight=hyper.loss_lambda_contrastive_sim,
        contrastive_sim_temperature=hyper.contrastive_sim_temperature,
        similarity_calibration_only=hyper.similarity_calibration_only,
    )
    trainer.loss_calculator = MultiTaskLossCalculator(
        MultiTaskLossWeights(
            lambda_mlm=hyper.loss_lambda_mlm,
            lambda_nli=hyper.loss_lambda_nli,
            lambda_para=hyper.loss_lambda_para,
            lambda_sim=hyper.loss_lambda_sim,
            lambda_qa=hyper.loss_lambda_qa,
        )
    )

    dataset_manifest = Path(args.data_dir) / "task_splits_manifest.json"
    provenance = {
        "run_id": run_id,
        "git_commit": current_git_commit(),
        "seed": args.seed,
        "model_size": args.model_size,
        "model_config": config,
        "training": hyper.model_dump(),
        "precision": args.precision,
        "use_8bit_adam": use_8bit_adam,
        "vram_ceiling_gb": ceiling_gb,
        "gpu_name": torch.cuda.get_device_name(0) if torch.cuda.is_available() else None,
        "tokenizer_model": str(args.tokenizer_model),
        "tokenizer_sha256": tokenizer_digest,
        "text_normalization": NORMALIZATION_ID if args.normalize_input else None,
        "initial_checkpoint": args.init_from,
        "initial_model_sha256": initialization_sha256,
        "dataset_manifest_sha256": (
            file_sha256(dataset_manifest) if dataset_manifest.is_file() else None
        ),
    }
    print(f"Run directory:             {run_dir}")
    mixed = f", {hyper.tasks_per_step} tasks per micro-step" if hyper.tasks_per_step > 1 else ""
    print(f"Training for {hyper.max_steps} optimizer steps (effective batch "
          f"{args.micro_batch_size * args.grad_accum_steps} per task{mixed})...")
    result = run_training(
        trainer,
        loader,
        TrainingRunConfig(
            total_optimizer_steps=hyper.max_steps,
            eval_interval=args.eval_interval,
            eval_batches_per_task=args.eval_batches,
            save_interval=args.save_interval,
            patience=args.patience,
            log_interval=args.log_interval,
            tasks_per_step=hyper.tasks_per_step,
        ),
        run_dir,
        eval_loader=eval_loader,
        provenance=provenance,
        resume_from=Path(args.resume) if args.resume else None,
        progress=TrainingProgress(
            hyper.max_steps,
            grad_accum_steps=hyper.gradient_accumulation_steps,
            log_interval=args.log_interval,
        ),
    )
    status = "stopped early" if result.stopped_early else "completed"
    print(f"\n[SUCCESS] Training {status} at optimizer step {result.optimizer_steps}.")
    if result.best_dir is not None:
        print(f"Best checkpoint: {result.best_dir} (val mean loss {result.best_metric:.4f} "
              f"at step {result.best_step})")
    print(f"Last checkpoint: {result.last_dir}")

    if not args.evaluate_after:
        return 0
    checkpoint = result.best_dir or result.last_dir
    assert checkpoint is not None
    print(f"\n[EVALUATION] Scoring {checkpoint} on the test split...")
    try:
        code, _ = evaluate_checkpoint(
            Path(checkpoint),
            Path(args.data_dir),
            "test",
            Path(args.evaluation_config),
            output=run_dir / "evaluation-test.json",
            tokenizer_model=Path(args.tokenizer_model),
            batch_size=args.micro_batch_size,
            seed=args.seed,
            device=device,
        )
    except (FileNotFoundError, ValueError, RuntimeError) as exc:
        print(f"[ERROR] evaluation could not run: {exc}")
        return EXIT_USAGE
    return code
