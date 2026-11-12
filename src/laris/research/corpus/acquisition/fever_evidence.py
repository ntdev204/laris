"""Resolves FEVER evidence references (Wikipedia page + sentence id) to sentence text.

FEVER labels point at sentences of a 2017 Wikipedia snapshot (`wiki-pages.zip` from fever.ai, one
JSON object per page). The snapshot is streamed file by file and only the sentences some claim
references are kept, producing one compact table: `page`, `sentence_id`, `text`. The Hugging
Face parquet conversion of the snapshot is truncated (about a fifth of the pages are missing), so
it is not used.
"""

import json
import re
import zipfile
from pathlib import Path
from typing import Dict, Iterable, Iterator, List, Sequence, Set, Tuple

import pyarrow as pa
import pyarrow.parquet as pq

EVIDENCE_FILENAME = "evidence_sentences.parquet"
EVIDENCE_SCHEMA = pa.schema(
    [("page", pa.string()), ("sentence_id", pa.int32()), ("text", pa.string())]
)

_PTB_TOKENS = {
    "-LRB-": "(",
    "-RRB-": ")",
    "-LSB-": "[",
    "-RSB-": "]",
    "-LCB-": "{",
    "-RCB-": "}",
    "``": '"',
    "''": '"',
}
_PTB_PATTERN = re.compile("|".join(re.escape(k) for k in _PTB_TOKENS))
_SPACE_BEFORE_PUNCT = re.compile(r"\s+([,.;:!?%)\]}])")
_SPACE_AFTER_OPEN = re.compile(r"([(\[{])\s+")


def detokenize(text: str) -> str:
    """Undoes the Penn Treebank bracket/quote tokens and spacing used in the FEVER dump."""
    text = _PTB_PATTERN.sub(lambda m: _PTB_TOKENS[m.group(0)], text)
    text = _SPACE_BEFORE_PUNCT.sub(r"\1", text)
    text = _SPACE_AFTER_OPEN.sub(r"\1", text)
    return " ".join(text.split())


def collect_needed_sentences(claim_files: Iterable[Path]) -> Dict[str, Set[int]]:
    """Maps each referenced page to the sentence ids that some claim cites."""
    needed: Dict[str, Set[int]] = {}
    for path in claim_files:
        table = pq.read_table(path, columns=["evidence_wiki_url", "evidence_sentence_id"])
        for page, sid in zip(
            table.column("evidence_wiki_url").to_pylist(),
            table.column("evidence_sentence_id").to_pylist(),
        ):
            if page and sid is not None and sid >= 0:
                needed.setdefault(page, set()).add(int(sid))
    return needed


def _parse_lines(lines: str) -> Iterator[Tuple[int, str]]:
    """Yields (sentence_id, text) from a wiki page `lines` field (`id<TAB>text<TAB>links`)."""
    for raw in lines.split("\n"):
        parts = raw.split("\t")
        if len(parts) >= 2 and parts[0].isdigit() and parts[1].strip():
            yield int(parts[0]), parts[1]


def _is_wiki_shard(name: str) -> bool:
    """True for `wiki-pages/wiki-NNN.jsonl`, skipping macOS resource-fork entries."""
    return name.startswith("wiki-pages/wiki-") and name.endswith(".jsonl")


def extract_sentences(
    archive: Path, needed: Dict[str, Set[int]]
) -> Iterator[Tuple[str, int, str]]:
    """Streams the wiki-pages zip, yielding only the referenced sentences."""
    with zipfile.ZipFile(archive) as zf:
        for name in sorted(n for n in zf.namelist() if _is_wiki_shard(n)):
            with zf.open(name) as handle:
                for raw in handle:
                    if not raw.strip():
                        continue
                    page = json.loads(raw)
                    wanted = needed.get(page.get("id", ""))
                    if not wanted:
                        continue
                    for sid, text in _parse_lines(page.get("lines", "")):
                        if sid in wanted:
                            yield page["id"], sid, detokenize(text)


def build_evidence_table(
    claim_files: Sequence[Path], archive: Path, output_path: Path
) -> int:
    """Writes the evidence table for every referenced sentence in `archive`; returns row count."""
    needed = collect_needed_sentences(claim_files)
    seen: Dict[Tuple[str, int], str] = {}
    for page, sid, text in extract_sentences(archive, needed):
        seen.setdefault((page, sid), text)
    rows: List[Dict[str, object]] = [
        {"page": page, "sentence_id": sid, "text": text}
        for (page, sid), text in sorted(seen.items())
    ]
    output_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = output_path.with_suffix(".tmp")
    pq.write_table(pa.Table.from_pylist(rows, schema=EVIDENCE_SCHEMA), tmp)
    tmp.replace(output_path)
    return len(rows)
