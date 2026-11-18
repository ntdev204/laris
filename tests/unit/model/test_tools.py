"""T149: the scientific tools served by the model block give the results of the library they wrap.

Fixture tests: the extraction annotations score the baseline macro-F1 through the tool and the
citation fixture returns its gold edges. The route is driven through ASGI (no network)."""

import asyncio
import json
from pathlib import Path

import pytest

from laris.model.app import create_app
from laris.model.service import ModelService
from laris.model.tools import Limits, ToolBox, ToolError, UnknownTool
from laris.research.evaluation.extraction import (
    TYPES,
    evaluate,
    extract_spans,
    gate,
    load_annotations,
)
from laris.shared.backend import load_backend

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures"
LIMITS = Limits(max_chars=100_000, max_documents=10)
GROUPS = ("claims", "methods", "datasets", "metrics", "results", "limitations", "assumptions")


@pytest.fixture(scope="module")
def tools() -> ToolBox:
    return ToolBox(LIMITS)


def spans_through_tool(tools: ToolBox, text: str):
    found = tools.call("extract_discourse", {"text": text, "document_id": "eval"})
    return [
        (kind, r["coordinate"]["char_start"], r["coordinate"]["char_end"])
        for kind, group in zip(TYPES, GROUPS)
        for r in found[group]
    ]


def test_schemas_are_function_schemas_and_stable(tools):
    names = [s["function"]["name"] for s in tools.schemas()]
    assert names == sorted(names) and len(names) == 6
    for schema in tools.schemas():
        assert schema["type"] == "function"
        params = schema["function"]["parameters"]
        assert params["type"] == "object" and params["additionalProperties"] is False
        assert set(params["required"]) <= set(params["properties"])
    assert json.dumps(tools.schemas()) == json.dumps(ToolBox(LIMITS).schemas())


def test_extraction_through_the_tool_reproduces_the_baseline(tools):
    docs = load_annotations(FIXTURES / "extraction" / "annotations.json")
    baseline = json.loads((FIXTURES / "extraction" / "baseline.json").read_text())
    for doc in docs:  # the same spans as calling the library
        assert spans_through_tool(tools, doc["text"]) == extract_spans(doc["text"])
    report = evaluate(docs, predict=lambda text: spans_through_tool(tools, text))
    assert report["macro_f1"] == baseline["macro_f1"] == 0.9433
    assert gate(report, baseline) == []


def test_citation_fixture_returns_its_gold_edges(tools):
    data = json.loads((FIXTURES / "scholarly" / "citations.json").read_text())
    documents = [{"id": k, "text": t} for k, t in sorted(data["documents"].items())]
    result = tools.call("analyse_citations", {"documents": documents})
    assert sorted(map(tuple, ([e["citing"], e["cited"]] for e in result["edges"]))) == sorted(
        map(tuple, data["gold_edges"])
    )
    assert result["scope"]["documents"] == 4
    unresolved = tools.call("analyse_citations", {"documents": documents, "kind": "unresolved"})
    assert "unresolved" in unresolved


def test_bibliography_fixture(tools):
    cases = json.loads((FIXTURES / "scholarly" / "biblio.json").read_text())
    assert cases  # the fixture is a list or an object of cases; each text must at least not fail
    items = cases if isinstance(cases, list) else list(cases.values())
    for case in items:
        text = case["text"] if isinstance(case, dict) and "text" in case else json.dumps(case)
        found = tools.call("parse_bibliography", {"text": text})
        assert set(found) == {"title", "authors", "year", "doi", "arxiv", "evidence", "properties"}


def test_units_limitations_and_mining(tools):
    quantities = tools.call(
        "normalize_quantities", {"text": "Heated to 300 K under 2.5 GPa.", "document_id": "d"}
    )
    assert [q["canonical_unit"] for q in quantities] == ["K", "Pa"]
    assert quantities[1]["canonical_value"] == 2.5e9
    assert quantities[0]["coordinate"]["document_id"] == "d"
    found = tools.call(
        "detect_limitations",
        {"text": "A limitation of this study is that only English papers were used."},
    )
    assert found["limitations"] and found["document_id"] == "doc"
    docs = [
        {"id": "a", "text": "Perovskite cells degrade."},
        {"id": "b", "text": "Perovskite cells degrade."},
    ]
    assert tools.call("mine_literature", {"documents": docs})["scope"]["documents"] == 2
    pairs = tools.call(
        "mine_literature", {"documents": docs, "kind": "near_duplicates", "threshold": 0.5}
    )
    assert isinstance(pairs, dict)


@pytest.mark.parametrize(
    ("name", "arguments", "code"),
    [
        ("extract_discourse", {}, "invalid_arguments"),
        ("extract_discourse", {"text": ""}, "invalid_arguments"),
        ("extract_discourse", {"text": 5}, "invalid_arguments"),
        ("extract_discourse", {"text": "x", "extra": 1}, "invalid_arguments"),
        ("extract_discourse", {"text": "x" * 100_001}, "input_too_large"),
        ("extract_discourse", {"text": "x", "document_id": " "}, "invalid_arguments"),
        ("extract_discourse", [], "invalid_arguments"),
        ("detect_limitations", {"text": "x", "strip_headers": "yes"}, "invalid_arguments"),
        ("analyse_citations", {"documents": []}, "invalid_arguments"),
        ("analyse_citations", {"documents": [{"id": "a"}]}, "invalid_arguments"),
        ("analyse_citations", {"documents": [{"id": "a", "text": "t"}] * 2}, "invalid_arguments"),
        (
            "analyse_citations",
            {"documents": [{"id": str(i), "text": "t"} for i in range(11)]},
            "input_too_large",
        ),
        (
            "analyse_citations",
            {"documents": [{"id": "a", "text": "t"}], "kind": "nope"},
            "invalid_arguments",
        ),
        (
            "mine_literature",
            {"documents": [{"id": "a", "text": "t"}], "kind": "groups", "threshold": 2},
            "invalid_arguments",
        ),
        ("parse_bibliography", {"text": "t", "metadata": 3}, "invalid_arguments"),
    ],
)
def test_bad_calls_are_typed_refusals(tools, name, arguments, code):
    with pytest.raises(ToolError) as caught:
        tools.call(name, arguments)
    assert caught.value.code == code


def test_unknown_tool_and_unexpected_failure_do_not_leak(tools, monkeypatch):
    with pytest.raises(UnknownTool):
        tools.call("nope", {})

    def boom(args, limits):
        raise RuntimeError("secret text from the input")

    monkeypatch.setattr("laris.model.tools._extract_discourse", boom)
    with pytest.raises(ToolError) as caught:
        ToolBox(LIMITS).call("extract_discourse", {"text": "x"})
    assert caught.value.code == "tool_failed" and "secret" not in caught.value.message


def test_a_library_refusal_does_not_quote_the_input(monkeypatch):
    from laris.shared.core.errors import ModuleContractViolationError

    def refuse(args, limits):
        raise ModuleContractViolationError("bad input: secret text")

    monkeypatch.setattr("laris.model.tools._extract_discourse", refuse)
    with pytest.raises(ToolError) as caught:
        ToolBox(LIMITS).call("extract_discourse", {"text": "x"})
    assert caught.value.code == "rejected" and "secret" not in caught.value.message


# -- the HTTP route, through ASGI ----------------------------------------------------------------
def call(app, method: str, path: str, body=None):
    raw = b"" if body is None else json.dumps(body).encode()
    sent = []

    async def receive():
        return {"type": "http.request", "body": raw, "more_body": False}

    async def send(message):
        sent.append(message)

    scope = {
        "type": "http",
        "method": method,
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "headers": [
            (b"content-length", str(len(raw)).encode()),
            (b"content-type", b"application/json"),
        ],
        "http_version": "1.1",
        "scheme": "http",
        "server": ("test", 80),
        "client": ("test", 1),
    }
    asyncio.run(app(scope, receive, send))
    status = next(m["status"] for m in sent if m["type"] == "http.response.start")
    payload = b"".join(m.get("body", b"") for m in sent if m["type"] == "http.response.body")
    return status, json.loads(payload)


@pytest.fixture(scope="module")
def app(tools):
    service = ModelService(load_backend(None), "test", None, None, tools)
    return create_app(service, 1_000_000)


def test_route_lists_and_runs_tools(app, tools):
    status, body = call(app, "GET", "/v1/tools")
    assert status == 200 and body["tools"] == tools.schemas()
    status, body = call(
        app, "POST", "/v1/tools/normalize_quantities", {"arguments": {"text": "5 K"}}
    )
    assert status == 200 and body["result"][0]["raw_unit"] == "K" and "error" not in body
    assert call(app, "GET", "/health")[1]["tools"] == 6


def test_route_errors(app):
    status, body = call(app, "POST", "/v1/tools/extract_discourse", {"arguments": {"text": ""}})
    assert status == 200 and body == {
        "error": {"message": "text must be a non-empty string", "type": "invalid_arguments"}
    }
    assert call(app, "POST", "/v1/tools/nope", {"arguments": {}})[0] == 404
    assert call(app, "POST", "/v1/tools/extract_discourse", {"arguments": {}, "x": 1})[0] == 400
    assert call(app, "POST", "/v1/tools/extract_discourse", [1])[0] == 400


def test_no_toolbox_means_no_tools():
    app = create_app(ModelService(load_backend(None), "test"), 1000)
    assert call(app, "GET", "/v1/tools")[1] == {"tools": []}
    assert call(app, "POST", "/v1/tools/extract_discourse", {"arguments": {"text": "x"}})[0] == 404
