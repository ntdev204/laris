"""Server-sent events as used by P1 and P2: `data: <json>` lines closed by `data: [DONE]`."""

import json
from typing import Any, Dict, Iterable, Iterator, Union

DONE = "[DONE]"


def encode_event(payload: Dict[str, Any]) -> bytes:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n".encode("utf-8")


def encode_done() -> bytes:
    return f"data: {DONE}\n\n".encode("utf-8")


def decode_events(lines: Iterable[Union[bytes, str]]) -> Iterator[Dict[str, Any]]:
    """Yield each JSON payload; stop at `[DONE]`. Other lines (comments, blanks) are skipped."""
    for raw in lines:
        line = (raw.decode("utf-8") if isinstance(raw, bytes) else raw).strip()
        if not line.startswith("data:"):
            continue
        data = line[5:].strip()
        if data == DONE:
            return
        yield json.loads(data)
