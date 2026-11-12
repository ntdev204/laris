"""SR-S1 / ADR-019: the blocks import only `protocol` and `shared`, nothing imports `research`,
and `shared` and `protocol` import no block.

`KNOWN` lists the edges that still cross a boundary, each with the task that removes it. The test
fails on any new edge and on a listed edge that has disappeared (so the list only shrinks).
`research` is owner-only tooling: it may use every block, but no block may use it.
"""

import ast
from pathlib import Path
from typing import Dict, Iterable, List, Set, Tuple

SRC = Path(__file__).resolve().parents[3] / "src"
BLOCKS = ("protocol", "shared", "client", "server", "model", "research")
BLOCK_PEERS = {"client", "server", "model"}

# (importing module, imported module prefix) -> task that removes the edge
KNOWN: Dict[Tuple[str, str], str] = {}


def block_of(module: str) -> str:
    parts = module.split(".")
    if parts[0] == "laris" and len(parts) > 1 and parts[1] in BLOCKS:
        return parts[1]
    return ""


def imports_of(path: Path) -> Set[str]:
    found: Set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            found.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            found.add(node.module)
    return found


def forbidden(importer_block: str, imported_block: str) -> bool:
    if not imported_block or imported_block == importer_block:
        return False
    if importer_block == "research":
        return False  # owner tooling may use every block
    if imported_block == "research":
        return True  # nothing imports research
    if importer_block == "protocol":
        return True
    if importer_block == "shared":
        return imported_block != "protocol"
    return imported_block not in ("protocol", "shared")  # client, server, model


def violations(root: Path = SRC, tree: str = "laris") -> List[Tuple[str, str]]:
    found: List[Tuple[str, str]] = []
    for path in sorted((root / tree).rglob("*.py")):
        module = ".".join(path.with_suffix("").relative_to(root).parts).removesuffix(".__init__")
        mine = block_of(module)
        for name in imports_of(path):
            if forbidden(mine, block_of(name)):
                found.append((module, name))
    return found


def _known(edge: Tuple[str, str]) -> bool:
    return any(edge[0] == m and edge[1].startswith(p) for (m, p) in KNOWN)


def test_no_new_block_boundary_violation() -> None:
    new = [edge for edge in violations() if not _known(edge)]
    assert new == [], "\n".join(f"{a} imports {b}" for a, b in new)


def test_known_violations_are_still_present() -> None:
    present = violations()
    stale = [k for k in KNOWN if not any(e[0] == k[0] and e[1].startswith(k[1]) for e in present)]
    assert stale == [], f"remove from KNOWN (fixed): {stale}"


def test_rules_reject_each_kind_of_planted_violation() -> None:
    assert forbidden("client", "server") and forbidden("server", "client")
    assert forbidden("model", "client") and forbidden("client", "model")
    assert forbidden("client", "research") and forbidden("shared", "research")
    assert forbidden("shared", "client") and forbidden("protocol", "shared")
    assert not forbidden("client", "shared") and not forbidden("server", "protocol")
    assert not forbidden("shared", "protocol") and not forbidden("research", "client")


def test_a_planted_file_is_reported(tmp_path: Path) -> None:
    folder = tmp_path / "laris" / "client"
    folder.mkdir(parents=True)
    (folder / "bad.py").write_text("from laris.server.serving import auth\n", encoding="utf-8")
    (folder / "good.py").write_text("from laris.shared.core import errors\n", encoding="utf-8")
    assert violations(tmp_path) == [("laris.client.bad", "laris.server.serving")]


def test_blocks_are_the_only_directories_under_laris() -> None:
    names: Iterable[str] = (
        p.name for p in (SRC / "laris").iterdir() if p.is_dir() and p.name != "__pycache__"
    )
    assert set(names) <= set(BLOCKS)
