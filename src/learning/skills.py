"""RAG skills: complete knowledge skills built when new documents arrive, and skill authoring.

A generated skill carries only metadata derived from the corpus (source names, counts, key terms),
never passage text, so a hostile document cannot write instructions into the prompt. Hand-written
skills pass the same completeness and safety lint before they are installed.
"""

import datetime
import hashlib
import math
import re
from collections import Counter
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import yaml

from application.workspace import Chunk
from config.runtime_schemas import LearningConfig
from harness.guard import InjectionScanner, SecretRedactor
from skills.loader import MAX_DESCRIPTION_CHARS, NAME_RE, SkillError, parse_skill_file

_SLUG = re.compile(r"[^a-z0-9]+")
_CONTROL = re.compile(r"[\x00-\x1f\x7f<>`{}\[\]|]")


def slug(text: str, limit: int = 40) -> str:
    return _SLUG.sub("-", text.lower()).strip("-")[:limit].strip("-")


def clean_label(text: str, scanner: InjectionScanner, limit: int = 80) -> str:
    """Single-line, markup-free text; instruction-like text is dropped."""
    value = " ".join(_CONTROL.sub(" ", text).split())[:limit]
    return "" if scanner.flagged(value) else value


# -- lint --------------------------------------------------------------------------------------
def lint_skill(
    text: str,
    cfg: LearningConfig,
    scanner: InjectionScanner,
    redactor: SecretRedactor,
    max_chars: int,
    expected_name: str = "",
) -> List[str]:
    """Completeness and safety problems of a SKILL.md text (empty list = installable)."""
    problems: List[str] = []
    match = re.match(r"^---\s*\n(.*?)\n---\s*\n?(.*)$", text, re.S)
    if not match:
        return ["missing YAML front matter"]
    try:
        meta = yaml.safe_load(match.group(1)) or {}
    except yaml.YAMLError:
        return ["front matter is not valid YAML"]
    body = match.group(2).strip()
    name = str(meta.get("name") or "")
    description = " ".join(str(meta.get("description") or "").split())
    if not NAME_RE.match(name):
        problems.append("name must be lowercase letters, digits and dashes")
    if expected_name and name != expected_name:
        problems.append("name does not match the requested name")
    if len(description) < 40 or len(description) > MAX_DESCRIPTION_CHARS:
        problems.append("description must be 40-%d characters" % MAX_DESCRIPTION_CHARS)
    if "use when" not in description.lower():
        problems.append('description must say when to use the skill ("Use when ...")')
    headings = {h.strip().lower() for h in re.findall(r"(?m)^##\s+(.+)$", body)}
    missing = [s for s in cfg.skill_required_sections if s.lower() not in headings]
    if missing:
        problems.append("missing sections: " + ", ".join(missing))
    if len(body) < cfg.skill_min_body_chars:
        problems.append("instructions are too short to be actionable")
    if len(text) > max_chars:
        problems.append("skill is longer than the allowed size")
    if scanner.flagged(text):
        problems.append("contains instruction-override wording")
    if redactor.redact(text)[1]:
        problems.append("contains a credential")
    for pattern in cfg.skill_protected_patterns:
        if re.search(pattern, text):
            problems.append("refers to protected policy or secret files")
            break
    return problems


def install_skill(folder: Path, name: str, text: str, overwrite: bool = False) -> Tuple[Path, bool]:
    """Write `<folder>/<name>/SKILL.md`. Returns (path, replaced). Never touches other files."""
    if not NAME_RE.match(name):
        raise SkillError("invalid skill name")
    target = folder / name / "SKILL.md"
    replaced = target.exists()
    if replaced and not overwrite:
        raise SkillError("a skill with that name exists; pass overwrite=true to replace it")
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(".tmp")
    tmp.write_text(text.rstrip() + "\n", encoding="utf-8")
    tmp.replace(target)
    return target, replaced


def is_generated(path: Path) -> bool:
    try:
        meta, _ = parse_skill_file(path)
    except (SkillError, OSError):
        return False
    return meta.get("generated") is True


# -- knowledge skills --------------------------------------------------------------------------
def _terms(chunks: Sequence[Chunk], cfg: LearningConfig) -> List[str]:
    stop = {w.lower() for w in cfg.skill_stopwords}
    pattern = re.compile(r"[^\W\d_]{%d,}" % cfg.skill_min_term_chars)
    df: Counter = Counter()
    tf: Counter = Counter()
    for chunk in chunks:
        words = [w for w in pattern.findall(chunk.text.lower()) if w not in stop]
        tf.update(words)
        df.update(set(words))
    n = max(len(chunks), 1)
    min_df = cfg.skill_min_df if n >= 2 * cfg.skill_min_df else 1
    scored = []
    for word, count in tf.items():
        if df[word] < min_df or (n >= 5 and df[word] / n > cfg.skill_max_df_ratio):
            continue
        scored.append((count * math.log(1 + n / df[word]), word))
    scored.sort(key=lambda item: (-item[0], item[1]))
    return [w for _, w in scored[: cfg.skill_top_terms]]


def _label_for(sources: Sequence[str], scope_dir: str) -> Tuple[str, str]:
    """(human label, skill name) for a batch: folder name, single stem, or hashed batch."""
    if scope_dir:
        label = Path(scope_dir).name
        return label, "corpus-" + slug(label)
    if len(sources) == 1:
        label = Path(sources[0]).stem
        return label, "corpus-" + slug(label)
    digest = hashlib.sha256("\n".join(sorted(sources)).encode("utf-8")).hexdigest()[:6]
    return f"batch {digest}", f"corpus-batch-{digest}"


def _common_dir(sources: Sequence[str]) -> str:
    parents = {str(Path(s).parent) for s in sources}
    if len(parents) == 1:
        only = parents.pop()
        return "" if only in (".", "") else only
    return ""


def build_knowledge_skill(
    new_chunks: Sequence[Chunk],
    all_chunks: Sequence[Chunk],
    cfg: LearningConfig,
    scanner: InjectionScanner,
    template: str,
    today: Optional[datetime.date] = None,
) -> Optional[Tuple[str, str]]:
    """(skill name, SKILL.md text) covering the documents that arrived, or None when empty."""
    if not new_chunks:
        return None
    sources = sorted({c.source for c in new_chunks})
    scope_dir = _common_dir(sources)
    label, name = _label_for(sources, scope_dir)
    if not NAME_RE.match(name) or name == "corpus-":
        return None
    prefix = scope_dir + "/"
    scope = [
        c for c in all_chunks if c.source in sources or (scope_dir and c.source.startswith(prefix))
    ]
    by_source: Dict[str, List[Chunk]] = {}
    for chunk in scope:
        by_source.setdefault(chunk.source, []).append(chunk)
    terms = _terms(scope, cfg) or [clean_label(label, scanner, 40) or "the new documents"]
    rows = []
    for source in sorted(by_source)[: cfg.skill_max_sources]:
        title = clean_label(by_source[source][0].title, scanner) or "(title omitted)"
        shown = clean_label(source, scanner, 120) or "source"
        rows.append(f"- `{shown}`: {len(by_source[source])} passages, {title}")
    if len(by_source) > cfg.skill_max_sources:
        rows.append(f"- … and {len(by_source) - cfg.skill_max_sources} more documents")
    values = {
        "label": clean_label(label, scanner, 60) or name,
        "documents": str(len(by_source)),
        "passages": str(len(scope)),
        "terms": ", ".join(terms),
        "sources": "\n".join(rows),
    }
    body = re.sub(r"\{\{(\w+)\}\}", lambda m: values[m.group(1)], template)
    description = (
        f"Use when the user asks about {', '.join(terms[:6])} or needs facts from the "
        f"{values['label']} sources in the local corpus ({values['documents']} documents). "
        "Search the corpus first and cite every source."
    )[:MAX_DESCRIPTION_CHARS]
    meta = {
        "name": name,
        "description": description,
        "generated": True,
        "version": (today or datetime.date.today()).isoformat(),
    }
    front = yaml.safe_dump(meta, sort_keys=False, allow_unicode=True, width=1000).strip()
    return name, f"---\n{front}\n---\n\n{body.strip()}\n"


def generated_count(folder: Path) -> int:
    return sum(1 for p in folder.glob("*/SKILL.md") if is_generated(p)) if folder.is_dir() else 0


def sync_chunks(chunks: Iterable[Chunk]) -> Dict[str, List[Chunk]]:
    """Group chunks the way ingestion would: by folder, else by document."""
    docs: Dict[str, List[Chunk]] = {}
    for chunk in chunks:
        docs.setdefault(chunk.source, []).append(chunk)
    groups: Dict[str, List[Chunk]] = {}
    for source, items in docs.items():
        parent = str(Path(source).parent)
        key = parent if parent not in (".", "") else source
        groups.setdefault(key, []).extend(items)
    return groups


def skill_meta(text: str) -> Dict[str, Any]:
    match = re.match(r"^---\s*\n(.*?)\n---", text, re.S)
    return (yaml.safe_load(match.group(1)) or {}) if match else {}
