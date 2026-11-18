"""ADR-017: the loop runs inside the harness, the harness composes the prompt, the prompt layer
knows neither the loop nor the tools, and the loop carries no policy path or prompt text."""

import ast
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[3] / "src" / "laris"


def _imports(path: Path) -> set:
    found = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            found |= {a.name for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module)
    return found


# `laris-v2` removed the Python client, harness and policy modules (the Rust system replaces them,
# ADR-021); these checks apply again if such modules return, and are skipped while they are absent.
_NO_PYTHON_FRONT = pytest.mark.skipif(
    not (SRC / "client/agent/loop.py").exists(),
    reason="the Python client and policy layers are not on laris-v2 (ADR-021)",
)


@_NO_PYTHON_FRONT
def test_prompt_layer_knows_neither_the_loop_nor_the_tools():
    names = _imports(SRC / "shared/policy/prompts.py")
    front = ("laris.client.agent", "laris.client.application", "laris.server.gateway")
    assert not {n for n in names if n.startswith(front)}
    assert not {n for n in names if n.startswith("laris.shared.harness.runtime")}


@_NO_PYTHON_FRONT
def test_loop_carries_no_policy_path_or_prompt_text():
    for name in ("loop.py", "context.py", "tools.py"):
        text = (SRC / "client/agent" / name).read_text(encoding="utf-8")
        for needle in (".laris", "policy.toml", "integrity.toml", "internal_policy"):
            assert needle not in text, (name, needle)


def test_harness_does_not_depend_on_a_front_end():
    front = ("laris.client.application", "cli", "laris.server.gateway")
    for folder in ("client/harness", "shared/harness", "shared/policy"):
        for path in (SRC / folder).glob("*.py"):
            names = _imports(path)
            assert not {n for n in names if n == "cli" or n.startswith(front)}, path
