"""Config-driven acquirers for the English stage-1 replacement data (D46 / ADR-022, T175).

Sources, file selection, licences and endpoints live in `configs/data/english_sources.yaml`.
Files are listed through the Hugging Face tree API, downloaded with resume support and
recorded with SHA-256 and row counts. Acquiring data is not training: no model is loaded
and no optimiser runs.
"""

import fnmatch
import gzip
import json
import os
import tarfile
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import yaml

from laris.research.corpus.acquisition.common import (
    RAW_DIR,
    REPO_ROOT,
    DatasetEntry,
    _finalize_entry,
    _record_files,
    count_parquet_rows,
)

SOURCES_CONFIG_ENV = "LARIS_ENGLISH_SOURCES"
DEFAULT_SOURCES_CONFIG = REPO_ROOT / "configs" / "data" / "english_sources.yaml"
CHUNK_BYTES = 1 << 20


def load_sources_config(path: Optional[Path] = None) -> Dict[str, Any]:
    """Loads and minimally validates the English sources configuration."""
    config_path = Path(path or os.environ.get(SOURCES_CONFIG_ENV, DEFAULT_SOURCES_CONFIG))
    with open(config_path, "r", encoding="utf-8") as handle:
        config = yaml.safe_load(handle)
    seen = set()
    for source in config["sources"]:
        for key in (
            "id",
            "role",
            "repo",
            "pattern",
            "license_name",
            "license_approved",
            "min_rows",
        ):
            if key not in source:
                raise ValueError(f"source {source.get('id', '?')} lacks '{key}' in {config_path}")
        if source["id"] in seen:
            raise ValueError(f"duplicate source id {source['id']}")
        seen.add(source["id"])
    return config


def _open(url: str, config: Dict[str, Any], headers: Optional[Dict[str, str]] = None):
    request_headers = {"User-Agent": config["user_agent"]}
    token = os.environ.get("HF_TOKEN")
    if token:
        request_headers["Authorization"] = f"Bearer {token}"
    request_headers.update(headers or {})
    request = urllib.request.Request(url, headers=request_headers)
    return urllib.request.urlopen(request, timeout=config["timeout_seconds"])


def list_remote_files(source: Dict[str, Any], config: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Lists files of a dataset directory through the tree API, following pagination."""
    rev = source.get("rev", "main")
    path = source.get("path", "").strip("/")
    base = f"{config['hf_endpoint']}/api/datasets/{source['repo']}/tree/{rev}"
    url = f"{base}/{urllib.parse.quote(path)}" if path else base
    if source.get("recursive"):
        url += "?recursive=true"
    files: List[Dict[str, Any]] = []
    while url:
        with _open(url, config) as response:
            files.extend(item for item in json.load(response) if item["type"] == "file")
            link = response.headers.get("Link", "")
        url = ""
        for part in link.split(","):
            if 'rel="next"' in part:
                url = part.split(";")[0].strip().strip("<>")
    return files


def select_files(source: Dict[str, Any], listing: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Applies the glob pattern and the optional file limit deterministically (sorted by path)."""
    chosen = sorted(
        (f for f in listing if fnmatch.fnmatch(f["path"].rsplit("/", 1)[-1], source["pattern"])),
        key=lambda f: f["path"],
    )
    limit = source.get("limit")
    return chosen[: int(limit)] if limit else chosen


def local_name(source: Dict[str, Any], remote_path: str) -> str:
    """Flattens a remote path below the source directory into a local file name."""
    prefix = source.get("path", "").strip("/")
    relative = remote_path[len(prefix) :].lstrip("/") if prefix else remote_path
    return relative.replace("/", "__")


def download_resumable(url: str, dest: Path, expected_size: int, config: Dict[str, Any]) -> bool:
    """Downloads to ``dest`` with HTTP Range resume; a finished file of the expected size is kept."""  # noqa: E501
    if dest.exists() and dest.stat().st_size == expected_size:
        print(f"  [CACHE] {dest.name} ({expected_size:,} bytes)")
        return True
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part")
    for attempt in range(1, int(config["max_retries"]) + 1):
        have = part.stat().st_size if part.exists() else 0
        try:
            headers = {"Range": f"bytes={have}-"} if have else {}
            with _open(url, config, headers) as response:
                mode = "ab" if have and response.status == 206 else "wb"
                with open(part, mode) as out:
                    while chunk := response.read(CHUNK_BYTES):
                        out.write(chunk)
            if part.stat().st_size != expected_size:
                raise OSError(f"size {part.stat().st_size} != expected {expected_size}")
            part.replace(dest)
            print(f"  [DONE] {dest.name} ({expected_size:,} bytes)")
            return True
        except urllib.error.HTTPError as error:
            if error.code == 416 and part.exists() and part.stat().st_size == expected_size:
                part.replace(dest)
                return True
            print(f"  [WARN] attempt {attempt} for {dest.name}: HTTP {error.code}")
        except (OSError, urllib.error.URLError) as error:
            print(f"  [WARN] attempt {attempt} for {dest.name}: {error}")
        time.sleep(min(60, 2**attempt))
    return False


def count_rows(path: Path) -> int:
    """Counts samples in a parquet, JSONL, JSONL.GZ, JSON.GZ (one object per line) or TSV file."""
    name = path.name
    if name.endswith(".parquet"):
        return count_parquet_rows(path)
    if name.endswith((".tar.gz", ".tgz")):
        with tarfile.open(path, "r:gz") as archive:
            return sum(1 for member in archive if member.name.lower().endswith(".pdf"))
    opener: Callable[..., Any] = gzip.open if name.endswith(".gz") else open
    with opener(path, "rt", encoding="utf-8", errors="replace") as handle:
        lines = sum(1 for line in handle if line.strip())
    return lines - 1 if name.endswith(".tsv") else lines


def acquire_english_source(source: Dict[str, Any], config: Dict[str, Any]) -> DatasetEntry:
    """Acquires one configured English source and returns its manifest entry."""
    dataset_id = source["id"]
    print(f"\n--- Acquiring {dataset_id} ({source['repo']}) ---")
    dest_dir = RAW_DIR / dataset_id.lower().replace("-", "_")
    rev = source.get("rev", "main")
    listing = select_files(source, list_remote_files(source, config))
    selected: List[Tuple[Dict[str, Any], str]] = [
        (f, local_name(source, f["path"])) for f in listing
    ]
    complete = bool(selected)
    for remote, name in selected:
        url = (
            f"{config['hf_endpoint']}/datasets/{source['repo']}/resolve/{rev}/"
            f"{urllib.parse.quote(remote['path'])}"
        )
        if not download_resumable(url, dest_dir / name, int(remote["size"]), config):
            complete = False
    records, size, rows = _record_files(dest_dir, [name for _, name in selected], count_rows)
    complete = complete and len(records) == len(selected)
    notes = (
        f"Role: {source['role']}. {source.get('notes', '')} Source {source['repo']}@{rev}; "
        f"{len(records)} file(s) selected by pattern '{source['pattern']}'"
        f"{' with limit ' + str(source['limit']) if source.get('limit') else ''}. "
        f"{source.get('stage_note', 'English stage-1 replacement data (D46 / ADR-022)')}; not a training run."  # noqa: E501
    ).strip()
    if not source["license_approved"]:
        notes += " Licence is non-commercial or undeclared: owner review pending."
    return _finalize_entry(
        dataset_id=dataset_id,
        name=source.get("name", dataset_id.replace("-", " ").title()),
        version=f"{source['repo']}@{rev}",
        source_url=f"{config['hf_endpoint']}/datasets/{source['repo']}",
        license_name=source["license_name"],
        license_approved=bool(source["license_approved"]),
        language=source.get("language", "English"),
        sample_unit=source["sample_unit"],
        expected=f">= {int(source['min_rows']):,} samples",
        dest_dir=dest_dir,
        records=records,
        size=size,
        rows=rows,
        complete=complete,
        min_rows=int(source["min_rows"]),
        notes=notes,
    )


def english_acquirers(path: Optional[Path] = None) -> Dict[str, Callable[[], DatasetEntry]]:
    """Maps each configured English source id to a zero-argument acquirer."""
    config = load_sources_config(path)

    def make(source: Dict[str, Any]) -> Callable[[], DatasetEntry]:
        return lambda: acquire_english_source(source, config)

    return {source["id"]: make(source) for source in config["sources"]}
