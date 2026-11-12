"""Engine protocol E1: every event and command is described by the schema and validated by it."""

import json
from pathlib import Path

import pytest

from laris.protocol import engine as e1

SCHEMA_FILE = Path(e1.__file__).with_name("e1.schema.json")

EVENTS = [
    {
        "type": "ready",
        "version": "1",
        "engine": "2.0.0",
        "session": "abc",
        "cwd": "/w",
        "mode": "ask",
    },
    {"type": "text", "delta": "xin chào"},
    {"type": "tool_call", "id": "call_1", "name": "search_corpus", "arguments": {"query": "x"}},
    {"type": "tool_result", "id": "call_1", "name": "search_corpus", "result": {"hits": []}},
    {"type": "plan", "source": "auto", "steps": [{"text": "a", "status": "pending"}]},
    {"type": "permission_request", "id": "perm_1", "tool": "write_file", "arguments": {}},
    {"type": "status", "kind": "brain", "data": {"trace": ["a"]}},
    {"type": "usage", "tokens": 10, "window": 100},
    {"type": "compact", "before": 90, "after": 20, "summarized": 5, "method": "trim"},
    {"type": "goal", "complete": False, "open": ["a"], "failed": []},
    {"type": "completion", "id": "c1", "items": [{"value": "help", "description": ""}]},
    {"type": "error", "code": "busy", "message": "m"},
    {"type": "done", "status": "completed", "answer": "ok"},
]
COMMANDS = [
    {"type": "user_message", "text": "hi"},
    {"type": "permission_response", "id": "perm_1", "decision": "allow", "remember": True},
    {"type": "interrupt"},
    {"type": "command", "name": "compact", "args": "keep results"},
    {"type": "set_mode", "mode": "acceptEdits"},
    {"type": "complete", "id": "c1", "trigger": "/", "text": "he"},
    {"type": "shutdown"},
]


def test_every_event_and_command_has_an_example_and_round_trips():
    assert {e["type"] for e in EVENTS} == set(e1.EVENTS)
    assert {c["type"] for c in COMMANDS} == set(e1.COMMANDS)
    for event in EVENTS:
        parsed = e1.parse_event(event)
        assert parsed.model_dump(mode="json")["type"] == event["type"]
    for command in COMMANDS:
        assert e1.parse_command(command).model_dump(mode="json")["type"] == command["type"]


def test_the_shipped_schema_equals_the_generated_one_and_names_every_message():
    shipped = json.loads(SCHEMA_FILE.read_text(encoding="utf-8"))
    assert shipped == json.loads(json.dumps(e1.json_schema()))
    assert shipped["version"] == e1.E1_VERSION == "1"
    for side, table in (("events", e1.EVENTS), ("commands", e1.COMMANDS)):
        names = {
            d["properties"]["type"]["const"]
            if "const" in d["properties"]["type"]
            else d["properties"]["type"]["default"]
            for d in shipped[side]["$defs"].values()
            if "type" in d.get("properties", {})
        }
        assert set(table) <= names


@pytest.mark.parametrize(
    "bad",
    [
        {"type": "nope"},
        {"text": "no type"},
        {"type": "text"},  # delta missing
        {"type": "text", "delta": "x", "extra": 1},  # unknown field
        {"type": "usage", "tokens": -1, "window": 1},
        "not an object",
    ],
)
def test_malformed_events_are_rejected_with_a_readable_reason(bad):
    with pytest.raises(e1.ProtocolError):
        e1.parse_event(bad)


@pytest.mark.parametrize(
    "bad",
    [
        {"type": "user_message", "text": ""},
        {"type": "permission_response", "id": "p", "decision": "maybe"},
        {"type": "set_mode", "mode": "yolo"},
        {"type": "complete", "id": "c", "trigger": "#"},
        {"type": "command", "name": ""},
        {"type": "interrupt", "extra": True},
    ],
)
def test_malformed_commands_are_rejected(bad):
    with pytest.raises(e1.ProtocolError):
        e1.parse_command(bad)


def test_the_error_names_the_field():
    with pytest.raises(e1.ProtocolError, match="decision"):
        e1.parse_command({"type": "permission_response", "id": "p", "decision": "maybe"})


def test_a_version_mismatch_is_reported_for_the_user():
    assert e1.check_version({"version": "1"}) is None
    message = e1.check_version({"version": "2"})
    assert "version 1" in message and "'2'" in message and "update" in message
    assert e1.check_version({}) is not None
