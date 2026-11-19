"""TF-IDF (T186): hand-computed values, options, neighbours, and `group_documents` parity."""

import json
import math

import pytest

from laris.shared.scholarly.biblio import Bibliography
from laris.shared.scholarly.mining import Doc, group_documents, tokens
from laris.shared.text.tfidf import (
    TfidfModel,
    cosine,
    idf,
    nearest,
    term_frequencies,
    top_terms,
)

DOCS = [["a", "a", "b"], ["b", "c"], ["a", "c", "c", "c"]]  # n = 3; df: a 2, b 2, c 2


def test_term_frequencies_keep_first_seen_order():
    assert list(term_frequencies(["x", "y", "x"]).items()) == [("x", 2), ("y", 1)]


def test_smoothed_idf_matches_hand_value():
    assert idf(3, 1) == pytest.approx(math.log(4 / 2))
    assert idf(3, 0) == pytest.approx(math.log(4))
    assert idf(3, 1, offset=1.0) == pytest.approx(math.log(2) + 1.0)


def test_vector_matches_hand_computed_weights():
    model = TfidfModel.from_documents(
        [["a", "a", "b"], ["b", "c"], ["c", "d"], ["d", "e"]], idf_offset=0.0
    )  # n = 4: df a 1, b 2, c 2, d 2, e 1
    vec = model.transform(["a", "a", "b"])
    ia, ib = math.log(5 / 2), math.log(5 / 3)
    raw = {"a": 2 * ia, "b": 1 * ib}
    norm = math.sqrt(raw["a"] ** 2 + raw["b"] ** 2)
    assert vec["a"] == pytest.approx(raw["a"] / norm)
    assert vec["b"] == pytest.approx(raw["b"] / norm)
    assert math.sqrt(sum(v * v for v in vec.values())) == pytest.approx(1.0)


def test_sublinear_tf_uses_one_plus_log():
    model = TfidfModel.from_documents(DOCS, sublinear_tf=True, idf_offset=1.0)
    vec = model.transform(["a", "a", "a", "a", "b"])
    i = math.log(4 / 3) + 1.0
    raw = {"a": (1 + math.log(4)) * i, "b": 1.0 * i}
    norm = math.hypot(*raw.values())
    assert vec["a"] == pytest.approx(raw["a"] / norm)
    assert vec["b"] == pytest.approx(raw["b"] / norm)


def test_zero_idf_terms_are_dropped_without_offset_and_kept_with_it():
    docs = [["x", "p"], ["x", "q"]]  # x is in every document
    assert "x" not in TfidfModel.from_documents(docs).transform(["x", "p"])
    assert "x" in TfidfModel.from_documents(docs, idf_offset=1.0).transform(["x", "p"])


def test_unseen_terms_and_empty_input():
    model = TfidfModel.from_documents(DOCS)
    assert model.transform([]) == {}
    assert "zzz" in model.transform(["zzz"])  # df 0 gives the largest idf
    assert TfidfModel.from_documents([]).transform(["a"]) == {}  # n = 0: ln(1) = 0


def test_cosine_top_terms_and_nearest_are_deterministic():
    model = TfidfModel.from_documents(DOCS, idf_offset=1.0)
    vectors = {f"d{i}": model.transform(d) for i, d in enumerate(DOCS)}
    assert cosine(vectors["d0"], vectors["d0"]) == pytest.approx(1.0)
    assert cosine(vectors["d0"], {}) == 0.0
    assert [t for t, _ in top_terms(vectors["d2"], 1)] == ["c"]
    hits = nearest(vectors["d0"], vectors, k=2, exclude="d0")
    assert [i for i, _ in hits] == sorted([i for i, _ in hits], key=lambda i: -dict(hits)[i])
    assert "d0" not in dict(hits)
    assert hits == nearest(vectors["d0"], vectors, k=2, exclude="d0")
    assert nearest(vectors["d0"], vectors, k=0) == []


def _reference_group_documents(docs, threshold=0.25, label_terms=3):
    """The pre-T186 algorithm, frozen here so the refactor is proved byte-identical."""
    counts = {}
    for d in docs:
        tf = {}
        for t in tokens(d.text):
            tf[t] = tf.get(t, 0) + 1
        counts[d.doc_id] = tf
    n = len(docs)
    df = {}
    for tf in counts.values():
        for t in tf:
            df[t] = df.get(t, 0) + 1
    vec = {}
    for doc_id, tf in counts.items():
        raw = {t: c * math.log((1 + n) / (1 + df[t])) + 0.0 for t, c in tf.items()}
        norm = math.sqrt(sum(v * v for v in raw.values())) or 1.0
        vec[doc_id] = {t: v / norm for t, v in raw.items() if v > 0}
    parent = {d.doc_id: d.doc_id for d in docs}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    ids = sorted(parent)
    for i, a in enumerate(ids):
        for b in ids[i + 1 :]:
            small, large = sorted((vec[a], vec[b]), key=len)
            if sum(v * large.get(t, 0.0) for t, v in small.items()) >= threshold:
                ra, rb = find(a), find(b)
                if ra != rb:
                    parent[max(ra, rb)] = min(ra, rb)
    groups = {}
    for doc_id in ids:
        groups.setdefault(find(doc_id), []).append(doc_id)
    out = []
    for members in sorted(groups.values(), key=lambda g: (-len(g), g[0])):
        weights = {}
        for m in members:
            for t, w in vec[m].items():
                weights[t] = weights.get(t, 0.0) + w
        label = [t for t, _ in sorted(weights.items(), key=lambda x: (-x[1], x[0]))[:label_terms]]
        out.append({"documents": members, "label_terms": label})
    return {
        "scope": {"documents": n, "documents_left_out": 0, "threshold": threshold},
        "groups": out,
    }


@pytest.mark.parametrize("threshold", [0.05, 0.25, 0.35, 0.7])
def test_group_documents_is_identical_to_the_pre_refactor_algorithm(threshold):
    words = (
        "solar cell perovskite lithium anode cathode transformer attention token decoder".split()
    )
    docs = [
        Doc(
            f"d{i}",
            f"d{i}.txt",
            " ".join(words[(i + j * 3) % 10] for j in range(40)),
            Bibliography(),
        )
        for i in range(9)
    ]
    docs.append(Doc("empty", "e.txt", "", Bibliography()))
    assert json.dumps(group_documents(docs, threshold=threshold)) == json.dumps(
        _reference_group_documents(docs, threshold=threshold)
    )
