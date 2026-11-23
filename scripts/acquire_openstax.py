#!/usr/bin/env python3
"""Fetch the pinned OpenStax textbooks of T277 (CNXML only) and record their provenance.

Each book is read from its GitHub repository at the commit pinned in `configs/stem-brain.json`
(owner decision 2026-11-23: the newest commit at which the book was CC BY 4.0). Only the
collection files and the `index.cnxml` of each module are fetched (a sparse, blob-less git
fetch): no images. The script refuses a collection whose licence is not CC BY 4.0, and checks
each collection against the openstax.org catalogue (title and `cnx_id` must equal the
collection's title and uuid). It writes `provenance.json` with the SHA-256 of every file.

Network: GitHub and openstax.org only, at acquisition time. Usage:

    python scripts/acquire_openstax.py [--config configs/stem-brain.json]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_TITLE = re.compile(r"<md:title>([^<]*)</md:title>")
_UUID = re.compile(r"<md:uuid>([^<]*)</md:uuid>")
_LICENCE = re.compile(r'<md:license url="([^"]*)"')


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True
    ).stdout


def fetch_repo(target: Path, repo: str, commit: str) -> None:
    """A sparse checkout of `collections/` and `modules/*/index.cnxml` at `commit`."""
    if (target / ".git").exists():
        head = git(target, "rev-parse", "HEAD").strip()
        if head == commit:
            return
        raise SystemExit(f"{target} holds {head}, not the pinned {commit}")
    target.mkdir(parents=True, exist_ok=True)
    git(target, "init", "-q")
    git(target, "remote", "add", "origin", f"https://github.com/openstax/{repo}.git")
    git(target, "sparse-checkout", "set", "--no-cone", "/collections/*", "/modules/*/index.cnxml")
    git(target, "fetch", "-q", "--depth", "1", "--filter=blob:none", "origin", commit)
    git(target, "checkout", "-q", "FETCH_HEAD")
    head = git(target, "rev-parse", "HEAD").strip()
    if head != commit:
        raise SystemExit(f"{repo}: fetched {head}, expected {commit}")


def catalogue(url: str) -> tuple[dict, str]:
    request = urllib.request.Request(url, headers={"User-Agent": "laris-brain-build"})
    with urllib.request.urlopen(request, timeout=60) as response:  # noqa: S310 (fixed https URL)
        raw = response.read()
    items = json.loads(raw)["items"]
    return {item["cnx_id"]: item for item in items if item.get("cnx_id")}, sha256(raw)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--config", default=str(ROOT / "configs" / "stem-brain.json"))
    args = parser.parse_args()
    config = json.loads(Path(args.config).read_text(encoding="utf-8"))
    base = ROOT / config["data_dir"] / "raw" / "openstax"
    books, catalogue_sha = catalogue(config["catalogue_url"])
    record = {
        "catalogue_url": config["catalogue_url"],
        "catalogue_sha256": catalogue_sha,
        "registry": config["catalogue_registry"],
        "books": [],
    }
    for pin in config["openstax"]:
        repo, commit = pin["repo"], pin["commit"]
        target = base / f"{repo}@{commit[:12]}"
        fetch_repo(target, repo, commit)
        files = sorted(p for p in target.rglob("*") if p.is_file() and ".git" not in p.parts)
        hashes = {str(p.relative_to(target)): sha256(p.read_bytes()) for p in files}
        for slug in pin["collections"]:
            path = target / "collections" / f"{slug}.collection.xml"
            text = path.read_text(encoding="utf-8")
            licence = _LICENCE.search(text)
            if not licence or config["licence_required"] not in licence.group(1):
                raise SystemExit(
                    f"{repo}/{slug}: licence is not CC BY 4.0 ({licence and licence.group(1)})"
                )
            title = _TITLE.search(text).group(1).strip()
            uuid = _UUID.search(text).group(1).strip()
            entry = books.get(uuid)
            if entry is None or entry["title"].strip() != title:
                raise SystemExit(f"{repo}/{slug}: not in the catalogue as {title!r} ({uuid})")
            record["books"].append(
                {
                    "repo": repo,
                    "commit": commit,
                    "collection": slug,
                    "title": title,
                    "uuid": uuid,
                    "licence_url": licence.group(1),
                    "catalogue": {
                        "title": entry["title"],
                        "book_state": entry.get("book_state"),
                        "licence_now": entry.get("license_name"),
                    },
                    "folder": str(target.relative_to(ROOT)),
                    "files": len(hashes),
                }
            )
            print(f"ok {title} ({repo}@{commit[:12]}, {len(hashes)} files)")
        record.setdefault("files", {})[str(target.relative_to(ROOT))] = hashes
    out = ROOT / config["data_dir"] / "raw" / "openstax" / "provenance.json"
    out.write_text(json.dumps(record, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    print(f"wrote {out.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
