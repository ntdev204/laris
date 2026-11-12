import json
from pathlib import Path

from laris.shared.scholarly.biblio import extract, find_arxiv, find_doi, from_metadata

FIX = Path(__file__).resolve().parents[2] / "fixtures" / "scholarly" / "biblio.json"
CASES = json.loads(FIX.read_text(encoding="utf-8"))
FIELDS = ("title", "authors", "year", "doi", "arxiv")


def got(case):
    bib = extract(case["text"], case["meta"] or None)
    return {
        "title": bib.title,
        "authors": bib.authors,
        "year": bib.year,
        "doi": bib.doi,
        "arxiv": bib.arxiv,
    }


def test_fixture_accuracy_and_nothing_is_guessed():
    correct = wrong = missing = total = 0
    for case in CASES:
        found = got(case)
        for name in FIELDS:
            want, have = case["gold"][name], found[name]
            total += 1
            if have == want:
                correct += 1
            elif have in ("", [], None):
                missing += 1  # a value that was not read: allowed, never guessed
            else:
                wrong += 1
    print(f"fixture: {total} fields, correct {correct}, missing {missing}, wrong {wrong}")
    assert wrong == 0
    assert correct / total >= 0.95  # reported figure; the fixture is small and synthetic


def test_missing_values_stay_empty():
    bib = extract("we found nothing in 1999 and 2004.\n")
    assert bib.properties() == {} and bib.filled() == 0


def test_patterns():
    assert find_doi("see https://doi.org/10.1234/ABC.def-5). next") == "10.1234/abc.def-5"
    assert find_arxiv("arXiv:2101.00001v3") == "2101.00001"
    assert find_arxiv("arXiv:hep-th/9711200") == "hep-th/9711200"
    assert from_metadata({"/CreationDate": "D:19991231"}).year == 1999


def test_properties_use_note_safe_names():
    props = extract(CASES[0]["text"]).properties()
    assert set(props) <= {"bib_title", "authors", "year", "doi", "arxiv"}
    assert props["year"] == 2021 and props["authors"] == ["Ada Lovelace", "Alan Turing"]
