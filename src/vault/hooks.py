"""Write-through: ingestion and finished chat turns become notes in the project vault."""

import json
from pathlib import Path
from typing import Any, Dict, List, Sequence

from application.workspace import Chunk
from harness.runtime import HarnessRuntime
from learning.skills import _terms
from vault.knowledge import KnowledgeWriter
from vault.project import ProjectVault, source_title


def project_vault(runtime: HarnessRuntime) -> ProjectVault:
    return ProjectVault(runtime.root, runtime.config.vault, scan=runtime.injection.flagged)


def record_ingest(runtime: HarnessRuntime, new_chunks: Sequence[Chunk]) -> Dict[str, Any]:
    """One Source note per new document, linked to Concept notes for its key terms."""
    cfg = runtime.config.vault
    if not (cfg.enabled and cfg.auto_record) or not new_chunks:
        return {}
    vault = project_vault(runtime)
    by_source: Dict[str, List[Chunk]] = {}
    for chunk in new_chunks:
        by_source.setdefault(chunk.source, []).append(chunk)
    written, skipped = 0, 0
    domains: set = set()
    for source, chunks in sorted(by_source.items()):
        terms = _terms(chunks, runtime.config.learning)[: runtime.config.learning.skill_top_terms]
        text = runtime.redactor.redact(chunks[0].text)[0]
        result = vault.record_source(
            source_title(source), runtime.redactor.redact(source)[0], len(chunks), terms, text
        )
        if result.status == "skipped":
            skipped += 1
        else:
            written += 1
            if runtime.config.brain.enabled and runtime.config.brain.knowledge:
                known = KnowledgeWriter(
                    vault, runtime.brain, runtime.config.brain, runtime.redactor.redact
                ).add_document(source_title(source), chunks, terms)
                if known is not None and known.note.status != "skipped":
                    domains.add(known.domain)
    vault.refresh_index()
    out: Dict[str, Any] = {"vault_notes": written, "vault_skipped": skipped}
    if domains:
        out["knowledge_domains"] = sorted(domains)
    return out


def _cited_sources(messages: Sequence[Dict[str, Any]]) -> List[str]:
    found: List[str] = []
    for message in messages:
        if message.get("role") != "tool":
            continue
        try:
            data = json.loads(message.get("content") or "")
        except (TypeError, ValueError):
            continue
        hits = data.get("hits") if isinstance(data, dict) else None
        for hit in hits or []:
            if isinstance(hit, dict) and isinstance(hit.get("source"), str):
                if hit["source"] not in found:
                    found.append(hit["source"])
    return [source_title(s) for s in found]


def record_turn(
    runtime: HarnessRuntime,
    session_id: str,
    history: Sequence[Dict[str, Any]],
    last_turn: Dict[str, Any],
) -> Dict[str, Any]:
    """A finished, verified turn becomes a Question note linked to its session and sources."""
    cfg = runtime.config.vault
    if not (cfg.enabled and cfg.auto_record) or last_turn.get("status") != "completed":
        return {}
    question = next(
        (m["content"] for m in history if m.get("role") == "user" and not m.get("harness")), ""
    )
    answer = next(
        (
            m["content"]
            for m in reversed(history)
            if m.get("role") == "assistant" and m.get("content") and not m.get("superseded")
        ),
        "",
    )
    if not question or not answer or last_turn.get("guard_hits", {}).get("leak"):
        return {}
    clean_q = runtime.redactor.redact(str(question))[0]
    clean_a = runtime.redactor.redact(str(answer))[0]
    vault = project_vault(runtime)
    result = vault.record_answer(session_id, clean_q, clean_a, _cited_sources(history))
    vault.refresh_index()
    return {"vault_note": Path(result.note).stem, "vault_status": result.status}
