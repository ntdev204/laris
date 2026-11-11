"""Graph analytics over a vault index: degree, PageRank, components, paths, local graphs.

Everything is deterministic: nodes are note paths, ties break by path, floats are rounded.
Edges are the resolved links of the index (directed, one per source/target pair).
"""

from collections import deque
from typing import Dict, List, Optional, Sequence, Set, Tuple

from vault.index import VaultIndex

ROUND = 8


class VaultGraph:
    def __init__(self, index: VaultIndex) -> None:
        self.index = index
        self.nodes: List[str] = sorted(index.notes)
        self.out: Dict[str, List[Tuple[str, str]]] = {
            p: sorted(index.outgoing(p)) for p in self.nodes
        }
        self.inn: Dict[str, List[str]] = {p: index.backlinks(p) for p in self.nodes}

    # -- degree --------------------------------------------------------------------------------
    def degree(self, path: str) -> Dict[str, int]:
        out = len({t for t, _ in self.out.get(path, [])})
        inn = len(self.inn.get(path, []))
        return {"in": inn, "out": out, "total": inn + out}

    def top_by_degree(self, n: int = 10) -> List[Tuple[str, int]]:
        rows = [(p, self.degree(p)["total"]) for p in self.nodes]
        return sorted(rows, key=lambda r: (-r[1], r[0]))[:n]

    # -- PageRank ------------------------------------------------------------------------------
    def pagerank(
        self, damping: float = 0.85, iterations: int = 100, tolerance: float = 1e-10
    ) -> Dict[str, float]:
        count = len(self.nodes)
        if count == 0:
            return {}
        rank = {p: 1.0 / count for p in self.nodes}
        for _ in range(iterations):
            sink = sum(rank[p] for p in self.nodes if not self.out[p])
            fresh = {}
            for p in self.nodes:
                incoming = sum(
                    rank[q] / len({t for t, _ in self.out[q]}) for q in self.inn[p] if self.out[q]
                )
                fresh[p] = (1 - damping) / count + damping * (incoming + sink / count)
            delta = sum(abs(fresh[p] - rank[p]) for p in self.nodes)
            rank = fresh
            if delta < tolerance:
                break
        return {p: round(v, ROUND) for p, v in rank.items()}

    # -- components and paths ---------------------------------------------------------------------
    def neighbours(self, path: str) -> List[str]:
        return self.index.neighbours(path)

    def components(self) -> List[List[str]]:
        """Weakly connected components, largest first, members sorted."""
        seen: Set[str] = set()
        found: List[List[str]] = []
        for start in self.nodes:
            if start in seen:
                continue
            group, queue = [], deque([start])
            seen.add(start)
            while queue:
                node = queue.popleft()
                group.append(node)
                for other in self.neighbours(node):
                    if other not in seen:
                        seen.add(other)
                        queue.append(other)
            found.append(sorted(group))
        return sorted(found, key=lambda g: (-len(g), g[0]))

    def shortest_path(
        self, source: str, target: str, directed: bool = False
    ) -> Optional[List[str]]:
        if source not in self.out or target not in self.out:
            return None
        previous: Dict[str, Optional[str]] = {source: None}
        queue = deque([source])
        while queue:
            node = queue.popleft()
            if node == target:
                break
            nxt = sorted({t for t, _ in self.out[node]}) if directed else self.neighbours(node)
            for other in nxt:
                if other not in previous:
                    previous[other] = node
                    queue.append(other)
        if target not in previous:
            return None
        route, node = [], target  # type: ignore[assignment]
        while node is not None:
            route.append(node)
            node = previous[node]  # type: ignore[assignment]
        return route[::-1]

    def local_graph(self, path: str, depth: int = 1) -> Dict[str, List]:
        """Nodes within `depth` steps and the edges between them."""
        if path not in self.out:
            return {"nodes": [], "edges": []}
        level = {path: 0}
        queue = deque([path])
        while queue:
            node = queue.popleft()
            if level[node] >= depth:
                continue
            for other in self.neighbours(node):
                if other not in level:
                    level[other] = level[node] + 1
                    queue.append(other)
        keep = set(level)
        edges = [[p, t, kind] for p in sorted(keep) for t, kind in self.out[p] if t in keep]
        return {"nodes": sorted(keep), "edges": edges}

    def neighbours_by_relation(self, path: str, relation: str) -> List[str]:
        """Targets linked through the named property (for example `children`, `requires`)."""
        return sorted({t for t, kind in self.out.get(path, []) if kind == relation})

    def relations(self, paths: Sequence[str] = ()) -> Dict[str, int]:
        counts: Dict[str, int] = {}
        for p in paths or self.nodes:
            for _, kind in self.out.get(p, []):
                counts[kind] = counts.get(kind, 0) + 1
        return dict(sorted(counts.items()))
