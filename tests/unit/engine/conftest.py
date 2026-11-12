import io
import json
import queue
import threading
import time

import pytest

from laris.client.application.chat_app import ChatApp
from laris.client.application.service import SearchService
from laris.client.application.workspace import Workspace, chunks_from_text
from laris.client.engine import Engine


class Feed:
    """A stdin the test writes to one line at a time; `close()` is end of input."""

    def __init__(self):
        self._q: "queue.Queue" = queue.Queue()

    def send(self, obj):
        self._q.put(json.dumps(obj) + "\n")

    def raw(self, text):
        self._q.put(text)

    def close(self):
        self._q.put(None)

    def __iter__(self):
        while True:
            item = self._q.get()
            if item is None:
                return
            yield item


class Out(io.StringIO):
    def events(self):
        return [json.loads(x) for x in self.getvalue().splitlines() if x.strip()]

    def wait(self, kind, count=1, timeout=10.0):
        deadline = time.time() + timeout
        while time.time() < deadline:
            found = [e for e in self.events() if e["type"] == kind]
            if len(found) >= count:
                return found
            time.sleep(0.01)
        raise AssertionError(f"no {kind} event; got {[e['type'] for e in self.events()]}")


def wait_status(out, kind, count=1, timeout=10.0):
    """Wait for `count` status events of one kind (status lines arrive on their own schedule)."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        found = [e for e in out.events() if e["type"] == "status" and e["kind"] == kind]
        if len(found) >= count:
            return found
        time.sleep(0.01)
    raise AssertionError(f"no {count} status {kind}; got {out.events()}")


class Harness:
    def __init__(self, chat, project):
        self.feed, self.out = Feed(), Out()
        self.engine = Engine(chat, self.feed, self.out, "2.0.0-test", cwd=project)
        self.code = []
        self.thread = threading.Thread(
            target=lambda: self.code.append(self.engine.run()), daemon=True
        )
        self.thread.start()

    def stop(self):
        self.feed.close()
        self.thread.join(timeout=15)
        assert not self.thread.is_alive()
        return self.code[0]


@pytest.fixture
def chat(tmp_path, project, use_placeholder_model):
    service = SearchService(Workspace(tmp_path / "ws"))
    service.workspace.add(
        chunks_from_text("solar.txt", "Perovskite solar cells reach 25% efficiency in labs.")
    )
    return ChatApp(service, project, project / "chat")


@pytest.fixture
def run(chat, project):
    started = []

    def make():
        h = Harness(chat, project)
        started.append(h)
        return h

    yield make
    for h in started:
        if h.thread.is_alive():
            h.stop()
