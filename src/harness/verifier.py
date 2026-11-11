"""Answer verification: grounded answers must cite the sources the tools returned."""

import re
from dataclasses import dataclass
from typing import Any, Dict, List

from config.runtime_schemas import VerifyConfig

CITATION = re.compile(r"\[[^\]\n]{2,}#\d+\]")


@dataclass
class Verdict:
    ok: bool
    reason: str = ""


def _sources(result: Any) -> List[str]:
    found: List[str] = []
    if isinstance(result, dict):
        if isinstance(result.get("source"), str):
            found.append(result["source"])
        if isinstance(result.get("path"), str):
            found.append(result["path"])
        for hit in result.get("hits") or []:
            if isinstance(hit, dict) and isinstance(hit.get("source"), str):
                found.append(hit["source"])
        primary = result.get("primary")
        if isinstance(primary, dict) and isinstance(primary.get("source"), str):
            found.append(primary["source"])
    return found


class AnswerVerifier:
    def __init__(self, cfg: VerifyConfig) -> None:
        self.cfg = cfg

    def check(self, answer: str, tool_results: List[Dict[str, Any]]) -> Verdict:
        if not self.cfg.require_citations or not answer.strip():
            return Verdict(True)
        grounded = [r for r in tool_results if r["tool"] in self.cfg.citation_tools]
        sources = [s for r in grounded if "error" not in r["result"] for s in _sources(r["result"])]
        if not sources:
            return Verdict(True, "no grounded evidence in this turn")
        if CITATION.search(answer) or any(s in answer for s in sources):
            return Verdict(True)
        return Verdict(False, "answer uses tool evidence without citing a source")
