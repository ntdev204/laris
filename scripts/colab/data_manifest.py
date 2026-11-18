#!/usr/bin/env python3
"""List the training data a Colab run needs and write a checksum file (T210). Reads data only.

The language-encoder loader reads the train and val splits of the task directories, the
retrieval directories and the relation pairs. This lists exactly those files and leaves out the
test splits (a run on Colab passes `--no-evaluate-after`, so the sealed test split never leaves
this machine) and every directory the loader does not read (for example `uspto_patents`).

Usage:
    .venv/bin/python -I scripts/colab/data_manifest.py              # list and total size
    .venv/bin/python -I scripts/colab/data_manifest.py --stage DIR  # hard-link exactly these files
                                                                    # into DIR with files.sha256
    .venv/bin/python -I scripts/colab/data_manifest.py --paths      # one relative path per line

`--stage` makes the folder to upload to Google Drive (hard links: no extra disk space, and the
data under data/processed is not modified).
"""

from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path
from typing import List

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))

from laris.shared.language.loading.dataloader import (  # noqa: E402
    CONTRASTIVE_SIM_DATASET_DIR,
    RETRIEVAL_DATASET_DIRS,
    TASK_DATASET_DIRS,
)

PROCESSED = REPO_ROOT / "data" / "processed"
SPLITS = ("train", "val")


def needed_files() -> List[Path]:
    """Parquet files of the train and val splits that the loader would read, sorted."""
    dirs = {d for names in TASK_DATASET_DIRS.values() for d in names}
    dirs |= set(RETRIEVAL_DATASET_DIRS) | {CONTRASTIVE_SIM_DATASET_DIR}
    found: List[Path] = []
    for name in sorted(dirs):
        folder = PROCESSED / name
        if not folder.is_dir():
            continue
        for path in sorted(folder.glob("**/*.parquet")):
            relative = path.relative_to(folder).parts
            if path.name.startswith(SPLITS) or any(part in SPLITS for part in relative[:-1]):
                found.append(path)
    return found


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--paths", action="store_true", help="print relative paths")
    parser.add_argument("--stage", type=Path, help="hard-link the files and files.sha256 here")
    args = parser.parse_args()
    files = needed_files()
    if args.paths:
        print("\n".join(str(p.relative_to(PROCESSED)) for p in files))
        return 0
    if args.stage:
        for path in files:
            target = args.stage / path.relative_to(PROCESSED)
            target.parent.mkdir(parents=True, exist_ok=True)
            if not target.exists():
                target.hardlink_to(path)
        lines = [f"{sha256(p)}  {p.relative_to(PROCESSED)}" for p in files]
        (args.stage / "files.sha256").write_text("\n".join(lines) + "\n")
        print(f"staged {len(files)} files and files.sha256 in {args.stage}")
        return 0
    total = sum(p.stat().st_size for p in files)
    print(f"{len(files)} files, {total / 1e9:.2f} GB (train and val splits; test excluded)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
