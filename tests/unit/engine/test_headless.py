"""Headless mode: every output format and every exit code, with a scripted model (SR-C4).

A scripted provider stands in for the model: nothing here says anything about model quality."""

import io
import json

import pytest

from laris.client.agent.provider import AssistantTurn, ChatProvider, ProviderError, ToolCall
from laris.client.application.chat_app import ChatApp
from laris.client.application.service import SearchService
from laris.client.application.workspace import Workspace, chunks_from_text
from laris.client.headless import HeadlessOptions, run_headless, split_rules
from laris.protocol import engine as e1

pytestmark = pytest.mark.usefixtures("use_placeholder_model")


class Scripted(ChatProvider):
    name = "scripted"

    def __init__(self, turns):
        self.turns = list(turns)
        self.seen = []

    def chat(self, messages, tools):
        self.seen.append(messages)
        if not self.turns:
            raise ProviderError("the scripted model has nothing left to say")
        turn = self.turns.pop(0)
        if isinstance(turn, BaseException):
            raise turn
        return turn


CITED = "Perovskite cells reach 25% efficiency [nguồn #1]."


def search(i=1):
    return ToolCall(f"s{i}", "search_corpus", {"query": "perovskite", "top_k": 2})


def write(path="out.txt"):
    return ToolCall("w-" + path, "Write", {"path": path, "content": "hi\n"})


@pytest.fixture
def rig(tmp_path, project, monkeypatch):
    service = SearchService(Workspace(tmp_path / "ws"))
    service.workspace.add(chunks_from_text("solar.txt", "Perovskite cells reach 25% efficiency."))
    chat = ChatApp(service, project, project / "chat")

    def go(turns, **options):
        provider = Scripted(turns)
        monkeypatch.setattr(chat, "provider", lambda runtime: provider)
        out, err = io.StringIO(), io.StringIO()
        code = run_headless(chat, HeadlessOptions(**{"prompt": "go", **options}), out, err)
        return code, out.getvalue(), err.getvalue(), provider

    go.chat = chat
    return go


def test_text_format_prints_only_the_answer(rig):
    code, out, err, _ = rig([AssistantTurn("All done.")])
    assert (code, out, err) == (0, "All done.\n", "")


def test_json_format_is_one_result_object(rig):
    code, out, _, _ = rig(
        [AssistantTurn(None, [search()]), AssistantTurn(CITED)], output_format="json"
    )
    result = json.loads(out)
    assert code == 0 and result["type"] == "result" and result["status"] == "completed"
    assert result["answer"] == CITED and result["tool_calls"] == 1 and not result["is_error"]
    assert result["permission_denials"] == [] and len(result["session_id"]) >= 6
    assert len(out.splitlines()) == 1


def test_stream_json_is_engine_protocol_e1(rig):
    code, out, _, _ = rig(
        [AssistantTurn(None, [search()]), AssistantTurn(CITED)], output_format="stream-json"
    )
    events = [e1.parse_event(json.loads(line)) for line in out.splitlines()]
    kinds = [e.type for e in events]
    assert code == 0 and kinds[0] == "ready" and kinds[-1] == "done"
    assert "tool_call" in kinds and "tool_result" in kinds and "text" in kinds
    assert events[0].engine == "headless" and events[-1].status == "completed"


def test_standard_input_is_added_to_the_prompt(rig):
    code, out, _, provider = rig(
        [AssistantTurn("ok")], prompt="summarise", stdin_text="LINE-FROM-STDIN"
    )
    flat = json.dumps(provider.seen[0])
    assert code == 0 and "summarise" in flat and "LINE-FROM-STDIN" in flat
    code, _, err, _ = rig([AssistantTurn("x")], prompt="", stdin_text="")
    assert code == 2 and "nothing to do" in err
    code, _, _, provider = rig([AssistantTurn("ok")], prompt="", stdin_text="only stdin")
    assert code == 0 and "only stdin" in json.dumps(provider.seen[0])


def test_continue_and_resume_reuse_the_saved_session(rig):
    code, out, _, _ = rig([AssistantTurn("first")], output_format="json")
    first = json.loads(out)["session_id"]
    code, out, _, provider = rig(
        [AssistantTurn("second")], output_format="json", continue_last=True
    )
    assert json.loads(out)["session_id"] == first
    assert "go" in json.dumps(provider.seen[0])  # the earlier turn is part of the context
    code, out, _, _ = rig([AssistantTurn("third")], output_format="json", resume=first[:6])
    assert json.loads(out)["session_id"] == first
    code, _, err, _ = rig([AssistantTurn("x")], resume="zzzzzz")
    assert code == 2 and "no single session" in err


def test_continue_without_a_session_is_a_usage_error(rig):
    code, _, err, _ = rig([AssistantTurn("x")], continue_last=True)
    assert code == 2 and "no earlier session" in err


def test_max_turns_stops_a_runaway_run_and_is_validated(rig):
    turns = [AssistantTurn(None, [search(i)]) for i in range(8)]
    code, out, _, provider = rig(turns, max_turns=2, output_format="json")
    assert code == 1 and json.loads(out)["status"] != "completed" and len(provider.seen) <= 3
    for bad in (0, 11):
        assert rig([AssistantTurn("x")], max_turns=bad)[0] == 2


def test_permission_mode_plan_denies_writes_and_exit_code_is_3_when_stopped_by_it(rig, project):
    code, out, _, _ = rig(
        [
            AssistantTurn(None, [write("a.txt")]),
            AssistantTurn(None, [write("b.txt")]),
        ],  # then the model fails
        permission_mode="plan",
        output_format="json",
    )
    result = json.loads(out)
    assert code == 3 and result["permission_denials"] == ["Write", "Write"]
    assert not (project / "out.txt").exists()


def test_a_denied_action_followed_by_an_answer_still_completes(rig, project):
    code, out, _, _ = rig(
        [AssistantTurn(None, [write()]), AssistantTurn("I could not write the file.")],
        output_format="json",
    )  # default mode, nobody to ask: refused
    assert code == 0 and json.loads(out)["permission_denials"] == ["Write"]
    assert not (project / "out.txt").exists()


def test_allowed_tools_run_without_a_prompt_and_disallowed_are_refused(rig, project):
    code, out, _, _ = rig(
        [AssistantTurn(None, [write()]), AssistantTurn("written")],
        allowed_tools=["Write(out.txt)"],
        output_format="json",
    )
    assert code == 0 and (project / "out.txt").read_text() == "hi\n"
    assert json.loads(out)["permission_denials"] == []
    (project / "out.txt").unlink()
    code, out, _, _ = rig(
        [AssistantTurn(None, [write()]), AssistantTurn("could not")],
        permission_mode="acceptEdits",
        disallowed_tools=["Write"],
        output_format="json",
    )
    assert json.loads(out)["permission_denials"] == ["Write"] and not (project / "out.txt").exists()


def test_bypass_needs_policy_and_bad_rules_and_formats_are_usage_errors(rig):
    code, _, err, _ = rig([AssistantTurn("x")], permission_mode="bypass")
    assert code == 2 and "not allowed" in err
    code, _, err, _ = rig([AssistantTurn("x")], allowed_tools=["(("])
    assert code == 2 and "not a tool rule" in err
    code, _, err, _ = rig([AssistantTurn("x")], output_format="xml")
    assert code == 2 and "--output-format" in err


def test_a_failing_model_is_exit_1_with_the_reason_on_stderr(rig):
    code, out, err, _ = rig([ProviderError("model offline")], output_format="json")
    assert code == 1 and json.loads(out)["is_error"] is True and out.count("\n") == 1


def test_ctrl_c_is_exit_130_and_the_session_is_saved(rig):
    code, out, err, _ = rig([KeyboardInterrupt()])
    assert code == 130 and "interrupted" in err and out == ""
    assert rig.chat.conversations.list()  # what happened is kept


@pytest.mark.parametrize(
    "values,expected",
    [
        (["Read,Edit"], ["Read", "Edit"]),
        (["Bash(git status:*)", "Read"], ["Bash(git status:*)", "Read"]),
        (["Bash(a,b)", "Edit src"], ["Bash(a,b)", "Edit", "src"]),
        (None, []),
        ([""], []),
    ],
)
def test_rule_lists_split_on_commas_and_spaces_outside_parentheses(values, expected):
    assert split_rules(values) == expected
