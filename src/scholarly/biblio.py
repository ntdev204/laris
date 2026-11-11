"""Bibliographic metadata from a document's text and (when available) its PDF metadata.

Fields: title, authors, year, DOI and arXiv id. A field is filled only from explicit evidence: a
metadata field, a DOI or arXiv pattern, a copyright or publication line, or a title/author block
that passes strict shape checks. Anything else stays empty.
"""

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional

_DOI = re.compile(r"\b(10\.\d{4,9}/[^\s\"<>\]\)]+)", re.IGNORECASE)
_ARXIV_NEW = re.compile(r"\barxiv\s*:\s*(\d{4}\.\d{4,5})(v\d+)?", re.IGNORECASE)
_ARXIV_OLD = re.compile(r"\barxiv\s*:\s*([a-z-]+(?:\.[A-Z]{2})?/\d{7})(v\d+)?", re.IGNORECASE)
_YEAR_CTX = re.compile(
    r"(?:©|\(c\)|copyright|published|accepted|received|submitted|online)[^\n\d]{0,40}"
    r"(?:\d{1,2}\s+\w+\s+|\w+\s+\d{1,2},?\s+)?((?:19|20)\d{2})\b",
    re.IGNORECASE,
)
_NAME = re.compile(r"^[A-ZÀ-Ỹ][\w'’.-]*(?:\s+[A-ZÀ-Ỹ][\w'’.-]*){1,3}$")
_TRAIL = ".,;:)]}'\""
REFERENCES_HEADING = re.compile(
    r"^\s*(?:\d+[.)]?\s*)?(references|bibliography|literature cited|tài liệu tham khảo)\s*:?\s*$",
    re.IGNORECASE | re.MULTILINE,
)
MAX_HEAD_CHARS = 3000
MIN_YEAR, MAX_YEAR = 1900, 2100


@dataclass
class Bibliography:
    title: str = ""
    authors: List[str] = field(default_factory=list)
    year: Optional[int] = None
    doi: str = ""
    arxiv: str = ""
    evidence: Dict[str, str] = field(default_factory=dict)  # field -> where it came from

    def properties(self) -> Dict[str, Any]:
        """Non-empty fields as note properties (names chosen not to clash with note keys)."""
        out: Dict[str, Any] = {}
        if self.title:
            out["bib_title"] = self.title
        if self.authors:
            out["authors"] = self.authors
        if self.year:
            out["year"] = self.year
        if self.doi:
            out["doi"] = self.doi
        if self.arxiv:
            out["arxiv"] = self.arxiv
        return out

    def filled(self) -> int:
        return len(self.properties())


def clean_doi(raw: str) -> str:
    return raw.strip().rstrip(_TRAIL).lower()


def find_doi(text: str) -> str:
    match = _DOI.search(text)
    return clean_doi(match.group(1)) if match else ""


def find_arxiv(text: str) -> str:
    match = _ARXIV_NEW.search(text) or _ARXIV_OLD.search(text)
    return match.group(1).lower() if match else ""


def _arxiv_year(arxiv: str) -> Optional[int]:
    match = re.match(r"(\d{2})(\d{2})\.\d{4,5}$", arxiv)
    if not match or not 1 <= int(match.group(2)) <= 12:
        return None
    return 2000 + int(match.group(1))


def _year(value: Any) -> Optional[int]:
    pdf_date = re.match(r"\s*D:((?:19|20)\d{2})", str(value or ""))  # PDF date: D:YYYYMMDD...
    if pdf_date:
        return int(pdf_date.group(1))
    match = re.search(r"(?<!\d)((?:19|20)\d{2})(?!\d)", str(value or ""))
    year = int(match.group(1)) if match else None
    return year if year and MIN_YEAR <= year <= MAX_YEAR else None


def split_authors(raw: str) -> List[str]:
    parts = re.split(r"\s*(?:;|,|\band\b|&|\bvà\b)\s*", raw.strip())
    names = [" ".join(p.split()) for p in parts if p.strip()]
    return [n for n in names if _NAME.match(n)] if names else []


def _title_ok(line: str) -> bool:
    words = line.split()
    if not 3 <= len(words) <= 30 or not 10 <= len(line) <= 220:
        return False
    low = line.lower()
    if low.startswith(("abstract", "arxiv", "doi", "http", "www", "keywords", "journal", "vol.")):
        return False
    if _DOI.search(line) or "@" in line or line.endswith((".", ":")):
        return False
    letters = [c for c in line if c.isalpha()]
    return bool(letters) and sum(c.isupper() for c in letters) / len(letters) < 0.85


def from_text(text: str) -> Bibliography:
    """Read what the first page states. Empty fields stay empty."""
    head = text[:MAX_HEAD_CHARS]
    cut = REFERENCES_HEADING.search(head)
    if cut:  # identifiers of cited works are not this document's own
        head = head[: cut.start()]
    bib = Bibliography()
    bib.doi = find_doi(head)
    if bib.doi:
        bib.evidence["doi"] = "doi pattern"
    bib.arxiv = find_arxiv(head)
    if bib.arxiv:
        bib.evidence["arxiv"] = "arxiv pattern"
    match = _YEAR_CTX.search(head)
    if match and _year(match.group(1)):
        bib.year, bib.evidence["year"] = int(match.group(1)), "publication line"
    elif bib.arxiv and _arxiv_year(bib.arxiv):
        bib.year, bib.evidence["year"] = _arxiv_year(bib.arxiv), "arxiv id"
    lines = [ln.strip() for ln in head.splitlines() if ln.strip()]
    for i, line in enumerate(lines[:8]):
        if _title_ok(line):
            bib.title, bib.evidence["title"] = line, "first lines"
            following = lines[i + 1 : i + 3]
            for candidate in following:
                names = split_authors(candidate)
                if names and len(names) == len(
                    [p for p in re.split(r"\s*(?:;|,|\band\b|&)\s*", candidate) if p.strip()]
                ):
                    bib.authors, bib.evidence["authors"] = names, "line after title"
                    break
            break
    return bib


def from_metadata(meta: Mapping[str, Any]) -> Bibliography:
    """PDF document-information fields (`/Title`, `/Author`, `/CreationDate`, ...)."""
    bib = Bibliography()
    title = str(meta.get("title") or meta.get("/Title") or "").strip()
    if title and _title_ok(title) or (title and len(title.split()) >= 2 and len(title) <= 220):
        bib.title, bib.evidence["title"] = title, "pdf metadata"
    author = str(meta.get("author") or meta.get("/Author") or "").strip()
    names = split_authors(author) if author else []
    if names:
        bib.authors, bib.evidence["authors"] = names, "pdf metadata"
    year = _year(meta.get("year") or meta.get("/CreationDate") or meta.get("creation_date"))
    if year:
        bib.year, bib.evidence["year"] = year, "pdf metadata"
    subject = " ".join(str(meta.get(k) or "") for k in ("subject", "/Subject", "doi", "/doi"))
    bib.doi = find_doi(subject)
    if bib.doi:
        bib.evidence["doi"] = "pdf metadata"
    return bib


def extract(text: str, metadata: Optional[Mapping[str, Any]] = None) -> Bibliography:
    """Metadata wins where it is present and plausible; the text fills the rest."""
    bib = from_text(text)
    if metadata:
        meta = from_metadata(metadata)
        for name in ("title", "authors", "year", "doi"):
            if getattr(meta, name):
                setattr(bib, name, getattr(meta, name))
                bib.evidence[name] = meta.evidence[name]
    return bib


def pdf_metadata(data: bytes) -> Dict[str, Any]:
    """Document-information fields of a PDF, or {} when unreadable or pypdf is missing."""
    try:
        import io

        from pypdf import PdfReader

        info: Any = PdfReader(io.BytesIO(data)).metadata or {}
        return {str(k): str(v) for k, v in dict(info).items()}
    except Exception:
        return {}
