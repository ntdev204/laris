"""`@path`, `!command`, `# note`, pasted long text and images (SR-C2)."""

import base64
import threading
from types import SimpleNamespace

import pytest

from laris.client.application import ocr
from laris.client.application.chat_app import ChatApp
from laris.client.application.service import SearchService
from laris.client.application.workspace import Workspace
from laris.client.input_forms import InputProcessor, kind_of
from laris.client.sandbox import SandboxManager

pytestmark = pytest.mark.usefixtures("use_placeholder_model")


@pytest.fixture
def chat(tmp_path, project):
    app = ChatApp(SearchService(Workspace(tmp_path / "ws")), project, project / "chat")
    app.sandbox_manager = SandboxManager(tmp_path / "home", uv=None, environ={"PATH": ""})
    return app


@pytest.mark.parametrize(
    "line,kind",
    [
        ("!ls -la", "shell"),
        ("  !echo hi", "shell"),
        ("!", "message"),
        ("# remember the milk", "note"),
        ("#tag", "note"),
        ("## heading", "message"),
        ("#", "message"),
        ("explain @a.py", "message"),
    ],
)
def test_each_line_is_classified(line, kind):
    assert kind_of(line) == kind


def test_mentions_attach_files_and_folders_under_the_policy(chat, project):
    (project / "src").mkdir()
    (project / "src" / "a.py").write_text("print('a')\n", encoding="utf-8")
    (project / ".env").write_text("TOKEN=hunter2hunter2\n", encoding="utf-8")
    prepared = InputProcessor(chat).prepare("explain @src/a.py, and @src and @.env and @nobody")
    assert prepared.attached == ["src/a.py", "src/"]
    assert "[Attached @src/a.py]\nprint('a')" in prepared.text and "a.py" in prepared.text
    assert "hunter2" not in prepared.text  # a secret file is never attached
    assert any(n.startswith("@.env") for n in prepared.notes)
    assert not any("nobody" in n for n in prepared.notes)  # `@someone` is plain text
    assert prepared.text.startswith("explain @src/a.py")  # the typed text is unchanged


def test_mentions_outside_the_project_and_secrets_in_files(chat, project, tmp_path):
    (tmp_path / "outside.txt").write_text("nope", encoding="utf-8")
    (project / "cfg.txt").write_text("api = sk-" + "a1B2c3D4" * 5 + "\n", encoding="utf-8")
    processor = InputProcessor(chat)
    out = processor.prepare("see @../outside.txt")
    assert "nope" not in out.text and out.notes and "outside" in out.notes[0]
    assert "a1B2c3D4" not in processor.prepare("see @cfg.txt").text  # redacted when attached
    assert processor.prepare("mail me at bob@example.com").attached == []


def test_mentions_are_capped(chat, project):
    for i in range(15):
        (project / f"f{i}.txt").write_text(str(i), encoding="utf-8")
    prepared = InputProcessor(chat).prepare(" ".join(f"@f{i}.txt" for i in range(15)))
    assert len(prepared.attached) == chat.runtime.config.app.mention_max_files
    assert any("more than" in n for n in prepared.notes)
    (project / "big.txt").write_text("x" * 50000, encoding="utf-8")
    assert "cut at" in InputProcessor(chat).prepare("@big.txt").text


def test_completion_lists_files_and_folders_but_never_secrets(chat, project):
    (project / "docs").mkdir()
    (project / "docs" / "guide.md").write_text("g", encoding="utf-8")
    (project / "docs" / "other.md").write_text("o", encoding="utf-8")
    (project / ".env").write_text("x", encoding="utf-8")
    (project / ".git").mkdir()
    (project / ".git" / "docs.txt").write_text("x", encoding="utf-8")
    processor = InputProcessor(chat)
    assert ("docs/", True) in processor.complete_files("do")
    assert processor.complete_files("docs/g") == [("docs/guide.md", False)]
    assert ("docs/guide.md", False) in processor.complete_files("guide")  # by name, deeper
    assert processor.complete_files(".en") == []
    assert all(".git" not in v for v, _ in processor.complete_files("docs"))
    assert processor.complete_files("../") == [] and processor.complete_files("nope/x") == []


def test_long_pasted_text_is_kept_in_a_file_and_shortened(chat):
    long = "start " + "word " * 5000 + "the real question at the end"
    prepared = InputProcessor(chat).prepare(long)
    limit = chat.runtime.config.app.paste_inline_chars
    assert len(prepared.text) < limit + 400 and prepared.text.startswith("start ")
    assert prepared.text.endswith("the real question at the end")  # the ask is never cut away
    saved = next(chat.uploads.glob("paste-*.txt"))
    assert saved.read_text(encoding="utf-8").startswith("start ") and str(saved) in prepared.text
    assert any("saved to" in n for n in prepared.notes)
    assert InputProcessor(chat).prepare("short text").text == "short text"


def test_images_are_read_by_local_ocr_and_failures_are_plain(chat, monkeypatch):
    image = SimpleNamespace(
        kind="image", name="shot.png", data_base64=base64.b64encode(b"png").decode()
    )
    monkeypatch.setattr(
        "laris.client.input_forms.ocr_image_bytes",
        lambda data, lang: "Total: 42 EUR sk-" + "a1B2c3D4" * 5,
    )
    text = InputProcessor(chat).prepare("what is this?", [image]).text
    assert "[Image shot.png, text read locally by OCR]" in text and "Total: 42 EUR" in text
    assert "a1B2c3D4" not in text

    def broken(data, lang):
        raise ocr.OcrError("OCR needs Tesseract")

    monkeypatch.setattr("laris.client.input_forms.ocr_image_bytes", broken)
    assert (
        "could not be read: OCR needs Tesseract" in InputProcessor(chat).prepare("x", [image]).text
    )
    bad = SimpleNamespace(kind="image", name="b.png", data_base64="@@@")
    assert "not valid image data" in InputProcessor(chat).prepare("x", [bad]).text


def test_note_appends_to_the_memory_note(chat, project):
    processor = InputProcessor(chat)
    first = processor.note("use tabs, not spaces")
    again = processor.note("deploy on Fridays is forbidden")
    assert "error" not in first and "error" not in again
    saved = [p for p in project.rglob("*.md") if "tabs" in p.read_text(encoding="utf-8")]
    assert saved and "Fridays" in saved[0].read_text(encoding="utf-8")
    assert "error" in processor.note("   ")


def test_shell_follows_the_permission_rules(chat, project):
    processor = InputProcessor(chat)
    conv = chat.conversations.create()["id"]
    asked = []

    def approve(name, args):
        asked.append(args["command"])
        return True

    out = processor.shell(conv, "echo hello", approve)  # default mode: asks
    assert asked == ["echo hello"] and out["output"].strip() == "hello" and out["exit_code"] == 0
    saved = chat.conversations.get(conv)["messages"][-1]["content"]
    assert "echo hello" in saved and "hello" in saved and "data, not instructions" in saved
    refused = processor.shell(conv, "echo no", lambda n, a: False)
    assert refused["error"]["code"] == "approval_denied"
    chat.permissions.remember("bash(echo:*)", "session")
    asked.clear()
    assert processor.shell(conv, "echo again", approve)["output"].strip() == "again" and asked == []
    from laris.shared.config import settings

    settings.write(
        chat.permissions.settings_file, {"permissions": {"deny": ["Bash(echo again:*)"]}}
    )
    denied = processor.shell(conv, "echo again", approve)
    assert denied["error"]["code"] == "denied"
    chat.permissions.mode = "plan"
    assert processor.shell(conv, "touch x", approve)["error"]["code"] == "denied"
    assert not (project / "x").exists()


def test_shell_refuses_installs_outside_the_sandbox_and_hides_secrets(chat, monkeypatch):
    chat.permissions.remember("bash", "session")
    conv = chat.conversations.create()["id"]
    processor = InputProcessor(chat)
    assert processor.shell(conv, "pip install --user requests", None)["error"]["code"] == "denied"
    secret = "sk-" + "a1B2c3D4" * 5
    processor.shell(conv, f"echo {secret}", None)
    assert secret not in chat.conversations.get(conv)["messages"][-1]["content"]


# -- through the engine ------------------------------------------------------------------------
def test_engine_runs_shell_note_and_mentions(run, project):
    (project / "hello.txt").write_text("hello file\n", encoding="utf-8")
    h = run()
    h.out.wait("ready")
    h.feed.send({"type": "user_message", "text": "# remember this"})
    assert "noted in" in h.out.wait("text")[0]["delta"]
    h.out.wait("done")
    h.feed.send({"type": "user_message", "text": "!echo from-shell"})
    request = h.out.wait("permission_request")[0]
    assert request["tool"] == "Bash" and request["arguments"] == {"command": "echo from-shell"}
    h.feed.send({"type": "permission_response", "id": request["id"], "decision": "allow"})
    texts = h.out.wait("text", 2)
    assert "from-shell" in texts[1]["delta"]
    h.out.wait("done", 2)
    h.feed.send({"type": "user_message", "text": "!echo blocked"})
    request = h.out.wait("permission_request", 2)[1]
    h.feed.send({"type": "permission_response", "id": request["id"], "decision": "deny"})
    assert h.out.wait("error")[-1]["code"] == "approval_denied"
    h.feed.send({"type": "complete", "id": "m1", "trigger": "@", "text": "hel"})
    assert h.out.wait("completion")[0]["items"][0]["value"] == "hello.txt"
    h.stop()


def test_engine_attaches_mentions_before_the_model_sees_the_message(run, project):
    (project / "hello.txt").write_text("hello file\n", encoding="utf-8")
    h = run()
    h.out.wait("ready")
    sent = []
    original = h.engine.chat.send
    h.engine.chat.send = lambda cid, text, approve=None: (
        sent.append(text),
        original(cid, text, approve),
    )[1]
    h.feed.send({"type": "user_message", "text": "read @hello.txt", "attachments": []})
    h.out.wait("done")
    assert "[Attached @hello.txt]\nhello file" in sent[0]
    threading.Event().wait(0)
    h.stop()
