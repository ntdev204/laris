"""`Read`, `Write`, `Edit`, `Glob`, `Grep`, `Bash`, checkpoints and `/rewind` (SR-C3, SR-C5)."""

import time

import pytest

from laris.client.agent.coding_tools import (
    Checkpoints,
    CodingContext,
    build_coding_tools,
    preview_change,
)
from laris.client.agent.tools import Sandbox, ToolExecutionError, ToolRegistry
from laris.client.sandbox import SandboxManager
from laris.shared.harness.runtime import HarnessRuntime


@pytest.fixture
def rig(project, tmp_path):
    rt = HarnessRuntime.load(project)
    home = tmp_path / "home"
    manager = SandboxManager(home, uv=None, environ={"PATH": ""})
    ctx = CodingContext(
        root=project,
        cfg=rt.config.agent.coding,
        policy=rt.paths,
        redact=lambda text: rt.redactor.redact(text)[0],
        checkpoints=Checkpoints(tmp_path / "checkpoints" / "s1"),
        sandbox=manager,
    )
    sandbox = Sandbox([project], tmp_path / "out", policy=rt.paths, base=project)
    registry = ToolRegistry()
    for spec in build_coding_tools(ctx, sandbox):
        registry.register(spec)
    registry.ctx = ctx  # type: ignore[attr-defined]
    return registry


def call(rig, name, **args):
    return rig.call(name, args)


def code_of(rig, name, **args):
    with pytest.raises(ToolExecutionError) as caught:
        rig.call(name, args)
    return caught.value.code


def test_the_six_tools_are_registered_and_write_ones_need_approval(rig):
    assert set(rig.tools) == {"Read", "Write", "Edit", "Glob", "Grep", "Bash"}
    assert {n for n, t in rig.tools.items() if t.writes} == {"Write", "Edit", "Bash"}
    assert code_of(rig, "Read", path="a", bogus=1) == "invalid_arguments"


def test_read_numbers_lines_and_honours_the_range(rig, project):
    (project / "a.py").write_text("one\ntwo\nthree\nfour\n", encoding="utf-8")
    out = call(rig, "Read", path="a.py", offset=2, limit=2)
    assert out["text"] == "     2\ttwo\n     3\tthree" and out["total_lines"] == 4
    assert out["start"] == 2 and out["end"] == 3 and out["truncated"] is True
    assert "/" not in out["path"]  # never an absolute path
    assert call(rig, "Read", path="a.py")["truncated"] is False


def test_read_refuses_secrets_binary_missing_and_outside(rig, project, tmp_path):
    (project / ".env").write_text("TOKEN=abc", encoding="utf-8")
    (project / "bin.dat").write_bytes(b"\x00\x01\x02")
    (tmp_path / "outside.txt").write_text("x", encoding="utf-8")
    assert code_of(rig, "Read", path=".env") == "denied"
    assert code_of(rig, "Read", path="bin.dat") == "binary"
    assert code_of(rig, "Read", path="missing.py") == "not_found"
    assert code_of(rig, "Read", path="../outside.txt") == "outside_sandbox"
    (project / "link").symlink_to(tmp_path / "outside.txt")
    assert code_of(rig, "Read", path="link") == "outside_sandbox"  # a symlink cannot leave


def test_write_creates_overwrites_redacts_and_checkpoints(rig, project):
    out = call(rig, "Write", path="pkg/new.py", content="print(1)\n")
    assert out == {"path": "pkg/new.py", "bytes": 9, "created": True}
    assert (project / "pkg" / "new.py").read_text() == "print(1)\n"
    again = call(rig, "Write", path="pkg/new.py", content="print(2)\n")
    assert again["created"] is False
    secret = "sk-" + "a1B2c3D4" * 5
    call(rig, "Write", path="cfg.txt", content=f"key = {secret}\n")
    assert secret not in (project / "cfg.txt").read_text()  # a credential is never persisted
    assert [e["tool"] for e in rig.ctx.checkpoints.list()] == ["Write", "Write", "Write"]


@pytest.mark.parametrize(
    "path,code",
    [
        (".git/config", "denied"),
        ("sub/.git/hooks/pre-commit", "denied"),
        (".laris/prompts/x.md", "denied"),
        (".laris/commands/evil.md", "denied"),
        (".env", "denied"),
        ("../escape.txt", "outside_project"),
        ("/etc/laris-test", "outside_project"),
    ],
)
def test_write_never_touches_forbidden_places(rig, project, tmp_path, path, code):
    assert code_of(rig, "Write", path=path, content="x") == code
    assert code_of(rig, "Edit", path=path, old_string="a", new_string="b") in (code, "not_found")
    assert not (tmp_path / "escape.txt").exists() and not (project / ".git" / "config").exists()
    assert rig.ctx.checkpoints.list() == []  # nothing was changed, nothing is checkpointed


def test_write_cannot_follow_a_symlink_out_of_the_project(rig, project, tmp_path):
    (tmp_path / "victim.txt").write_text("keep", encoding="utf-8")
    (project / "sneaky").symlink_to(tmp_path)
    assert code_of(rig, "Write", path="sneaky/victim.txt", content="x") == "outside_project"
    assert (tmp_path / "victim.txt").read_text() == "keep"


def test_edit_needs_a_unique_exact_match(rig, project):
    (project / "m.py").write_text("a = 1\nb = 2\na = 1\n", encoding="utf-8")
    assert code_of(rig, "Edit", path="m.py", old_string="zzz", new_string="y") == "not_found"
    assert code_of(rig, "Edit", path="m.py", old_string="a = 1", new_string="a = 9") == "not_unique"
    assert code_of(rig, "Edit", path="m.py", old_string="b = 2", new_string="b = 2") == "no_change"
    assert code_of(rig, "Edit", path="m.py", old_string="", new_string="x") == "invalid_arguments"
    assert (project / "m.py").read_text() == "a = 1\nb = 2\na = 1\n"  # nothing changed so far
    call(rig, "Edit", path="m.py", old_string="b = 2", new_string="b = 3")
    out = call(rig, "Edit", path="m.py", old_string="a = 1", new_string="a = 0", replace_all=True)
    assert out["replacements"] == 2
    assert (project / "m.py").read_text() == "a = 0\nb = 3\na = 0\n"
    assert code_of(rig, "Edit", path="nope.py", old_string="a", new_string="b") == "not_found"


def test_diff_preview_for_edit_and_write(rig, project):
    (project / "d.py").write_text("x = 1\ny = 2\n", encoding="utf-8")
    diff = preview_change(
        rig.ctx, "Edit", {"path": "d.py", "old_string": "y = 2", "new_string": "y = 3"}
    )
    assert "-y = 2" in diff and "+y = 3" in diff and "a/d.py" in diff
    new = preview_change(rig.ctx, "Write", {"path": "fresh.py", "content": "z = 1\n"})
    assert new.startswith("new file") and "+z = 1" in new
    assert (
        preview_change(rig.ctx, "Edit", {"path": "d.py", "old_string": "q", "new_string": "r"})
        == ""
    )
    assert preview_change(rig.ctx, "Bash", {"command": "ls"}) == ""
    assert (project / "d.py").read_text() == "x = 1\ny = 2\n"  # a preview changes nothing


def test_rewind_restores_edits_newest_first_and_removes_new_files(rig, project):
    (project / "r.py").write_text("v0\n", encoding="utf-8")
    call(rig, "Edit", path="r.py", old_string="v0", new_string="v1")
    call(rig, "Edit", path="r.py", old_string="v1", new_string="v2")
    call(rig, "Write", path="made.py", content="new\n")
    marks = rig.ctx.checkpoints
    assert [r["status"] for r in marks.rewind(1)] == ["removed"] and not (
        project / "made.py"
    ).exists()
    assert [r["status"] for r in marks.rewind(1)] == ["restored"]
    assert (project / "r.py").read_text() == "v1\n"
    marks.rewind(None)
    assert (project / "r.py").read_text() == "v0\n" and marks.list() == []
    assert marks.rewind(3) == []


def test_rewind_never_writes_where_the_policy_forbids(rig, project, tmp_path):
    call(rig, "Write", path="p.py", content="x")
    marks = rig.ctx.checkpoints
    entries = marks._entries()
    entries[-1]["path"] = str(tmp_path / "elsewhere.txt")  # a tampered index
    marks._write(entries)
    result = marks.rewind(1, rig.ctx.editable)
    assert result[0]["status"] == "skipped" and not (tmp_path / "elsewhere.txt").exists()


def test_checkpoints_keep_only_the_newest(tmp_path):
    marks = Checkpoints(tmp_path / "c", keep=3)
    target = tmp_path / "f.txt"
    for i in range(6):
        target.write_text(str(i), encoding="utf-8")
        marks.record(target, "Edit")
    assert [e["seq"] for e in marks.list()] == [4, 5, 6]
    assert sorted(p.name for p in (tmp_path / "c").glob("*.blob")) == ["4.blob", "5.blob", "6.blob"]


def test_glob_and_grep_skip_secrets_and_git(rig, project):
    (project / "src").mkdir()
    (project / "src" / "a.py").write_text("def alpha():\n    return 1\n", encoding="utf-8")
    (project / "src" / "b.txt").write_text("alpha beta\n", encoding="utf-8")
    (project / ".git").mkdir()
    (project / ".git" / "x.py").write_text("alpha\n", encoding="utf-8")
    (project / ".env").write_text("alpha=secret\n", encoding="utf-8")
    assert call(rig, "Glob", pattern="src/**/*.py")["files"] == ["src/a.py"]
    assert call(rig, "Glob", pattern="**/*.py")["files"] == ["src/a.py"]
    hits = call(rig, "Grep", pattern="alpha")["matches"]
    assert sorted((h["path"], h["line"]) for h in hits) == [("src/a.py", 1), ("src/b.txt", 1)]
    only = call(rig, "Grep", pattern="ALPHA", ignore_case=True, glob="*.py")["matches"]
    assert [h["path"] for h in only] == ["src/a.py"]
    assert code_of(rig, "Grep", pattern="(") == "invalid_pattern"
    assert code_of(rig, "Grep", pattern="a", path="../") == "outside_project"
    assert code_of(rig, "Glob", pattern="*", path="nope") == "not_a_directory"


def test_grep_results_are_capped(rig, project):
    (project / "many.txt").write_text("hit\n" * 500, encoding="utf-8")
    out = call(rig, "Grep", pattern="hit")
    assert len(out["matches"]) == rig.ctx.cfg.grep_max_results and out["truncated"] is True


def test_bash_runs_in_the_project_with_the_sandbox_environment(rig, project, monkeypatch):
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "do-not-leak")
    out = call(
        rig,
        "Bash",
        command="pwd; echo venv=$VIRTUAL_ENV pip=$PIP_REQUIRE_VIRTUALENV; "
        "echo leak=[$AWS_SECRET_ACCESS_KEY]; echo $PATH",
    )
    text = out["output"]
    assert out["exit_code"] == 0 and str(project.resolve()) in text
    assert "pip=1" in text and "leak=[]" in text
    assert f"venv={rig.ctx.sandbox.venv}" in text
    assert text.splitlines()[-1].startswith(
        str(rig.ctx.sandbox.bin)
    )  # the sandbox is first on PATH
    assert call(rig, "Bash", command="exit 3")["exit_code"] == 3
    assert "unavailable" in call(rig, "Bash", command="true")["sandbox"]  # no uv here: said plainly


def test_bash_times_out_and_kills_the_whole_group(rig, project):
    started = time.time()
    out = call(rig, "Bash", command="(sleep 30; touch survivor) & sleep 30", timeout_s=1)
    assert out["timed_out"] is True and out["exit_code"] is None
    assert time.time() - started < 10
    time.sleep(0.3)
    assert not (project / "survivor").exists()


def test_bash_output_is_capped_and_cwd_is_confined(rig, project, tmp_path):
    out = call(rig, "Bash", command="python3 -c \"print('x' * 100000)\" || yes x | head -c 100000")
    assert (
        len(out["output"]) <= rig.ctx.cfg.bash_output_max_chars + 40
        and "truncated" in out["output"]
    )
    (project / "sub").mkdir()
    assert call(rig, "Bash", command="pwd", cwd="sub")["output"].strip().endswith("/sub")
    assert code_of(rig, "Bash", command="pwd", cwd="..") == "outside_project"
    assert code_of(rig, "Bash", command="pwd", cwd="/") == "outside_project"


@pytest.mark.parametrize(
    "command",
    [
        "pip install --user requests",
        "python3 -m pip install --break-system-packages x",
        "/usr/bin/pip install x",
        "sudo apt-get install gcc",
        "pipx install black",
        "echo ok && pip install -t /tmp/x y",
    ],
)
def test_bash_refuses_installs_outside_the_sandbox(rig, command):
    assert code_of(rig, "Bash", command=command) == "denied"
