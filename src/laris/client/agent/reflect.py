"""Progress check after a tool result: did the step get anywhere?

A result is a problem when it is a typed error or when it is an empty answer to a question
(`hits: []`, `passages: 0`). The check is deterministic; the model decides what to do about it.
"""

from typing import Any, Optional, Sequence, Tuple


def assess(name: str, result: Any, empty_keys: Sequence[str]) -> Optional[Tuple[str, str]]:
    """None when the step made progress, else ("error", code) or ("empty", "")."""
    if not isinstance(result, dict):
        return None
    error = result.get("error")
    if isinstance(error, dict):
        return "error", str(error.get("code", "error"))
    for key in empty_keys:
        if key in result:
            value = result[key]
            if value == [] or value == 0 or value == {}:
                return "empty", ""
            break
    return None


def describe(kind: str, code: str, name: str, strings: Any) -> str:
    return (
        str(strings.get("reflect.error", tool=name, code=code))
        if kind == "error"
        else str(strings.get("reflect.empty", tool=name))
    )
