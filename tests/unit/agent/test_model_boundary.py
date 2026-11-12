"""T38: the boundary any core model must satisfy, checked with a scripted reference model.
No model is trained, loaded or fitted here."""

import json

import pytest

from laris.client.agent.builtin_tools import build_registry
from laris.client.agent.loop import AgentSession
from laris.client.agent.provider import AssistantTurn, ChatProvider, ToolCall
from laris.client.agent.tools import Sandbox
from laris.client.application.service import SearchService
from laris.client.application.workspace import Workspace, chunks_from_text
from laris.server.serving.model_server import ModelService, load_backend
from laris.shared.harness.runtime import HarnessRuntime
from laris.shared.plan import PLAN_TOOL

QA = "Assumptions: none. Uncertainties: none. Next step: none. Sources: solar.txt."


class ReferenceModel(ChatProvider):
    """The smallest model that honours the boundary: scripted turns, optional private reasoning."""

    name = "reference"

    def __init__(self, turns=None):
        self.turns = list(turns or [AssistantTurn("hello")])
        self.calls = []

    def chat(self, messages, tools):
        self.calls.append((list(messages), list(tools)))
        return self.turns.pop(0) if len(self.turns) > 1 else self.turns[0]

    def stream(self, messages, tools):
        yield {"type": "reasoning", "delta": "private chain of thought about the task"}
        yield from super().stream(messages, tools)


def embed(texts):
    return [[float(len(t)), 1.0, 0.0] for t in texts]


def make(project, tmp_path, turns):
    rt = HarnessRuntime.load(project)
    service = SearchService(Workspace(tmp_path / "ws"))
    service.workspace.add(chunks_from_text("solar.txt", "Perovskite cells reach 25% efficiency."))
    registry = build_registry(service, Sandbox([project], tmp_path / "o", policy=rt.paths), rt)
    model = ReferenceModel(turns)
    return rt, registry, model


def test_backend_loading_accepts_providers_and_rejects_everything_else():
    backend = load_backend("tests.unit.agent.test_model_boundary:ReferenceModel")
    assert isinstance(backend, ChatProvider) and backend.chat([], []).content == "hello"
    with pytest.raises(TypeError):
        load_backend("json:JSONDecoder")  # constructs, but is not a ChatProvider
    with pytest.raises(ValueError):
        load_backend("no_class_given")


def test_server_wire_format_for_text_and_tool_calls_and_embeddings():
    call = ToolCall("c1", "search_corpus", {"query": "x"})
    service = ModelService(ReferenceModel([AssistantTurn(None, [call])]), "ref", embed)
    message = service.complete({"messages": [{"role": "user", "content": "hi"}]})["choices"][0]
    assert message["finish_reason"] == "tool_calls"
    sent = message["message"]["tool_calls"][0]
    assert sent["function"]["name"] == "search_corpus"
    assert json.loads(sent["function"]["arguments"]) == {"query": "x"}
    vectors = service.embeddings({"input": ["ab", "abcd"]})["data"]
    assert [v["index"] for v in vectors] == [0, 1] and len(
        {len(v["embedding"]) for v in vectors}
    ) == 1
    assert ModelService(ReferenceModel(), "ref").models()["data"][0]["id"] == "ref"


def test_tool_calls_are_validated_and_disallowed_tools_return_errors(project, tmp_path):
    rt, registry, _ = make(project, tmp_path, [])
    model = ReferenceModel(
        [
            AssistantTurn(None, [ToolCall("a", "no_such_tool", {})]),
            AssistantTurn(None, [ToolCall("b", "search_corpus", {"bad": 1})]),
            AssistantTurn(QA),
        ]
    )
    session = AgentSession(model, registry, rt)
    events = list(session.send("find cells"))
    errors = [e["result"]["error"]["code"] for e in events if e["type"] == "tool_result"]
    assert len(errors) == 2 and all(errors)  # an error result each, no exception
    assert events[-1]["status"] in {"completed", "unverified", "max_steps"}


def test_plan_tool_is_available_and_the_model_can_use_it(project, tmp_path):
    rt, registry, _ = make(project, tmp_path, [])
    steps = [{"text": "search", "status": "in_progress"}, {"text": "answer", "status": "pending"}]
    model = ReferenceModel(
        [AssistantTurn(None, [ToolCall("p", PLAN_TOOL, {"steps": steps})]), AssistantTurn(QA)]
    )
    events = list(AgentSession(model, registry, rt).send("compare two things step by step"))
    assert any(e["type"] == "plan" for e in events)
    assert PLAN_TOOL in [t["function"]["name"] for t in model.calls[0][1]]


def test_the_brain_brief_reaches_the_model_hidden_and_reasoning_never_surfaces(project, tmp_path):
    rt, registry, model = make(project, tmp_path, [AssistantTurn(QA)])
    session = AgentSession(model, registry, rt)
    events = list(session.send("Hãy xác minh các trích dẫn của bài báo"))
    brief = [m for m in model.calls[0][0] if m["role"] == "user" and "Domain:" in str(m["content"])]
    assert brief  # the model gets the brief as a message
    shown = json.dumps([e for e in events if e["type"] in {"text", "brain"}], ensure_ascii=False)
    assert "private chain of thought" not in shown and "Domain:" not in shown
    assert "private chain of thought" not in json.dumps(session.messages, ensure_ascii=False)


def test_messages_given_to_the_model_carry_only_wire_keys(project, tmp_path):
    rt, registry, model = make(project, tmp_path, [AssistantTurn(QA)])
    list(AgentSession(model, registry, rt).send("what do the cells reach?"))
    allowed = {"role", "content", "tool_calls", "tool_call_id", "name"}
    for message in model.calls[0][0]:
        assert set(message) <= allowed
    spec = model.calls[0][1][0]
    assert spec["type"] == "function" and {"name", "description", "parameters"} <= set(
        spec["function"]
    )
