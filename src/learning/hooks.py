"""Glue between ingestion and skill generation."""

from pathlib import Path
from typing import Any, Callable, Dict, List, Sequence

from application.workspace import Chunk
from harness.runtime import HarnessRuntime
from learning.skills import (
    build_knowledge_skill,
    generated_count,
    install_skill,
    is_generated,
    lint_skill,
)


def _resolve(root: Path, relative: str) -> Path:
    path = Path(relative).expanduser()
    return path if path.is_absolute() else root / path


def knowledge_skill_for(
    runtime: HarnessRuntime, new_chunks: Sequence[Chunk], all_chunks: Sequence[Chunk]
) -> Dict[str, Any]:
    """Create or refresh the complete RAG skill for newly ingested documents (never a hand-written
    one). Returns `{"skill": name, "skill_updated": bool}` or `{"skill_skipped": [...]}`."""
    cfg = runtime.config.learning
    if not cfg.skill_on_ingest or not new_chunks:
        return {}
    prompts = _resolve(runtime.root, runtime.config.prompts.dir)
    template_path = prompts / cfg.knowledge_template
    if not template_path.is_file():
        return {"skill_skipped": ["knowledge template is missing"]}
    built = build_knowledge_skill(
        new_chunks,
        all_chunks,
        cfg,
        runtime.injection,
        template_path.read_text(encoding="utf-8"),
    )
    if built is None:
        return {}
    name, text = built
    problems = lint_skill(
        text, cfg, runtime.injection, runtime.redactor, runtime.config.agent.skill_max_chars, name
    )
    if problems:
        return {"skill_skipped": problems}
    folder = _resolve(runtime.root, cfg.skill_dir)
    target = folder / name / "SKILL.md"
    if target.exists() and not is_generated(target):
        return {"skill_skipped": ["a hand-written skill already uses that name"]}
    if not target.exists() and generated_count(folder) >= cfg.max_generated_skills:
        return {"skill_skipped": ["generated skill limit reached"]}
    _, replaced = install_skill(folder, name, text, overwrite=True)
    return {"skill": name, "skill_updated": replaced}


def make_ingest_hook(
    get_runtime: Callable[[], HarnessRuntime],
) -> Callable[[List[Chunk], List[Chunk]], Dict[str, Any]]:
    def hook(new_chunks: List[Chunk], all_chunks: List[Chunk]) -> Dict[str, Any]:
        result: Dict[str, Any] = {}
        try:
            result.update(knowledge_skill_for(get_runtime(), new_chunks, all_chunks))
        except Exception:  # ingestion must never fail because a skill could not be written
            result["skill_skipped"] = ["skill generation failed"]
        try:
            from vault.hooks import record_ingest

            result.update(record_ingest(get_runtime(), new_chunks))
        except Exception:  # nor because a note could not be written
            result["vault_skipped"] = 1
        return result

    return hook
