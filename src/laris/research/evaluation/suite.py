"""Model-free evaluation: retrieval, citation, extraction, leak, injection and vault round-trip.

One run produces one deterministic JSON report (no timestamps, sorted keys, rounded numbers), so two
runs of the same code give the same bytes. Nothing here loads a model, trains or fits anything.
`fast` skips the suites that read the whole brain or the extraction fixture.
"""

import json
import re
import tempfile
from pathlib import Path
from typing import Any, Callable, Dict, List

FAST = ("retrieval", "citation", "injection", "vault")
ALL = (*FAST, "extraction", "leak")


def suite_retrieval(fixtures: Path, root: Path) -> Dict[str, Any]:
    from laris.shared.vault.index import VaultIndex
    from laris.shared.vault.retrieval import GraphRetriever, evaluate
    from laris.shared.vault.search import NoteSearch

    base = fixtures / "retrieval"
    index = VaultIndex.build(base / "vault")
    qrels = {q: set(v) for q, v in json.loads((base / "qrels.json").read_text()).items()}
    plain = evaluate(qrels, lambda q: [h.path for h in NoteSearch(index).search(q, 5)])
    graph = evaluate(qrels, lambda q: [r.path for r in GraphRetriever(index).retrieve(q, 5)])
    return {
        "queries": len(qrels),
        "bm25": plain,
        "graph": graph,
        "passed": graph["recall@5"] >= plain["recall@5"] and graph["mrr"] >= plain["mrr"],
    }


def suite_citation(fixtures: Path, root: Path) -> Dict[str, Any]:
    from laris.shared.scholarly.biblio import extract
    from laris.shared.scholarly.citations import analyse
    from laris.shared.scholarly.mining import Doc

    data = json.loads((fixtures / "scholarly" / "citations.json").read_text(encoding="utf-8"))
    docs = [Doc(k, f"{k}.txt", t, extract(t[:3000])) for k, t in sorted(data["documents"].items())]
    found = {tuple(e) for e in analyse(docs).edges}
    gold = {tuple(e) for e in data["gold_edges"]}
    tp = len(found & gold)
    precision = tp / len(found) if found else 1.0
    recall = tp / len(gold) if gold else 1.0
    return {
        "documents": len(docs),
        "edges_found": len(found),
        "edges_gold": len(gold),
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "passed": precision == 1.0 and recall == 1.0,
    }


def suite_injection(fixtures: Path, root: Path) -> Dict[str, Any]:
    from laris.shared.config.loader import load_runtime_config
    from laris.shared.harness.guard import InjectionScanner

    data = json.loads((fixtures / "security" / "injection.json").read_text(encoding="utf-8"))
    scanner = InjectionScanner(load_runtime_config(root).security)
    hit = sum(scanner.flagged(t) for t in data["positive"])
    false = sum(scanner.flagged(t) for t in data["negative"])
    return {
        "positives": len(data["positive"]),
        "negatives": len(data["negative"]),
        "recall": round(hit / len(data["positive"]), 4),
        "false_positive_rate": round(false / len(data["negative"]), 4),
        "passed": hit == len(data["positive"]) and false == 0,
    }


def suite_vault(fixtures: Path, root: Path) -> Dict[str, Any]:
    from laris.shared.config.runtime_schemas import VaultConfig
    from laris.shared.vault.index import VaultIndex
    from laris.shared.vault.lint import lint_format
    from laris.shared.vault.project import ProjectVault
    from laris.shared.vault.repair import accept_edits, find_conflicts
    from laris.shared.vault.schema import lint_schema

    checks: Dict[str, bool] = {}
    with tempfile.TemporaryDirectory() as tmp:
        vault = ProjectVault(Path(tmp), VaultConfig())
        vault.record_source("Paper (source)", "p.txt", 2, ["perovskite"], "text", {"sha256": "ab"})
        vault.record_answer("sess-0001", "Q?", "A.", ["Paper (source)"])
        vault.refresh_index()
        first = VaultIndex.build(vault.root)
        checks["lint_clean"] = lint_format(first) == [] and lint_schema(first) == []
        checks["rebuild_identical"] = first.dumps() == VaultIndex.build(vault.root).dumps()
        note = vault.root / "Concepts" / "perovskite.md"
        note.write_text(note.read_text(encoding="utf-8") + "\nMy own line.\n", encoding="utf-8")
        vault.record_concept("perovskite", "Other (source)")
        checks["user_text_survives"] = "My own line." in note.read_text(encoding="utf-8")
        note.write_text(
            note.read_text(encoding="utf-8").replace("Mentioned in", "EDITED Mentioned in"),
            encoding="utf-8",
        )
        checks["edit_is_a_conflict"] = len(find_conflicts(vault.root)) == 1
        accept_edits(vault)
        checks["accept_clears_conflict"] = find_conflicts(vault.root) == []
    return {"checks": dict(sorted(checks.items())), "passed": all(checks.values())}


def suite_extraction(fixtures: Path, root: Path) -> Dict[str, Any]:
    from laris.research.evaluation.extraction import evaluate, gate, load_annotations

    docs = load_annotations(fixtures / "extraction" / "annotations.json")
    report = evaluate(docs)
    baseline = json.loads((fixtures / "extraction" / "baseline.json").read_text())
    problems = gate(report, baseline)
    return {
        "micro": report["micro"],
        "macro_f1": report["macro_f1"],
        "per_type_f1": {k: v["f1"] for k, v in sorted(report["per_type"].items())},
        "regressions": problems,
        "passed": not problems,
    }


def suite_leak(fixtures: Path, root: Path) -> Dict[str, Any]:
    from laris.shared.config.loader import load_runtime_config
    from laris.shared.harness.guard import LeakDetector

    config = load_runtime_config(root)
    brain = root / config.prompts.brain_dir
    texts = [p.read_text(encoding="utf-8") for p in sorted(brain.rglob("*.md"))]
    if not texts:
        return {"skipped": "no brain under this root", "passed": True}
    detector = LeakDetector(config.security, texts)
    paragraphs: List[str] = []
    for text in texts:
        for para in re.split(r"\n\s*\n", text.split("---", 2)[-1]):
            if len(para.split()) >= 25 and not para.lstrip().startswith(("|", "```")):
                paragraphs.append(para.strip())
    forms: Dict[str, Callable[[str], str]] = {
        "verbatim": lambda p: p,
        "upper": str.upper,
        "one_word_per_line": lambda p: "\n".join(p.split()),
        "punctuated": lambda p: " , ".join(p.split()),
        "emphasised": lambda p: " ".join(f"**{w}**" for w in p.split()),
        "window_12_words": lambda p: " ".join(p.split()[5:17]),
    }
    sample = paragraphs[:30]
    caught = {name: sum(detector.leaked(f(p)) for p in sample) for name, f in forms.items()}
    clean = "Perovskite cells reach a power conversion efficiency of 25 percent."
    return {
        "paragraphs_tested": len(sample),
        "shingles": detector.size,
        "truncated": detector.truncated,
        "blocked": dict(sorted(caught.items())),
        "false_positive_on_unrelated_text": bool(detector.leaked(clean)),
        "passed": all(n == len(sample) for n in caught.values())
        and not detector.leaked(clean)
        and not detector.truncated,
    }


SUITES: Dict[str, Callable[[Path, Path], Dict[str, Any]]] = {
    "retrieval": suite_retrieval,
    "citation": suite_citation,
    "injection": suite_injection,
    "vault": suite_vault,
    "extraction": suite_extraction,
    "leak": suite_leak,
}


def run(fixtures: Path, root: Path, names: List[str]) -> Dict[str, Any]:
    results = {name: SUITES[name](fixtures, root) for name in names}
    return {
        "suites": dict(sorted(results.items())),
        "passed": all(r["passed"] for r in results.values()),
        "model": "none: model-free suites; the core model is NOT QUALIFIED",
    }


def dumps(report: Dict[str, Any]) -> str:
    return json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
