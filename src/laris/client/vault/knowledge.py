"""User knowledge by domain: new knowledge joins the brain's domain hubs without changing the brain.

The protected system brain (`.laris/brain/`) never changes at runtime. New knowledge from the
user's documents or teaching is written to the project vault under `Knowledge/<Domain hub>/`. The
brain navigation tools list those notes next to the matching domain hub, so reasoning finds them by
walking the same tree. Notes made from documents are untrusted data. Skills are separate: they are
created only when the user asks (`save_skill`), never on ingestion.
"""

import re
from dataclasses import dataclass
from typing import Any, List, Optional, Sequence

from laris.client.application.workspace import Chunk
from laris.shared.brain import Brain
from laris.shared.config.runtime_schemas import BrainConfig
from laris.shared.vault.notes import wikilink
from laris.shared.vault.project import ProjectVault, RecordResult
from laris.shared.vault.writer import safe_title

KNOWLEDGE_SUFFIX = " (knowledge)"
HUB_SUFFIX = " (user knowledge)"
_SENTENCE = re.compile(r"\s+")


@dataclass
class KnowledgeResult:
    domain: str
    note: RecordResult


def domain_titles(brain: Brain) -> List[str]:
    """The domain hubs (level 1) a knowledge note can belong to."""
    return sorted({t for t in brain.routes.values()})


def classify(brain: Brain, text: str, general: str, hint: str = "") -> str:
    """The domain hub for a text: an explicit hint that names a hub, else keyword routing."""
    hubs = {h.lower(): h for h in domain_titles(brain)}
    if hint and hint.strip().lower() in hubs:
        return hubs[hint.strip().lower()]
    routed = brain.route(text)
    return routed[0] if routed else general


def _short(text: str, limit: int) -> str:
    flat = _SENTENCE.sub(" ", text).strip()
    return flat if len(flat) <= limit else flat[: limit - 1].rstrip() + "…"


class KnowledgeWriter:
    def __init__(self, vault: ProjectVault, brain: Brain, cfg: BrainConfig, redact: Any) -> None:
        self.vault, self.brain, self.cfg = vault, brain, cfg
        self.redact = redact
        self.folder = vault.cfg.knowledge_dir

    def _hub_note(self, domain: str) -> RecordResult:
        """The per-domain list of user knowledge, rebuilt inside its managed block."""
        from laris.shared.vault.index import VaultIndex

        index = VaultIndex.build(self.vault.root / self.folder / safe_title(domain))
        rows = [
            f"- {wikilink(n.title)} - {_short(str(n.props.get('summary', '')), 140)}"
            for _, n in sorted(index.notes.items())
            if n.props.get("type") == "knowledge"
        ]
        title = safe_title(domain) + HUB_SUFFIX
        return self.vault._write(
            f"{self.folder}/{safe_title(domain)}",
            title,
            {"type": "knowledge-hub", "domain": domain, "created": self.vault._today()},
            {"items": "\n".join(rows) or "_Nothing yet._"},
            lead=f"# {title}\n\nKnowledge added by use, under the system domain hub {domain}.",
        )

    def add(
        self,
        title: str,
        body_lines: Sequence[str],
        summary: str,
        domain: str,
        origin: str,
        source: str = "",
        trust: str = "untrusted",
    ) -> KnowledgeResult:
        name = safe_title(title)
        name = name if name.endswith(KNOWLEDGE_SUFFIX.strip()) else name + KNOWLEDGE_SUFFIX
        props = {
            "type": "knowledge",
            "trust": trust,
            "domain": domain,
            "summary": _short(self.redact(summary)[0], self.cfg.summary_max_chars),
            "origin": origin,
            "created": self.vault._today(),
        }
        if source:
            props["source"] = wikilink(source)
        body = self.redact("\n".join(body_lines))[0]
        result = self.vault._write(
            f"{self.folder}/{safe_title(domain)}",
            name,
            props,
            {"knowledge": body},
            lead=f"# {name}\n\nDomain hub: {domain}",
        )
        if result.status != "skipped":
            self._hub_note(domain)
        return KnowledgeResult(domain, result)

    # -- from an ingested document ------------------------------------------------------------
    def add_document(
        self, source_title: str, chunks: Sequence[Chunk], terms: Sequence[str]
    ) -> Optional[KnowledgeResult]:
        text = " ".join(c.text for c in chunks)[: self.cfg.knowledge_extract_chars]
        domain = classify(self.brain, " ".join([*terms, text]), self.cfg.general_hub)
        lines: List[str] = []
        summary = ", ".join(terms[:8]) or _short(text, 160)
        if terms:
            lines.append("Key terms: " + ", ".join(terms))
        claims: List[str] = []
        try:
            from laris.shared.scientific.extractor import ScientificDiscourseExtractor

            found = ScientificDiscourseExtractor().extract("doc", text)
            claims = [c.text for c in found.claims][: self.cfg.knowledge_max_claims]
            for label, items in (
                ("Methods", found.methods),
                ("Datasets", found.datasets),
                ("Metrics", found.metrics),
            ):
                names = sorted({i.name for i in items})[:8]
                if names:
                    lines.append(f"{label}: " + ", ".join(names))
        except Exception:  # extraction is best effort; the note still records terms and source
            pass
        if claims:
            lines.append("Claims stated in the document:")
            lines += [f"- {_short(c, 280)}" for c in claims]
            summary = _short(claims[0], self.cfg.summary_max_chars)
        lines.append(f"Source note: {wikilink(source_title)}")
        stem = source_title.removesuffix(" (source)")
        return self.add(stem, lines, summary, domain, "ingest", source=source_title)

    # -- from the user's teaching --------------------------------------------------------------
    def add_taught(self, title: str, content: str, domain_hint: str = "") -> KnowledgeResult:
        domain = classify(self.brain, f"{title} {content}", self.cfg.general_hub, domain_hint)
        return self.add(
            title,
            [content.strip()],
            _short(content, self.cfg.summary_max_chars),
            domain,
            "user",
            trust="user",
        )
