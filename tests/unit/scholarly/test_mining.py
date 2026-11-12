from laris.shared.scholarly.biblio import Bibliography
from laris.shared.scholarly.mining import (
    Doc,
    exact_duplicates,
    group_documents,
    near_duplicates,
    overview,
    term_trends,
    to_markdown,
)

TOPICS = {
    "solar": "perovskite solar cell efficiency passivation interface stability moisture annealing",
    "battery": "lithium electrolyte anode cathode interphase charging capacity cycling degradation",
    "language": "transformer attention tokens embedding pretraining corpus decoder finetuning",
}


def body(topic: str, n: int) -> str:
    words = TOPICS[topic].split()
    return " ".join(
        f"{words[(i * 3 + n) % len(words)]} {words[(i + n) % len(words)]}" for i in range(80)
    )


def docs():
    out = []
    spec = [
        ("s1", "solar", 0, 2018), ("s2", "solar", 1, 2019), ("s3", "solar", 2, 2020),
        ("b1", "battery", 0, 2019), ("b2", "battery", 1, 2020), ("l1", "language", 0, 2020),
        ("l2", "language", 1, 2021), ("nodate", "language", 2, None),
    ]  # fmt: skip
    for doc_id, topic, n, year in spec:
        out.append(Doc(doc_id, f"{doc_id}.txt", body(topic, n), Bibliography(year=year)))
    long = " ".join(
        chr(97 + i % 26) + chr(97 + (i // 26) % 26) + chr(97 + (i // 676) % 26) + "ab"
        for i in range(400)
    )  # a long document with distinct shingles
    out.append(Doc("copy-a", "a.txt", long, Bibliography(year=2020)))
    out.append(
        Doc("copy-b", "b.txt", long + " one extra closing sentence here", Bibliography(year=2021))
    )
    return out


def test_overview_names_its_scope():
    result = overview(docs())
    assert result["scope"]["documents"] == 10 and result["scope"]["documents_with_year"] == 9
    assert result["scope"]["year_range"] == [2018, 2021]
    assert result["per_year"]["2020"] == 4 and "without a stated year" in result["note"]


def test_term_trends_count_documents_per_year_and_exclude_undated():
    result = term_trends(docs(), top=5)
    assert result["scope"]["documents_with_year"] == 9 and result["scope"]["documents"] == 10
    assert result["docs_per_year"] == {"2018": 1, "2019": 2, "2020": 4, "2021": 2}
    assert len(result["terms"]) == 5
    assert all(sum(row.values()) >= 2 for row in result["terms"].values())
    assert result == term_trends(docs(), top=5)


def test_near_duplicates_precision_and_recall_against_brute_force():
    corpus = docs()
    found = {(p["a"], p["b"]) for p in near_duplicates(corpus, 0.8)["pairs"]}
    truth = set(exact_duplicates(corpus, 0.8))
    precision = len(found & truth) / len(found) if found else 1.0
    recall = len(found & truth) / len(truth) if truth else 1.0
    print(f"near-duplicates: precision {precision:.2f}, recall {recall:.2f}, pairs {sorted(found)}")
    assert ("copy-a", "copy-b") in found and precision == 1.0 and recall == 1.0
    assert near_duplicates(corpus, 0.8)["scope"]["threshold"] == 0.8


def test_groups_follow_topics_and_have_labels():
    result = group_documents(docs(), threshold=0.35)
    groups = [set(g["documents"]) for g in result["groups"]]
    assert {"s1", "s2", "s3"} <= next(g for g in groups if "s1" in g)
    assert {"b1", "b2"} <= next(g for g in groups if "b1" in g)
    solar = next(g for g in result["groups"] if "s1" in g["documents"])
    assert solar["label_terms"] and set(solar["label_terms"]) <= set(TOPICS["solar"].split())
    assert not ({"s1", "b1"} <= next(g for g in groups if "s1" in g))
    assert result == group_documents(docs(), threshold=0.35)


def test_markdown_starts_with_scope():
    text = to_markdown("overview", overview(docs()))
    assert text.startswith("Scope: documents: 10")
