"""T285: a journal paper is admitted only when its DOI resolves at Crossref, no retraction is
recorded, its venue is on the list, and both Crossref and its full text carry an accepted licence;
each refusal is named. Responses are written for the test (no network, no real paper)."""

import json
from pathlib import Path

import pytest

from laris.research.knowledge import build, papers

ROOT = Path(__file__).resolve().parents[3]
CONFIG = json.loads((ROOT / "configs" / "admissible-sources.json").read_text(encoding="utf-8"))
SETTINGS, CLASSES = CONFIG["papers"], CONFIG["classes"]
DOI = "10.1038/s41467-000-00000-x"


def crossref(**over) -> bytes:
    message = {
        "DOI": DOI.upper(),
        "title": ["Ribosomes in   living cells"],
        "ISSN": ["2041-1723"],
        "license": [
            {"URL": "http://creativecommons.org/licenses/by/4.0/", "content-version": "vor"}
        ],
    }
    message.update(over)
    return json.dumps({"status": "ok", "message": message}).encode()


def jats(doi: str = DOI, licence: str = "https://creativecommons.org/licenses/by/4.0/") -> bytes:
    return f"""<article xmlns:xlink="http://www.w3.org/1999/xlink"><front><article-meta>
<article-id pub-id-type="doi">{doi}</article-id>
<title-group><article-title>Ribosomes in living cells</article-title></title-group>
<permissions><license xlink:href="{licence}"><license-p>Open.</license-p></license>
</permissions>
<abstract><p>Ribosomes translate messenger RNA into protein in every living cell. Here we review
how they work. Each ribosome is built from two subunits made of RNA and protein.</p></abstract>
</article-meta></front><body><p>Body text.</p></body></article>""".encode()


def verdict(raw, full=jats()):
    v = papers.check_crossref(DOI, raw, SETTINGS, CLASSES)
    parsed = papers.parse_jats(full) if full is not None else None
    papers.check_full_text(v, parsed, SETTINGS, CLASSES)
    return v


def test_an_admissible_paper_carries_its_record():
    raw = crossref()
    v = verdict(raw)
    assert v.admitted, v
    assert v.admission == {
        "class": "journal_paper",
        "resolved_by": "crossref",
        "resolution_sha256": build.sha256(raw),
        "licence": "cc-by-4.0",
        "venue": "2041-1723",
        "retraction_check": "crossref:none",
    }


@pytest.mark.parametrize(
    "raw, full, reason",
    [
        (None, jats(), "unresolved"),
        (b"not json", jats(), "unresolved"),
        (crossref(DOI="10.1/other"), jats(), "unresolved"),
        (
            crossref(**{"updated-by": [{"type": "retraction", "DOI": "10.1/notice"}]}),
            jats(),
            "retracted",
        ),
        (crossref(relation={"is-retracted-by": [{"id": "10.1/n"}]}), jats(), "retracted"),
        (crossref(ISSN=["1234-5678"]), jats(), "venue"),
        (
            crossref(license=[{"URL": "https://creativecommons.org/licenses/by-nc/4.0/"}]),
            jats(),
            "licence",
        ),
        (crossref(), jats(licence="https://creativecommons.org/licenses/by-nc-nd/4.0/"), "licence"),
        (
            crossref(license=[]),
            jats(licence="https://creativecommons.org/licenses/by-nc/4.0/"),
            "licence",
        ),
        (crossref(), jats(doi="10.1/elsewhere"), "unresolved"),
        (crossref(), None, "no-full-text"),
    ],
)
def test_each_refusal_is_named(raw, full, reason):
    v = verdict(raw, full)
    assert not v.admitted
    assert v.reason == reason, v


def test_claims_are_statements_not_framing():
    parsed = papers.parse_jats(jats())
    found = papers.claim_sentences(parsed.abstract, SETTINGS["claims"])
    assert found == [
        "Ribosomes translate messenger RNA into protein in every living cell.",
        "Each ribosome is built from two subunits made of RNA and protein.",
    ]


def test_paper_lines_quote_the_source_text_and_leave_out_overlaps():
    v = verdict(crossref())
    parsed = papers.parse_jats(jats())
    sources, claims, counts = papers.paper_lines(v, parsed, "PMC1", "ab" * 32, SETTINGS, "tool:t")
    (source,) = sources
    assert source["admission"]["licence"] == "cc-by-4.0"
    assert source["identifier"] == f"https://doi.org/{DOI}"
    for claim in claims:
        assert claim["quote"] in source["text"]
        assert claim["source"] == source["title"]
    assert counts["claims"] == 2
    _, none, left = papers.paper_lines(
        v, parsed, "PMC1", "ab" * 32, SETTINGS, "tool:t", overlaps=lambda t: "Ribosomes" in t
    )
    assert none == [] and left["paragraphs_left_out"] == 1


def test_licence_urls_are_read_by_stem():
    table = SETTINGS["licence_urls"]
    assert (
        papers.licence_id("https://creativecommons.org/licenses/by/4.0/legalcode", table)
        == "cc-by-4.0"
    )
    assert (
        papers.licence_id("http://creativecommons.org/publicdomain/zero/1.0/", table) == "cc0-1.0"
    )
    assert papers.licence_id("https://creativecommons.org/licenses/by-nc/4.0/", table) is None
    assert papers.normalise_doi("https://doi.org/10.7554/ELIFE.1") == "10.7554/elife.1"


def test_reference_tables_and_textbooks_get_their_records(tmp_path):
    from laris.model.solver.elements import PACKAGED
    from laris.model.solver.settings import CIAAW_2024_SHA256

    sources, claims, counts = build.ciaaw_lines(PACKAGED, CIAAW_2024_SHA256, "tool:t")
    assert sources[0]["admission"]["class"] == "reference_table"
    assert sources[0]["admission"]["licence"] in CLASSES["reference_table"]["licences"]
    assert counts["atomic_weights"] == len(claims) > 80
    assert all(c["quote"] in sources[0]["text"] for c in claims)
    assert "hydrogen (H, atomic number 1) is 1.0080" in sources[0]["text"]
    with pytest.raises(ValueError):
        build.ciaaw_lines(PACKAGED, "0" * 64, "tool:t")
    assert build.textbook_licence("http://creativecommons.org/licenses/by/4.0/") == "cc-by-4.0"
    with pytest.raises(ValueError):
        build.textbook_licence("http://creativecommons.org/licenses/by-nc-sa/4.0/")


def test_without_a_crossref_licence_the_full_text_decides():
    v = verdict(crossref(license=[]))
    assert v.admitted and v.admission["licence"] == "cc-by-4.0" and not v.crossref_licence


def test_a_licence_link_inside_the_licence_text_is_read():
    raw = jats().replace(
        b'<license xlink:href="https://creativecommons.org/licenses/by/4.0/">',
        b'<license><license-p>See <ext-link xlink:href="http://creativecommons.org/licenses/by/4.0/">'
        b"the licence</ext-link>.</license-p>",
    )
    assert papers.parse_jats(raw).licence_url == "http://creativecommons.org/licenses/by/4.0/"
