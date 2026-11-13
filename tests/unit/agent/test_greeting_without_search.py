"""A greeting gets a reply with no tool call; a real question still searches (placeholder)."""

import pytest

from laris.shared.backend import load_backend


def _turn(text: str):
    backend = load_backend(None)
    return backend.chat([{"role": "user", "content": text}], [])


@pytest.mark.parametrize("text", ["hello", "Hello!", "  hi ", "xin chào", "Chào bạn.", "hey?"])
def test_greeting_gets_a_reply_and_no_tool_call(text):
    turn = _turn(text)
    assert not turn.tool_calls
    assert "mô hình ngôn ngữ" in turn.content


@pytest.mark.parametrize(
    "text", ["hello world paper on graphs", "what is BM25", "chào các tác giả của bài"]
)
def test_a_real_question_still_searches(text):
    assert [c.name for c in _turn(text).tool_calls] == ["search_corpus"]
