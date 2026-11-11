import json
from pathlib import Path

from scholarly.biblio import extract
from scholarly.citations import (
    analyse,
    in_text_citations,
    link_in_text,
    parse_reference,
    resolve,
    split_references,
    summary,
)
from scholarly.mining import Doc

FIXTURE = json.loads(
    (Path(__file__).resolve().parents[2] / "fixtures" / "scholarly" / "citations.json").read_text(
        encoding="utf-8"
    )
)
D1, D2, D3, D4 = (FIXTURE["documents"][k] for k in ("D1", "D2", "D3", "D4"))
T_CURIE = "Efficient Perovskite Solar Cells with Passivated Interfaces"
T_HOPPER = "Interface Passivation by Alkylammonium Salts in Solar Devices"


def docs():
    out = []
    for doc_id, text in (("D1", D1), ("D2", D2), ("D3", D3), ("D4", D4)):
        out.append(Doc(doc_id, f"{doc_id}.txt", text, extract(text[:3000])))
    return out


def test_reference_lists_numbered_and_unnumbered_are_split():
    body, entries = split_references(D1)
    assert "References" not in body and len(entries) == 3 and entries[1].startswith("[2]")
    _, plain = split_references(D4)
    assert len(plain) == 3 and plain[0].startswith("Curie, M.")
    assert split_references("no list here") == ("no list here", [])


def test_reference_fields():
    ref = parse_reference(f"[1] M. Curie and N. Bohr. {T_CURIE}. J. Photov., 2019. doi:10.1000/x.1")
    assert (ref.label, ref.doi, ref.year, ref.surname) == ("1", "10.1000/x.1", 2019, "Curie")
    ap = parse_reference("Hopper, G. (2020). Something. Letters.")
    assert (ap.label, ap.year, ap.surname) == ("", 2020, "Hopper")


def test_in_text_citations_numeric_ranges_and_author_year():
    numeric = in_text_citations("As shown [1,3-4] and [7].")
    assert [c.key for c in numeric] == ["1", "3", "4", "7"]
    ay = {
        c.key for c in in_text_citations("Curie and Bohr (2019) and (Hopper, 2020; Turing, 1950).")
    }
    assert ay == {"curie|2019", "hopper|2020", "turing|1950"}


def test_known_reference_lists_reproduce_the_expected_edges():
    report = analyse(docs())
    assert report.edges == [
        ("D1", "D2"), ("D1", "D3"), ("D3", "D2"), ("D4", "D2"), ("D4", "D3"),
    ]  # fmt: skip
    assert report.in_degree() == {"D1": 0, "D2": 3, "D3": 2, "D4": 0}
    assert report.out_degree() == {"D1": 2, "D2": 0, "D3": 1, "D4": 2}
    assert report.cocitation() == {"D2|D3": 2}
    coupling = report.coupling()
    assert coupling["D1|D4"] >= 3 and coupling["D1|D3"] >= 2  # D2, D3/Turing shared
    rank = report.centrality()
    assert rank["D2"] == max(rank.values()) and abs(sum(rank.values()) - 1.0) < 1e-6
    assert rank == report.centrality()


def test_unresolved_and_broken_citations_are_listed_not_guessed():
    report = analyse(docs())
    raw = {u["reference"][:20] for u in report.unresolved()}
    assert any("Turing" in r for r in raw) and all(
        u["status"] != "resolved" for u in report.unresolved()
    )
    assert [c.key for c, _ in report.broken["D1"]] == ["5"]
    assert report.scope["references"] == 8 and report.scope["resolved"] == 5
    assert summary(report, "edges")["scope"]["documents"] == 4


def test_weak_and_ambiguous_matches_never_become_edges():
    corpus = docs()
    weak = resolve(
        parse_reference("Hopper, G. (2020). A different title entirely. Elsewhere."), corpus
    )
    assert weak.status == "weak" and weak.doc_ids == ["D3"]
    twin = Doc("D2b", "x.txt", D2, extract(D2[:3000]))
    ambiguous = resolve(parse_reference("x 10.1000/jap.2019.0042"), [*corpus, twin])
    assert ambiguous.status == "ambiguous" and ambiguous.doc_ids == ["D2", "D2b"]
    nothing = resolve(parse_reference("Nobody, N. (1800). Nothing at all here. Void."), corpus)
    assert nothing.status == "unresolved"
    refs = [parse_reference("[1] one"), parse_reference("[1] two")]
    _, bad = link_in_text(in_text_citations("see [1]"), refs)
    assert bad and bad[0][1] == "several entries match"
