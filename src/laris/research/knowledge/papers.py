"""Journal papers as admissible Sources for the main brain (T285, SR-K3).

A paper is admissible only when, at import:

* its DOI resolves at Crossref (the response is kept and its SHA-256 recorded),
* Crossref records no retraction, withdrawal or removal for it,
* its venue (ISSN) is on the configured list of `configs/admissible-sources.json`,
* the licence of its full text (the JATS `<license>` of the Europe PMC copy) is one the class
  accepts (CC BY or CC0), and a licence Crossref states, when it states one, is accepted too, and
* the JATS copy names the same DOI.

The Source keeps the paper's title and abstract verbatim (with a provenance header); its Claims are
abstract sentences that state something (no first-person or "this review" framing). Whether a
Claim is later *certain* is decided by the Rust rule `laris-brain::certain` from the admission
record written here; this module only proposes. No network: the acquisition script fetches the
responses, this module reads bytes.
"""

from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

from laris.research.knowledge.build import claim_line, never, safe_title, sha256

Overlap = Callable[[str], bool]
XLINK = "{http://www.w3.org/1999/xlink}"
ALI = "{http://www.niso.org/schemas/ali/1.0/}"
_SENTENCE = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9(])")
_WORD = re.compile(r"[A-Za-z0-9]+(?:[-'][A-Za-z0-9]+)*")


def normalise_doi(text: str) -> str:
    """The DOI in lower case without a resolver prefix."""
    doi = text.strip()
    for prefix in ("https://doi.org/", "http://doi.org/", "https://dx.doi.org/", "doi:"):
        if doi.lower().startswith(prefix):
            doi = doi[len(prefix) :]
    return doi.strip().lower()


def licence_id(url: Optional[str], table: Dict[str, str]) -> Optional[str]:
    """The licence name for a licence URL (`table` maps URL stems to names), else None."""
    if not url:
        return None
    stem = re.sub(r"^https?://", "", url.strip().lower()).rstrip("/")
    stem = re.sub(r"/legalcode(\.[a-z]+)?$", "", stem)
    for key, name in table.items():
        if stem == key.lower().rstrip("/"):
            return name
    return None


@dataclass
class Verdict:
    """The import checks for one paper: admitted with a record, or refused by name."""

    doi: str
    reason: Optional[str] = None  # None when admitted
    detail: str = ""
    admission: Dict[str, Any] = field(default_factory=dict)
    venue_name: str = ""
    title: str = ""
    crossref_licence: bool = False  # whether Crossref stated an accepted licence too

    @property
    def admitted(self) -> bool:
        return self.reason is None


def _venue(issns: List[str], venues: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    wanted = {i.upper() for i in issns}
    for venue in venues:
        if wanted & {i.upper() for i in venue["issns"]}:
            return venue
    return None


def check_crossref(
    doi: str, raw: Optional[bytes], settings: Dict[str, Any], classes: Dict[str, Any]
) -> Verdict:
    """Checks Crossref's response `raw` for `doi` (None: it did not resolve)."""
    doi = normalise_doi(doi)
    verdict = Verdict(doi=doi)
    if raw is None:
        verdict.reason, verdict.detail = "unresolved", "Crossref has no record of the DOI"
        return verdict
    try:
        message = json.loads(raw)["message"]
    except (ValueError, KeyError, TypeError):
        verdict.reason, verdict.detail = "unresolved", "Crossref's response is not a work record"
        return verdict
    if normalise_doi(str(message.get("DOI", ""))) != doi:
        verdict.reason, verdict.detail = "unresolved", "Crossref returned another DOI"
        return verdict
    verdict.title = " ".join(" ".join(message.get("title") or []).split())
    kinds = set(settings["retraction_update_types"])
    updates = list(message.get("updated-by") or []) + list(message.get("update-to") or [])
    relation = message.get("relation") or {}
    if any(str(u.get("type", "")).lower() in kinds for u in updates) or any(
        "retract" in key for key in relation
    ):
        verdict.reason, verdict.detail = "retracted", "Crossref records a retraction or withdrawal"
        return verdict
    venue = _venue(list(message.get("ISSN") or []), settings["venues"])
    allowed = {v.upper() for v in classes["journal_paper"]["venues"] or []}
    if venue is None or venue["issn_l"].upper() not in allowed:
        verdict.reason, verdict.detail = "venue", "the venue is not on the configured list"
        return verdict
    listed = [
        item
        for item in message.get("license") or []
        if item.get("content-version") in (None, "vor", "unspecified")
    ]
    licences = {licence_id(item.get("URL"), settings["licence_urls"]) for item in listed}
    accepted = set(classes["journal_paper"]["licences"])
    # a licence Crossref states must be accepted; when it states none, the full text decides
    if listed and not (licences - {None}) & accepted:
        verdict.reason, verdict.detail = "licence", "Crossref states a licence that is not accepted"
        return verdict
    verdict.crossref_licence = bool(listed)
    verdict.venue_name = venue["name"]
    verdict.admission = {
        "class": "journal_paper",
        "resolved_by": "crossref",
        "resolution_sha256": sha256(raw),
        "licence": "",  # taken from the full text
        "venue": venue["issn_l"],
        "retraction_check": "crossref:none",
    }
    return verdict


@dataclass
class Jats:
    doi: str
    title: str
    abstract: List[str]
    licence_url: Optional[str]


def _text(node: Optional[ET.Element]) -> str:
    return " ".join("".join(node.itertext()).split()) if node is not None else ""


def parse_jats(raw: bytes) -> Jats:
    """Title, abstract paragraphs, DOI and licence URL of a JATS article (Europe PMC full text)."""
    root = ET.fromstring(raw)
    meta = root.find(".//article-meta")
    if meta is None:
        raise ValueError("no article-meta")
    doi = ""
    for node in meta.findall("article-id"):
        if node.get("pub-id-type") == "doi":
            doi = normalise_doi(node.text or "")
    title = _text(meta.find("title-group/article-title"))
    abstract_node = None
    for node in meta.findall("abstract"):
        if node.get("abstract-type") in (None, "", "summary"):
            abstract_node = node
            break
    paragraphs: List[str] = []
    if abstract_node is not None:
        found = abstract_node.findall(".//p")
        paragraphs = [t for t in (_text(p) for p in found) if t] or [_text(abstract_node)]
    url = None
    for lic in meta.findall(".//license"):
        url = lic.get(f"{XLINK}href")
        if not url:
            ref = lic.find(f"{ALI}license_ref")
            url = ref.text.strip() if ref is not None and ref.text else None
        if not url:
            # a link inside the licence text: <ext-link xlink:href="...creativecommons...">
            for node in lic.iter():
                href = node.get(f"{XLINK}href") or ""
                if "creativecommons.org/" in href:
                    url = href
                    break
        if not url:
            match = re.search(r"https?://creativecommons\.org/[^\s\"<)]+", _text(lic))
            url = match.group(0).rstrip(".") if match else None
        if url:
            break
    return Jats(doi=doi, title=title, abstract=[p for p in paragraphs if p], licence_url=url)


def check_full_text(verdict: Verdict, jats: Optional[Jats], settings: Dict, classes: Dict) -> None:
    """Completes `verdict` from the JATS copy: same DOI, an accepted licence, an abstract."""
    if not verdict.admitted:
        return
    if jats is None:
        verdict.reason, verdict.detail = "no-full-text", "no JATS copy with an accepted licence"
        return
    if jats.doi != verdict.doi:
        verdict.reason, verdict.detail = "unresolved", "the full text names another DOI"
        return
    name = licence_id(jats.licence_url, settings["licence_urls"])
    if name is None or name not in classes["journal_paper"]["licences"]:
        verdict.reason, verdict.detail = "licence", "the full text's licence is not accepted"
        return
    if not jats.abstract:
        verdict.reason, verdict.detail = "no-abstract", "the full text has no abstract"
        return
    verdict.admission["licence"] = name


def claim_sentences(paragraphs: List[str], rules: Dict[str, Any]) -> List[str]:
    """Abstract sentences that state something: length within bounds, no first-person or framing."""
    left_out = [w.lower() for w in rules["left_out_words"]]
    out: List[str] = []
    for paragraph in paragraphs:
        for sentence in _SENTENCE.split(paragraph):
            sentence = sentence.strip()
            words = _WORD.findall(sentence.lower())
            if not (rules["min_words"] <= len(words) <= rules["max_words"]):
                continue
            joined = " " + " ".join(words) + " "
            if any(f" {w} " in joined for w in left_out):
                continue
            if not sentence.endswith((".", "!", "?")):
                continue
            out.append(sentence)
    return out


def paper_lines(
    verdict: Verdict,
    jats: Jats,
    pmcid: str,
    jats_sha: str,
    settings: Dict[str, Any],
    proposer: str,
    overlaps: Overlap = never,
) -> Tuple[List[Dict], List[Dict], Dict[str, int]]:
    """One Source (provenance header, title, abstract) and its Claims for an admitted paper."""
    assert verdict.admitted
    kept, left = [], 0
    for paragraph in jats.abstract:
        if overlaps(paragraph):
            left += 1
        else:
            kept.append(paragraph)
    header = (
        f'Source: {verdict.venue_name}, "{jats.title}", https://doi.org/{verdict.doi}.\n'
        f"Location: Europe PMC {pmcid}, "
        f"{settings['registries']['full_text'].format(pmcid=pmcid)} (SHA-256 {jats_sha}).\n"
        f"Resolution: Crossref (response SHA-256 {verdict.admission['resolution_sha256']}); "
        "no retraction recorded at import; licence "
        + (
            "stated by Crossref and the full text"
            if verdict.crossref_licence
            else "stated by the full text (Crossref states none)"
        )  # fmt: skip
        + ".\n"
        f"Licence: {jats.licence_url} ({verdict.admission['licence']}); attribution: the authors.\n"
        "Changes: title and abstract only, converted from JATS to plain text.\n"
        + (
            f"Benchmark overlap: {left} paragraph(s) sharing a word sequence with a benchmark "
            "item left out (ADR-026 gate B6).\n"
            if left
            else ""
        )
    )
    title = safe_title(f"Paper {jats.title}")
    text = header + "\n" + jats.title + "\n\n" + "\n\n".join(kept) + "\n"
    source = {
        "type": "source",
        "title": title,
        "kind": "document",
        "identifier": f"https://doi.org/{verdict.doi}",
        "text": text,
        "metadata": {"kind": "verified", "registry": "crossref"},
        "admission": dict(verdict.admission),
        "proposer": proposer,
    }
    claims = [
        claim_line(s, title, proposer, None)
        for s in claim_sentences(kept, settings["claims"])
        if not overlaps(s)
    ]
    return [source], claims, {"paragraphs_left_out": left, "claims": len(claims)}
