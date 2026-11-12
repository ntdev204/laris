"""Security suite (T83): fixtures shared by the hostile-input tests of the second programme.

Every test here plays an attacker (a network client, a compromised container, a hostile project
folder, a manipulated model) against a real component. No model, no training, no network beyond
loopback; the Docker tests skip when Docker or the `caddy:2` image is not available."""

import shutil
import subprocess
import threading
from pathlib import Path

import pytest

from laris.protocol import AssistantTurn, ChatProvider
from laris.server.api import ApiServer, create_app
from laris.server.gateway import PolicyGateway
from laris.server.serving.auth import KeyRing
from laris.server.serving.service import ModelService
from laris.shared.harness.runtime import HarnessRuntime
from tests.unit.conftest import *  # noqa: F401,F403  (isolated project and HOME, autouse guards)

ROOT = Path(__file__).resolve().parents[2]
KEY = "sec-test-key-1"
BODY = {
    "messages": [{"role": "user", "content": "Is perovskite stable?"}],
    "laris": {"kind": "turn", "session_id": "abc123", "task": "perovskite"},
}


class Model(ChatProvider):
    name = "scripted"

    def chat(self, messages, tools):
        return AssistantTurn("Perovskite is stable [nguồn #1].")


@pytest.fixture
def api():
    """`start(max_body, body_timeout)` -> a running API server on a free loopback port."""
    runtime = HarnessRuntime.load(ROOT)
    model = Model()
    gateway = PolicyGateway(runtime, model, "laris-test")
    service = ModelService(model, "laris-test", None, KeyRing([KEY]), gateway)
    made = []

    def start(max_body=1_000_000, body_timeout=30.0):
        server = ApiServer(create_app(service, max_body, body_timeout), "127.0.0.1", 0)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        made.append(server)
        return server

    yield start
    for server in made:
        server.shutdown()


def docker_ready(image: str = "caddy:2") -> bool:
    """True when the Docker daemon answers and `image` is already local (nothing is pulled)."""
    docker = shutil.which("docker")
    if docker is None:
        return False
    try:
        done = subprocess.run(
            [docker, "image", "inspect", image], capture_output=True, timeout=20, check=False
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return done.returncode == 0
