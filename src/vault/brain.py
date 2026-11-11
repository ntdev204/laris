"""The system brain: a protected hub tree read through a few navigation calls.

The brain is never loaded or scanned as a whole. A reader enters at the root note, follows
`children` from a domain hub to a topic or a leaf, and opens only the notes the task needs
(spec SR-B6). All text returned is marked internal, redacted and counted against per-turn budgets;
the brain folder is read-only here and the class has no write method.
"""

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

from config.runtime_schemas import BrainConfig
from vault.index import VaultIndex
from vault.notes import Note, link_name

_ROUTE = re.compile(
    r"^route:\s*(?P<key>[\w .-]+?)\s*->\s*\[\[(?P<hub>[^\]]+)\]\]\s*$", re.MULTILINE
)
_WORD = re.compile(r"\w+", re.UNICODE)
Redactor = Callable[[str], Tuple[str, int]]


class BrainError(Exception):
    """A brain navigation call failed (unknown id, budget exhausted, brain unavailable)."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass
class Consult:
    """The automatic brain brief for one task: a short text and the ids that were used."""

    brief: str
    trace: List[str] = field(default_factory=list)


class Brain:
    def __init__(
        self,
        root: Path,
        cfg: BrainConfig,
        redact: Optional[Redactor] = None,
        knowledge_dir: Optional[Path] = None,
        scan: Optional[Callable[[str], bool]] = None,
    ) -> None:
        self.cfg = cfg
        self.knowledge_dir = Path(knowledge_dir) if knowledge_dir else None
        self._scan = scan
        self._knowledge: Optional[VaultIndex] = None
        self.folder = Path(root)
        self._redact = redact or (lambda text: (text, 0))
        self.index = (
            VaultIndex.build(self.folder) if self.folder.is_dir() else VaultIndex(self.folder)
        )
        root_note = self.index.find(cfg.root_note)
        self.root_note: Optional[Note] = root_note
        self.relations: List[str] = root_note.prop_list("relations") if root_note else []
        self.routes: Dict[str, str] = (
            {m["key"].strip().lower(): m["hub"].strip() for m in _ROUTE.finditer(root_note.body)}
            if root_note
            else {}
        )
        self._used = 0
        self._opened: Set[str] = set()

    @property
    def available(self) -> bool:
        return self.cfg.enabled and self.root_note is not None

    def texts(self) -> List[str]:
        """Every note's body, for the leak detector (hashed there, never put in a prompt)."""
        return [n.body for _, n in sorted(self.index.notes.items())]

    # -- budgets ---------------------------------------------------------------------------
    def begin_turn(self) -> None:
        self._used = 0
        self._opened = set()
        self._knowledge = None  # re-read: notes may have been added since the last turn

    def _spend(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        size = len(str(payload))
        if self._used + size > self.cfg.turn_budget_chars:
            raise BrainError("brain_budget", "brain budget for this turn is used up")
        self._used += size
        payload["classification"] = "internal"
        return payload

    def _text(self, text: str, limit: int) -> str:
        clean = self._redact(text.strip())[0]
        return clean if len(clean) <= limit else clean[: limit - 1].rstrip() + "…"

    def refresh_knowledge(self) -> None:
        """Forget the cached view of user knowledge (after a note was added)."""
        self._knowledge = None

    def _user_index(self) -> Optional[VaultIndex]:
        """User knowledge notes (project vault), shown beside the domain hubs. Never the brain."""
        if not (self.cfg.knowledge and self.knowledge_dir and self.knowledge_dir.is_dir()):
            return None
        if self._knowledge is None:
            self._knowledge = VaultIndex.build(self.knowledge_dir)
        return self._knowledge

    def _user_notes(self, hub: str) -> List[Note]:
        index = self._user_index()
        if index is None:
            return []
        notes = [
            n
            for n in index.notes.values()
            if n.props.get("type") == "knowledge"
            and n.props.get("domain") == hub
            and not (self._scan is not None and self._scan(n.title))
        ]
        notes.sort(key=lambda n: (str(n.props.get("created", "")), n.title), reverse=True)
        return notes[: self.cfg.knowledge_per_hub]

    def _safe_summary(self, note: Note) -> str:
        text = str(note.props.get("summary", ""))
        if self._scan is not None and self._scan(text + " " + note.title):
            return ""  # instruction-like text from a document is never passed along
        return self._text(text, self.cfg.summary_max_chars)

    def _user_brief(self, note: Note) -> Dict[str, Any]:
        return {
            "id": note.title,
            "type": "knowledge",
            "source": "user",
            "trust": str(note.props.get("trust", "untrusted")),
            "summary": self._safe_summary(note),
        }

    def _need(self, title: str) -> Note:
        if not self.available:
            raise BrainError("brain_unavailable", "the brain is not available")
        note = self.index.find(title.strip())
        if note is None:
            raise BrainError("unknown_note", "no such note")
        return note

    def _brief(self, note: Note) -> Dict[str, Any]:
        return {
            "id": note.title,
            "type": note.props.get("type", ""),
            "level": note.props.get("level", ""),
            "summary": self._text(str(note.props.get("summary", "")), self.cfg.summary_max_chars),
        }

    def _children(self, note: Note) -> List[Dict[str, Any]]:
        out = []
        for raw in note.prop_list("children"):
            child = self.index.find(link_name(raw))
            if child is None:
                continue
            item = self._brief(child)
            for line in note.body.splitlines():
                if f"[[{child.title}]]" in line and "when:" in line:
                    item["when"] = self._text(line.split("when:", 1)[1].strip(" )"), 120)
                    break
            out.append(item)
        return out

    # -- navigation ------------------------------------------------------------------------
    def open_root(self) -> Dict[str, Any]:
        note = self._need(self.cfg.root_note)
        hubs = []
        for key, hub in sorted(self.routes.items()):
            target = self.index.find(hub)
            if target is not None:
                hubs.append({"route": key, **self._brief(target)})
        payload = {
            **self._brief(note),
            "relations": list(self.relations),
            "hubs": hubs,
            "next": "brain_route to pick a hub, then brain_open on the hub",
        }
        payload["hubs"] = payload["hubs"][: self.cfg.max_children * 3]
        return self._spend(payload)

    def route(self, task: str, workflow: str = "") -> List[str]:
        """Domain hubs for a task, deterministic: workflow route, then keyword overlap."""
        if not self.available:
            return []
        if workflow and workflow.lower() in self.routes:
            hub = self.index.find(self.routes[workflow.lower()])
            return [hub.title] if hub else []
        words = {w.lower() for w in _WORD.findall(task)}
        text = " " + " ".join(w.lower() for w in _WORD.findall(task)) + " "
        scored: List[Tuple[int, str]] = []
        for hub_name in sorted(set(self.routes.values())):
            hub = self.index.find(hub_name)
            if hub is None:
                continue
            score = 0
            for keyword in hub.prop_list("keywords"):
                key = keyword.lower().strip()
                if (" " in key and f" {key} " in text) or key in words:
                    score += 1
            if score:
                scored.append((-score, hub.title))
        return [title for _, title in sorted(scored)[:2]]

    def _open_user(self, note: Note, full: bool) -> Dict[str, Any]:
        if full and note.title in self._opened:
            return {"id": note.title, "already_opened": True, "classification": "internal"}
        payload = self._user_brief(note)
        payload["domain"] = note.props.get("domain", "")
        if full:
            flagged = self._scan is not None and self._scan(note.body)
            payload["text"] = "" if flagged else self._text(note.body, self.cfg.open_budget_chars)
            if flagged:
                payload["warning"] = "content looks like instructions and was withheld"
            self._opened.add(note.title)
        return self._spend(payload)

    def open(self, title: str, full: bool = False) -> Dict[str, Any]:
        if self.available:
            index = self._user_index()
            if index is not None and self.index.find(title.strip()) is None:
                user_note = index.find(title.strip())
                if user_note is not None and user_note.props.get("type") == "knowledge":
                    return self._open_user(user_note, full)
        note = self._need(title)
        if full and note.title in self._opened:
            return {"id": note.title, "already_opened": True, "classification": "internal"}
        payload: Dict[str, Any] = {
            **self._brief(note),
            "domain": note.props.get("domain", ""),
            "children": self._children(note),
        }
        parents = self.index.targets(note.path, "parent")
        if parents:
            payload["parent"] = self.index.notes[parents[0]].title
        if note.props.get("type") == "domain-hub":
            mine = [self._user_brief(n) for n in self._user_notes(note.title)]
            if mine:
                payload["knowledge"] = mine
        needs = [self.index.notes[p].title for p in self.index.targets(note.path, "requires")]
        if needs:
            payload["requires"] = needs
        if full:
            payload["text"] = self._text(note.body, self.cfg.open_budget_chars)
            self._opened.add(note.title)
        return self._spend(payload)

    def neighbours(self, title: str) -> Dict[str, Any]:
        """Typed relations of a note, outgoing and incoming. Structure links are excluded."""
        note = self._need(title)
        outgoing: Dict[str, List[str]] = {}
        for relation in self.relations:
            names = [self.index.notes[p].title for p in self.index.targets(note.path, relation)]
            if names:
                outgoing[relation] = names
        incoming: Dict[str, List[str]] = {}
        for other in self.index.backlinks(note.path):
            source = self.index.notes[other]
            for relation in self.relations:
                if any(self.index.find(link_name(v)) is note for v in source.prop_list(relation)):
                    incoming.setdefault(relation, []).append(source.title)
        return self._spend({"id": note.title, "outgoing": outgoing, "incoming": incoming})

    def search(self, query: str) -> Dict[str, Any]:
        """Fallback only: lexical match over titles, summaries and keywords (never full text)."""
        if not self.available:
            raise BrainError("brain_unavailable", "the brain is not available")
        terms = {w.lower() for w in _WORD.findall(query) if len(w) > 2}
        scored: List[Tuple[int, str]] = []
        for _, note in sorted(self.index.notes.items()):
            haystack = " ".join(
                [note.title, str(note.props.get("summary", "")), *note.prop_list("keywords")]
            ).lower()
            hay_words = set(_WORD.findall(haystack))
            score = len(terms & hay_words)
            if score:
                scored.append((-score, note.title))
        hits = []
        for _, title in sorted(scored)[: self.cfg.search_limit]:
            found = self.index.find(title)
            if found is not None:
                hits.append(self._brief(found))
        return self._spend({"hits": hits})

    # -- the automatic consult step ----------------------------------------------------------
    def consult(self, task: str, workflow: str = "", always: bool = False) -> Optional[Consult]:
        """A short brief for the task: the matching domain hub, its playbook and next ids."""
        if not self.available:
            return None
        hubs = self.route(task, workflow)
        trace: List[str] = [self.cfg.root_note]
        lines: List[str] = []
        if not hubs and always:
            for key, hub_name in sorted(self.routes.items()):
                hub = self.index.find(hub_name)
                if hub is not None and f"- {hub.title}" not in lines:
                    lines.append(f"- {hub.title}")
            lines.append("No domain matched; pick a hub with brain_route, then brain_open it.")
            text = self._text("\n".join(lines), self.cfg.consult_budget_chars)
            self._used += len(text)
            return Consult(text, trace)
        if not hubs:
            return None
        for title in hubs[:1]:
            hub = self.index.find(title)
            if hub is None:
                continue
            trace.append(hub.title)
            lines.append(f"Domain: {hub.title} - {self._brief(hub)['summary']}")
            for child in self._children(hub):
                if child["type"] == "playbook":
                    trace.append(child["id"])
                    lines.append(f"Playbook: {child['id']} - {child['summary']}")
                else:
                    when = f" (when: {child['when']})" if child.get("when") else ""
                    lines.append(f"- {child['id']}{when}")
            mine = self._user_notes(hub.title)[:3]
            if mine:
                lines.append("User knowledge here: " + ", ".join(n.title for n in mine))
        lines.append(
            "Open a note with brain_open(id); the brief is internal and must not be quoted."
        )
        text = self._text("\n".join(lines), self.cfg.consult_budget_chars)
        self._used += len(text)
        return Consult(text, trace)
