"""Multi-task language encoder trainer and composite loss formulation.

Adheres to:
- DOC-SPEC-TRAIN-001 Section 4.1 & 4.2
- Composite loss formula:
    L_total = 0.35 * L_MLM + 0.25 * L_NLI + 0.15 * L_PARA + 0.10 * L_SIM + 0.15 * L_QA
- Hardware optimization: 8-bit AdamW, mixed precision BF16, and gradient accumulation
- Mandatory stop condition: Strict authorization gate (assert_training_authorized)
"""

import math
import warnings
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from laris.research.language.training.objectives import (
    contrastive_retrieval_loss,
    contrastive_similarity_loss,
    sentence_order_loss,
)
from laris.shared.core.authorization import (
    assert_training_authorized,
)

try:
    import torch
    import torch.nn as nn
    import torch.nn.functional as F

    TORCH_AVAILABLE = True
except ImportError:
    TORCH_AVAILABLE = False


@dataclass(frozen=True)
class MultiTaskLossWeights:
    """Canonical mixture weights for multi-task learning curriculum."""

    lambda_mlm: float = 0.35
    lambda_nli: float = 0.25
    lambda_para: float = 0.15
    lambda_sim: float = 0.10
    lambda_qa: float = 0.15

    def __post_init__(self) -> None:
        total = (
            self.lambda_mlm
            + self.lambda_nli
            + self.lambda_para
            + self.lambda_sim
            + self.lambda_qa
        )
        if not (0.999 <= total <= 1.001):
            raise ValueError(f"Loss weights must sum to 1.0, got {total}")


@dataclass
class TrainingMetricsSnapshot:
    """Telemetry and loss accounting for a single training or validation step."""

    step: int
    task_type: str
    loss_value: float
    effective_batch_size: int
    peak_vram_gb: Optional[float] = None
    optimizer_step: int = 0
    learning_rate: Optional[float] = None
    grad_norm: Optional[float] = None
    # Unweighted sentence-order cross-entropy of this micro-batch (T195), when it had one
    order_loss: Optional[float] = None
    # Weighted loss of every task of this micro-step (T201); `loss_value` is their sum and
    # `task_type` joins the names with "+" when a mixed step carries more than one
    task_losses: Optional[Dict[str, float]] = None


class MultiTaskLossCalculator:
    """Calculates individual task losses and weighted multi-task composite loss."""

    def __init__(self, weights: Optional[MultiTaskLossWeights] = None) -> None:
        self.weights = weights or MultiTaskLossWeights()

    def compute_loss_numpy(
        self,
        task_type: str,
        predictions: Dict[str, np.ndarray],
        labels: Dict[str, np.ndarray],
    ) -> float:
        """Pure NumPy mathematical formulation of task loss for CPU test verification."""
        if task_type == "mlm":
            # Masked language modeling cross entropy
            logits = predictions["mlm_logits"]  # (b, s, v)
            targets = labels["mlm_labels"]  # (b, s)
            mask = targets != -100
            if not np.any(mask):
                return 0.0
            # Numerically stable log-softmax
            flat_logits = logits[mask]
            flat_targets = targets[mask]
            max_l = np.max(flat_logits, axis=-1, keepdims=True)
            exp_l = np.exp(flat_logits - max_l)
            probs = exp_l / np.sum(exp_l, axis=-1, keepdims=True)
            chosen_probs = probs[np.arange(len(flat_targets)), flat_targets]
            loss = -np.mean(np.log(np.maximum(chosen_probs, 1e-12)))
            return float(loss * self.weights.lambda_mlm)

        elif task_type == "nli":
            # 3-way cross entropy
            logits = predictions["nli_logits"]  # (b, 3)
            targets = labels["nli_labels"]  # (b,)
            max_l = np.max(logits, axis=-1, keepdims=True)
            exp_l = np.exp(logits - max_l)
            probs = exp_l / np.sum(exp_l, axis=-1, keepdims=True)
            chosen_probs = probs[np.arange(len(targets)), targets]
            loss = -np.mean(np.log(np.maximum(chosen_probs, 1e-12)))
            return float(loss * self.weights.lambda_nli)

        elif task_type == "paraphrase":
            # Binary cross entropy
            probs = predictions["paraphrase_prob"].squeeze(-1)  # (b,)
            targets = labels["para_labels"].astype(np.float32)  # (b,)
            probs = np.clip(probs, 1e-7, 1.0 - 1e-7)
            bce = -np.mean(targets * np.log(probs) + (1.0 - targets) * np.log(1.0 - probs))
            return float(bce * self.weights.lambda_para)

        elif task_type == "similarity":
            # Mean Squared Error on [0, 1] scores
            preds = predictions["similarity_score"].squeeze(-1)  # (b,)
            targets = labels["sim_labels"].astype(np.float32)  # (b,)
            mse = float(np.mean((preds - targets) ** 2))
            return float(mse * self.weights.lambda_sim)

        elif task_type == "qa":
            # Span extraction start/end cross entropy
            qa_logits = predictions["qa_logits"]  # (b, s, 2)
            start_logits = qa_logits[:, :, 0]
            end_logits = qa_logits[:, :, 1]
            start_targets = labels["qa_start_positions"]
            end_targets = labels["qa_end_positions"]

            def _ce(logits_arr: np.ndarray, t: np.ndarray) -> float:
                max_l = np.max(logits_arr, axis=-1, keepdims=True)
                exp_l = np.exp(logits_arr - max_l)
                probs = exp_l / np.sum(exp_l, axis=-1, keepdims=True)
                chosen = probs[np.arange(len(t)), t]
                return float(-np.mean(np.log(np.maximum(chosen, 1e-12))))

            loss = (_ce(start_logits, start_targets) + _ce(end_logits, end_targets)) / 2.0
            return float(loss * self.weights.lambda_qa)

        else:
            raise ValueError(f"Unknown task_type: {task_type}")


class LanguageEncoderTrainer:
    """Language encoder trainer with 14GB VRAM optimization and authorization barrier."""

    def __init__(
        self,
        model: Any,
        config: Any,
        dataloader: Any,
        optimizer: Optional[Any] = None,
        scheduler: Optional[Any] = None,
        use_8bit_adam: bool = True,
        learning_rate: float = 1e-4,
        weight_decay: float = 0.01,
        grad_accum_steps: int = 4,
        max_grad_norm: float = 1.0,
        max_vram_ceiling_gb: float = 14.5,
        device: Optional[str] = None,
        precision: str = "fp32",
        warmup_steps: int = 0,
        total_optimizer_steps: Optional[int] = None,
        min_lr_ratio: float = 0.1,
        retrieval_loss_weight: float = 0.0,
        retrieval_temperature: float = 0.07,
        order_loss_weight: float = 0.0,
        contrastive_sim_weight: float = 0.0,
        contrastive_sim_temperature: float = 0.05,
        similarity_calibration_only: bool = False,
    ) -> None:
        if precision not in ("fp32", "bf16", "fp16"):
            raise ValueError(f"precision must be fp32, bf16 or fp16, got '{precision}'")
        self.precision = precision
        self.optimizer_steps = 0
        self.skipped_steps = 0
        self.model = model
        self.config = config
        self.dataloader = dataloader
        self.use_8bit_adam = use_8bit_adam
        self.learning_rate = learning_rate
        self.weight_decay = weight_decay
        self.grad_accum_steps = max(1, grad_accum_steps)
        self.max_grad_norm = max_grad_norm
        self.max_vram_ceiling_gb = max_vram_ceiling_gb
        self.loss_calculator = MultiTaskLossCalculator()
        self.retrieval_loss_weight = retrieval_loss_weight
        self.retrieval_temperature = retrieval_temperature
        if not order_loss_weight >= 0.0 or order_loss_weight == float("inf"):
            raise ValueError("order_loss_weight must be finite and non-negative")
        # Sentence-order loss (T195): added to the MLM loss of batches with order labels
        self.order_loss_weight = order_loss_weight
        self._last_order_loss: Optional[float] = None
        if not math.isfinite(contrastive_sim_weight) or contrastive_sim_weight < 0:
            raise ValueError("contrastive_sim_weight must be finite and non-negative")
        if not math.isfinite(contrastive_sim_temperature) or contrastive_sim_temperature <= 0:
            raise ValueError("contrastive_sim_temperature must be finite and positive")
        # Contrastive similarity (T199): in-batch InfoNCE of the bi-encoder embeddings
        self.contrastive_sim_weight = contrastive_sim_weight
        self.contrastive_sim_temperature = contrastive_sim_temperature
        # Graded STS pairs then reach only the head's scale and bias, not the body
        self.similarity_calibration_only = similarity_calibration_only
        self.step_history: List[TrainingMetricsSnapshot] = []
        self._accum_counter: int = 0

        # Device determination
        if device is not None:
            self.device = device
        elif TORCH_AVAILABLE and torch.cuda.is_available():
            self.device = "cuda"
        else:
            self.device = "cpu"

        if TORCH_AVAILABLE and isinstance(self.model, nn.Module):
            self.model.to(self.device)

        # Optimizer initialization
        if optimizer is not None:
            self.optimizer = optimizer
        elif TORCH_AVAILABLE and isinstance(self.model, nn.Module):
            if self.use_8bit_adam:
                try:
                    import bitsandbytes as bnb  # type: ignore[import-not-found]

                    self.optimizer = bnb.optim.AdamW8bit(
                        self._parameter_groups(), lr=learning_rate, weight_decay=weight_decay
                    )
                except Exception as exc:
                    warnings.warn(
                        f"8-bit AdamW unavailable ({exc}); falling back to torch AdamW. "
                        "Optimizer memory is ~4x higher than the 8-bit estimate.",
                        RuntimeWarning,
                        stacklevel=2,
                    )
                    self.optimizer = torch.optim.AdamW(
                        self._parameter_groups(), lr=learning_rate, weight_decay=weight_decay
                    )
            else:
                self.optimizer = torch.optim.AdamW(
                    self._parameter_groups(), lr=learning_rate, weight_decay=weight_decay
                )
        else:
            self.optimizer = None

        if scheduler is None and self.optimizer is not None and total_optimizer_steps:
            from laris.research.language.training.schedule import build_warmup_cosine_scheduler

            scheduler = build_warmup_cosine_scheduler(
                self.optimizer, warmup_steps, total_optimizer_steps, min_lr_ratio
            )
        self.scheduler = scheduler

        self.scaler: Any = None
        if TORCH_AVAILABLE and precision == "fp16" and str(self.device).startswith("cuda"):
            self.scaler = torch.amp.GradScaler("cuda")

        if optimizer is not None and TORCH_AVAILABLE and isinstance(self.model, nn.Module):
            model_param_ids = {id(prm) for prm in self.model.parameters()}
            optimizer_param_ids = {
                id(prm) for group in optimizer.param_groups for prm in group["params"]
            }
            if not optimizer_param_ids <= model_param_ids:
                raise ValueError(
                    "Injected optimizer is not bound to the model's parameters; construct it "
                    "after the model has been moved to its target device."
                )

    def _parameter_groups(self) -> List[Dict[str, Any]]:
        """Weight decay on weight matrices only; norm gains, biases and embeddings stay free."""
        decay: List[Any] = []
        no_decay: List[Any] = []
        for name, prm in self.model.named_parameters():
            if not prm.requires_grad:
                continue
            exempt = prm.ndim < 2 or name.startswith("token_embeddings")
            (no_decay if exempt else decay).append(prm)
        groups = [{"params": decay, "weight_decay": self.weight_decay}]
        if no_decay:
            groups.append({"params": no_decay, "weight_decay": 0.0})
        return groups

    def _autocast(self) -> Any:
        """Autocast context for the configured precision (no-op for fp32)."""
        import contextlib

        if not TORCH_AVAILABLE or self.precision == "fp32":
            return contextlib.nullcontext()
        device_type = "cuda" if str(self.device).startswith("cuda") else "cpu"
        if self.precision == "fp16" and device_type == "cpu":
            return contextlib.nullcontext()
        dtype = torch.bfloat16 if self.precision == "bf16" else torch.float16
        return torch.autocast(device_type=device_type, dtype=dtype)

    def _forward(
        self,
        task_type: str,
        token_ids: Any,
        attention_mask: Any,
        labels: Dict[str, Any],
        training_pass: bool = False,
    ) -> Dict[str, Any]:
        """Runs the model computing only the head `task_type` needs (MLM: masked positions)."""
        import inspect

        if task_type == "retrieval":
            # Dense-retrieval task (T178): only the embedding path runs; labels carry both sides.
            if self.retrieval_loss_weight <= 0:
                raise ValueError(
                    "The retrieval task needs retrieval_loss_weight (loss_lambda_retrieval) > 0"
                )
            return {"retrieval_loss": self._retrieval_loss(labels, training_pass)}
        if task_type == "contrastive_sim":
            if self.contrastive_sim_weight <= 0:
                raise ValueError(
                    "The contrastive_sim task needs contrastive_sim_weight "
                    "(loss_lambda_contrastive_sim) > 0"
                )
            return {"contrastive_sim_loss": self._contrastive_sim_loss(labels, training_pass)}
        if task_type == "similarity" and self._bi_encoder_similarity():
            # two single-sentence passes; the pair input of the batch is not used (T198)
            sides = [
                torch.as_tensor(labels[f"sim_{side}_{kind}"], device=self.device)
                for side in ("a", "b")
                for kind in ("ids", "mask")
            ]
            similarity: Dict[str, Any] = self.model.bi_encoder_similarity(
                *sides,
                training_pass=training_pass,
                detach_embeddings=self.similarity_calibration_only,
            )
            return similarity
        kwargs: Dict[str, Any] = {"attention_mask": attention_mask}
        if training_pass:
            kwargs["training_pass"] = True
        parameters = inspect.signature(self.model.forward).parameters
        if "task" in parameters:
            kwargs["task"] = task_type
            if task_type == "mlm":
                targets = torch.as_tensor(labels["mlm_labels"]).to(self.device)
                kwargs["mlm_positions"] = targets != -100
        if self._uses_order(task_type, labels):
            if "with_order" not in parameters:
                raise ValueError("The sentence-order loss needs a model with an order head")
            kwargs["with_order"] = True
        outputs: Dict[str, Any] = self.model(token_ids, **kwargs)
        if (
            training_pass and task_type == "qa" and self.retrieval_loss_weight > 0
            and "retrieval_positives" in labels
        ):
            outputs["retrieval_loss"] = self._retrieval_loss(labels, True)
        return outputs

    def _bi_encoder_similarity(self) -> bool:
        return getattr(getattr(self.model, "config", None), "similarity_head", "cross") == (
            "bi_encoder"
        )

    def _contrastive_sim_loss(self, labels: Dict[str, Any], training_pass: bool) -> Any:
        """In-batch InfoNCE: anchors against their positives (a second dropout pass for SimCSE
        rows) and the hard negatives; the dropout passes are independent (T199)."""
        import inspect

        if training_pass and not self.model.training:
            # SimCSE positives differ from their anchors only by dropout masks; a module in
            # eval mode would make every pair identical and the loss meaningless
            raise ValueError("the contrastive_sim task needs the model in training mode")
        if "stochastic" not in inspect.signature(self.model.forward).parameters:
            raise ValueError("the contrastive_sim task needs a model with a dropout pass")

        def embed(name: str) -> Any:
            return self.model(
                torch.as_tensor(labels[f"contrastive_sim_{name}_ids"], device=self.device),
                attention_mask=torch.as_tensor(
                    labels[f"contrastive_sim_{name}_mask"], device=self.device
                ),
                task="embedding",
                training_pass=training_pass,
                stochastic=True,
            )["cls_embedding"]

        candidates = [embed("positive")]
        if "contrastive_sim_negative_ids" in labels:
            candidates.append(embed("negative"))
        return contrastive_similarity_loss(
            embed("anchor"),
            torch.cat(candidates, dim=0),
            torch.as_tensor(labels["contrastive_sim_known_positives"], device=self.device),
            torch.as_tensor(labels["contrastive_sim_weights"], device=self.device),
            self.contrastive_sim_temperature,
        )

    def _uses_order(self, task_type: str, labels: Dict[str, Any]) -> bool:
        """Order labels ride on MLM batches (T194); the loss runs only with a positive weight."""
        return task_type == "mlm" and self.order_loss_weight > 0 and "order_labels" in labels

    def _retrieval_loss(self, labels: Dict[str, Any], training_pass: bool) -> Any:
        """In-batch InfoNCE of query and passage embeddings (known positives are masked)."""
        embeddings = [
            self.model(
                torch.as_tensor(labels[f"retrieval_{kind}_ids"], device=self.device),
                attention_mask=torch.as_tensor(
                    labels[f"retrieval_{kind}_mask"], device=self.device
                ),
                task="embedding",
                training_pass=training_pass,
            )["cls_embedding"]
            for kind in ("query", "passage")
        ]
        return contrastive_retrieval_loss(
            embeddings[0],
            embeddings[1],
            torch.as_tensor(labels["retrieval_positives"], device=self.device),
            self.retrieval_temperature,
        )

    def _to_device(self, batch: Any) -> Any:
        token_ids = batch.token_ids
        if not isinstance(token_ids, torch.Tensor):
            token_ids = torch.as_tensor(token_ids, dtype=torch.long, device=self.device)
        else:
            token_ids = token_ids.to(self.device)
        attention_mask = getattr(batch, "attention_mask", None)
        if attention_mask is not None:
            if not isinstance(attention_mask, torch.Tensor):
                attention_mask = torch.as_tensor(
                    attention_mask, dtype=torch.long, device=self.device
                )
            else:
                attention_mask = attention_mask.to(self.device)
        return token_ids, attention_mask

    def counters(self) -> Dict[str, Any]:
        """Progress counters persisted in checkpoints."""
        return {
            "micro_steps": len(self.step_history),
            "optimizer_steps": self.optimizer_steps,
            "skipped_steps": self.skipped_steps,
            "accum_counter": self._accum_counter,
        }

    def load_counters(self, counters: Dict[str, Any]) -> None:
        self.optimizer_steps = int(counters.get("optimizer_steps", 0))
        self.skipped_steps = int(counters.get("skipped_steps", 0))
        self._accum_counter = int(counters.get("accum_counter", 0))

    def evaluate(
        self,
        eval_loader: Any,
        batches_per_task: int = 8,
        tasks: Optional[List[str]] = None,
    ) -> Dict[str, float]:
        """Mean loss per task (and `mean`) on a held-out loader; weights are not modified.

        Uses the inference path (no gradients), so it needs no training authorization.
        """
        if not (TORCH_AVAILABLE and isinstance(self.model, nn.Module)):
            raise RuntimeError("evaluate requires a PyTorch model")
        if hasattr(eval_loader, "reset"):
            eval_loader.reset()  # every evaluation scores the same records
        was_training = self.model.training
        self.model.eval()
        task_names = tasks or sorted(eval_loader.task_paths)
        results: Dict[str, float] = {}
        try:
            with torch.no_grad():
                for task in task_names:
                    losses = []
                    for _ in range(batches_per_task):
                        batch = eval_loader.generate_batch(task_type=task)
                        token_ids, attention_mask = self._to_device(batch)
                        with self._autocast():
                            outputs = self._forward(task, token_ids, attention_mask, batch.labels)
                            loss = self._compute_torch_loss(
                                task, outputs, batch.labels, attention_mask
                            )
                        losses.append(float(loss.float().item()))
                    results[task] = float(np.mean(losses))
        finally:
            self.model.train(was_training)
        results["mean"] = float(np.mean([results[t] for t in task_names]))
        return results

    def _compute_torch_loss(
        self,
        task_type: str,
        outputs: Dict[str, Any],
        labels: Dict[str, Any],
        attention_mask: Optional[Any] = None,
    ) -> Any:
        """Computes loss tensor using PyTorch autograd loss functions.

        `attention_mask` keeps padded positions out of the QA span softmax.
        """
        weights = self.loss_calculator.weights
        if task_type == "mlm":
            logits = outputs["mlm_logits"]
            targets = labels["mlm_labels"]
            if not isinstance(targets, torch.Tensor):
                targets = torch.as_tensor(targets, dtype=torch.long, device=self.device)
            else:
                targets = targets.to(self.device)
            vocab_size = logits.size(-1)
            if not bool((targets != -100).any()):
                mlm_loss = logits.sum() * 0.0  # nothing masked: zero, not a NaN mean over nothing
            elif logits.dim() == 2:  # logits already restricted to the masked positions
                mlm_loss = F.cross_entropy(logits, targets[targets != -100]) * weights.lambda_mlm
            else:
                mlm_loss = F.cross_entropy(
                    logits.view(-1, vocab_size), targets.view(-1), ignore_index=-100
                ) * weights.lambda_mlm
            self._last_order_loss = None
            if self._uses_order(task_type, labels) and "order_logits" in outputs:
                order = sentence_order_loss(
                    outputs["order_logits"], torch.as_tensor(labels["order_labels"])
                )
                self._last_order_loss = float(order.detach().float().item())
                mlm_loss = mlm_loss + self.order_loss_weight * order
            return mlm_loss

        elif task_type == "nli":
            logits = outputs["nli_logits"]
            targets = labels["nli_labels"]
            if not isinstance(targets, torch.Tensor):
                targets = torch.as_tensor(targets, dtype=torch.long, device=self.device)
            else:
                targets = targets.to(self.device)
            ce = F.cross_entropy(logits, targets)
            return ce * weights.lambda_nli

        elif task_type == "paraphrase":
            probs = outputs["paraphrase_prob"].squeeze(-1)
            targets = labels["para_labels"]
            if not isinstance(targets, torch.Tensor):
                targets = torch.as_tensor(targets, dtype=torch.float32, device=self.device)
            else:
                targets = targets.to(self.device).float()
            # binary_cross_entropy raises under CUDA autocast; compute it in fp32 outside it
            with torch.autocast(device_type=probs.device.type, enabled=False):
                probs = torch.clamp(probs.float(), 1e-7, 1.0 - 1e-7)
                bce = F.binary_cross_entropy(probs, targets)
            return bce * weights.lambda_para

        elif task_type == "similarity":
            preds = outputs["similarity_score"].squeeze(-1)
            targets = labels["sim_labels"]
            if not isinstance(targets, torch.Tensor):
                targets = torch.as_tensor(targets, dtype=torch.float32, device=self.device)
            else:
                targets = targets.to(self.device).float()
            mse = F.mse_loss(preds, targets)
            return mse * weights.lambda_sim

        elif task_type == "qa":
            qa_logits = outputs["qa_logits"]
            start_logits = qa_logits[:, :, 0].float()
            end_logits = qa_logits[:, :, 1].float()
            if attention_mask is not None:
                keep = attention_mask.to(qa_logits.device) == 1
                start_logits = start_logits.masked_fill(~keep, -1e4)
                end_logits = end_logits.masked_fill(~keep, -1e4)
            start_targets = labels["qa_start_positions"]
            end_targets = labels["qa_end_positions"]
            if not isinstance(start_targets, torch.Tensor):
                start_targets = torch.as_tensor(
                    start_targets, dtype=torch.long, device=self.device
                )
            else:
                start_targets = start_targets.to(self.device)
            if not isinstance(end_targets, torch.Tensor):
                end_targets = torch.as_tensor(end_targets, dtype=torch.long, device=self.device)
            else:
                end_targets = end_targets.to(self.device)
            loss = (
                F.cross_entropy(start_logits, start_targets)
                + F.cross_entropy(end_logits, end_targets)
            ) / 2.0
            qa_loss = loss * weights.lambda_qa
            if "retrieval_loss" in outputs:
                qa_loss = qa_loss + self.retrieval_loss_weight * outputs["retrieval_loss"]
            return qa_loss

        elif task_type == "retrieval":
            return self.retrieval_loss_weight * outputs["retrieval_loss"]

        elif task_type == "contrastive_sim":
            return self.contrastive_sim_weight * outputs["contrastive_sim_loss"]

        else:
            raise ValueError(f"Unknown task_type: {task_type}")

    def current_learning_rate(self) -> Optional[float]:
        if self.optimizer is None:
            return None
        return float(self.optimizer.param_groups[0]["lr"])

    def _optimizer_update(self) -> Optional[float]:
        """Clips, steps and resets after a full accumulation window; returns the grad norm."""
        if self.scaler is not None:
            self.scaler.unscale_(self.optimizer)
        grad_norm = float(
            torch.nn.utils.clip_grad_norm_(
                self.model.parameters(), self.max_grad_norm if self.max_grad_norm > 0 else 1e9
            )
        )
        if not np.isfinite(grad_norm):
            # never apply a non-finite update; drop this window's gradients
            self.skipped_steps += 1
            warnings.warn(
                "Non-finite gradient norm; skipping optimizer update", RuntimeWarning, stacklevel=2
            )
            if self.scaler is not None:
                self.scaler.update()
            self.optimizer.zero_grad(set_to_none=True)
            return grad_norm
        if self.scaler is not None:
            self.scaler.step(self.optimizer)
            self.scaler.update()
        else:
            self.optimizer.step()
        self.optimizer.zero_grad(set_to_none=True)
        self.optimizer_steps += 1
        if self.scheduler is not None:
            self.scheduler.step()
        return grad_norm

    @staticmethod
    def _as_batches(batch: Any) -> List[Any]:
        """One batch or a sequence of batches of different tasks (a mixed step, T201)."""
        batches = list(batch) if isinstance(batch, (list, tuple)) else [batch]
        if not batches:
            raise ValueError("a training step needs at least one batch")
        names = [getattr(item, "task_type", "mlm") for item in batches]
        if len(set(names)) != len(names):
            raise ValueError(f"a mixed step needs different tasks, got {names}")
        return batches

    def _step_loss(
        self, batches: List[Any], training_pass: bool = True
    ) -> Tuple[Any, Dict[str, float], Optional[float]]:
        """Forward passes of a micro-step: the summed loss, each task's loss, the order loss.

        The graphs of every task stay alive in the sum until the caller's backward pass.
        """
        losses: List[Any] = []
        task_losses: Dict[str, float] = {}
        order_loss: Optional[float] = None
        for item in batches:
            name = getattr(item, "task_type", "mlm")
            token_ids, attention_mask = self._to_device(item)
            with self._autocast():
                outputs = self._forward(
                    name, token_ids, attention_mask, item.labels, training_pass=training_pass
                )
                task_loss = self._compute_torch_loss(name, outputs, item.labels, attention_mask)
            task_losses[name] = float(task_loss.detach().float().item())
            if name == "mlm":
                order_loss = self._last_order_loss
            losses.append(task_loss)
        loss = losses[0]
        for extra in losses[1:]:
            loss = loss + extra
        return loss, task_losses, order_loss

    def execute_training_step(self, batch: Any) -> TrainingMetricsSnapshot:
        """Executes a single optimization step under strict authorization governance.

        `batch` is one task batch, or a sequence of batches of different tasks (a mixed step,
        T201): their weighted losses are added and one backward pass covers the sum, so the
        graphs of all its tasks are alive together (memory grows with the tasks per step).

        Performs:
        - Strict authorization assertion
        - Forward pass (with autograd enabled)
        - Multi-task composite loss calculation
        - Gradient backward and accumulation
        - Gradient norm clipping and optimizer.step()
        - Metrics recording and peak VRAM tracking
        """
        assert_training_authorized("Language encoder neural backpropagation and parameter update")

        batches = self._as_batches(batch)
        task_types = [getattr(item, "task_type", "mlm") for item in batches]
        if len(set(task_types)) != len(task_types):
            raise ValueError(f"a mixed step needs different tasks, got {task_types}")
        task_type = "+".join(task_types)
        effective_batch_size = (
            sum(getattr(item, "batch_size", 16) for item in batches) * self.grad_accum_steps
        )

        # Check if PyTorch neural execution is active
        if TORCH_AVAILABLE and isinstance(self.model, nn.Module):
            self.model.train()
            loss, task_losses, order_loss = self._step_loss(batches)
            loss_value = float(loss.detach().float().item())

            # Scaled backward pass; gradients accumulate across micro-batches (and tasks)
            scaled_loss = loss / self.grad_accum_steps
            if self.scaler is not None:
                self.scaler.scale(scaled_loss).backward()
            else:
                scaled_loss.backward()

            self._accum_counter += 1
            lr_used = self.current_learning_rate()  # rate applied by this window's update
            grad_norm: Optional[float] = None
            if (self._accum_counter % self.grad_accum_steps) == 0 and self.optimizer is not None:
                grad_norm = self._optimizer_update()

            # Peak VRAM measurement
            peak_vram_gb: Optional[float] = None
            if torch.cuda.is_available() and str(self.device).startswith("cuda"):
                peak_vram_gb = torch.cuda.max_memory_allocated() / (1024**3)

            snapshot = TrainingMetricsSnapshot(
                step=len(self.step_history) + 1,
                task_type=task_type,
                loss_value=loss_value,
                effective_batch_size=effective_batch_size,
                peak_vram_gb=peak_vram_gb,
                optimizer_step=self.optimizer_steps,
                learning_rate=lr_used,
                grad_norm=grad_norm,
                order_loss=order_loss,
                task_losses=task_losses,
            )
            self.step_history.append(snapshot)
            return snapshot

        # Fallback NumPy / test mock execution
        loss_val = 0.0
        np_losses: Dict[str, float] = {}
        for item, name in zip(batches, task_types):
            outputs_np: Dict[str, Any] = {}
            if hasattr(self.model, "forward"):
                outputs_np = self.model.forward(item.token_ids, attention_mask=item.attention_mask)
            elif callable(self.model):
                outputs_np = self.model(item.token_ids, attention_mask=item.attention_mask)
            labels_dict = getattr(item, "labels", {})
            value = 0.0
            if outputs_np and labels_dict:
                value = self.loss_calculator.compute_loss_numpy(name, outputs_np, labels_dict)
            np_losses[name] = value
            loss_val += value

        snapshot = TrainingMetricsSnapshot(
            step=len(self.step_history) + 1,
            task_type=task_type,
            loss_value=loss_val,
            effective_batch_size=effective_batch_size,
            task_losses=np_losses,
        )
        self.step_history.append(snapshot)
        return snapshot
