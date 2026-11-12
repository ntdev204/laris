"""One-time, idempotent import of the earlier JSON/JSONL files into the SQLite space.

Every source is copied to `backups/<name>` beside the database first and is left in place; a
`meta` row per source makes a second run change nothing.
"""

import json
import shutil
from pathlib import Path
from typing import Dict, Iterable, List, Optional

from laris.client.store.store import Store


def _marker(kind: str, source: Path) -> str:
    return f"legacy:{kind}:{source.resolve()}"


def _backup(store: Store, source: Path, label: str) -> None:
    target = store.path.parent / "backups" / f"{store.path.stem}-{label}-{source.name}"
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.exists():
        shutil.copy2(source, target)


LEARNING_KINDS = ("sft", "retrieval", "preference", "feedback")


def migrate_legacy(
    store: Store,
    workspace: Optional[Path] = None,
    conversations: Optional[Path] = None,
    learning: Optional[Path] = None,
) -> Dict[str, int]:
    """Import `<workspace>/chunks.jsonl`, `<conversations>/*.json` and `<learning>/<kind>.jsonl`;
    returns what was added."""
    added = {"chunks": 0, "conversations": 0, "learning": 0}
    if learning is not None:
        for kind in LEARNING_KINDS:
            source = Path(learning) / f"{kind}.jsonl"
            marker = _marker("learning", source)
            if not source.is_file() or store.get_meta(marker) is not None:
                continue
            with open(source, encoding="utf-8") as handle:
                kept = [json.loads(line) for line in handle if line.strip()]
            _backup(store, source, "learning")
            with store.transaction() as conn:
                for row in kept:
                    cur = conn.execute(
                        "INSERT OR IGNORE INTO learning(kind, created, data) VALUES (?,?,?)",
                        (kind, float(row.get("ts", 0)), json.dumps(row, ensure_ascii=False)),
                    )
                    added["learning"] += cur.rowcount
                conn.execute("INSERT INTO meta VALUES (?, 'done')", (marker,))
    if workspace is not None:
        source = Path(workspace) / "chunks.jsonl"
        if source.is_file() and store.get_meta(_marker("chunks", source)) is None:
            with open(source, encoding="utf-8") as handle:
                rows: List[dict] = [json.loads(line) for line in handle if line.strip()]
            _backup(store, source, "workspace")
            with store.transaction() as conn:
                conn.executemany(
                    "INSERT OR REPLACE INTO chunks VALUES (?,?,?,?,?,?,?,?)",
                    [
                        (
                            r["chunk_id"],
                            r["doc_id"],
                            r["source"],
                            r["title"],
                            r["text"],
                            r["start"],
                            r["end"],
                            n,
                        )
                        for n, r in enumerate(rows)
                    ],
                )
                conn.execute("INSERT INTO meta VALUES (?, 'done')", (_marker("chunks", source),))
            added["chunks"] = len(rows)
    if conversations is not None:
        for source in _json_files(Path(conversations)):
            marker = _marker("conversation", source)
            if store.get_meta(marker) is not None:
                continue
            try:
                data = json.loads(source.read_text(encoding="utf-8"))
                row = (data["id"], data["title"], data["created"], data["updated"])
            except (ValueError, KeyError):
                continue  # not a conversation file: left alone
            _backup(store, source, "conversations")
            with store.transaction() as conn:
                conn.execute(
                    "INSERT OR REPLACE INTO conversations VALUES (?,?,?,?,?)",
                    (*row, json.dumps(data, ensure_ascii=False)),
                )
                conn.execute("INSERT INTO meta VALUES (?, 'done')", (marker,))
            added["conversations"] += 1
    return added


def _json_files(folder: Path) -> Iterable[Path]:
    return sorted(folder.glob("*.json")) if folder.is_dir() else []
