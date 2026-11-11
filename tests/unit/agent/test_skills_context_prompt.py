"""Skills, LARIS.md prompt assembly and automatic context compaction."""

import json
from pathlib import Path

import pytest

from agent.builtin_tools import build_registry
from agent.context import ContextManager, is_overflow_error
from agent.loop import AgentSession
from agent.provider import AssistantTurn, ChatProvider, OfflinePlanner, ProviderError
from agent.tools import Sandbox
from application.chat_app import ChatApp
from application.service import SearchService
from application.workspace import Workspace, chunks_from_text
from config.loader import load_runtime_config
from harness.integrity import write_lock
from harness.runtime import HarnessRuntime
from skills import SkillLibrary
from skills.loader import SkillError

SKILL = """---
name: demo-skill
description: >-
  Does a demo. Use when the user asks for a demo.
model: any
---

# Demo

## Steps
1. Do the thing.
"""


def make_skill(root: Path, name: str = "demo-skill", text: str = SKILL) -> None:
    folder = root / ".laris" / "skills" / name
    (folder / "references").mkdir(parents=True)
    (folder / "SKILL.md").write_text(text, encoding="utf-8")
    (folder / "references" / "r.md").write_text("reference text", encoding="utf-8")


@pytest.fixture
def project(project):
    make_skill(project)
    return project


def library(project):
    return SkillLibrary([(project / ".laris" / "skills", "project")])


def test_repository_skills_are_all_valid():
    repo = Path(__file__).resolve().parents[3]
    lib = SkillLibrary([(repo / ".laris" / "skills", "project")])
    assert lib.problems == [] and len(lib.skills) >= 15
    assert (repo / "LARIS.md").read_text(encoding="utf-8").strip()


def test_skill_loading_and_validation(project):
    lib = library(project)
    skill = lib.get("/demo-skill")
    assert skill.description.startswith("Does a demo") and skill.metadata == {"model": "any"}
    assert [p.name for p in skill.references] == ["r.md"]
    assert lib.read_reference("demo-skill", "references/r.md") == "reference text"
    with pytest.raises(SkillError):
        lib.read_reference("demo-skill", "../../../etc/passwd")
    with pytest.raises(SkillError):
        lib.get("nope")
    make_skill(project, "wrong-name", SKILL)  # folder name differs from front-matter name
    make_skill(project, "no-front", "just text")
    assert len(library(project).problems) == 2


def test_system_prompt_includes_policy_skills_and_memory(project):
    (project / "LARIS.local.md").write_text("Local note.", encoding="utf-8")
    (project / ".laris" / "memory").mkdir(parents=True, exist_ok=True)
    (project / ".laris" / "memory" / "research-state.md").write_text("RQ1", encoding="utf-8")
    rt = HarnessRuntime.load(project)
    prompt = rt.composer.compose("abc", library(project), "Prefer short answers.")
    for needle in (
        "Local note.",
        "demo-skill",
        "research-state.md",
        "Prefer short answers.",
        "internal_policy",
    ):
        assert needle in prompt.text
    assert prompt.text.index("internal_policy") < prompt.text.index("Local note.")
    (project / "LARIS.md").write_text("Changed policy line.", encoding="utf-8")
    write_lock(project, load_runtime_config(project).prompts)
    again = HarnessRuntime.load(project).composer.compose("abc", library(project))
    assert "Changed policy line." in again.text  # re-read every time
    assert again.sha256 != prompt.sha256


def test_use_skill_tool_and_memory_write(project, tmp_path):
    rt = HarnessRuntime.load(project)
    service = SearchService(Workspace(tmp_path / "ws"))
    registry = build_registry(
        service,
        Sandbox([project], tmp_path / "o"),
        rt,
        library(project),
        project / ".laris" / "memory",
    )
    out = registry.call("use_skill", {"name": "demo-skill", "arguments": "go"})
    assert "Do the thing." in out["instructions"] and out["references"][0]["bytes"] > 0
    with pytest.raises(Exception) as exc:
        registry.call("use_skill", {"name": "missing"})
    assert "unknown_skill" in str(exc.value.code)
    registry.call("save_memory", {"name": "decisions-log", "content": "2026-11-11 chose X"})
    registry.call("save_memory", {"name": "decisions-log", "content": "second"})
    text = (project / ".laris" / "memory" / "decisions-log.md").read_text()
    assert "chose X" in text and "second" in text
    with pytest.raises(Exception):
        registry.call("save_memory", {"name": "../evil", "content": "x"})


def conversation(turns: int, tool_chars: int = 4000):
    messages = [{"role": "system", "content": "sys"}]
    for i in range(turns):
        messages.append({"role": "user", "content": f"question {i} " + "word " * 40})
        messages.append(
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": f"c{i}",
                        "type": "function",
                        "function": {
                            "name": "search_corpus",
                            "arguments": json.dumps({"query": str(i)}),
                        },
                    }
                ],
            }
        )
        messages.append({"role": "tool", "tool_call_id": f"c{i}", "content": "x" * tool_chars})
        messages.append({"role": "assistant", "content": f"answer {i} " + "text " * 30})
    return messages


def manager(rt, window=None, threshold=None, summarizer=None, enabled=True):
    cfg = rt.config.context.model_copy(update={"enabled": enabled})
    if window:
        cfg.window_tokens = window
    if threshold:
        cfg.threshold = threshold
    return ContextManager(cfg, rt.strings, summarizer)


def test_autocompact_is_on_by_default():
    assert HarnessRuntime().config.context.enabled is True


def test_compaction_trims_then_summarises_and_keeps_tool_pairs():
    rt = HarnessRuntime()
    messages = conversation(30)
    cm = manager(rt, window=8000, threshold=0.8)
    assert cm.needs_compaction(messages)
    new, result = cm.compact(messages)
    assert result is not None and result.after < result.before
    assert new[0]["role"] == "system" and new[1]["content"].startswith(cm.marker)
    assert new[2]["role"] == "assistant" and new[3]["role"] == "user"
    ids_called = {c["id"] for m in new if m.get("tool_calls") for c in m["tool_calls"]}
    ids_answered = {m["tool_call_id"] for m in new if m["role"] == "tool"}
    assert ids_called == ids_answered  # no orphaned tool call or result
    assert "question 29" in json.dumps(new)  # the latest turn survives verbatim
    assert cm.estimate(new) < 8000 * 0.8


def test_model_summary_is_used_and_falls_back_on_failure():
    rt = HarnessRuntime()
    messages = conversation(20)
    ok = manager(rt, window=4000, summarizer=lambda transcript, hint: "MODEL SUMMARY")
    assert "MODEL SUMMARY" in ok.compact(messages, force=True)[0][1]["content"]
    bad = manager(rt, window=4000, summarizer=lambda transcript, hint: 1 / 0)
    new, result = bad.compact(messages, force=True)
    assert result is not None and result.method == "extractive" and "question" in new[1]["content"]
    assert "question 0" in bad.extractive_summary(messages[1:])


class Overflowing(ChatProvider):
    def __init__(self):
        self.calls = 0

    def chat(self, messages, tools):
        self.calls += 1
        if self.calls == 1:
            raise ProviderError("maximum context length exceeded")
        return AssistantTurn("ok after compaction")


def test_session_autocompacts_before_calls_and_retries_on_overflow(tmp_path):
    rt = HarnessRuntime()
    service = SearchService(Workspace(tmp_path / "ws"))
    registry = build_registry(service, Sandbox([tmp_path], tmp_path / "o"), rt)
    session = AgentSession(
        Overflowing(),
        registry,
        rt,
        messages=conversation(25)[1:],
        context=manager(rt, window=6000, threshold=0.9),
    )
    events = list(session.send("next question"))
    kinds = [e["type"] for e in events]
    assert "compact" in kinds and kinds[-1] == "done" and events[-1]["status"] == "completed"
    assert any(e["type"] == "usage" for e in events)
    assert is_overflow_error(
        "This model's Maximum Context Length is 4096", rt.config.context.overflow_hints
    )


def test_disabled_autocompact_leaves_messages_alone(tmp_path):
    rt = HarnessRuntime()
    service = SearchService(Workspace(tmp_path / "ws"))
    registry = build_registry(service, Sandbox([tmp_path], tmp_path / "o"), rt)
    session = AgentSession(
        OfflinePlanner(rt.strings),
        registry,
        rt,
        messages=conversation(25)[1:],
        context=manager(rt, window=4000, enabled=False),
    )
    assert not [e for e in session.send("hello world") if e["type"] == "compact"]


def test_chat_app_runs_skill_command_and_archives_compaction(project, tmp_path):
    service = SearchService(Workspace(tmp_path / "ws"))
    service.workspace.add(chunks_from_text("a.txt", "graphene conducts electricity"))
    chat = ChatApp(service, project, project / "chat")
    conv = chat.conversations.create()
    events = list(chat.send(conv["id"], "/demo-skill make a demo"))
    assert [e["name"] for e in events if e["type"] == "tool_call"] == ["use_skill"]
    final = events[-1]["answer"]
    assert "demo-skill" in final and "make a demo" in final
    chat.update_settings({"context_window": 2048, "compact_threshold": 0.3})
    saved = chat.conversations.get(conv["id"])
    saved["messages"] += conversation(12, tool_chars=500)[1:]
    chat.conversations.save(saved)
    events = list(chat.compact(conv["id"]))
    assert any(e["type"] == "compact" for e in events)
    assert list((project / "chat" / "archive").glob(f"{conv['id']}-*.json"))
    assert chat.conversations.get(conv["id"])["messages"][0].get("compacted") is True
