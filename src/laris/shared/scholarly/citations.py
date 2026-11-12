"""Citations: in-text and reference-list extraction, resolution to corpus documents, graph metrics.

A reference is resolved to a corpus document only on strong evidence (same DOI, same arXiv id, or
the document's whole title inside the reference with a compatible year). A weaker author-and-year
match is reported as `weak`, and several candidates are reported as `ambiguous`; neither becomes an
edge. References that match nothing are listed as unresolved.
"""

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

from laris.shared.scholarly.biblio import REFERENCES_HEADING, find_arxiv, find_doi
from laris.shared.scholarly.mining import Doc, tokens

_LABEL = re.compile(r"^\s*(?:\[(\d{1,3})\]|(\d{1,3})[.)])\s+")
_NUMERIC = re.compile(r"\[(\d{1,3}(?:\s*[,;–-]\s*\d{1,3})*)\]")
_NAME = r"[A-ZÀ-Ỹ][\w'’-]+"
_PAREN = re.compile(r"\(([^()]*?(?:19|20)\d{2}[a-z]?[^()]*?)\)")
_AUTHOR_YEAR = re.compile(
    rf"({_NAME})(?:\s+et al\.?|\s+(?:and|&)\s+{_NAME})?,?\s*((?:19|20)\d{{2}})[a-z]?"
)
_NARRATIVE = re.compile(
    rf"({_NAME})(?:\s+et al\.?|\s+(?:and|&)\s+{_NAME})?\s+\(((?:19|20)\d{{2}})[a-z]?\)"
)
_YEAR = re.compile(r"(?<!\d)((?:19|20)\d{2})[a-z]?(?!\d)")
MIN_TITLE_TOKENS = 3
CONTAINMENT = 0.85


@dataclass
class Reference:
    label: str  # "1" for numbered lists, "" otherwise
    raw: str
    doi: str = ""
    arxiv: str = ""
    year: Optional[int] = None
    surname: str = ""

    @property
    def key(self) -> str:
        """Identity used for coupling when the reference is not in the corpus."""
        return self.doi or self.arxiv or " ".join(tokens(self.raw)[:8])


@dataclass
class Citation:
    kind: str  # numeric | author-year
    key: str
    position: int


@dataclass
class Resolution:
    reference: Reference
    status: str  # resolved | weak | ambiguous | unresolved
    doc_ids: List[str] = field(default_factory=list)
    reason: str = ""


# -- extraction ----------------------------------------------------------------------------------
def split_references(text: str) -> Tuple[str, List[str]]:
    """(body, entries). The reference list starts at the last 'References' heading."""
    matches = list(REFERENCES_HEADING.finditer(text))
    if not matches:
        return text, []
    start = matches[-1]
    body, tail = text[: start.start()], text[start.end() :]
    entries: List[str] = []
    for line in tail.splitlines():
        if not line.strip():
            if entries and not entries[-1].endswith("\n"):
                entries[-1] += "\n"  # a blank line closes an unnumbered entry
            continue
        if _LABEL.match(line) or not entries or entries[-1].endswith("\n"):
            entries.append(line.strip())
        else:
            entries[-1] += " " + line.strip()
    return body, [" ".join(e.split()) for e in entries if e.strip()]


def _surname(entry: str) -> str:
    text = _LABEL.sub("", entry, count=1).strip()
    first = re.split(r"\s+(?:and|&)\s+|;|,\s*&", text, 1)[0]
    chunk = first.split(",")[0].strip()
    words = chunk.replace(".", ". ").split()
    if not words:
        return ""
    if re.fullmatch(r"(?:[A-Z]\.?)+", words[0]) and len(words) > 1:  # "J. Smith"
        words = [w for w in words if not re.fullmatch(r"(?:[A-Z]\.?)+", w)]
    return re.sub(r"[^\w'’-]", "", words[-1] if "," not in first else words[0]) if words else ""


def parse_reference(entry: str) -> Reference:
    label = _LABEL.match(entry)
    ident = (label.group(1) or label.group(2)) if label else ""
    years = _YEAR.findall(entry)
    return Reference(
        label=ident,
        raw=entry,
        doi=find_doi(entry),
        arxiv=find_arxiv(entry),
        year=int(years[0]) if years else None,
        surname=_surname(entry),
    )


def _expand(spec: str) -> List[str]:
    out: List[str] = []
    for part in re.split(r"\s*[,;]\s*", spec):
        span = re.split(r"\s*[–-]\s*", part)
        if (
            len(span) == 2
            and span[0].isdigit()
            and span[1].isdigit()
            and 0 < int(span[1]) - int(span[0]) < 50
        ):
            out += [str(n) for n in range(int(span[0]), int(span[1]) + 1)]
        elif part.strip().isdigit():
            out.append(str(int(part)))
    return out


def in_text_citations(body: str) -> List[Citation]:
    found: List[Citation] = []
    for m in _NUMERIC.finditer(body):
        found += [Citation("numeric", n, m.start()) for n in _expand(m.group(1))]
    for m in _NARRATIVE.finditer(body):
        found.append(Citation("author-year", f"{m.group(1).lower()}|{m.group(2)}", m.start()))
    for paren in _PAREN.finditer(body):
        for part in paren.group(1).split(";"):
            hit = _AUTHOR_YEAR.search(part)
            if hit:
                found.append(
                    Citation("author-year", f"{hit.group(1).lower()}|{hit.group(2)}", paren.start())
                )
    return sorted(found, key=lambda c: (c.position, c.key))


# -- resolution ------------------------------------------------------------------------------------
def _title_tokens(doc: Doc) -> Set[str]:
    return set(tokens(doc.bib.title)) if doc.bib.title else set()


def resolve(reference: Reference, docs: Sequence[Doc], citing: str = "") -> Resolution:
    pool = [d for d in docs if d.doc_id != citing]
    for field_name, value in (("doi", reference.doi), ("arxiv", reference.arxiv)):
        if value:
            hits = [d.doc_id for d in pool if getattr(d.bib, field_name) == value]
            if len(hits) == 1:
                return Resolution(reference, "resolved", hits, field_name)
            if len(hits) > 1:
                return Resolution(reference, "ambiguous", sorted(hits), f"several {field_name}")
    ref_tokens = set(tokens(reference.raw))
    hits = []
    for d in pool:
        title = _title_tokens(d)
        if len(title) >= MIN_TITLE_TOKENS and len(title & ref_tokens) / len(title) >= CONTAINMENT:
            if not (reference.year and d.bib.year and reference.year != d.bib.year):
                hits.append(d.doc_id)
    if len(hits) == 1:
        return Resolution(reference, "resolved", hits, "title")
    if len(hits) > 1:
        return Resolution(reference, "ambiguous", sorted(hits), "several titles match")
    weak = [
        d.doc_id
        for d in pool
        if reference.surname
        and reference.year
        and d.bib.year == reference.year
        and any(a.split()[-1].lower() == reference.surname.lower() for a in d.bib.authors)
    ]
    if weak:
        return Resolution(reference, "weak", sorted(weak), "author and year only")
    return Resolution(reference, "unresolved")


def link_in_text(
    citations: Sequence[Citation], references: Sequence[Reference]
) -> Tuple[Dict[int, List[Citation]], List[Tuple[Citation, str]]]:
    """Map each reference (index) to its in-text citations; return the ones that cannot be linked
    as (citation, reason) - missing label, no entry, or several author-year entries."""
    linked: Dict[int, List[Citation]] = {}
    broken: List[Tuple[Citation, str]] = []
    for c in citations:
        if c.kind == "numeric":
            hits = [i for i, r in enumerate(references) if r.label == c.key]
        else:
            name, year = c.key.split("|")
            hits = [
                i
                for i, r in enumerate(references)
                if r.surname.lower() == name and str(r.year) == year
            ]
        if len(hits) == 1:
            linked.setdefault(hits[0], []).append(c)
        else:
            broken.append((c, "no reference entry" if not hits else "several entries match"))
    return linked, broken


# -- the corpus graph --------------------------------------------------------------------------
@dataclass
class CitationReport:
    edges: List[Tuple[str, str]]  # citing -> cited (corpus documents only)
    resolutions: Dict[str, List[Resolution]]
    broken: Dict[str, List[Tuple[Citation, str]]]
    scope: Dict[str, Any]
    reference_of: Dict[Tuple[str, str], str] = field(default_factory=dict)

    def triples(self) -> List[Tuple[str, str, str]]:
        """(citing, cited, the reference line that links them)."""
        return [(a, b, self.reference_of.get((a, b), "")) for a, b in self.edges]

    # -- graph metrics (all deterministic) ---------------------------------------------------------
    def nodes(self) -> List[str]:
        return sorted(self.scope["document_ids"])

    def in_degree(self) -> Dict[str, int]:
        d = {n: 0 for n in self.nodes()}
        for _, cited in self.edges:
            d[cited] += 1
        return d

    def out_degree(self) -> Dict[str, int]:
        d = {n: 0 for n in self.nodes()}
        for citing, _ in self.edges:
            d[citing] += 1
        return d

    def cocitation(self) -> Dict[str, int]:
        """Pairs cited together by the same document: count of citing documents."""
        by_citing: Dict[str, List[str]] = {}
        for citing, cited in self.edges:
            by_citing.setdefault(citing, []).append(cited)
        out: Dict[str, int] = {}
        for group in by_citing.values():
            ordered = sorted(set(group))
            for i, a in enumerate(ordered):
                for b in ordered[i + 1 :]:
                    out[f"{a}|{b}"] = out.get(f"{a}|{b}", 0) + 1
        return dict(sorted(out.items()))

    def coupling(self) -> Dict[str, int]:
        """Pairs of documents that cite the same references (corpus or not): shared count."""
        keys: Dict[str, Set[str]] = {}
        for doc_id, rows in self.resolutions.items():
            keys[doc_id] = {
                (r.doc_ids[0] if r.status == "resolved" else r.reference.key) for r in rows
            }
        ids = sorted(keys)
        out: Dict[str, int] = {}
        for i, a in enumerate(ids):
            for b in ids[i + 1 :]:
                shared = len(keys[a] & keys[b])
                if shared:
                    out[f"{a}|{b}"] = shared
        return out

    def centrality(self, damping: float = 0.85, iterations: int = 100) -> Dict[str, float]:
        """PageRank on the citation graph (a cited document inherits from its citers)."""
        nodes = self.nodes()
        n = len(nodes)
        if not n:
            return {}
        out_deg = self.out_degree()
        rank = {x: 1.0 / n for x in nodes}
        for _ in range(iterations):
            sink = sum(rank[x] for x in nodes if not out_deg[x])
            new = {x: (1 - damping) / n + damping * sink / n for x in nodes}
            for citing, cited in self.edges:
                new[cited] += damping * rank[citing] / out_deg[citing]
            delta = sum(abs(new[x] - rank[x]) for x in nodes)
            rank = new
            if delta < 1e-12:
                break
        return {x: round(v, 8) for x, v in rank.items()}

    def unresolved(self) -> List[Dict[str, Any]]:
        return [
            {"document": d, "reference": r.reference.raw[:200], "status": r.status,
             "candidates": r.doc_ids}
            for d, rows in sorted(self.resolutions.items())
            for r in rows
            if r.status != "resolved"
        ]  # fmt: skip


def analyse(docs: Sequence[Doc]) -> CitationReport:
    edges: Set[Tuple[str, str]] = set()
    reference_of: Dict[Tuple[str, str], str] = {}
    resolutions: Dict[str, List[Resolution]] = {}
    broken: Dict[str, List[Tuple[Citation, str]]] = {}
    with_refs = total_refs = resolved = 0
    for doc in docs:
        body, entries = split_references(doc.text)
        if not entries:
            continue
        with_refs += 1
        refs = [parse_reference(e) for e in entries]
        rows = [resolve(r, docs, doc.doc_id) for r in refs]
        resolutions[doc.doc_id] = rows
        total_refs += len(rows)
        for row in rows:
            if row.status == "resolved":
                resolved += 1
                edges.add((doc.doc_id, row.doc_ids[0]))
                reference_of.setdefault((doc.doc_id, row.doc_ids[0]), row.reference.raw)
        _, bad = link_in_text(in_text_citations(body), refs)
        if bad:
            broken[doc.doc_id] = bad
    return CitationReport(
        sorted(edges),
        resolutions,
        broken,
        {
            "documents": len(docs),
            "document_ids": [d.doc_id for d in docs],
            "documents_with_reference_list": with_refs,
            "references": total_refs,
            "resolved": resolved,
            "unresolved_or_flagged": total_refs - resolved,
        },
        reference_of,
    )


def summary(report: CitationReport, kind: str = "summary") -> Dict[str, Any]:
    scope = {k: v for k, v in report.scope.items() if k != "document_ids"}
    if kind == "edges":
        body: Any = [{"citing": a, "cited": b} for a, b in report.edges]
    elif kind == "cocitation":
        body = report.cocitation()
    elif kind == "coupling":
        body = report.coupling()
    elif kind == "centrality":
        body = {"in_degree": report.in_degree(), "pagerank": report.centrality()}
    elif kind == "unresolved":
        body = report.unresolved()
    else:
        body = {
            "edges": len(report.edges),
            "in_degree": report.in_degree(),
            "out_degree": report.out_degree(),
            "citations_without_entry": sum(len(v) for v in report.broken.values()),
        }
    return {"scope": scope, kind if kind != "summary" else "summary": body}
