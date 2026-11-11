"""Document workspace: ingestion into passages with character spans, stored as JSONL.

Nothing here trains or scores a model. A workspace is a directory holding `chunks.jsonl`
(one passage per line) and, once indexed, `embeddings.npy` with its `embeddings.json` identity.
"""

import base64
import hashlib
import io
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable, Dict, Iterable, Iterator, List, Optional, Tuple

from laris.application.ocr import OcrError, ocr_image_bytes, ocr_pdf_bytes

CHUNK_WORDS = 140
MIN_CHUNK_WORDS = 20
TEXT_SUFFIXES = {".txt", ".md", ".markdown", ".text"}
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp"}
CHUNKS_FILE = "chunks.jsonl"


class IngestError(ValueError):
    """Raised when a document cannot be read or contains no text."""


@dataclass(frozen=True)
class Chunk:
    chunk_id: str
    doc_id: str
    source: str
    title: str
    text: str
    start: int  # character span of `text` inside the cleaned document
    end: int


def clean_text(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\x00", "")
    return re.sub(r"[ \t\f\v]+", " ", text).strip()


def split_passages(text: str, target_words: int = CHUNK_WORDS) -> List[Tuple[int, int]]:
    """Paragraph-aware spans of about `target_words` words; tiny tails join the previous span."""
    spans: List[Tuple[int, int]] = []
    start: Optional[int] = None
    end = 0
    words = 0
    for match in re.finditer(r"\S[^\n]*(?:\n(?!\n)[^\n]*)*", text):
        count = len(match.group(0).split())
        if start is None:
            start = match.start()
        end = match.end()
        words += count
        if words >= target_words:
            spans.append((start, end))
            start, words = None, 0
    if start is not None:
        if spans and words < MIN_CHUNK_WORDS:
            spans[-1] = (spans[-1][0], end)
        else:
            spans.append((start, end))
    out: List[Tuple[int, int]] = []
    for s, e in spans:  # split any single huge paragraph on word boundaries
        pieces = list(re.finditer(r"\S+", text[s:e]))
        if len(pieces) <= target_words * 2:
            out.append((s, e))
            continue
        for i in range(0, len(pieces), target_words):
            group = pieces[i : i + target_words]
            out.append((s + group[0].start(), s + group[-1].end()))
    return out


def chunks_from_text(source: str, text: str, title: str = "") -> List[Chunk]:
    text = clean_text(text)
    if not text:
        raise IngestError(f"{source}: no text found")
    doc_id = hashlib.sha256(source.encode("utf-8")).hexdigest()[:12]
    return [
        Chunk(f"{doc_id}:{n}", doc_id, source, title or source, text[s:e], s, e)
        for n, (s, e) in enumerate(split_passages(text))
    ]


def read_text_from_bytes(name: str, data: bytes) -> str:
    """Plain text of a txt/md/pdf/image file; scanned PDFs and images go through OCR."""
    suffix = Path(name).suffix.lower()
    if suffix in IMAGE_SUFFIXES:
        return _ocr_or_fail(lambda: ocr_image_bytes(data), name)
    if suffix == ".pdf":
        text = _pdf_text(data, name)
        if len(text.strip()) < 20:  # no text layer: treat as a scan
            text = _ocr_or_fail(lambda: ocr_pdf_bytes(data), name)
        return text
    if suffix in TEXT_SUFFIXES or not suffix:
        return data.decode("utf-8", errors="replace")
    raise IngestError(f"{name}: unsupported type {suffix}")


def _ocr_or_fail(call: Callable[[], str], name: str) -> str:
    try:
        return call()
    except OcrError as exc:
        raise IngestError(f"{name}: {exc}") from exc


def _pdf_text(data: bytes, name: str) -> str:
    try:
        from pypdf import PdfReader
    except ImportError as exc:  # pypdf is an optional extra
        raise IngestError("PDF input needs pypdf (pip install 'laris[ocr]')") from exc
    try:
        reader = PdfReader(io.BytesIO(data))
        return "\n\n".join((page.extract_text() or "") for page in reader.pages)
    except Exception as exc:
        raise IngestError(f"{name}: unreadable PDF ({exc})") from exc


def chunks_from_bytes(name: str, data: bytes) -> List[Chunk]:
    return chunks_from_text(name, read_text_from_bytes(name, data))


def chunks_from_jsonl(path: Path, limit: Optional[int] = None) -> Iterator[Chunk]:
    """BEIR-style corpus lines: {"_id", "title", "text"}; each record is one passage."""
    with open(path, encoding="utf-8") as handle:
        for count, line in enumerate(handle):
            if limit is not None and count >= limit:
                return
            if not line.strip():
                continue
            row = json.loads(line)
            body = clean_text(str(row.get("text", "")))
            if not body:
                continue
            ident = str(row.get("_id", count))
            title = str(row.get("title") or ident)
            yield Chunk(f"{path.stem}:{ident}", path.stem, path.name, title, body, 0, len(body))


def chunks_from_parquet(path: Path, limit: Optional[int] = None) -> Iterator[Chunk]:
    """BEIR corpus parquet with `_id`, `title` and `text` columns."""
    import pyarrow.parquet as pq

    table = pq.read_table(path)
    if "text" not in table.column_names:
        raise IngestError(f"{path.name}: parquet needs a `text` column")
    rows = table.to_pylist()
    for count, row in enumerate(rows if limit is None else rows[:limit]):
        body = clean_text(str(row.get("text") or ""))
        if body:
            ident = str(row.get("_id", count))
            title = str(row.get("title") or ident)
            yield Chunk(f"{path.stem}:{ident}", path.stem, path.name, title, body, 0, len(body))


def chunks_from_path(path: Path, limit: Optional[int] = None) -> List[Chunk]:
    if path.is_dir():
        found: List[Chunk] = []
        for child in sorted(path.rglob("*")):
            if child.is_file() and child.suffix.lower() in TEXT_SUFFIXES | {
                ".pdf",
                ".jsonl",
                ".parquet",
            }:
                found.extend(chunks_from_path(child, limit))
        return found
    if path.suffix.lower() == ".jsonl":
        return list(chunks_from_jsonl(path, limit))
    if path.suffix.lower() == ".parquet":
        return list(chunks_from_parquet(path, limit))
    return chunks_from_bytes(str(path), path.read_bytes())


def decode_upload(name: str, text: Optional[str], data_base64: Optional[str]) -> List[Chunk]:
    if data_base64:
        return chunks_from_bytes(name, base64.b64decode(data_base64))
    if text is not None:
        return chunks_from_text(name, text)
    raise IngestError("provide text or data_base64")


class Workspace:
    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    @property
    def chunks_path(self) -> Path:
        return self.root / CHUNKS_FILE

    def load(self) -> List[Chunk]:
        if not self.chunks_path.exists():
            return []
        with open(self.chunks_path, encoding="utf-8") as handle:
            return [Chunk(**json.loads(line)) for line in handle if line.strip()]

    def add(self, new_chunks: Iterable[Chunk]) -> Dict[str, int]:
        """Replace every document that appears in `new_chunks`; returns counts."""
        incoming = list(new_chunks)
        replaced = {c.doc_id for c in incoming}
        kept = [c for c in self.load() if c.doc_id not in replaced]
        merged = kept + incoming
        tmp = self.chunks_path.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as handle:
            for chunk in merged:
                handle.write(json.dumps(asdict(chunk), ensure_ascii=False) + "\n")
        tmp.replace(self.chunks_path)
        for stale in ("embeddings.npy", "embeddings.json"):  # the dense index no longer matches
            (self.root / stale).unlink(missing_ok=True)
        return {"documents": len(replaced), "passages": len(incoming), "total": len(merged)}

    def clear(self) -> None:
        for name in (CHUNKS_FILE, "embeddings.npy", "embeddings.json"):
            (self.root / name).unlink(missing_ok=True)
