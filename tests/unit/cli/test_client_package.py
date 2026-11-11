def test_settings_are_shared_by_every_key_on_the_machine(tmp_path, monkeypatch):
    from application.chat_app import ChatApp
    from application.service import SearchService
    from application.workspace import Workspace

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
