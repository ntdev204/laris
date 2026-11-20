"""The decision network: a small multilayer perceptron over tabular features (T169, ADR-024 5.4).

It is non-generative. It scores ``(state, candidate)`` pairs; the system picks the legal candidate
with the best
calibrated probability, and a confidence below the sealed threshold falls back to the rule decider.
The exported
file is plain JSON weights and is evaluated by a handwritten forward pass in Rust (``network.rs``),
so inference adds
no dependency there.

``forward`` is the numpy reference, in float64, used for the parity fixtures. ``TorchNet`` is the
same network as a
``torch.nn.Module`` for the owner's training run (T170); this module never trains it: there is no
loss, optimizer or
backward step here.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np

from .features import FEATURE_NAMES

FORMAT = "laris-decision-net"
VERSION = 1


class NetworkError(ValueError):
    """The exported network is malformed."""


@dataclass(frozen=True)
class Layer:
    """One affine layer: ``weights`` is ``out x in``."""

    weights: np.ndarray
    bias: np.ndarray
    activation: str  # "relu" or "none"


@dataclass(frozen=True)
class Net:
    """A network with its calibration and abstention threshold."""

    layers: tuple[Layer, ...]
    temperature: float
    threshold: float

    def logit(self, x: Sequence[float]) -> float:
        """The raw score of one input, in float64."""
        h = np.asarray(x, dtype=np.float64)
        for layer in self.layers:
            h = layer.weights @ h + layer.bias
            if layer.activation == "relu":
                h = np.maximum(h, 0.0)
        return float(h[0])

    def probability(self, x: Sequence[float]) -> float:
        """The calibrated probability that the candidate's outcome is good."""
        return sigmoid(self.logit(x) / self.temperature)

    def parameter_count(self) -> int:
        return sum(layer.weights.size + layer.bias.size for layer in self.layers)


def sigmoid(z: float) -> float:
    """Numerically safe logistic function."""
    if z >= 0:
        return 1.0 / (1.0 + float(np.exp(-z)))
    e = float(np.exp(z))
    return e / (1.0 + e)


def validate(net: Net) -> None:
    """Raises ``NetworkError`` unless the shapes chain from the features to one logit and all
    numbers are finite."""
    width = len(FEATURE_NAMES)
    if not net.layers:
        raise NetworkError("no layers")
    for i, layer in enumerate(net.layers):
        if layer.activation not in ("relu", "none"):
            raise NetworkError(f"layer {i}: unknown activation {layer.activation!r}")
        if layer.weights.ndim != 2 or layer.weights.shape[1] != width:
            raise NetworkError(
                f"layer {i}: expected {width} inputs, got shape {layer.weights.shape}"
            )
        if layer.bias.shape != (layer.weights.shape[0],):
            raise NetworkError(f"layer {i}: bias does not match the output size")
        if not (np.isfinite(layer.weights).all() and np.isfinite(layer.bias).all()):
            raise NetworkError(f"layer {i}: non-finite number")
        width = layer.weights.shape[0]
    if width != 1:
        raise NetworkError("the last layer must have one output")
    if not (np.isfinite(net.temperature) and net.temperature > 0):
        raise NetworkError("temperature must be positive")
    if not np.isfinite(net.threshold) or net.threshold < 0:
        raise NetworkError("threshold must be a non-negative number")


def export(net: Net, extra: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """The JSON object of a network. ``extra`` carries the manifest (dataset checksums, run id,
    date)."""
    validate(net)
    return {
        "format": FORMAT,
        "version": VERSION,
        "features": list(FEATURE_NAMES),
        "layers": [
            {
                "weights": layer.weights.tolist(),
                "bias": layer.bias.tolist(),
                "activation": layer.activation,
            }
            for layer in net.layers
        ],
        "calibration": {"temperature": net.temperature},
        "abstention": {"threshold": net.threshold},
        "manifest": dict(extra or {}),
    }


def dumps(net: Net, extra: Mapping[str, Any] | None = None) -> str:
    """The exported network as canonical JSON text (sorted keys, no spaces, a trailing newline)."""
    return json.dumps(export(net, extra), sort_keys=True, separators=(",", ":")) + "\n"


def load(data: Mapping[str, Any]) -> Net:
    """The network of an exported object."""
    if data.get("format") != FORMAT or data.get("version") != VERSION:
        raise NetworkError("not a laris-decision-net version 1")
    if list(data.get("features", [])) != list(FEATURE_NAMES):
        raise NetworkError("the feature names differ from this code's")
    try:
        layers = tuple(
            Layer(
                np.asarray(raw["weights"], dtype=np.float64),
                np.asarray(raw["bias"], dtype=np.float64),
                raw["activation"],
            )
            for raw in data["layers"]
        )
        net = Net(
            layers,
            float(data["calibration"]["temperature"]),
            float(data["abstention"]["threshold"]),
        )
    except (KeyError, TypeError, ValueError) as error:
        raise NetworkError(f"malformed network: {error}") from error
    validate(net)
    return net


def random_net(seed: int, hidden: Sequence[int] = (32, 32)) -> Net:
    """A network with seeded random weights and no training. Used for fixtures and mechanics tests
    only."""
    rng = np.random.RandomState(seed)  # noqa: NPY002 - fixed legacy stream
    sizes = [len(FEATURE_NAMES), *hidden, 1]
    layers = []
    for i in range(len(sizes) - 1):
        scale = (2.0 / sizes[i]) ** 0.5
        weights = np.round(rng.standard_normal((sizes[i + 1], sizes[i])) * scale, 6)
        bias = np.round(rng.standard_normal(sizes[i + 1]) * 0.1, 6)
        layers.append(Layer(weights, bias, "relu" if i < len(sizes) - 2 else "none"))
    return Net(tuple(layers), 1.0, 0.0)


def torch_module(hidden: Sequence[int] = (32, 32)):  # type: ignore[no-untyped-def]
    """The same architecture as a ``torch.nn.Module`` (imported here so that numpy-only users need
    no torch)."""
    import torch
    from torch import nn

    class TorchNet(nn.Module):
        """Multilayer perceptron with ReLU, one logit out."""

        def __init__(self) -> None:
            super().__init__()
            sizes = [len(FEATURE_NAMES), *hidden, 1]
            self.linears = nn.ModuleList(
                nn.Linear(sizes[i], sizes[i + 1]) for i in range(len(sizes) - 1)
            )

        def forward(self, x: "torch.Tensor") -> "torch.Tensor":
            for i, linear in enumerate(self.linears):
                x = linear(x)
                if i < len(self.linears) - 1:
                    x = torch.relu(x)
            return x.squeeze(-1)

        def to_net(self, temperature: float = 1.0, threshold: float = 0.0) -> Net:
            """The float64 export of the current weights."""
            last = len(self.linears) - 1
            linears: list[nn.Linear] = list(self.linears)  # type: ignore[arg-type]
            layers = tuple(
                Layer(
                    lin.weight.detach().cpu().double().numpy().copy(),
                    lin.bias.detach().cpu().double().numpy().copy(),
                    "relu" if i < last else "none",
                )
                for i, lin in enumerate(linears)
            )
            return Net(layers, temperature, threshold)

    return TorchNet()
