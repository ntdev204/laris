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
