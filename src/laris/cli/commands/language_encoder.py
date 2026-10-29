"""`laris train language-encoder`: multi-task language encoder training and bounded profiling.

Supports compact and large model sizes, 8-bit AdamW, FlashAttention SDPA, activation
checkpointing, a --profile-only mode without weight updates, and the strict authorization gate."""

import argparse
import random
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from laris.config.loader import load_config
from laris.config.schemas import TrainingConfig
from laris.core.authorization import (
    assert_training_authorized,
    is_training_authorized,
)
from laris.core.errors import TrainingExecutionProhibitedError
from laris.language.encoder.transformer import (
    TORCH_AVAILABLE,
    LanguageEncoderConfig,
    LargeLanguageEncoderConfig,
    PyTorchTransformerEncoder,
)
from laris.language.evaluation.runner import EXIT_USAGE, evaluate_checkpoint
from laris.language.training.checkpoint import current_git_commit, file_sha256
from laris.language.training.dataloader import (
    TASK_DATASET_DIRS,
    StreamingParquetMultiTaskDataLoader,
)
from laris.language.training.loop import TrainingRunConfig, run_training
from laris.language.training.memory_profile import profile_training_memory
from laris.language.training.trainer import (
    LanguageEncoderTrainer,
    MultiTaskLossCalculator,
    MultiTaskLossWeights,
)

MAX_VRAM_GB = 14.5


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
        "--max-seq-len",
        type=int,
        default=1024,
        help="Maximum sequence length tokens (default: 1024)",
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
        "--profile-only",
        action="store_true",
        help="Execute bounded non-training memory and latency profiling without weight updates",
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
    parser.add_argument("--eval-interval", type=int, default=200, help="Validate every N steps")
    parser.add_argument(
        "--eval-batches", type=int, default=8, help="Validation batches per task (default: 8)"
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
    parser.add_argument(
        "--resume",
        type=str,
        default=None,
        help="Checkpoint directory (e.g. <run>/last) to resume from",
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
    }
    merged = {**training.model_dump(), **{k: v for k, v in overrides.items() if v is not None}}
    merged["batch_size"] = max(
        merged["batch_size"], merged["micro_batch_size"] * merged["gradient_accumulation_steps"]
    )
    return TrainingConfig(**merged)


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
    tokenizer = spm.SentencePieceProcessor(model_file=args.tokenizer_model)
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
    )
    missing = sorted(set(TASK_DATASET_DIRS) - set(loader.task_paths))
    if missing:
        print(f"[ERROR] No real train data for tasks {missing}. Run `laris data partition`.")
        return 1
    stage = "forward+backward with a real optimizer step" if with_step else "forward only"
    print(f"\n[PROFILING MODE] Real model, real train batches, {stage}.")
    print("The model is randomly initialised and discarded; nothing is saved.")
    model = PyTorchTransformerEncoder(config).to("cuda")
    trainer = LanguageEncoderTrainer(
        model=model,
        config=config,
        dataloader=loader,
        use_8bit_adam=use_8bit_adam,
        learning_rate=hyper.learning_rate,
        grad_accum_steps=hyper.gradient_accumulation_steps,
        device="cuda",
        precision=args.precision,
    )
    profile = profile_training_memory(trainer, loader, MAX_VRAM_GB, with_training_step=with_step)
    print(f"GPU:                       {profile.gpu_name} ({profile.total_vram_gb:.2f} GB)")
    for t in profile.tasks:
        print(
            f"  {t.task_type:<11} peak {t.peak_allocated_gb:6.2f} GB, "
            f"loss {'finite' if t.loss_finite else 'NOT FINITE'}"
        )
    if profile.error:
        print(f"[FAIL] {profile.error}")
        print("Lower --micro-batch-size (raise --grad-accum-steps to keep the effective batch).")
        return 1
    print(f"Measured peak:             {profile.peak_gb:.2f} GB (limit {MAX_VRAM_GB} GB)")
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
    hyper = _resolve_hyperparameters(args)
    args.micro_batch_size = hyper.micro_batch_size
    args.grad_accum_steps = hyper.gradient_accumulation_steps

    # 1. Instantiate Configuration
    config: LanguageEncoderConfig
    if args.model_size == "large":
        config = LargeLanguageEncoderConfig(
            max_sequence_length=args.max_seq_len,
            precision=args.precision,
            gradient_checkpointing=True,
        )
    else:
        config = LanguageEncoderConfig(
            max_sequence_length=min(args.max_seq_len, 512),
            precision=args.precision,
            gradient_checkpointing=False,
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
    tokenizer = spm.SentencePieceProcessor(model_file=args.tokenizer_model)
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
    loader = StreamingParquetMultiTaskDataLoader(split="train", **common)  # type: ignore[arg-type]
    eval_loader = StreamingParquetMultiTaskDataLoader(split="val", **common)  # type: ignore[arg-type]

    for task_name, shard_paths in sorted(loader.task_paths.items()):
        print(f"Data shards [train] {task_name:<11}: {len(shard_paths)}")
    missing_val = sorted(set(loader.task_paths) - set(eval_loader.task_paths))
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
    model = PyTorchTransformerEncoder(config).to(device)

    trainer = LanguageEncoderTrainer(
        model=model,
        config=config,
        dataloader=loader,
        use_8bit_adam=use_8bit_adam,
        learning_rate=hyper.learning_rate,
        grad_accum_steps=args.grad_accum_steps,
        device=device,
        precision=args.precision,
        warmup_steps=hyper.warmup_steps,
        total_optimizer_steps=hyper.max_steps,
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

    run_id = args.run_id or datetime.now(timezone.utc).strftime("run-%Y%m%dT%H%M%SZ")
    run_dir = Path(args.output_dir) / run_id
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
        "tokenizer_model": str(args.tokenizer_model),
        "tokenizer_sha256": file_sha256(Path(args.tokenizer_model)),
        "dataset_manifest_sha256": (
            file_sha256(dataset_manifest) if dataset_manifest.is_file() else None
        ),
    }
    print(f"Run directory:             {run_dir}")
    print(f"Training for {hyper.max_steps} optimizer steps (effective batch "
          f"{args.micro_batch_size * args.grad_accum_steps})...")
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
        ),
        run_dir,
        eval_loader=eval_loader,
        provenance=provenance,
        resume_from=Path(args.resume) if args.resume else None,
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
