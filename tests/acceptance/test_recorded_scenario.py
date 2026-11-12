"""T82 (SR-C7): the golden session recorded from the real engine is the scenario the Ink front end
replays (`packaging/npm/test/scenarios/acceptance_session.json`). This test keeps that file equal to
what the engine produces today, so the Ink run cannot drift from the engine.

To refresh the file after an intended protocol change:
    LARIS_UPDATE_SCENARIOS=1 python -m pytest tests/acceptance/test_recorded_scenario.py
"""

import json
import os
from pathlib import Path

import pytest

from laris.protocol import engine as e1
from tests.acceptance.conftest import golden_turns
from tests.acceptance.session import run_engine

SCENARIO = (
    Path(__file__).resolve().parents[2]
    / "packaging"
    / "npm"
    / "test"
    / "scenarios"
    / "acceptance_session.json"
)

pytestmark = pytest.mark.usefixtures("use_placeholder_model")

LINE = {
    "model": "laris-base",
    "mode": "default",
    "context": {"tokens": 1200, "window": 8000, "percent": 15},
    "tokens_left": 750,
    "tokens_used": 250,
    "token_limit": 1000,
    "unlimited": False,
    "branch": "develop",
    "sandbox": "ready",
    "queued": 0,
}


def normalise(events):
    """Fix what changes from run to run (ids, paths, clocks, token counts) and drop what the front
    end does not draw (the learning note)."""
    out = []
    for event in events:
        event = json.loads(json.dumps(event))
        if event["type"] == "ready":
            event.update(
                engine="2.0.0",
                session="abcdef12-0000",
                cwd="/work/demo",
                server="https://laris.example",
            )
        elif event["type"] == "status":
            if event["kind"] != "line":
                continue
            event["data"] = dict(LINE)
        elif event["type"] == "usage":
            event.update(tokens=1500, window=8000)
        out.append(event)
    return out


def build(events):
    """Events to scenario steps: the start-up events, then one step per command."""
    events = normalise(events)
    steps = [{"emit": [e for e in events if e["type"] in ("ready", "status")][:2]}]
    rest = [e for e in events if e["type"] not in ("ready",)][1:]
    cut = next(i for i, e in enumerate(rest) if e["type"] == "permission_request")
    request = rest[cut]
    steps.append(
        {
            "expect": {"type": "user_message", "text": "go"},
            "emit": rest[: cut + 1],
        }
    )
    steps.append(
        {
            "expect": {"type": "permission_response", "id": request["id"], "decision": "allow"},
            "emit": rest[cut + 1 :],
        }
    )
    return {"name": "the golden session, recorded from the engine", "steps": steps}


def test_the_ink_scenario_is_the_engine_golden_session(make_chat, project):
    events = run_engine(make_chat(golden_turns()), project)
    for event in events:
        e1.parse_event(event)  # every recorded event is valid E1
    built = build(events)
    if os.environ.get("LARIS_UPDATE_SCENARIOS") == "1":
        text = json.dumps(built, ensure_ascii=False, indent=1)
        SCENARIO.write_text(text + "\n", encoding="utf-8")
    assert json.loads(SCENARIO.read_text(encoding="utf-8")) == built
