"""Write-through: ingestion and finished chat turns become notes in the project vault."""

import hashlib
import json
from pathlib import Path
from typing import Any, Dict, List, Sequence

from laris.client.application.workspace import Chunk
from laris.client.learning.skills import _terms
from laris.client.vault.knowledge import KnowledgeWriter
from laris.shared.harness.runtime import HarnessRuntime
from laris.shared.vault.project import ProjectVault, source_title


def project_vault(runtime: HarnessRuntime) -> ProjectVault:
    brain = Path(runtime.config.prompts.brain_dir)
    return ProjectVault(
        runtime.root,
        runtime.config.vault,
        scan=runtime.injection.flagged,
        protected=[brain if brain.is_absolute() else runtime.root / brain],
    )


def record_ingest(runtime: HarnessRuntime, new_chunks: Sequence[Chunk]) -> Dict[str, Any]:
    """One Source note per new document, linked to Concept notes for its key terms."""
    cfg = runtime.config.vault
    if not (cfg.enabled and cfg.auto_record) or not new_chunks:
        return {}
    vault = project_vault(runtime)
    by_source: Dict[str, List[Chunk]] = {}
    for chunk in new_chunks:
        by_source.setdefault(chunk.source, []).append(chunk)
    written, skipped, entity_notes = 0, 0, 0
    domains: set = set()
    for source, chunks in sorted(by_source.items()):
        terms = _terms(chunks, runtime.config.learning)[: runtime.config.learning.skill_top_terms]
        text = runtime.redactor.redact(chunks[0].text)[0]
        ordered = sorted(chunks, key=lambda c: c.start)
        meta = {
            "doc_id": ordered[0].doc_id,
            "sha256": hashlib.sha256("\n".join(c.text for c in ordered).encode()).hexdigest(),
            "chars": ordered[-1].end,
            "passages": len(ordered),
            "spans": [(c.start, c.end) for c in ordered],
        }
        meta["bibliography"] = _bibliography(runtime, source, ordered)
        result = vault.record_source(
            source_title(source), runtime.redactor.redact(source)[0], len(chunks), terms, text, meta
        )
        if result.status == "skipped":
            skipped += 1
        else:
            written += 1
            if cfg.entities:
                entity_notes += _entities(runtime, vault, source, ordered)
            if runtime.config.brain.enabled and runtime.config.brain.knowledge:
                known = KnowledgeWriter(
                    vault, runtime.brain, runtime.config.brain, runtime.redactor.redact
                ).add_document(source_title(source), chunks, terms)
                if known is not None and known.note.status != "skipped":
                    domains.add(known.domain)
    vault.refresh_index()
    out: Dict[str, Any] = {"vault_notes": written, "vault_skipped": skipped}
    if entity_notes:
        out["vault_entities"] = entity_notes
    if domains:
        out["knowledge_domains"] = sorted(domains)
    return out


def _bibliography(runtime: HarnessRuntime, source: str, ordered: Sequence[Chunk]) -> Dict[str, Any]:
    """Title, authors, year, DOI and arXiv id when the document states them (never guessed)."""
    try:
        from laris.shared.scholarly.biblio import extract, pdf_metadata
        from laris.shared.vault.entities import document_text

        metadata: Dict[str, Any] = {}
        path = runtime.root / source
        if source.lower().endswith(".pdf") and path.is_file() and path.stat().st_size < 50 << 20:
            metadata = pdf_metadata(path.read_bytes())
        bib = extract(document_text(ordered)[:3000], metadata)
        return {
            k: runtime.redactor.redact(str(v))[0] if isinstance(v, str) else v
            for k, v in bib.properties().items()
        }
    except Exception:
        return {}


def _entities(
    runtime: HarnessRuntime, vault: ProjectVault, source: str, ordered: Sequence[Chunk]
) -> int:
    """Method, dataset, metric, claim and limitation notes with character spans (best effort)."""
    try:
        from laris.shared.scientific.extractor import ScientificDiscourseExtractor
        from laris.shared.vault.entities import EntityWriter, document_text

        cfg = runtime.config.vault
        text = document_text(ordered)[: cfg.entity_max_chars]
        found = ScientificDiscourseExtractor().extract(ordered[0].doc_id, text)
        writer = EntityWriter(vault, runtime.redactor.redact, cfg.entity_max_statements)
        return writer.write_document(source_title(source), ordered[0].doc_id, text, found).notes
    except Exception:  # extraction never fails ingestion
        return 0


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
    plan_lines: Sequence[str] = (),
) -> Dict[str, Any]:
    """A finished, verified turn becomes a Question note linked to its session and sources.
    The plan the agent followed is kept with the answer."""
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
    if plan_lines:
        clean_a += "\n\n**Plan**\n" + runtime.redactor.redact("\n".join(plan_lines))[0]
    vault = project_vault(runtime)
    result = vault.record_answer(
        session_id,
        clean_q,
        clean_a,
        _cited_sources(history),
        trace=last_turn.get("brain_trace", []),
        notes=last_turn.get("vault_notes", []),
    )
    vault.refresh_index()
    return {"vault_note": Path(result.note).stem, "vault_status": result.status}
