"""Entity notes from extraction: methods, datasets, metrics, claims and limitations.

Every note carries the character span of its evidence inside the cleaned source document, so
`document_text[start:end]` is the quoted text. Ids are stable (a hash of the type and the
normalised name): the same entity found in two documents is one note with two mentions.
"""

import hashlib
import re
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Sequence, Tuple

from laris.protocol import Chunk
from laris.shared.vault.notes import wikilink
from laris.shared.vault.project import ProjectVault
from laris.shared.vault.writer import safe_title

_WS = re.compile(r"\s+")
FOLDER = {"method": "Concepts", "dataset": "Concepts", "metric": "Concepts"}


def document_text(chunks: Sequence[Chunk]) -> str:
    """The cleaned document rebuilt from its passages, each placed at its own offset."""
    parts: List[str] = []
    cursor = 0
    for chunk in sorted(chunks, key=lambda c: c.start):
        if chunk.start > cursor:
            parts.append(" " * (chunk.start - cursor))
            cursor = chunk.start
        overlap = cursor - chunk.start
        parts.append(chunk.text[overlap:] if overlap > 0 else chunk.text)
        cursor = max(cursor, chunk.start + len(chunk.text))
    return "".join(parts)


def normalise(name: str) -> str:
    return _WS.sub(" ", name).strip().lower()


def stable_id(kind: str, name: str) -> str:
    return hashlib.sha1(f"{kind}:{normalise(name)}".encode("utf-8")).hexdigest()[:10]


def _short(text: str, limit: int) -> str:
    flat = _WS.sub(" ", text).strip()
    return flat if len(flat) <= limit else flat[: limit - 1].rstrip() + "…"


@dataclass
class EntityCounts:
    notes: int = 0
    mentions: int = 0
    skipped: int = 0


class EntityWriter:
    def __init__(
        self, vault: ProjectVault, redact: Callable[[str], Tuple[Any, ...]], max_claims: int = 20
    ) -> None:
        self.vault, self.redact, self.max_claims = vault, redact, max_claims

    # -- mentions are merged across documents ---------------------------------------------------
    def _mentions(self, rel: str, new: str) -> str:
        old = self.vault._block_lines(self.vault._existing(rel), "mentions")
        lines = list(old)
        if new not in lines:
            lines.append(new)
        return "\n".join(sorted(set(lines)))

    def _mention_line(self, source_title: str, start: int, end: int, snippet: str) -> str:
        quote = _short(self.redact(snippet)[0], 160)
        return f"- {wikilink(source_title)} [{start}-{end}]: {quote}"

    def named(
        self,
        kind: str,
        name: str,
        source_title: str,
        doc_id: str,
        start: int,
        end: int,
        snippet: str,
        detail: str = "",
    ) -> bool:
        clean = safe_title(self.redact(name)[0])
        title = f"{clean} ({kind})"
        rel = f"{FOLDER[kind]}/{safe_title(title)}.md"
        existing = self.vault._existing(rel)
        mentions = self._mentions(rel, self._mention_line(source_title, start, end, snippet))
        lines = [mentions]
        if detail:
            lines.insert(0, f"- {detail}")
        body = {"mentions": "\n".join(lines)}
        result = self.vault._write(
            FOLDER[kind],
            title,
            {
                "type": kind,
                "entity_id": stable_id(kind, name),
                "aliases": [clean],
                "created": self.vault._today(),
            },
            body,
            lead=f"# {title}",
        )
        return result.status != "skipped" and bool(existing) is False

    def statement(
        self,
        kind: str,
        text: str,
        source_title: str,
        doc_id: str,
        start: int,
        end: int,
        confidence: float,
    ) -> bool:
        """A claim or limitation: one note per statement, linked to its Source with its span."""
        clean = self.redact(text)[0]
        ident = stable_id(kind, text)
        title = f"{_short(clean, 60)} [{ident[:6]}]"
        result = self.vault._write(
            "Claims",
            title,
            {
                "type": kind,
                "trust": "untrusted",
                "entity_id": ident,
                "source_ref": wikilink(source_title),
                "doc_id": doc_id,
                "char_start": start,
                "char_end": end,
                "confidence": round(confidence, 3),
                "created": self.vault._today(),
            },
            {"statement": f"> {_short(clean, 600)}"},
            lead=f"# {_short(clean, 60)}",
        )
        return result.status not in {"skipped", "conflict"}

    # -- one document ---------------------------------------------------------------------------
    def write_document(self, source_title: str, doc_id: str, text: str, found: Any) -> EntityCounts:
        counts = EntityCounts()

        def spans(records: Sequence[Any]) -> List[Tuple[Any, int, int]]:
            out = []
            for record in records:
                c = record.coordinate
                if 0 <= c.char_start < c.char_end <= len(text):
                    out.append((record, c.char_start, c.char_end))
                else:
                    counts.skipped += 1  # a span outside the text is never written
            return out

        for record, start, end in spans(found.methods):
            counts.notes += self.named(
                "method", record.name, source_title, doc_id, start, end, text[start:end]
            )
            counts.mentions += 1
        for record, start, end in spans(found.datasets):
            counts.notes += self.named(
                "dataset", record.name, source_title, doc_id, start, end, text[start:end]
            )
            counts.mentions += 1
        for record, start, end in spans(found.metrics):
            detail = (
                f"Value seen: {record.value} {record.unit or ''}".strip() if record.value else ""
            )
            counts.notes += self.named(
                "metric", record.name, source_title, doc_id, start, end, text[start:end], detail
            )
            counts.mentions += 1
        for record, start, end in spans([*found.claims, *found.results])[: self.max_claims]:
            self.statement(
                "claim", text[start:end], source_title, doc_id, start, end, record.confidence
            )
            counts.notes += 1
            counts.mentions += 1
        for record, start, end in spans(found.limitations)[: self.max_claims]:
            self.statement(
                "limitation", text[start:end], source_title, doc_id, start, end, record.confidence
            )
            counts.notes += 1
            counts.mentions += 1
        return counts


def entity_summary(counts: EntityCounts) -> Dict[str, int]:
    return {"entity_notes": counts.notes, "entity_mentions": counts.mentions}
