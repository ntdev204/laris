"""Fine-tune data collection: useful interactions are kept locally, redacted and deduplicated.

Nothing is trained here. Three datasets are written under `learning.dir` (git-ignored, never
readable by tools): `sft.jsonl` (chat examples), `retrieval.jsonl` (query with cited and uncited
passages for retrieval training) and `preference.jsonl` (rejected draft vs final answer). Turns are
stored only when they pass the quality gate; a leak, a credential or an injection flag rejects them.
"""

import hashlib
import json
import re
import threading
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from laris.client.store import Store, migrate_legacy
from laris.shared.config.runtime_schemas import LearningConfig
from laris.shared.harness.guard import Guard

SCHEMA = 1
KINDS = ("sft", "retrieval", "preference")
CITATION = re.compile(r"\[([^\]#\n]{2,}?)\s*#(\d+)\]")
_KEEP = ("role", "content", "tool_calls", "tool_call_id")


def _digest(*parts: str) -> str:
    return hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()[:16]


class Collector:
    def __init__(self, cfg: LearningConfig, root: Path, store: Optional[Store] = None) -> None:
        self.cfg = cfg
        self.dir = Path(root)
        self._lock = threading.Lock()
        self._seen: Optional[Dict[str, set]] = None
        self._store = store
        self._ready = False

    # -- storage ---------------------------------------------------------------------------
    @property
    def store(self) -> Store:
        """Opened on first use, so a disabled collector creates nothing."""
        if self._store is None:
            self.dir.mkdir(parents=True, exist_ok=True)
            try:
                self.dir.chmod(0o700)
            except OSError:
                pass
            self._store = Store(self.dir / "learning.sqlite")
        if not self._ready:
            migrate_legacy(self._store, learning=self.dir)
            self._ready = True
        return self._store

    def _ids(self) -> Dict[str, set]:
        if self._seen is None:
            self._seen = {k: {r["id"] for r in self._read(k)} for k in KINDS}
        return self._seen

    def _read(self, kind: str) -> Iterable[Dict[str, Any]]:
        if (
            self._store is None
            and not (self.dir / "learning.sqlite").exists()
            and not any((self.dir / f"{k}.jsonl").exists() for k in (*KINDS, "feedback"))
        ):
            return
        with self.store.connect() as conn:
            rows = conn.execute(
                "SELECT data FROM learning WHERE kind = ? ORDER BY id", (kind,)
            ).fetchall()
        for row in rows:
            yield json.loads(row[0])

    def _append(self, kind: str, row: Dict[str, Any]) -> bool:
        ids = self._ids()[kind]
        if row["id"] in ids:
            return False
        with self.store.transaction() as conn:
            cur = conn.execute(
                "INSERT OR IGNORE INTO learning(kind, created, data) VALUES (?,?,?)",
                (kind, float(row.get("ts", time.time())), json.dumps(row, ensure_ascii=False)),
            )
        ids.add(row["id"])
        return bool(cur.rowcount)

    # -- quality gate ----------------------------------------------------------------------
    def record(
        self,
        conversation_id: str,
        messages: List[Dict[str, Any]],
        turn: Dict[str, Any],
        guard: Guard,
    ) -> Dict[str, Any]:
        """Store one finished turn. Returns `{"stored": bool, "reason": code, "example_id": id}`."""
        if not self.cfg.enabled:
            return {"stored": False, "reason": "disabled"}
        reason = self._reject_reason(messages, turn, guard)
        if reason:
            return {"stored": False, "reason": reason}
        clean = self._clean(messages)
        final = next(
            (
                m["content"]
                for m in reversed(clean)
                if m["role"] == "assistant" and m.get("content") and not m.get("tool_calls")
            ),
            "",
        )
        if len(final) < self.cfg.min_answer_chars:
            return {"stored": False, "reason": "short_answer"}
        user = next((m["content"] for m in clean if m["role"] == "user"), "")
        example_id = _digest(user, final)
        sources = self._sources(messages)
        row = {
            "id": example_id,
            "schema": SCHEMA,
            "ts": int(time.time()),
            "conversation": conversation_id,
            "prompt_version": turn.get("prompt_version", ""),
            "workflow": turn.get("workflow", ""),
            "tools": sorted(
                {c["function"]["name"] for m in clean for c in m.get("tool_calls") or []}
            ),
            "sources": sources,
            "messages": clean,
        }
        with self._lock:
            stored = self._append("sft", row)
            self._retrieval(example_id, messages, final)
            self._preference(example_id, messages, final)
        return {
            "stored": stored,
            "reason": "ok" if stored else "duplicate",
            "example_id": example_id,
        }

    def _reject_reason(
        self, messages: List[Dict[str, Any]], turn: Dict[str, Any], guard: Guard
    ) -> str:
        if turn.get("status") != "completed":
            return "not_completed"
        if not turn.get("verified", True):
            return "unverified"
        hits = turn.get("guard_hits") or {}
        if hits.get("leak") or hits.get("secret"):
            return "guard_hit"
        for message in messages:
            text = json.dumps(message, ensure_ascii=False)
            if guard.leak.leaked(text) or guard.redactor.redact(text)[1]:
                return "sensitive"
            if message.get("role") == "tool" and '"_warning"' in str(message.get("content")):
                return "injection_flag"
        return ""

    def _clean(self, messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        limit = self.cfg.max_tool_result_chars
        for message in messages:
            if message.get("superseded") or message.get("harness") or message.get("ui_only"):
                continue
            row = {k: message[k] for k in _KEEP if k in message}
            if row.get("role") == "tool":
                content = str(row.get("content", ""))
                if not self.cfg.store_tool_results:
                    content = "[omitted]"
                elif len(content) > limit:
                    content = content[:limit] + " …[truncated]"
                row["content"] = content
            out.append(row)
        return out

    @staticmethod
    def _sources(messages: List[Dict[str, Any]]) -> List[str]:
        found: List[str] = []
        for message in messages:
            if message.get("role") != "tool":
                continue
            try:
                payload = json.loads(str(message.get("content")))
            except json.JSONDecodeError:
                continue
            for hit in (payload.get("hits") if isinstance(payload, dict) else None) or []:
                if isinstance(hit, dict) and hit.get("source") and hit["source"] not in found:
                    found.append(hit["source"])
        return found

    # -- retrieval pairs and preferences -----------------------------------------------------
    def _retrieval(self, example_id: str, messages: List[Dict[str, Any]], final: str) -> None:
        cited = {(m.group(1).strip(), int(m.group(2))) for m in CITATION.finditer(final)}
        cited_sources = {s for s, _ in cited}
        queries: Dict[str, Dict[str, Any]] = {}
        for message in messages:
            for call in message.get("tool_calls") or []:
                if call["function"]["name"] == "search_corpus":
                    try:
                        queries[call["id"]] = json.loads(call["function"]["arguments"])
                    except json.JSONDecodeError:
                        pass
        for message in messages:
            if message.get("role") != "tool" or message.get("tool_call_id") not in queries:
                continue
            try:
                result = json.loads(str(message["content"]))
            except json.JSONDecodeError:
                continue
            hits = result.get("hits") if isinstance(result, dict) else None
            if not hits:
                continue
            positives: List[Dict[str, Any]] = []
            negatives: List[Dict[str, Any]] = []
            for hit in hits:
                item = {
                    "chunk_id": hit.get("chunk_id"),
                    "source": hit.get("source"),
                    "rank": hit.get("rank"),
                    "text_sha256": hashlib.sha256(str(hit.get("text", "")).encode()).hexdigest(),
                }
                if self.cfg.store_passage_text:
                    item["text"] = hit.get("text", "")
                is_pos = (hit.get("source"), hit.get("rank")) in cited or hit.get(
                    "source"
                ) in cited_sources
                (positives if is_pos else negatives).append(item)
            if not positives:
                continue
            query = str(queries[message["tool_call_id"]].get("query", ""))
            self._append(
                "retrieval",
                {
                    "id": _digest("retrieval", query, *[p["chunk_id"] or "" for p in positives]),
                    "schema": SCHEMA,
                    "ts": int(time.time()),
                    "example": example_id,
                    "query": query,
                    "positives": positives,
                    "negatives": negatives[:5],
                },
            )

    def _preference(self, example_id: str, messages: List[Dict[str, Any]], final: str) -> None:
        for index, message in enumerate(messages):
            if message.get("superseded") and message.get("content"):
                prompt = self._clean(messages[:index])
                self._append(
                    "preference",
                    {
                        "id": _digest("pref", str(message["content"]), final),
                        "schema": SCHEMA,
                        "ts": int(time.time()),
                        "example": example_id,
                        "prompt": prompt,
                        "chosen": final,
                        "rejected": message["content"],
                        "reason": "rewritten after verification",
                    },
                )

    # -- feedback, stats, export, purge ------------------------------------------------------
    def rate(self, example_id: str, rating: str) -> Dict[str, Any]:
        if rating not in ("up", "down"):
            raise ValueError("rating must be 'up' or 'down'")
        with self._lock:
            if example_id not in self._ids()["sft"]:
                raise KeyError("unknown example")
            now = int(time.time())
            row = {"example": example_id, "rating": rating, "ts": now}
            with self.store.transaction() as conn:
                conn.execute(
                    "INSERT INTO learning(kind, created, data) VALUES ('feedback', ?, ?)",
                    (float(now), json.dumps(row)),
                )
        return {"example_id": example_id, "rating": rating}

    def ratings(self) -> Dict[str, str]:
        latest: Dict[str, str] = {}
        for row in self._read("feedback"):
            latest[row["example"]] = row["rating"]
        return latest

    def stats(self) -> Dict[str, Any]:
        ratings = self.ratings()
        counts = {k: len(self._ids()[k]) for k in KINDS}
        return {
            "enabled": self.cfg.enabled,
            "examples": counts,
            "rated_up": sum(1 for r in ratings.values() if r == "up"),
            "rated_down": sum(1 for r in ratings.values() if r == "down"),
        }

    def export(self, kind: str, out: Path, min_rating: Optional[str] = None) -> Dict[str, Any]:
        if kind not in KINDS:
            raise ValueError(f"kind must be one of {KINDS}")
        mode = min_rating or self.cfg.export_min_rating
        ratings = self.ratings()
        rows: List[Dict[str, Any]] = []
        for row in self._read(kind):
            owner = row["id"] if kind == "sft" else row.get("example", "")
            rating = ratings.get(owner)
            if rating == "down" or (mode == "up" and rating != "up"):
                continue
            rows.append(row)
        out.parent.mkdir(parents=True, exist_ok=True)
        text = "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows)
        out.write_text(text, encoding="utf-8")
        manifest = {
            "kind": kind,
            "schema": SCHEMA,
            "count": len(rows),
            "min_rating": mode,
            "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
            "note": "System prompt is not included; add it at training time. Not trained here.",
        }
        out.with_suffix(out.suffix + ".manifest.json").write_text(
            json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
        )
        return manifest

    def purge(self) -> int:
        """Delete everything collected: rows, the database file's content, imported JSONL files and
        their backups. Returns how many rows were removed."""
        removed = 0
        if (self.dir / "learning.sqlite").exists() or self._store is not None:
            with self.store.transaction() as conn:
                removed = conn.execute("DELETE FROM learning").rowcount
                conn.execute("DELETE FROM meta WHERE key LIKE 'legacy:learning:%'")
        for name in [f"{k}.jsonl" for k in (*KINDS, "feedback")]:
            path = self.dir / name
            if path.is_file():
                path.unlink()
                removed += 1
        backups = self.store.path.parent / "backups" if self._store else self.dir / "backups"
        for path in backups.glob("*-learning-*"):
            path.unlink()
        self._seen = None
        return removed
