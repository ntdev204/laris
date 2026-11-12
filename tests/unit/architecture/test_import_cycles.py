"""T49: the shared protocol package stands alone and the core packages have no import cycles."""

import ast
from pathlib import Path
from typing import Dict, Set

SRC = Path(__file__).resolve().parents[3] / "src"
CORE = ["laris"]  # every block and the protocol; research is checked with the rest


def _modules(packages: list) -> Dict[str, Path]:
    found: Dict[str, Path] = {}
    for package in packages:
        for path in (SRC / package).rglob("*.py"):
            name = ".".join(path.with_suffix("").relative_to(SRC).parts).removesuffix(".__init__")
            found[name] = path
    return found


def _imports(path: Path, known: Dict[str, Path]) -> Set[str]:
    """Every import in the file, lazy (inside functions) ones included."""
    out: Set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names = [node.module] + [f"{node.module}.{a.name}" for a in node.names]
        elif isinstance(node, ast.Import):
            names = [a.name for a in node.names]
        else:
            continue
        out.update(n for n in names if n in known)
    return out


def _cycles(graph: Dict[str, Set[str]]) -> list:
    index: Dict[str, int] = {}
    low: Dict[str, int] = {}
    stack: list = []
    on: Set[str] = set()
    found: list = []
    counter = [0]

    def visit(v: str) -> None:
        index[v] = low[v] = counter[0]
        counter[0] += 1
        stack.append(v)
        on.add(v)
        for w in graph[v]:
            if w not in index:
                visit(w)
                low[v] = min(low[v], low[w])
            elif w in on:
                low[v] = min(low[v], index[w])
        if low[v] == index[v]:
            component = []
            while True:
                w = stack.pop()
                on.discard(w)
                component.append(w)
                if w == v:
                    break
            if len(component) > 1:
                found.append(sorted(component))

    for v in graph:
        if v not in index:
            visit(v)
    return found


def test_core_packages_have_no_module_import_cycles() -> None:
    known = _modules(CORE)
    graph = {m: _imports(p, known) - {m} for m, p in known.items()}
    assert _cycles(graph) == []


def test_cycle_detector_finds_a_planted_cycle() -> None:
    assert _cycles({"a": {"b"}, "b": {"a"}, "c": set()}) == [["a", "b"]]


def test_protocol_imports_no_other_laris_package() -> None:
    for name, path in _modules(["laris/protocol"]).items():
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            modules = []
            if isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                modules = [node.module]
            elif isinstance(node, ast.Import):
                modules = [a.name for a in node.names]
            for module in modules:
                inside = module == "laris.protocol" or module.startswith("laris.protocol.")
                assert module.split(".")[0] not in {"cli", "laris"} or inside, f"{name}: {module}"


def test_named_cycles_are_gone() -> None:
    from laris.client.agent import provider
    from laris.client.application import workspace
    from laris.protocol import ChatProvider, Chunk, ToolCall

    assert workspace.Chunk is Chunk and provider.ChatProvider is ChatProvider
    assert provider.ToolCall is ToolCall
    assert "harness" not in (SRC / "laris/shared/config/loader.py").read_text(encoding="utf-8")
    assert "agent" not in (SRC / "laris/shared/harness/credentials.py").read_text(encoding="utf-8")
