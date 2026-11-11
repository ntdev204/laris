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
FOLDERS = (
    "Sources",
    "Concepts",
    "Claims",
    "Questions",
    "Sessions",
    "Decisions",
    "Memory",
    "Analyses",
)
TEMPLATES_DIR = "_templates"
_FRONT = "---\n{}\n---\n\n# {{{{title}}}}\n"
TEMPLATES = {
    "Source": _FRONT.format("type: source\ntrust: untrusted\nsource: \ncreated: \nconcepts: []"),
    "Concept": _FRONT.format("type: concept\ncreated: "),
    "Question": _FRONT.format("type: answer\ntrust: model\nsession: \ncreated: \nsources: []"),
    "Session": _FRONT.format("type: session\ncreated: "),
}
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
        protected: Sequence[Path] = (),
    ) -> None:
        folder = Path(cfg.dir)
        self.cfg = cfg
        self.root = folder if folder.is_absolute() else Path(project_root) / folder
        self.writer = VaultWriter(
            self.root,
            cfg.max_note_chars,
            scan,
            backup=cfg.backup,
            max_writes_per_minute=cfg.max_writes_per_minute,
        )
        self.protected = [Path(p).resolve() for p in protected]  # the system brain and the like
        self._now = clock or (lambda: datetime.datetime.now(datetime.timezone.utc))

    def enclosing_vault(self) -> Optional[Path]:
        """The nearest folder above this vault that is itself an Obsidian vault, if any."""
        for parent in self.root.resolve().parents:
            if (parent / ".obsidian").is_dir():
                return parent
        return None

    @property
    def exists(self) -> bool:
        return self.root.is_dir() and (self.root / ".obsidian").is_dir()

    # -- bootstrap -------------------------------------------------------------------------
    def ensure(self) -> bool:
        """Create the skeleton if missing. Returns True when something was created."""
        created = not self.exists
        here = self.root.resolve()
        for guarded in self.protected:
            if here == guarded or guarded in here.parents or here in guarded.parents:
                raise ValueError("the project vault may not overlap the protected system brain")
        outer = self.enclosing_vault()
        if created and outer is not None and not self.cfg.allow_nested:
            raise ValueError(f"refusing to create a vault inside another vault ({outer.name})")
        for name in (*FOLDERS, self.cfg.inbox_dir, TEMPLATES_DIR):
            (self.root / name).mkdir(parents=True, exist_ok=True)
        config = self.root / ".obsidian"
        config.mkdir(exist_ok=True)
        settings = config / "app.json"
        if not settings.exists():
            settings.write_text(json.dumps(APP_SETTINGS, indent=2) + "\n", encoding="utf-8")
        ignore = self.root / ".gitignore"
        if not ignore.exists():
            ignore.write_text(GITIGNORE, encoding="utf-8")
        for name, text in TEMPLATES.items():
            target = self.root / TEMPLATES_DIR / f"{name}.md"
            if not target.exists():
                target.write_text(text, encoding="utf-8")
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
        rel = f"{folder}/{safe_title(title)}.md"
        try:
            self.ensure()
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
        meta: Optional[Dict[str, Any]] = None,
    ) -> RecordResult:
        """`meta` may carry `doc_id`, `sha256` (of the cleaned text), `chars` and `spans`
        (passage character ranges); they are written as properties, never guessed."""
        meta = meta or {}
        concepts = [safe_title(t) for t in terms if t.strip()]
        body = [f"- Source file: `{source}`", f"- Passages indexed: {chunk_count}"]
        if meta.get("spans"):
            first, last = meta["spans"][0], meta["spans"][-1]
            body.append(f"- Passages cover characters {first[0]} to {last[1]}")
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
                **{k: meta[k] for k in ("doc_id", "sha256", "chars", "passages") if k in meta},
                **(meta.get("bibliography") or {}),
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
        self,
        session_id: str,
        question: str,
        answer: str,
        sources: Iterable[str] = (),
        trace: Sequence[str] = (),
        notes: Sequence[str] = (),
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
        known = self._existing_titles(notes)
        extra: Dict[str, Any] = {}
        trace_lines: List[str] = []
        if trace:  # titles only: the text of the brain never reaches a note
            trace_lines.append("Brain path: " + " → ".join(safe_title(t) for t in trace))
        if known:
            trace_lines.append("Notes used: " + ", ".join(wikilink(t) for t in known))
            extra["notes_used"] = [wikilink(t) for t in known]
        result = self._write(
            "Questions",
            title,
            {
                "type": "answer",
                "trust": "model",
                "session": wikilink(self.session_title(session_id)),
                "created": self._today(),
                "sources": [wikilink(s) for s in cited],
                **extra,
            },
            {"qa": "\n".join(lines), **({"trace": "\n".join(trace_lines)} if trace_lines else {})},
            lead=f"# {title}",
        )
        self.record_session(session_id, [title])
        return result

    def _existing_titles(self, titles: Sequence[str]) -> List[str]:
        """Only notes that exist are ever linked (every cited note exists)."""
        if not titles or not self.root.is_dir():
            return []
        index = VaultIndex.build(self.root)
        found: List[str] = []
        for title in titles:
            note = index.find(safe_title(title)) or index.find(title)
            if note is not None and note.title not in found:
                found.append(note.title)
        return found

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

    def record_analysis(
        self, name: str, scope: str, text: str, sources: Sequence[str] = ()
    ) -> RecordResult:
        """An analysis result with the scope it was computed over (links the sources it used)."""
        body = text.strip()
        linked = self._existing_titles([safe_title(s) for s in sources if s])
        if linked:
            body += "\n\nSources: " + ", ".join(wikilink(c) for c in linked)
        return self._write(
            "Analyses",
            safe_title(name),
            {"type": "analysis", "scope": scope, "created": self._today()},
            {"analysis": body},
            lead=f"# {safe_title(name)}",
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
        try:
            self.ensure()
        except ValueError as exc:
            return RecordResult(f"{self.cfg.index_note}.md", "skipped", str(exc))
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
