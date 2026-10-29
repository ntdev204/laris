"""Resumable, bounded streaming acquisition of the CC-100 Vietnamese corpus."""

import codecs
import hashlib
import json
import lzma
import sys
import unicodedata
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Tuple

from laris.corpus.acquisition.common import (
    RAW_DIR,
    DatasetEntry,
    _finalize_entry,
    _record_files,
    count_parquet_rows,
)

CC100_VI_URL = "https://data.statmt.org/cc-100/vi.txt.xz"


CC100_DEFAULT_MAX_DOCS = 2_700_000


CC100_SHARD_DOCS = 50_000


CC100_MIN_CHARS = 200


CC100_MAX_ATTEMPTS = 5


def _iter_cc100_documents(url: str, max_docs: int) -> Any:
    """Streams blank-line separated documents from the remote xz without downloading it all."""
    headers = {"User-Agent": "LARIS-Research-Agent/1.0 (+https://github.com/ntdev204/laris)"}
    req = urllib.request.Request(url, headers=headers)
    decomp = lzma.LZMADecompressor(format=lzma.FORMAT_XZ)
    utf8 = codecs.getincrementaldecoder("utf-8")(errors="replace")
    lines: List[str] = []
    tail = ""
    emitted = 0
    with urllib.request.urlopen(req, timeout=120) as resp:
        while emitted < max_docs:
            chunk = resp.read(1 << 20)
            if not chunk:
                break
            try:
                data = decomp.decompress(chunk)
            except EOFError:
                break
            parts = (tail + utf8.decode(data)).split("\n")
            tail = parts.pop()
            for line in parts:
                if line.strip():
                    lines.append(line.strip())
                    continue
                if lines:
                    yield "\n".join(lines)
                    emitted += 1
                    lines = []
                    if emitted >= max_docs:
                        return


def _resume_cc100_state(dest_dir: Path) -> Tuple[set, int, int]:
    """Rebuilds the digest set, document count and next shard index from existing shards."""
    import pyarrow.parquet as pq

    for stale in dest_dir.glob("*.tmp"):
        stale.unlink()
    seen: set = set()
    kept = 0
    shards = sorted(dest_dir.glob("*.parquet"))
    for shard in shards:
        texts = pq.read_table(shard, columns=["text"]).column("text").to_pylist()
        for text in texts:
            seen.add(hashlib.sha256(text.encode("utf-8")).digest()[:16])
        kept += len(texts)
    return seen, kept, len(shards)


def acquire_cc100_vi(max_docs: int = CC100_DEFAULT_MAX_DOCS) -> DatasetEntry:
    """Streams a bounded, cleaned and exact-deduplicated Vietnamese CC-100 sample into parquet."""
    print(f"\n--- Acquiring CC-100 Vietnamese (streamed, <= {max_docs:,} documents) ---")
    import pyarrow as pa
    import pyarrow.parquet as pq

    dest_dir = RAW_DIR / "cc100_vi_clean"
    expected = (
        f"{max_docs:,} documents (bounded stream of {CC100_VI_URL}; full file is ~29.5 GB xz)"
    )
    complete_marker = dest_dir / ".complete"
    if complete_marker.exists():
        print(f"  [CACHE] CC-100 shards already complete in {dest_dir.name}")
    else:
        dest_dir.mkdir(parents=True, exist_ok=True)
        seen, kept, shard_idx = _resume_cc100_state(dest_dir)
        if kept:
            print(f"  [RESUME] {kept:,} documents already on disk ({shard_idx} shards)")
        batch: List[Dict[str, str]] = []

        def flush() -> None:
            nonlocal batch, shard_idx
            if not batch:
                return
            table = pa.Table.from_pylist(batch, schema=pa.schema([
                ("doc_id", pa.string()), ("text", pa.string()), ("source", pa.string()),
            ]))
            tmp_path = dest_dir / f"{shard_idx:04d}.parquet.tmp"
            pq.write_table(table, tmp_path, compression="zstd")
            tmp_path.replace(dest_dir / f"{shard_idx:04d}.parquet")
            shard_idx += 1
            batch = []

        # A dropped connection restarts the stream from the beginning; documents already
        # written are recognised by digest and skipped, so every attempt resumes in place.
        for attempt in range(1, CC100_MAX_ATTEMPTS + 1):
            try:
                for doc in _iter_cc100_documents(CC100_VI_URL, sys.maxsize):
                    if kept >= max_docs:
                        break
                    text = unicodedata.normalize("NFC", doc)
                    if len(text) < CC100_MIN_CHARS:
                        continue
                    digest = hashlib.sha256(text.encode("utf-8")).digest()[:16]
                    if digest in seen:
                        continue
                    seen.add(digest)
                    batch.append(
                        {"doc_id": f"cc100-vi-{kept:09d}", "text": text, "source": "cc100-vi"}
                    )
                    kept += 1
                    if len(batch) >= CC100_SHARD_DOCS:
                        flush()
                        print(f"  [STREAM] {kept:,} documents written ({shard_idx} shards)")
                flush()
                complete_marker.write_text(json.dumps({"kept": kept}), encoding="utf-8")
                break
            except Exception as e:
                flush()
                print(
                    f"  [ERROR] CC-100 stream interrupted after {kept:,} documents "
                    f"(attempt {attempt}/{CC100_MAX_ATTEMPTS}): {e}"
                )

    done = complete_marker.exists()
    names = [p.name for p in sorted(dest_dir.glob("*.parquet"))] if dest_dir.exists() else []
    records, size, rows = _record_files(dest_dir, names, count_parquet_rows)
    return _finalize_entry(
        dataset_id="CC100-VI-CLEAN",
        name="Cleaned CC-100 Vietnamese Web Corpus (bounded stream)",
        version="CC-100 vi.txt.xz (bounded prefix)",
        source_url="https://data.statmt.org/cc-100/",
        license_name="Common Crawl Terms of Use (CC-100 declares no dataset license)",
        license_approved=False,
        language="Vietnamese",
        sample_unit="Cleaned Web Document (NFC, >= 200 chars, exact-deduplicated)",
        expected=expected,
        dest_dir=dest_dir,
        records=records,
        size=size,
        rows=rows,
        complete=done,
        min_rows=max_docs,
        notes=(
            "Prefix of the CC-100 stream, not a random sample: topical bias is possible. "
            "License is NOT CC-BY-SA as earlier spec stated; NEEDS_LICENSE_REVIEW "
            "before redistribution."
        ),
    )
