"""Bounded, resumable streaming acquisition of S2ORC full-text papers.

The Semantic Scholar Datasets API lists the `s2orc` release as hundreds of ~1 GB gzip shards. This
module never stores a raw shard: each one is streamed, decompressed and filtered on the fly,
and only the kept papers are written (parquet, zstd). Download stops at a hard byte budget
per stage.

Configuration comes from the environment only:
- `S2ORC_API_KEY` (required): Semantic Scholar Datasets API key, sent as `x-api-key`.
- `S2ORC_API_BASE` (optional): override of the Datasets API base URL.

STEM selection is by external identifiers (no `papers` join): a paper is kept when it carries an
ArXiv, DBLP, ACL, PubMed or PubMedCentral id. This is an approximation of "STEM", recorded as such.
"""

import json
import os
import random
import time
import urllib.error
import urllib.request
import zlib
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Tuple

from corpus.acquisition.common import (
    CACHE_DIR,
    RAW_DIR,
    DatasetEntry,
    _finalize_entry,
    _record_files,
    count_parquet_rows,
)

API_KEY_ENV = "S2ORC_API_KEY"
API_BASE_ENV = "S2ORC_API_BASE"
DEFAULT_API_BASE = "https://api.semanticscholar.org/datasets/v1"

S2ORC_DEFAULT_BUDGET_BYTES = 10 * 1000**3
S2ORC_MIN_CHARS = 2000
S2ORC_ROW_GROUP = 1000
S2ORC_MAX_ATTEMPTS = 5

# Stage -> (dataset id, directory, shard offset). Offsets are disjoint modulo 3 so stages never
# share a shard; offset 2 stays reserved for stage 03.
STAGES: Dict[str, Tuple[str, str, int]] = {
    "01": ("S2ORC-GENERAL-LM", "s2orc_stage01", 0),
    "02": ("S2ORC-STEM", "s2orc_stage02", 1),
}
SHARD_STRIDE = 3

STEM_ID_KEYS: Tuple[str, ...] = ("arxiv", "dblp", "acl", "pubmed", "pubmedcentral")
OPEN_LICENSES = frozenset({"CCBY", "CCBYSA", "CC0", "CCBYNC", "CCBYNCSA", "PUBLICDOMAIN"})
KEPT_ANNOTATIONS: Tuple[str, ...] = ("abstract", "sectionheader", "paragraph")


def _api_key() -> str:
    key = os.environ.get(API_KEY_ENV, "").strip()
    if not key:
        raise RuntimeError(f"{API_KEY_ENV} is not set; export it in the environment, not a file")
    return key


def _api_get(url: str, key: str, attempts: int = 6) -> Dict[str, Any]:
    """GET JSON from the Datasets API, backing off on rate limiting (about 1 request per second)."""
    headers = {"x-api-key": key, "User-Agent": "laris-data-acquisition/1.0"}
    for attempt in range(1, attempts + 1):
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=60) as resp:
                return json.load(resp)  # type: ignore[no-any-return]
        except urllib.error.HTTPError as exc:
            if exc.code != 429 or attempt == attempts:
                raise
            time.sleep(min(60, 5 * attempt))
    raise RuntimeError("unreachable")


def fetch_release(refresh: bool = False) -> Dict[str, Any]:
    """Returns {release_id, files}; the signed shard URLs are cached because they expire."""
    cache = CACHE_DIR / "s2orc_release.json"
    if cache.exists() and not refresh:
        return json.loads(cache.read_text(encoding="utf-8"))  # type: ignore[no-any-return]
    base = os.environ.get(API_BASE_ENV, DEFAULT_API_BASE).rstrip("/")
    key = _api_key()
    release = _api_get(f"{base}/release/latest", key)
    time.sleep(1.1)
    dataset = _api_get(f"{base}/release/{release['release_id']}/dataset/s2orc", key)
    data = {"release_id": release["release_id"], "files": dataset["files"]}
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(data), encoding="utf-8")
    cache.chmod(0o600)
    return data


def select_shards(total: int, stage: str, seed: int = 20261111) -> List[int]:
    """Deterministic, stage-disjoint shard order spread over the whole release."""
    offset = STAGES[stage][2]
    candidates = list(range(offset, total, SHARD_STRIDE))
    random.Random(f"{seed}:{stage}").shuffle(candidates)
    return candidates


def primary_source(external_ids: Dict[str, Any]) -> Optional[str]:
    for key in STEM_ID_KEYS:
        if external_ids.get(key):
            return key
    return None


def _lower_keys(obj: Any) -> Any:
    return {k.lower(): v for k, v in obj.items()} if isinstance(obj, dict) else {}


def _normalize(raw: Dict[str, Any]) -> Tuple[Dict[str, Any], str, str, Dict[str, Any], str]:
    """Maps both release schemas to (external ids, text, license, annotations, title).

    Older shards use `content` + `externalids`; newer ones use `body` + `openaccessinfo`.
    """
    if "body" in raw:
        info = _lower_keys(raw.get("openaccessinfo"))
        body = raw.get("body") or {}
        ids = _lower_keys(info.get("externalids"))
        annotations = {k.replace("_", ""): v for k, v in (body.get("annotations") or {}).items()}
        return ids, body.get("text") or "", str(info.get("license") or ""), annotations, (
            raw.get("title") or ""
        )
    content = raw.get("content") or {}
    ids = _lower_keys(raw.get("externalids") or raw.get("externalIds"))
    info = _lower_keys(_lower_keys(content.get("source")).get("oainfo"))
    return (
        ids, content.get("text") or "", str(info.get("license") or ""),
        content.get("annotations") or {}, "",
    )


def filter_record(
    raw: Dict[str, Any], min_chars: int = S2ORC_MIN_CHARS, drops: Optional[Dict[str, int]] = None
) -> Optional[Dict[str, Any]]:
    """Keeps an open-licensed paper with a STEM identifier and enough full text, else None."""
    ids, text, license_raw, annotations, title = _normalize(raw)

    def drop(reason: str) -> None:
        if drops is not None:
            drops[reason] = drops.get(reason, 0) + 1

    source = primary_source(ids)
    if source is None:
        drop("no_stem_id")
        return None
    if len(text) < min_chars:
        drop("short_text")
        return None
    license_code = license_raw.upper().replace("-", "").replace("_", "")
    if license_code not in OPEN_LICENSES:
        drop("license_missing_or_closed")
        return None
    structure = {
        k: v if isinstance(v, str) else json.dumps(v, separators=(",", ":"))
        for k, v in annotations.items()
        if k in KEPT_ANNOTATIONS and v
    }
    return {
        "doc_id": f"s2orc-{raw['corpusid']}",
        "corpusid": int(raw["corpusid"]),
        "source": source,
        "license": license_code,
        "title": title,
        "text": text,
        "structure": json.dumps(structure, separators=(",", ":")),
    }


def iter_shard_records(url: str) -> Iterator[Dict[str, Any]]:
    """Streams one gzip JSONL shard from its signed URL without storing it."""
    req = urllib.request.Request(url, headers={"User-Agent": "laris-data-acquisition/1.0"})
    decomp = zlib.decompressobj(16 + zlib.MAX_WBITS)
    tail = b""
    with urllib.request.urlopen(req, timeout=120) as resp:
        while chunk := resp.read(1 << 20):
            *lines, tail = (tail + decomp.decompress(chunk)).split(b"\n")
            for line in lines:
                if line:
                    yield json.loads(line)
    if tail.strip():
        yield json.loads(tail)


def _dir_bytes(dest: Path) -> int:
    return sum(p.stat().st_size for p in dest.glob("*.parquet*"))


def _write_shard(
    url: str, out: Path, remaining: int, seen: set, drops: Dict[str, int]
) -> Tuple[int, int, Dict[str, int], bool]:
    """Filters one shard into `out`; returns (papers, bytes, per-source counts, budget_hit)."""
    import pyarrow as pa
    import pyarrow.parquet as pq

    schema = pa.schema([
        ("doc_id", pa.string()), ("corpusid", pa.int64()), ("source", pa.string()),
        ("license", pa.string()), ("title", pa.string()), ("text", pa.string()),
        ("structure", pa.string()),
    ])
    tmp = out.with_suffix(".parquet.tmp")
    batch: List[Dict[str, Any]] = []
    counts: Dict[str, int] = {}
    papers = 0
    budget_hit = False
    writer = pq.ParquetWriter(tmp, schema, compression="zstd")

    def flush() -> None:
        nonlocal batch
        if batch:
            writer.write_table(pa.Table.from_pylist(batch, schema=schema))
            batch = []

    try:
        for raw in iter_shard_records(url):
            kept = filter_record(raw, drops=drops)
            if kept is None or kept["corpusid"] in seen:
                continue
            seen.add(kept["corpusid"])
            batch.append(kept)
            papers += 1
            counts[kept["source"]] = counts.get(kept["source"], 0) + 1
            if len(batch) >= S2ORC_ROW_GROUP:
                flush()
                if tmp.stat().st_size >= remaining:
                    budget_hit = True
                    break
        flush()
    finally:
        writer.close()
    tmp.replace(out)
    return papers, out.stat().st_size, counts, budget_hit


def acquire_s2orc(
    stage: str = "02",
    budget_bytes: int = S2ORC_DEFAULT_BUDGET_BYTES,
    max_shards: Optional[int] = None,
) -> DatasetEntry:
    """Streams a bounded, filtered S2ORC sample for a stage into `data/raw/<stage dir>`."""
    dataset_id, dirname, _ = STAGES[stage]
    print(f"\n--- Acquiring S2ORC for stage {stage} (<= {budget_bytes / 1e9:.1f} GB) ---")
    dest = RAW_DIR / dirname
    dest.mkdir(parents=True, exist_ok=True)
    for stale in dest.glob("*.tmp"):
        stale.unlink()

    release = fetch_release()
    files = release["files"]
    order = select_shards(len(files), stage)
    state_path = dest / "state.json"
    state: Dict[str, Any] = (
        json.loads(state_path.read_text(encoding="utf-8")) if state_path.exists()
        else {"release_id": release["release_id"], "done": {}, "sources": {}}
    )
    if state["release_id"] != release["release_id"]:
        raise RuntimeError("S2ORC release changed since the last run; refusing to mix releases")

    seen: set = set()
    import pyarrow.parquet as pq

    for shard_file in sorted(dest.glob("shard-*.parquet")):
        seen.update(pq.read_table(shard_file, columns=["corpusid"]).column("corpusid").to_pylist())

    processed = 0
    refreshed = False
    for idx in order:
        if max_shards is not None and processed >= max_shards:
            break
        if str(idx) in state["done"]:
            continue
        remaining = budget_bytes - _dir_bytes(dest)
        if remaining <= 0:
            print("  [BUDGET] byte budget reached; stopping")
            break
        out = dest / f"shard-{idx:04d}.parquet"
        drops: Dict[str, int] = {}
        for attempt in range(1, S2ORC_MAX_ATTEMPTS + 1):
            try:
                papers, size, counts, hit = _write_shard(files[idx], out, remaining, seen, drops)
                break
            except urllib.error.HTTPError as exc:
                if exc.code == 403 and not refreshed:  # signed URL expired
                    files = fetch_release(refresh=True)["files"]
                    refreshed = True
                    continue
                raise
            except (urllib.error.URLError, OSError, zlib.error, EOFError, json.JSONDecodeError):
                if attempt == S2ORC_MAX_ATTEMPTS:
                    raise
                time.sleep(5 * attempt)
        state["done"][str(idx)] = {
            "papers": papers, "bytes": size, "partial": hit, "dropped": drops,
        }
        for key, n in counts.items():
            state["sources"][key] = state["sources"].get(key, 0) + n
        state_path.write_text(json.dumps(state, indent=1), encoding="utf-8")
        processed += 1
        total_gb = _dir_bytes(dest) / 1e9
        print(
            f"  [SHARD {idx:03d}] {papers:,} papers, {size / 1e6:.0f} MB, total {total_gb:.2f} GB"
        )
        if hit:
            break

    names = [p.name for p in sorted(dest.glob("shard-*.parquet"))]
    records, size, rows = _record_files(dest, names, count_parquet_rows)
    complete = size >= budget_bytes * 0.9 or len(state["done"]) >= len(order)
    return _finalize_entry(
        dataset_id=dataset_id,
        name=f"S2ORC full-text papers (stage {stage}, STEM by external id)",
        version=f"s2ag-{release['release_id']}",
        source_url="https://api.semanticscholar.org/datasets/v1/release/latest/dataset/s2orc",
        license_name="ODC-BY-1.0 (collection); per-paper open license kept in `license`",
        license_approved=True,
        language="English",
        sample_unit="Parsed full-text paper",
        expected=f"Bounded stream: <= {budget_bytes / 1e9:.0f} GB stored, from {len(order)} shards",
        dest_dir=dest,
        records=records,
        size=size,
        rows=rows,
        complete=complete,
        min_rows=1000,
        notes=(
            "Filtered on the fly from signed s2orc shards; no raw shard is stored. "
            "Kept papers carry "
            f"an id in {STEM_ID_KEYS}, text >= {S2ORC_MIN_CHARS} chars and an open license "
            f"{sorted(OPEN_LICENSES)}. STEM is approximated by identifier, not by field of study. "
            f"Source counts: {state['sources']}."
        ),
    )
