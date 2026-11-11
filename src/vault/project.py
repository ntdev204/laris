"""The project vault: an Obsidian-format folder in the user's codebase, kept up to date.

Created on the first piece of work (an ingest, a chat turn or `laris vault init`). After that, each
unit of work becomes a linked note: Sources, Concepts, Sessions and Q&A. LARIS writes only inside
its managed blocks, so anything the user adds stays (see `vault.writer`). Notes made from documents
are untrusted data: they pass the injection scan on the way in and carry `trust: untrusted`.
"""

import datetime
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence

from config.runtime_schemas import VaultConfig
from vault.index import VaultIndex
from vault.notes import wikilink
from vault.writer import Scanner, VaultWriter, resolve_inside, safe_title

SOURCE_SUFFIX = " (source)"  # keeps source names distinct from concepts of the same word
MEMORY_SUFFIX = " (memory)"
FOLDERS = ("Sources", "Concepts", "Claims", "Questions", "Sessions", "Decisions", "Memory")
APP_SETTINGS = {"useMarkdownLinks": False, "newLinkFormat": "shortest", "alwaysUpdateLinks": True}
GITIGNORE = ".obsidian/workspace.json\n.obsidian/workspace-mobile.json\n"
SESSION_BLOCK = "session"


def source_title(source: str) -> str:
    """The note name for a source path; ingest and answers use the same rule so links resolve."""
    return safe_title(Path(source).stem or source) + SOURCE_SUFFIX


@dataclass
class RecordResult:
    note: str
    status: str  # created | updated | unchanged | conflict | skipped
    reason: str = ""


class ProjectVault:
    def __init__(
        self,
        project_root: Path,
        cfg: VaultConfig,
        scan: Optional[Scanner] = None,
        clock: Optional[Any] = None,
    ) -> None:
        folder = Path(cfg.dir)
        self.cfg = cfg
        self.root = folder if folder.is_absolute() else Path(project_root) / folder
        self.writer = VaultWriter(self.root, cfg.max_note_chars, scan)
        self._now = clock or (lambda: datetime.datetime.now(datetime.timezone.utc))

    @property
    def exists(self) -> bool:
        return self.root.is_dir() and (self.root / ".obsidian").is_dir()

    # -- bootstrap -------------------------------------------------------------------------
    def ensure(self) -> bool:
        """Create the skeleton if missing. Returns True when something was created."""
        created = not self.exists
        for name in (*FOLDERS, self.cfg.inbox_dir):
            (self.root / name).mkdir(parents=True, exist_ok=True)
        config = self.root / ".obsidian"
        config.mkdir(exist_ok=True)
        settings = config / "app.json"
        if not settings.exists():
            settings.write_text(json.dumps(APP_SETTINGS, indent=2) + "\n", encoding="utf-8")
        ignore = self.root / ".gitignore"
        if not ignore.exists():
            ignore.write_text(GITIGNORE, encoding="utf-8")
        index = self.root / f"{self.cfg.index_note}.md"
        if not index.exists():
            self.writer.write_note(
                f"{self.cfg.index_note}.md",
                {"type": "index", "created": self._today()},
                {"index": "_Nothing recorded yet._"},
                lead=f"# {self.cfg.index_note}\n\nMap of this project's knowledge. "
                "Notes link to each other; start from the lists below.",
            )
        return created

    def _today(self) -> str:
        return self._now().date().isoformat()

    # -- recording -------------------------------------------------------------------------
    def _write(
        self, folder: str, title: str, props: Dict[str, Any], blocks: Dict[str, str], lead: str = ""
    ) -> RecordResult:
        self.ensure()
        rel = f"{folder}/{safe_title(title)}.md"
        try:
            status = self.writer.write_note(rel, props, blocks, lead)
        except ValueError as exc:
            return RecordResult(rel, "skipped", str(exc))
        return RecordResult(rel, status)

    def record_source(
        self,
        title: str,
        source: str,
        chunk_count: int,
        terms: Sequence[str] = (),
        excerpt: str = "",
    ) -> RecordResult:
        concepts = [safe_title(t) for t in terms if t.strip()]
        body = [f"- Source file: `{source}`", f"- Passages indexed: {chunk_count}"]
        if concepts:
            body.append("- Key terms: " + ", ".join(wikilink(c) for c in concepts))
        if excerpt.strip():
            body.append("\n> " + " ".join(excerpt.split())[: self.cfg.snippet_chars])
        for term in concepts:
            self.record_concept(term, safe_title(title))
        return self._write(
            "Sources",
            title,
            {
                "type": "source",
                "trust": "untrusted",
                "source": source,
                "created": self._today(),
                "concepts": [wikilink(c) for c in concepts],
            },
            {"source": "\n".join(body)},
            lead=f"# {safe_title(title)}",
        )

    def record_concept(self, term: str, from_source: str = "") -> RecordResult:
        name = safe_title(term)
        found = self._existing(f"Concepts/{name}.md")
        mentions = [from_source] if from_source else []
        if found:
            for old in self._mentions(found):
                if old not in mentions:
                    mentions.append(old)
        lines = [f"- Mentioned in {wikilink(m)}" for m in sorted(set(mentions))[:50]]
        return self._write(
            "Concepts",
            name,
            {"type": "concept", "created": self._today()},
            {"mentions": "\n".join(lines) or "_No sources yet._"},
            lead=f"# {name}",
        )

    def record_answer(
        self, session_id: str, question: str, answer: str, sources: Iterable[str] = ()
    ) -> RecordResult:
        """One Q&A note linked to its session and to the sources it cited."""
        stamp = self._now().strftime("%Y-%m-%d %H%M%S")
        title = safe_title(f"{stamp} {question}")[:80]
        cited = [safe_title(s) for s in sources if s]
        lines = [
            f"**Question:** {' '.join(question.split())[:600]}",
            "",
            f"**Answer:** {' '.join(answer.split())[: self.cfg.max_note_chars // 2]}",
        ]
        if cited:
            lines += ["", "Sources: " + ", ".join(wikilink(s) for s in cited)]
        result = self._write(
            "Questions",
            title,
            {
                "type": "answer",
                "trust": "model",
                "session": wikilink(self.session_title(session_id)),
                "created": self._today(),
                "sources": [wikilink(s) for s in cited],
            },
            {"qa": "\n".join(lines)},
            lead=f"# {title}",
        )
        self.record_session(session_id, [title])
        return result

    def session_title(self, session_id: str) -> str:
        return safe_title(f"{self._today()} Session {session_id[:8]}")

    def record_session(self, session_id: str, notes: Sequence[str]) -> RecordResult:
        title = self.session_title(session_id)
        rel = f"Sessions/{title}.md"
        existing = self._existing(rel)
        seen = self._listed(existing)
        for name in notes:
            if name not in seen:
                seen.append(name)
        lines = [f"- {wikilink(n)}" for n in seen[:200]]
        return self._write(
            "Sessions",
            title,
            {"type": "session", "created": self._today()},
            {SESSION_BLOCK: "\n".join(lines)},
            lead=f"# {title}",
        )

    def record_memory(self, name: str, text: str) -> RecordResult:
        return self._write(
            "Memory",
            safe_title(name) + MEMORY_SUFFIX,
            {"type": "memory", "created": self._today()},
            {"memory": text.strip()},
            lead=f"# {safe_title(name)}",
        )

    def propose(self, title: str, text: str, origin: str) -> RecordResult:
        """Learnings go to the inbox, not into retrieval, until the owner accepts them."""
        return self._write(
            self.cfg.inbox_dir,
            title,
            {"type": "proposal", "status": "pending", "origin": origin, "created": self._today()},
            {"proposal": text.strip()},
            lead=f"# {safe_title(title)}",
        )

    # -- the index note ----------------------------------------------------------------------
    def refresh_index(self) -> RecordResult:
        """Rewrite the managed block of the index: counts per folder and the latest notes."""
        self.ensure()
        index = VaultIndex.build(self.root)
        rows: List[str] = []
        for folder in FOLDERS:
            members = sorted(p for p in index.notes if p.startswith(folder + "/"))
            rows.append(f"- **{folder}**: {len(members)}")
        latest = sorted(
            (p for p in index.notes if p.split("/")[0] in FOLDERS),
            key=lambda p: (str(index.notes[p].props.get("created", "")), p),
            reverse=True,
        )[: self.cfg.index_recent]
        rows += ["", "Latest:"] + [f"- {wikilink(index.notes[p].title)}" for p in latest]
        rel = f"{self.cfg.index_note}.md"
        status = self.writer.write_note(rel, {}, {"index": "\n".join(rows)})
        return RecordResult(rel, status)

    # -- helpers ---------------------------------------------------------------------------
    def _existing(self, relative: str) -> str:
        try:
            path = resolve_inside(self.root, relative)
        except ValueError:
            return ""
        return path.read_text(encoding="utf-8") if path.is_file() else ""

    @staticmethod
    def _block_lines(text: str, name: str) -> List[str]:
        marker = f"<!-- laris:begin {name} "
        if marker not in text:
            return []
        inner = text.split(marker, 1)[1].split("-->", 1)[1].split("<!-- laris:end", 1)[0]
        return [line.strip() for line in inner.strip().splitlines() if line.strip()]

    def _listed(self, text: str) -> List[str]:
        return [
            line[2:].strip()[2:-2]
            for line in self._block_lines(text, SESSION_BLOCK)
            if line.startswith("- [[") and line.endswith("]]")
        ]

    def _mentions(self, text: str) -> List[str]:
        return [
            line.split("[[", 1)[1].rstrip("]")
            for line in self._block_lines(text, "mentions")
            if "[[" in line
        ]
