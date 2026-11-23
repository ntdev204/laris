"""Proposals for the write gate from the pinned OpenStax books and NIST's CODATA table (T277).

Every Source carries its provenance in its first lines (source, licence, location, file hash and
what the conversion left out), so the text a Claim quotes and its attribution are one immutable,
hashed body. Every Claim is a line of that body, proposed at level `sourced`; the gate checks the
quote, the support, duplicates and contradictions. A formula the solver can compute with gets a
`tool_run` Source holding the solver call and the solver's result with its own status, and its
Claim links to it (`solver_ref`). The link says "this call runs and every check it ran passed",
not "verified": a symbolic `solve` stays a `proposal` (its completeness is not checkable), and the
link is not evidence and does not raise the Claim's level.

Output: JSON lines for `laris-server brain import`. No model, no network.
"""

from __future__ import annotations

import hashlib
import json
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

from laris.research.knowledge.cnxml import Module, Reader

COLLXML = "{http://cnx.rice.edu/collxml}"
MDML = "{http://cnx.rice.edu/mdml}"
FORBIDDEN = set('#|^:%[]\\/"<>?*')
_LHS = re.compile(r"\s*([A-Za-z][A-Za-z0-9_]{0,23})\s*=")

# a solver call returns its result dict (or raises); bound to laris.model.solver.runner.run
SolverCall = Callable[[Dict[str, Any]], Dict[str, Any]]
# whether a text shares a word sequence with a benchmark item (the 13-gram rule of gate B6)
Overlap = Callable[[str], bool]


def never(_text: str) -> bool:
    return False


def decontaminate(blocks: List[str], overlaps: Overlap, span: int = 13) -> Tuple[List[str], int]:
    """The blocks without those that share a sequence with a benchmark item, alone or together with
    the blocks before them (a sequence of `span` words crosses at most `span` blocks); and how
    many were left out. Only removes, never rewrites (ADR-026 B6)."""
    kept = [b for b in blocks if not overlaps(b)]
    while kept and overlaps("\n\n".join(kept)):
        for end in range(1, len(kept)):
            first = max(0, end - span + 1)
            if any(overlaps("\n\n".join(kept[i : end + 1])) for i in range(end - 1, first - 1, -1)):
                del kept[end]
                break
        else:  # the joined text overlaps but no window does: drop everything rather than guess
            kept = []
    return kept, len(blocks) - len(kept)


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def safe_title(text: str, limit: int = 100) -> str:
    cleaned = "".join(" " if c in FORBIDDEN or ord(c) < 32 else c for c in text)
    cleaned = " ".join(cleaned.split()).strip(" .")
    return cleaned[:limit].strip(" .")


@dataclass
class Place:
    """Where a module sits in a book."""

    book: str
    chapter: str
    position: int


def collection_places(path: Path) -> Tuple[str, Dict[str, Place]]:
    """Title of a collection and each module's place in it (first occurrence)."""
    root = ET.parse(path).getroot()
    title = (
        root.findtext(f"{COLLXML}metadata/{MDML}title")
        or root.findtext(f".//{MDML}title")
        or path.stem
    ).strip()
    places: Dict[str, Place] = {}

    def visit(node: ET.Element, chapter: str) -> None:
        for child in node:
            if child.tag == f"{COLLXML}module":
                mid = child.get("document", "")
                if mid and mid not in places:
                    places[mid] = Place(title, chapter, len(places) + 1)
            elif child.tag == f"{COLLXML}subcollection":
                name = (child.findtext(f"{MDML}title") or "").strip()
                content = child.find(f"{COLLXML}content")
                if content is not None:
                    visit(content, name or chapter)

    content = root.find(f"{COLLXML}content")
    if content is not None:
        visit(content, "")
    return title, places


def split_parts(text: str, limit: int) -> List[str]:
    """The text cut at block boundaries into parts of at most `limit` bytes."""
    if len(text.encode("utf-8")) <= limit:
        return [text]
    parts: List[str] = []
    current: List[str] = []
    size = 0
    for block in text.split("\n\n"):
        n = len(block.encode("utf-8")) + 2
        if current and size + n > limit:
            parts.append("\n\n".join(current) + "\n")
            current, size = [], 0
        current.append(block.strip("\n"))
        size += n
    if current:
        parts.append("\n\n".join(current) + "\n")
    return parts


def source_line(
    title: str,
    identifier: str,
    text: str,
    registry: str,
    proposer: str,
    admission: Optional[Dict[str, Any]] = None,
) -> Dict:
    line = {
        "type": "source",
        "title": title,
        "kind": "document",
        "identifier": identifier,
        "text": text,
        "metadata": {"kind": "verified", "registry": registry},
        "proposer": proposer,
    }
    if admission is not None:
        # the admission record of T285: whether a Claim is certain is decided from it when read
        line["admission"] = dict(admission)
    return line


def claim_line(statement: str, source: str, proposer: str, solver: Optional[str]) -> Dict:
    line = {
        "type": "claim",
        "statement": statement,
        "source": source,
        "quote": statement,
        "requested": "sourced",
        "proposer": proposer,
    }
    if solver:
        line["solver"] = solver
    return line


def usable(result: Dict[str, Any]) -> bool:
    """A result to link: verified, or a proposal whose every check that ran passed."""
    if result.get("status") == "verified":
        return True
    checks = result.get("checks") or []
    ran = [c for c in checks if c.get("detail") != "not checked"]
    return (
        result.get("status") == "proposal"
        and isinstance(result.get("answer"), list)
        and bool(ran)
        and all(c.get("passed") for c in ran)
    )


class SolverLinks:
    """`tool_run` Sources for formulas: one per distinct solver call whose result is `usable`."""

    def __init__(
        self, call: Optional[SolverCall], proposer: str, overlaps: Overlap = never
    ) -> None:
        self.call = call
        self.proposer = proposer
        self.overlaps = overlaps
        self.sources: Dict[str, Dict] = {}
        self.tried = 0
        self.linked: Dict[str, int] = {}

    def link(self, problem: Dict[str, Any]) -> Optional[str]:
        if self.call is None:
            return None
        key = json.dumps(problem, sort_keys=True, ensure_ascii=False)
        title = "Solver " + sha256(key.encode("utf-8"))[:12]
        if title in self.sources:
            return title
        self.tried += 1
        try:
            result = self.call(problem)
        except Exception:  # a refusal or a timeout: the formula stays text
            return None
        if not usable(result):
            return None
        output = json.dumps(
            {"problem": problem, "result": result}, sort_keys=True, ensure_ascii=False, default=str
        )
        if self.overlaps(output) or self.overlaps(key):
            return None
        status = str(result.get("status"))
        self.linked[status] = self.linked.get(status, 0) + 1
        self.sources[title] = {
            "type": "source",
            "title": title,
            "kind": "tool_run",
            "identifier": "tool:solve_stem",
            "text": output,
            "command": "solve_stem " + key,
            "inputs_sha256": sha256(key.encode("utf-8")),
            "metadata": {"kind": "not_applicable"},
            "proposer": self.proposer,
        }
        return title

    def formula(self, formula: Optional[str]) -> Optional[str]:
        """A solver link for `lhs = rhs` with one name on the left, absent on the right."""
        if not formula:
            return None
        match = _LHS.match(formula)
        if not match:
            return None
        name = match.group(1)
        rhs = formula.split("=", 1)[1]
        if re.search(rf"(?<![A-Za-z0-9_]){re.escape(name)}(?![A-Za-z0-9_])", rhs):
            return None
        # the complex domain gives the finite solution list a substitution check can run on
        return self.link(
            {"operation": "solve", "expression": formula, "variable": name, "domain": "complex"}
        )


def openstax_lines(
    config: Dict[str, Any],
    root: Path,
    provenance: Dict[str, Any],
    links: SolverLinks,
    overlaps: Overlap = never,
    span: int = 13,
    admitted: bool = False,
) -> Tuple[List[Dict], List[Dict], Dict[str, Any]]:
    """Source and Claim lines of every pinned book, and counts. Blocks that `overlaps` flags are
    left out of the Source text (and so are the statements they held). With `admitted` (T285),
    every Source carries the admission record of the class `textbook`: resolved against the
    openstax.org catalogue (the hash of its response at acquisition) under the book's licence."""
    build = config["build"]
    reader = Reader(build["dropped_elements"], build["dropped_classes"])
    proposer = build["proposer"]
    registry = config["catalogue_registry"]
    limit = int(config["source_part_bytes"])
    # whole modules of exercises (review exercises, practice tests, solution sheets, lab sheets)
    left_out_titles = [re.compile(p) for p in build.get("module_titles_left_out", [])]
    sources: List[Dict] = []
    claims: List[Dict] = []
    counts: Dict[str, Any] = {
        "modules": 0,
        "sources": 0,
        "statements": {},
        "books": {},
        "benchmark_overlap": {"blocks_left_out": 0, "modules_touched": 0},
        "modules_left_out_by_title": [],
    }
    files = provenance["files"]
    seen_titles: Dict[str, str] = {}
    for pin in config["openstax"]:
        repo, commit = pin["repo"], pin["commit"]
        folder = root / config["data_dir"] / "raw" / "openstax" / f"{repo}@{commit[:12]}"
        hashes = files[str(folder.relative_to(root))]
        books = [b for b in provenance["books"] if b["repo"] == repo and b["commit"] == commit]
        modules: Dict[str, List[Place]] = {}
        order: List[str] = []
        for slug in pin["collections"]:
            _, places = collection_places(folder / "collections" / f"{slug}.collection.xml")
            for mid, place in places.items():
                if mid not in modules:
                    modules[mid] = []
                    order.append(mid)
                modules[mid].append(place)
        for mid in order:
            rel = f"modules/{mid}/index.cnxml"
            path = folder / rel
            if not path.exists():
                continue
            module = reader.module(
                mid, path.read_text(encoding="utf-8"), int(build["max_statement_bytes"])
            )
            if any(p.search(module.title) for p in left_out_titles):
                counts["modules_left_out_by_title"].append(f"{mid} {module.title}")
                continue
            counts["modules"] += 1
            places = modules[mid]
            for place in places:
                counts["books"][place.book] = counts["books"].get(place.book, 0) + 1
            book = next(b for b in books if b["title"] == places[0].book)
            blocks, left_out = decontaminate(module.text.rstrip("\n").split("\n\n"), overlaps, span)
            if left_out:
                counts["benchmark_overlap"]["blocks_left_out"] += left_out
                counts["benchmark_overlap"]["modules_touched"] += 1
            if not blocks:
                continue
            text = "\n\n".join(blocks) + "\n"
            header = provenance_header(
                module, places, repo, commit, rel, hashes[rel], book, left_out
            )
            parts = split_parts(text, limit - len(header.encode("utf-8")) - 2)
            base = safe_title(f"OpenStax {mid} {module.title}", 90)
            if base.lower() in seen_titles and seen_titles[base.lower()] != repo:
                base = safe_title(f"OpenStax {repo} {mid}", 90)
            seen_titles[base.lower()] = repo
            for n, part in enumerate(parts, 1):
                title = base if len(parts) == 1 else f"{base} part {n}"
                identifier = f"https://github.com/openstax/{repo}/blob/{commit}/{rel}"
                if len(parts) > 1:
                    identifier += f"#part-{n}"
                note = f"Part {n} of {len(parts)}.\n" if len(parts) > 1 else ""
                admission = None
                if admitted:
                    admission = {
                        "class": "textbook",
                        "resolved_by": "openstax-catalogue",
                        "resolution_sha256": provenance["catalogue_sha256"],
                        "licence": textbook_licence(book["licence_url"]),
                    }
                sources.append(
                    source_line(
                        title,
                        identifier,
                        header + note + "\n" + part,
                        registry,
                        proposer,
                        admission,
                    )
                )
                counts["sources"] += 1
                folded = " ".join(part.split())
                for st in module.statements:
                    if st.text in folded and not overlaps(st.text):
                        kinds = counts["statements"]
                        kinds[st.kind] = kinds.get(st.kind, 0) + 1
                        claims.append(
                            claim_line(st.text, title, proposer, links.formula(st.formula))
                        )
    return sources, claims, counts


def provenance_header(
    module: Module,
    places: List[Place],
    repo: str,
    commit: str,
    rel: str,
    file_sha: str,
    book: Dict[str, Any],
    left_out: int = 0,
) -> str:
    where = "; ".join(
        f"{p.book}, {p.chapter + ', ' if p.chapter else ''}module {p.position}" for p in places
    )
    return (
        f'Source: OpenStax, {where}: "{module.title}" ({module.module_id}).\n'
        f"Location: https://github.com/openstax/{repo} at commit {commit}, file {rel} "
        f"(SHA-256 {file_sha}).\n"
        f"Licence: {book['licence_url']} (Creative Commons Attribution 4.0 at this commit); "
        f"attribution: OpenStax, Rice University.\n"
        "Changes: converted from CNXML to plain text; formulas written as linear text; exercises, "
        "review and practice sections, teacher notes, learning objectives and media left out.\n"
        + (
            f"Benchmark overlap: {left_out} block(s) sharing a word sequence with a benchmark "
            "item left out (ADR-026 gate B6).\n"
            if left_out
            else ""
        )
    )


def codata_lines(
    config: Dict[str, Any],
    table: Path,
    sha_expected: str,
    links: SolverLinks,
    overlaps: Overlap = never,
    admitted: bool = False,
) -> Tuple[List[Dict], List[Dict], Dict[str, Any]]:
    """One Source for NIST's table and one Claim per constant. With `admitted` (T285) the Source
    carries the admission record of the class `reference_table` (the pinned table's hash)."""
    raw = table.read_bytes()
    digest = sha256(raw)
    if digest != sha_expected:
        raise ValueError("the CODATA table differs from the pinned hash")
    spec = config["codata"]
    proposer = config["build"]["proposer"]
    text = raw.decode("utf-8")
    header = (
        "Source: NIST, Fundamental Physical Constants, 2022 CODATA adjustment, complete listing.\n"
        f"Location: {spec['identifier']} (SHA-256 {digest}).\n"
        f"Licence: {spec['licence']}.\n"
        "Changes: none; the table follows verbatim.\n\n"
    )
    if overlaps(text):
        raise ValueError("the CODATA table shares a word sequence with a benchmark item")
    title = "NIST CODATA 2022 fundamental physical constants"
    admission = None
    if admitted:
        admission = {
            "class": "reference_table",
            "resolved_by": "nist-codata",
            "resolution_sha256": digest,
            "licence": "us-public-domain-17usc105",
        }
    sources = [
        source_line(title, spec["identifier"], header + text, spec["registry"], proposer, admission)
    ]
    claims: List[Dict] = []
    started = False
    for line in text.splitlines():
        if line.startswith("-----"):
            started = True
            continue
        if not started or not line.strip():
            continue
        name = line[:60].strip()
        statement = " ".join(line.split())
        if overlaps(statement):
            continue
        solver = links.link({"operation": "constant", "constant": name})
        claims.append(claim_line(statement, title, proposer, solver))
    return sources, claims, {"constants": len(claims)}


def textbook_licence(url: str) -> str:
    """`cc-by-4.0` for the CC BY 4.0 URL the acquisition checked; anything else is refused."""
    if "creativecommons.org/licenses/by/4.0" not in url:
        raise ValueError(f"not a CC BY 4.0 licence: {url}")
    return "cc-by-4.0"


def ciaaw_lines(
    table: Path, sha_expected: str, proposer: str, overlaps: Overlap = never
) -> Tuple[List[Dict], List[Dict], Dict[str, Any]]:
    """One Source for CIAAW's abridged standard atomic weights (the table the solver packages,
    T276) with each row written as a sentence, and one Claim per element that has a value. The
    Source carries the admission record of the class `reference_table` (T285)."""
    raw = table.read_bytes()
    digest = sha256(raw)
    if digest != sha_expected:
        raise ValueError("the CIAAW table differs from the pinned hash")
    lines = raw.decode("utf-8").splitlines()
    page_sha = next(
        (ln.split(":", 1)[1].strip() for ln in lines if ln.startswith("# source_sha256:")), ""
    )
    release = lines[0].lstrip("# ").strip() if lines else ""
    sentences: List[str] = []
    for line in lines:
        if line.startswith("#") or not line.strip():
            continue
        cells = line.split("\t")
        if len(cells) < 5 or not cells[3].strip():
            continue
        z, symbol, element, value, uncertainty = (c.strip() for c in cells[:5])
        sentences.append(
            f"The abridged standard atomic weight of {element} ({symbol}, atomic number {z}) "
            f"is {value} with uncertainty {uncertainty}."
        )
    sentences = [s for s in sentences if not overlaps(s)]
    header = (
        f"Source: {release}.\n"
        "Location: https://www.ciaaw.org/abridged-atomic-weights.htm (page SHA-256 "
        f"{page_sha}); table as packaged for the solver (SHA-256 {digest}).\n"
        "Licence: factual data (atomic weights), no licence stated; attribution: IUPAC CIAAW.\n"
        "Changes: each row of the table written as one sentence; units g/mol as printed.\n\n"
    )
    title = "CIAAW abridged standard atomic weights 2024"
    admission = {
        "class": "reference_table",
        "resolved_by": "ciaaw",
        "resolution_sha256": page_sha if len(page_sha) == 64 else digest,
        "licence": "factual-data",
    }
    text = header + "\n".join(sentences) + "\n"
    sources = [
        source_line(
            title,
            "https://www.ciaaw.org/abridged-atomic-weights.htm",
            text,
            "ciaaw",
            proposer,
            admission,
        )
    ]
    claims = [claim_line(s, title, proposer, None) for s in sentences]
    return sources, claims, {"atomic_weights": len(claims)}


def write_lines(path: Path, groups: Iterable[List[Dict]]) -> int:
    count = 0
    with path.open("w", encoding="utf-8") as out:
        for group in groups:
            for line in group:
                out.write(json.dumps(line, ensure_ascii=False) + "\n")
                count += 1
    return count
