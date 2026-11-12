import json

from laris.client.agent.conversations import ConversationStore
from laris.client.learning.collector import Collector
from laris.shared.config.runtime_schemas import LearningConfig


def test_conversations_survive_a_move_from_json_files(tmp_path):
    root = tmp_path / "conv"
    root.mkdir()
    old = {
        "id": "0123456789ab",
        "title": "old",
        "created": 1.0,
        "updated": 5.0,
        "messages": [{"role": "user", "content": "hi"}],
    }
    (root / "0123456789ab.json").write_text(json.dumps(old), encoding="utf-8")
    store = ConversationStore(root)
    assert store.get("0123456789ab")["messages"][0]["content"] == "hi"
    new = store.create()
    assert [c["id"] for c in store.list()][0] == new["id"]
    assert store.list()[1]["messages"] == 1
    store.delete(new["id"])
    again = ConversationStore(root)  # a second open imports nothing twice
    assert [c["id"] for c in again.list()] == ["0123456789ab"]


def _row(n):
    return {
        "id": f"id{n}",
        "schema": 1,
        "ts": 100 + n,
        "messages": [{"role": "user", "content": n}],
    }


def test_learning_export_matches_the_earlier_jsonl_format(tmp_path):
    folder = tmp_path / "ft"
    folder.mkdir()
    rows = [_row(1), _row(2)]
    (folder / "sft.jsonl").write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8"
    )
    collector = Collector(LearningConfig(), folder)
    manifest = collector.export("sft", tmp_path / "out.jsonl", "any")
    assert (tmp_path / "out.jsonl").read_text(encoding="utf-8") == "".join(
        json.dumps(r, ensure_ascii=False) + "\n" for r in rows
    )
    assert manifest["count"] == 2
    assert collector.stats()["examples"]["sft"] == 2
    collector.rate("id1", "down")
    assert collector.export("sft", tmp_path / "o2.jsonl", "any")["count"] == 1


def test_purge_removes_rows_imported_files_and_their_backups(tmp_path):
    folder = tmp_path / "ft"
    folder.mkdir()
    (folder / "sft.jsonl").write_text(json.dumps(_row(1)) + "\n", encoding="utf-8")
    collector = Collector(LearningConfig(), folder)
    assert collector.stats()["examples"]["sft"] == 1
    assert list((folder / "backups").glob("*-learning-*"))
    collector.purge()
    assert (
        not list((folder / "backups").glob("*-learning-*")) and not (folder / "sft.jsonl").exists()
    )
    assert Collector(LearningConfig(), folder).stats()["examples"]["sft"] == 0
