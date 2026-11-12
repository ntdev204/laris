"""The scripted placeholder backend: a deterministic planner that needs no model.

`OfflinePlanner` reads mentioned files, searches the corpus and quotes the best evidence with fixed
rules; it is a scripted workflow, not a language model. It is the default backend of the model
service and a test fixture (D16). It sits in `shared` until the client's offline mode is removed.
"""

import json
import re
from typing import Any, Dict, List

from laris.protocol import AssistantTurn, ChatProvider, Message, ToolCall

_PATH_RE = re.compile(r"(?:^|\s)([\w./~-]+\.(?:txt|md|pdf|png|jpe?g|tiff?))(?=\s|$|[.,;:?])", re.I)
_EXTRACT_RE = re.compile(r"claim|metric|extract|trích|tách", re.I)


class OfflinePlanner(ChatProvider):
    """Scripted workflow: read mentioned files, search the corpus, quote the best evidence.

    It decides tool calls with fixed rules and writes the final answer from tool results only. Every
    sentence it produces comes from the string catalogue (`planner.*`).
    """

    name = "offline"

    def __init__(
        self, strings: Any, has_model: bool = False, top_k: int = 5, read_chars: int = 4000
    ):
        self.strings = strings
        self.has_model = has_model
        self.top_k = top_k
        self.read_chars = read_chars

    @staticmethod
    def _results(messages: List[Message]) -> Dict[str, List[Any]]:
        done: Dict[str, List[Any]] = {}
        calls: Dict[str, str] = {}
        for m in messages:
            for c in m.get("tool_calls") or []:
                calls[c["id"]] = c["function"]["name"]
            if m.get("role") == "tool":
                try:
                    payload = json.loads(m["content"])
                except json.JSONDecodeError:
                    payload = {"truncated": True}  # trimmed by context compaction
                done.setdefault(calls.get(m["tool_call_id"], "?"), []).append(payload)
        return done

    def chat(self, messages: List[Message], tools: List[Dict[str, Any]]) -> AssistantTurn:
        last_user = max(
            i for i, m in enumerate(messages) if m["role"] == "user" and not m.get("harness")
        )
        task = messages[last_user]["content"]
        messages = messages[last_user:]  # only this turn's tool results count
        done = self._results(messages)
        step = sum(1 for m in messages if m["role"] == "tool")

        def call(name: str, **arguments: Any) -> AssistantTurn:
            return AssistantTurn(None, [ToolCall(f"call_{step}", name, arguments)])

        if "use_skill" in done and len(done) == 1:
            return AssistantTurn(self._skill_notice(done["use_skill"][-1]))
        paths = _PATH_RE.findall(task)
        if paths and "read_file" not in done:
            return call("read_file", path=paths[0], max_chars=self.read_chars)
        if paths and _EXTRACT_RE.search(task) and "extract_discourse" not in done:
            return call("extract_discourse", path=paths[0])
        if "search_corpus" not in done:
            return call("search_corpus", query=task, top_k=self.top_k)
        hits = done["search_corpus"][-1].get("hits", [])
        if self.has_model and hits and "answer_question" not in done:
            return call("answer_question", question=task)
        return AssistantTurn(self._compose(task, done, hits))

    def _skill_notice(self, result: Dict[str, Any]) -> str:
        t = self.strings
        if "error" in result:
            return str(result["error"]["message"])
        headings = [
            line.lstrip("# ").strip()
            for line in result["instructions"].splitlines()
            if line.startswith("## ")
        ]
        lines = [
            t.get("planner.skill_loaded", name=result["name"], chars=len(result["instructions"])),
            "",
            result["description"][:400],
            "",
            t.get("planner.skill_sections", sections=", ".join(headings[:10])),
        ]
        if result.get("arguments"):
            lines += ["", t.get("planner.skill_request", request=result["arguments"])]
        lines += ["", t.get("planner.skill_no_model")]
        return "\n".join(lines)

    def _compose(self, task: str, done: Dict[str, List[Any]], hits: List[Dict[str, Any]]) -> str:
        t = self.strings
        lines = [t.get("planner.task", task=task), ""]
        read = (done.get("read_file") or [{}])[-1]
        if read.get("text"):
            head = t.get("planner.read_line", path=read["path"], chars=read["total_chars"])
            lines += [head, read["text"][:600], ""]
        found = (done.get("extract_discourse") or [{}])[-1]
        if "metrics" in found:
            counts = {k: len(found[k]) for k in ("claims", "methods", "datasets", "metrics")}
            lines.append(
                t.get("planner.entities", counts=", ".join(f"{n} {k}" for k, n in counts.items()))
            )
            for metric in found["metrics"][:5]:
                lines.append(f"- {metric['name']} {metric.get('value')}")
            lines.append("")
        search = (done.get("search_corpus") or [{}])[-1]
        if "error" in search:
            lines.append(t.get("planner.search_failed", message=search["error"]["message"]))
        elif search.get("truncated"):
            lines.append(t.get("planner.trimmed"))
        elif not hits:
            lines.append(t.get("planner.no_match"))
        else:
            answer = ((done.get("answer_question") or [{}])[-1]).get("primary")
            if answer:
                lines.append(
                    t.get("planner.answer_line", answer=answer["answer"], source=answer["source"])
                )
            lines.append(t.get("planner.evidence_heading"))
            for hit in hits[:3]:
                snippet = " ".join(hit["text"].split())[:240]
                lines.append(f"- [{hit['source']} #{hit['rank']}] {hit['title']}: {snippet}")
        lines += ["", t.get("planner.disclaimer")]
        return "\n".join(lines)
