import pytest

from laris.protocol import (
    PROTOCOL_HEADER,
    PROTOCOL_VERSION,
    ChatRequest,
    EmbedRequest,
    decode_events,
    encode_done,
    encode_event,
)


def test_sse_round_trip_stops_at_done() -> None:
    wire = encode_event({"a": 1, "t": "tiếng Việt"}) + encode_event({"b": 2}) + encode_done()
    wire += encode_event({"after": True})
    assert list(decode_events(wire.decode().splitlines())) == [
        {"a": 1, "t": "tiếng Việt"},
        {"b": 2},
    ]


def test_sse_skips_comments_and_blank_lines() -> None:
    lines = [": keepalive", "", b'data: {"x": 1}', b"data: [DONE]"]
    assert list(decode_events(lines)) == [{"x": 1}]


def test_p1_request_defaults_and_extra_fields() -> None:
    req = ChatRequest(messages=[{"role": "user", "content": "hi"}], future_field=1)
    assert req.laris.kind == "turn" and req.tools == [] and req.stream is True
    with pytest.raises(ValueError):
        ChatRequest(messages="not a list")  # type: ignore[arg-type]


def test_embed_request_accepts_one_text_or_many() -> None:
    assert EmbedRequest(input="a").input == "a"
    assert EmbedRequest(input=["a", "b"]).input == ["a", "b"]


def test_version_constants() -> None:
    assert PROTOCOL_VERSION == "1" and PROTOCOL_HEADER == "X-Laris-Protocol"
