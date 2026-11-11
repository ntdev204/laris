"""Skills, LARIS.md prompt assembly and automatic context compaction."""

import json
from pathlib import Path

import pytest

from agent.builtin_tools import build_registry
from agent.context import (
    SUMMARY_MARKER,
    ContextManager,
    estimate_tokens,
    extractive_summary,
    is_overflow_error,
)
from agent.conversations import DEFAULT_SETTINGS
from agent.loop import AgentSession
from agent.prompt import build_system_prompt
from agent.provider import AssistantTurn, ChatProvider, OfflinePlanner, ProviderError
from agent.tools import Sandbox
from application.chat_app import ChatApp
from application.service import SearchService
from application.workspace import Workspace, chunks_from_text
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
def project(tmp_path):
    make_skill(tmp_path)
    return tmp_path


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


def test_system_prompt_includes_instructions_skills_and_memory(project):
    (project / "LARIS.md").write_text("Always answer in Vietnamese.", encoding="utf-8")
    (project / "LARIS.local.md").write_text("Local note.", encoding="utf-8")
    (project / ".laris" / "memory").mkdir()
    (project / ".laris" / "memory" / "research-state.md").write_text("RQ1", encoding="utf-8")
    prompt = build_system_prompt(project, library(project))
    for needle in (
        "Always answer in Vietnamese.",
        "Local note.",
        "demo-skill",
        "research-state.md",
    ):
        assert needle in prompt
    assert prompt.index("Always answer") < prompt.index("Local note.")
    (project / "LARIS.md").write_text("Changed.", encoding="utf-8")
    assert "Changed." in build_system_prompt(project, library(project))  # re-read every time


def test_use_skill_tool_and_memory_write(project, tmp_path):
    service = SearchService(Workspace(tmp_path / "ws"))
    registry = build_registry(
        service, Sandbox([project], tmp_path / "o"), library(project), project / ".laris" / "memory"
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


def test_autocompact_is_on_by_default():
    assert DEFAULT_SETTINGS["auto_compact"] is True


def test_compaction_trims_then_summarises_and_keeps_tool_pairs():
    messages = conversation(30)
    manager = ContextManager(window=8000, threshold=0.8)
    assert manager.needs_compaction(messages)
    new, result = manager.compact(messages)
    assert result is not None and result.after < result.before
    assert new[0]["role"] == "system" and new[1]["content"].startswith(SUMMARY_MARKER)
    assert new[2]["role"] == "assistant" and new[3]["role"] == "user"
    ids_called = {c["id"] for m in new if m.get("tool_calls") for c in m["tool_calls"]}
    ids_answered = {m["tool_call_id"] for m in new if m["role"] == "tool"}
    assert ids_called == ids_answered  # no orphaned tool call or result
    assert "question 29" in json.dumps(new)  # the latest turn survives verbatim
    assert estimate_tokens(new) < 8000 * 0.8


def test_model_summary_is_used_and_falls_back_on_failure():
    messages = conversation(20)
    ok = ContextManager(4000, summarizer=lambda transcript, hint: "MODEL SUMMARY")
    assert "MODEL SUMMARY" in ok.compact(messages, force=True)[0][1]["content"]
    bad = ContextManager(4000, summarizer=lambda transcript, hint: 1 / 0)
    new, result = bad.compact(messages, force=True)
    assert result is not None and result.method == "extractive" and "question" in new[1]["content"]
    assert "question 0" in extractive_summary(messages[1:])


class Overflowing(ChatProvider):
    def __init__(self):
        self.calls = 0

    def chat(self, messages, tools):
        self.calls += 1
        if self.calls == 1:
            raise ProviderError("maximum context length exceeded")
        return AssistantTurn("ok after compaction")


def test_session_autocompacts_before_calls_and_retries_on_overflow(tmp_path):
    service = SearchService(Workspace(tmp_path / "ws"))
    registry = build_registry(service, Sandbox([tmp_path], tmp_path / "o"))
    history = conversation(25)
    session = AgentSession(
        Overflowing(), registry, messages=history, context=ContextManager(6000, threshold=0.9)
    )
    events = list(session.send("next question"))
    kinds = [e["type"] for e in events]
    assert "compact" in kinds and kinds[-1] == "done" and events[-1]["status"] == "completed"
    assert any(e["type"] == "usage" for e in events)
    assert is_overflow_error("This model's Maximum Context Length is 4096")


def test_disabled_autocompact_leaves_messages_alone(tmp_path):
    service = SearchService(Workspace(tmp_path / "ws"))
    registry = build_registry(service, Sandbox([tmp_path], tmp_path / "o"))
    session = AgentSession(
        OfflinePlanner(),
        registry,
        messages=conversation(25),
        context=ContextManager(4000, enabled=False),
    )
    assert not [e for e in session.send("hello world") if e["type"] == "compact"]


def test_chat_app_runs_skill_command_and_archives_compaction(project, tmp_path):
    service = SearchService(Workspace(tmp_path / "ws"))
    service.workspace.add(chunks_from_text("a.txt", "graphene conducts electricity"))
    chat = ChatApp(service, tmp_path / "chat", project_root=project)
    conv = chat.conversations.create()
    events = list(chat.send(conv["id"], "/demo-skill make a demo"))
    assert [e["name"] for e in events if e["type"] == "tool_call"] == ["use_skill"]
    final = events[-1]["answer"]
    assert "demo-skill" in final and "make a demo" in final
    chat.settings.update({"context_window": 2048, "compact_threshold": 0.3})
    saved = chat.conversations.get(conv["id"])
    saved["messages"] += conversation(12, tool_chars=500)[1:]
    chat.conversations.save(saved)
    events = list(chat.compact(conv["id"]))
    assert any(e["type"] == "compact" for e in events)
    assert list((tmp_path / "chat" / "archive").glob(f"{conv['id']}-*.json"))
    assert chat.conversations.get(conv["id"])["messages"][0].get("compacted") is True
