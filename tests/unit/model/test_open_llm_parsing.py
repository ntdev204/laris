"""Parsing helpers of the open-weight chat backend (no weights are loaded)."""

from laris.model.inference.open_llm import parse_tool_calls, split_reasoning, template_messages


def test_reasoning_is_split_from_the_answer():
    assert split_reasoning("<think>\nstep\n</think>\n\nHello") == ("step", "\n\nHello")
    assert split_reasoning("step\n</think>\n\nHello") == ("step", "\n\nHello")  # tag in the prompt
    assert split_reasoning("plain") == ("", "plain")
    assert split_reasoning("<think>cut off") == ("cut off", "")


def test_xml_tool_call():
    text = (
        "Checking.\n<tool_call>\n<function=search>\n<parameter=query>\nbm25\n</parameter>\n"
        "<parameter=k>\n3\n</parameter>\n</function>\n</tool_call>"
    )
    content, calls = parse_tool_calls(text)
    assert content == "Checking."
    assert [(c.name, c.arguments) for c in calls] == [("search", {"query": "bm25", "k": 3})]


def test_json_tool_call_and_garbage():
    content, calls = parse_tool_calls(
        '<tool_call>{"name": "f", "arguments": {"a": 1}}</tool_call><tool_call>nope</tool_call>'
    )
    assert content == "" and [(c.name, c.arguments) for c in calls] == [("f", {"a": 1})]


def test_template_messages_decode_arguments():
    out = template_messages(
        [
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "1",
                        "type": "function",
                        "function": {"name": "f", "arguments": '{"a": 2}'},
                    }
                ],
            }
        ]
    )
    assert out[0]["content"] == "" and out[0]["tool_calls"][0]["function"]["arguments"] == {"a": 2}


def test_a_long_prompt_is_shortened_to_the_budget_without_touching_system_or_last_message():
    import pytest

    from laris.model.inference.open_llm import fit_to_budget
    from laris.protocol import ProviderError

    messages = [
        {"role": "system", "content": "S" * 3000},
        {"role": "user", "content": "question"},
        {"role": "assistant", "content": "", "tool_calls": [{"id": "1"}]},
        {"role": "tool", "content": "page " * 4000},
        {"role": "user", "content": "now answer"},
    ]

    def measure(items):
        return sum(len(str(m.get("content") or "")) for m in items)

    assert fit_to_budget(messages, measure, 0) is messages  # off
    fitted = fit_to_budget(messages, measure, 4500)
    assert measure(fitted) <= 4500
    assert fitted[0]["content"] == messages[0]["content"] and fitted[-1] == messages[-1]
    assert "shortened" in fitted[3]["content"]
    assert messages[3]["content"].startswith("page ")  # the input is not changed
    assert len(messages[3]["content"]) == 20000
    # when shortening is not enough, old turns go, and a tool result never loses its call
    small = fit_to_budget(messages, measure, 3200)
    assert small[0]["role"] == "system" and small[-1]["content"] == "now answer"
    assert all(m["role"] != "tool" for m in small)
    with pytest.raises(ProviderError):
        fit_to_budget(messages, measure, 100)
