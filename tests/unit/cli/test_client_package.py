def test_settings_are_shared_by_every_key_on_the_machine(tmp_path, monkeypatch):
    from laris.client.application.chat_app import ChatApp
    from laris.client.application.service import SearchService
    from laris.client.application.workspace import Workspace

    shared = tmp_path / "home" / "settings.json"
    monkeypatch.setenv("LARIS_APP__SETTINGS_FILE", str(shared))
    service = SearchService(Workspace(tmp_path / "ws"))
    first = ChatApp(service, tmp_path, tmp_path / "chat", user="aaaa1111aaaa1111")
    second = ChatApp(service, tmp_path, tmp_path / "chat", user="bbbb2222bbbb2222")
    assert first.prefs.path == second.prefs.path == shared
    first.update_settings({"allow_write": True})
    assert second.settings()["allow_write"] is True  # one machine, one set of preferences
    assert first.conversations.root != second.conversations.root  # conversations stay per key


def test_version_flag_prints_without_touching_the_home(capsys, monkeypatch):
    from cli import client

    monkeypatch.setattr(
        "cli.bootstrap.ensure_global_home", lambda: (_ for _ in ()).throw(AssertionError("touched"))
    )
    assert client.main(["--version"]) == 0
    assert capsys.readouterr().out.startswith("laris ")


def _packaging():
    import importlib.util
    from pathlib import Path

    path = Path(__file__).resolve().parents[3] / "packaging" / "build_client.py"
    spec = importlib.util.spec_from_file_location("build_client", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_client_wheel_holds_only_the_client_blocks():
    import ast

    build = _packaging()
    files = build.client_files()
    names = {".".join(f.relative_to(build.SRC).with_suffix("").parts) for f in files}
    names |= {n.removesuffix(".__init__") for n in names}
    assert not [n for n in names if n.startswith(build.NOT_SHIPPED)]
    assert not [f for f in files if ".laris" in f.parts]
    assert {"laris.client.agent.loop", "laris.shared.vault.index", "cli.client"} <= names
    # every module the client imports is shipped, and none comes from server, model or research
    for file in files:
        for node in ast.walk(ast.parse(file.read_text(encoding="utf-8"))):
            found = []
            if isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                found = [node.module]
            elif isinstance(node, ast.Import):
                found = [a.name for a in node.names]
            for name in found:
                assert not name.startswith(build.NOT_SHIPPED), (file.name, name)
                if name.startswith(("laris.", "cli.")):
                    assert name in names or name.rsplit(".", 1)[0] in names, (file.name, name)


def test_three_entry_points_are_declared():
    import re
    from pathlib import Path

    text = (Path(__file__).resolve().parents[3] / "pyproject.toml").read_text(encoding="utf-8")
    scripts = dict(re.findall(r'^(laris[\w-]*) = "([^"]+)"$', text, re.M))
    assert scripts == {
        "laris": "cli.client:main",
        "laris-server": "cli.server:main",
        "laris-model": "cli.model:main",
    }
