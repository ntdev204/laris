"""Agentic scenario suite (ADR-017, SR-H8): the harness plans, tracks, reflects, completes,
resumes and stays inside its limits. A scripted provider stands in for the model, so nothing here
says anything about the quality of a trained model: the core model is NOT QUALIFIED."""

import json

import pytest

from agent.builtin_tools import build_registry
from agent.loop import AgentSession
from agent.provider import AssistantTurn, ChatProvider, ProviderError, ToolCall
from agent.tools import Sandbox
from application.chat_app import ChatApp
from application.service import SearchService
from application.workspace import Workspace, chunks_from_text
from harness.runtime import HarnessRuntime

CITED = "Perovskite cells reach 25% efficiency [nguồn #1]."
LONG_GOAL = "Find the efficiency of perovskite solar cells then compare it with silicon and report"


def plan(*steps):
    return ToolCall("p" + str(len(steps)) + steps[0][0], "update_plan", {"steps": [
        {"text": t, "status": s} for t, s in steps]})  # fmt: skip


def search(query, call_id="s1"):
    return ToolCall(call_id, "search_corpus", {"query": query, "top_k": 3})


class Scripted(ChatProvider):
    name = "scripted"

    def __init__(self, turns):
        self.turns = list(turns)
        self.views = []
        self.tool_names = []

    def chat(self, messages, tools):
        self.views.append(messages)
        self.tool_names.append([t["function"]["name"] for t in tools])
        if not self.turns:
            raise ProviderError("the scripted model has nothing left to say")
        return self.turns.pop(0)


@pytest.fixture
def rig(project, tmp_path):
    def make(provider, overrides=None, plan_steps=None):
        rt = HarnessRuntime.load(project, overrides)
        service = SearchService(Workspace(tmp_path / "ws"))
        service.workspace.add(
            chunks_from_text("solar.txt", "Perovskite cells reach 25% efficiency.")
        )
        registry = build_registry(service, Sandbox([project], tmp_path / "o", policy=rt.paths), rt)
        return AgentSession(provider, registry, rt, plan=plan_steps)

    return make


def kinds(events):
    return [e["type"] for e in events]


# 1. a visible plan exists before the first tool call -----------------------------------------
def test_plan_is_shown_before_the_first_tool_call_and_tracked(rig):
    provider = Scripted([
        AssistantTurn(None, [plan(("find efficiency", "in_progress"), ("compare", "pending"))]),
        AssistantTurn(None, [search("perovskite efficiency")]),
        AssistantTurn(None, [plan(("find efficiency", "done"), ("compare", "done"))]),
        AssistantTurn(CITED),
    ])  # fmt: skip
    events = list(rig(provider).send(LONG_GOAL))
    order = kinds(events)
    first_plan = order.index("plan")
    first_search = next(i for i, e in enumerate(events)
                        if e["type"] == "tool_call" and e["name"] == "search_corpus")  # fmt: skip
    assert first_plan < first_search
    plans = [e for e in events if e["type"] == "plan"]
    assert plans[0]["source"] == "model" and plans[-1]["steps"][-1]["status"] == "done"
    goal = next(e for e in events if e["type"] == "goal")
    assert goal["complete"] is True and events[-1]["status"] == "completed"
    seen_by_model = json.dumps(provider.views[1])
    assert "find efficiency" in seen_by_model  # the model is shown its own plan each step


def test_without_a_plan_the_harness_records_one_before_acting(rig):
    provider = Scripted(
        [AssistantTurn(None, [search("perovskite efficiency")]), AssistantTurn(CITED)]
    )
    events = list(rig(provider).send(LONG_GOAL))
    order = kinds(events)
    assert order.index("plan") < order.index("tool_call")
    auto = next(e for e in events if e["type"] == "plan")
    assert auto["source"] == "auto" and auto["steps"][0]["status"] == "in_progress"
    goal = next(e for e in events if e["type"] == "goal")
    assert goal["complete"] is True  # the harness closed its own step when the tool succeeded
    assert "plan" in json.dumps(provider.views[0])  # the first call already asked for a plan


def test_a_short_question_needs_no_plan(rig):
    provider = Scripted([AssistantTurn(None, [search("perovskite")]), AssistantTurn(CITED)])
    events = list(rig(provider).send("perovskite?"))
    assert "plan" not in kinds(events) and "goal" not in kinds(events)


def test_planning_can_be_switched_off(rig):
    provider = Scripted([AssistantTurn(None, [search("perovskite")]), AssistantTurn(CITED)])
    events = list(rig(provider, {"agent.plan.mode": "off"}).send(LONG_GOAL))
    assert "plan" not in kinds(events)
    assert all("update_plan" not in names for names in provider.tool_names)  # not offered


# 2. reflect and replan, bounded --------------------------------------------------------------
def test_an_empty_result_triggers_a_replan_that_can_succeed(rig):
    provider = Scripted([
        AssistantTurn(None, [plan(("search", "in_progress"))]),
        AssistantTurn(None, [search("quantum gravity")]),
        AssistantTurn(None, [plan(("search again with other words", "in_progress")),
                             search("perovskite efficiency", "s2")]),
        AssistantTurn(None, [plan(("search again with other words", "done"))]),
        AssistantTurn(CITED),
    ])  # fmt: skip
    events = list(rig(provider).send(LONG_GOAL))
    reflect = [e for e in events if e["type"] == "reflect"]
    assert (
        len(reflect) == 1
        and reflect[0]["replans"] == 1
        and "search_corpus" in reflect[0]["issues"][0]
    )
    assert events[-1]["status"] == "completed"
    assert any("Còn 1 lần" in json.dumps(m, ensure_ascii=False) for m in provider.views[2])


def test_replanning_is_bounded_then_the_agent_reports_the_gap(rig):
    turns = [AssistantTurn(None, [plan(("search", "in_progress"))])]
    for i in range(1, 6):  # a model that never gives up
        turns.append(AssistantTurn(None, [search(f"nothing here {i}", f"s{i}")]))
    turns.append(AssistantTurn(None, [plan(("search", "failed"))]))
    turns.append(AssistantTurn("Không tìm thấy bằng chứng cho yêu cầu này."))
    provider = Scripted(turns)
    session = rig(provider)
    events = list(session.send(LONG_GOAL))
    reflects = [e for e in events if e["type"] == "reflect"]
    assert sum(1 for e in reflects if not e.get("budget_out")) == 2  # agent.reflect.max_replans
    assert sum(1 for e in reflects if e.get("budget_out")) == 1  # told once to stop retrying
    steps = sum(1 for k in kinds(events) if k == "usage")
    assert steps == 1 and events[-1]["status"] in {"completed", "max_steps"}  # the cap held


# 3. completion check -------------------------------------------------------------------------
def test_a_goal_is_not_closed_while_steps_are_open(rig):
    provider = Scripted([
        AssistantTurn(None, [plan(("find", "in_progress"), ("compare", "pending"))]),
        AssistantTurn(None, [search("perovskite efficiency")]),
        AssistantTurn(CITED),  # tries to finish with "compare" still pending
        AssistantTurn(None, [plan(("find", "done"), ("compare", "skipped"))]),
        AssistantTurn(CITED),
    ])  # fmt: skip
    events = list(rig(provider).send(LONG_GOAL))
    retry = [e for e in events if e["type"] == "goal" and e.get("retry")]
    assert len(retry) == 1 and retry[0]["open"] == ["find", "compare"]
    final = [e for e in events if e["type"] == "goal"][-1]
    assert final["complete"] is True and events[-1]["status"] == "completed"


def test_an_unfinished_goal_is_reported_when_the_model_will_not_finish_it(rig):
    stuck = [AssistantTurn(None, [plan(("find", "in_progress"), ("compare", "pending"))])]
    stuck += [AssistantTurn(None, [search("perovskite efficiency")])]
    stuck += [AssistantTurn(CITED)] * 4
    session = rig(Scripted(stuck))
    events = list(session.send(LONG_GOAL))
    answer = events[-1]["answer"]
    assert "Chưa hoàn thành" in answer and "compare" in answer
    assert [e for e in events if e["type"] == "goal"][-1]["complete"] is False
    assert session.last_turn["goal"] == "open"


# 4. resume: an interrupted goal continues without repeating finished steps -------------------
def test_an_interrupted_plan_survives_resume_and_is_not_repeated(project, tmp_path):
    service = SearchService(Workspace(tmp_path / "ws"))
    service.workspace.add(chunks_from_text("solar.txt", "Perovskite cells reach 25% efficiency."))
    first = Scripted([
        AssistantTurn(None, [plan(("find efficiency", "in_progress"), ("compare", "pending"))]),
        AssistantTurn(None, [search("perovskite efficiency")]),
        AssistantTurn(None, [plan(("find efficiency", "done"), ("compare", "in_progress"))]),
    ])  # fmt: skip
    app = ChatApp(service, project, project / "chat")
    app.provider = lambda runtime: first  # type: ignore[method-assign]
    conversation = app.conversations.create()
    list(app.send(conversation["id"], LONG_GOAL))  # runs out of script: the provider fails
    saved = app.conversations.get(conversation["id"])
    assert [s["status"] for s in saved["plan"]] == ["done", "in_progress"]

    second = Scripted([
        AssistantTurn(None, [plan(("find efficiency", "done"), ("compare", "done"))]),
        AssistantTurn(CITED),
    ])  # fmt: skip
    app2 = ChatApp(service, project, project / "chat")
    app2.provider = lambda runtime: second  # type: ignore[method-assign]
    events = list(app2.send(conversation["id"], "tiếp tục"))
    assert next(e for e in events if e["type"] == "plan")["source"] == "resumed"
    shown = json.dumps(second.views[0], ensure_ascii=False)
    assert "find efficiency (done)" in shown and "compare (in_progress)" in shown
    assert not [e for e in events if e["type"] == "tool_call" and e["name"] == "search_corpus"]
    assert events[-1]["status"] == "completed"
    assert app2.conversations.get(conversation["id"])["plan"][-1]["status"] == "done"


# 5. memory: the plan is kept with the answer in the vault ------------------------------------
def test_the_finished_goal_and_its_plan_are_written_to_the_vault(project, tmp_path):
    service = SearchService(Workspace(tmp_path / "ws"))
    service.workspace.add(chunks_from_text("solar.txt", "Perovskite cells reach 25% efficiency."))
    provider = Scripted([
        AssistantTurn(None, [plan(("find efficiency", "in_progress"))]),
        AssistantTurn(None, [search("perovskite efficiency")]),
        AssistantTurn(None, [plan(("find efficiency", "done"))]),
        AssistantTurn(CITED),
    ])  # fmt: skip
    app = ChatApp(service, project, project / "chat")
    app.provider = lambda runtime: provider  # type: ignore[method-assign]
    conversation = app.conversations.create()
    events = list(app.send(conversation["id"], LONG_GOAL))
    learning = next(e for e in events if e["type"] == "learning")
    assert learning.get("vault_status") not in (None, "failed")
    notes = list((project / "vault").rglob("*.md"))
    assert any("find efficiency" in n.read_text(encoding="utf-8") for n in notes)


# 6. bounded autonomy: planning never widens a limit ------------------------------------------
def test_planning_does_not_widen_tools_steps_or_approvals(rig, project, tmp_path):
    write = ToolCall("w1", "write_file", {"path": "x.txt", "content": "hi"})
    provider = Scripted([
        AssistantTurn(None, [plan(("write the file", "in_progress"))]),
        AssistantTurn(None, [write]),
        AssistantTurn(None, [plan(("write the file", "failed"))]),
        AssistantTurn("Không ghi được tệp vì chưa được duyệt."),
    ])  # fmt: skip
    session = rig(provider)  # no approver: writes are refused
    events = list(session.send(LONG_GOAL))
    result = next(e for e in events if e["type"] == "tool_result" and e["name"] == "write_file")
    assert result["result"]["error"]["code"] == "approval_denied"
    assert not (tmp_path / "o" / "x.txt").exists()


def test_the_step_ceiling_holds_even_for_a_planner_that_never_stops(rig):
    turns = [AssistantTurn(None, [plan((f"step {i}", "in_progress"))]) for i in range(40)]
    session = rig(Scripted(turns))
    events = list(session.send(LONG_GOAL))
    assert events[-1]["status"] == "max_steps"
    assert sum(1 for e in events if e["type"] == "tool_call") <= session.cfg.max_steps


def test_a_bad_plan_is_refused_with_a_typed_error(rig):
    bad = ToolCall("b1", "update_plan", {"steps": [{"text": "x", "status": "someday"}]})
    provider = Scripted([AssistantTurn(None, [bad]), AssistantTurn(CITED)])
    events = list(rig(provider).send("perovskite?"))
    result = next(e for e in events if e["type"] == "tool_result")["result"]
    assert result["error"]["code"] == "invalid_plan"


# 7. the report ------------------------------------------------------------------------------
def test_the_report_states_that_the_model_is_not_qualified():
    from pathlib import Path

    text = (Path(__file__).resolve().parents[3] / "docs/testing/AGENTIC_SCENARIOS.md").read_text(
        encoding="utf-8"
    )
    assert "NOT QUALIFIED" in text and "scripted" in text
