"""T210: the Colab data manifest lists train and val files of the directories the loader reads."""

import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "colab" / "data_manifest.py"


@pytest.fixture()
def manifest(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):  # type: ignore[no-untyped-def]
    spec = importlib.util.spec_from_file_location("data_manifest", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "PROCESSED", tmp_path)
    return module


def _touch(root: Path, *names: str) -> None:
    for name in names:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"x")


def test_lists_train_and_val_and_leaves_test_and_unread_directories(manifest, tmp_path) -> None:  # type: ignore[no-untyped-def]
    _touch(
        tmp_path,
        "all_nli/train.parquet", "all_nli/val.parquet", "all_nli/test.parquet",
        "stsb/train-00000.parquet", "stsb/test.parquet",
        "relation_pairs_en/train.parquet",
        "gooaq_en/train.parquet", "gooaq_en/val.parquet",
        "uspto_patents/train.parquet",
        "squad/train/part.parquet", "squad/val/part.parquet", "squad/test/part.parquet",
    )  # fmt: skip
    listed = sorted(str(p.relative_to(tmp_path)) for p in manifest.needed_files())
    assert listed == [
        "all_nli/train.parquet", "all_nli/val.parquet",
        "gooaq_en/train.parquet", "gooaq_en/val.parquet",
        "relation_pairs_en/train.parquet",
        "squad/train/part.parquet", "squad/val/part.parquet",
        "stsb/train-00000.parquet",
    ]  # fmt: skip
    assert not any("test" in name for name in listed)
    assert not any(name.startswith("uspto_patents") for name in listed)
