"""D05-a human-gold workflow: pooling, blind sheets, agreement and reconciliation (no models)."""

import json

import pytest

from laris.evaluation import human_gold as H


def test_kappa_known_values():
    assert H.cohen_kappa([0, 1, 2, 2], [0, 1, 2, 2]) == 1.0
    # Hand-computed: p_o = 0.5, p_e = 0.5 -> nominal kappa 0 for [0,0,1,1] vs [0,1,0,1].
    assert H.cohen_kappa([0, 0, 1, 1], [0, 1, 0, 1], labels=(0, 1)) == pytest.approx(0.0)
    # Quadratic weighting penalises a 0-vs-2 miss more than a 0-vs-1 miss.
    near = H.cohen_kappa([0, 1, 2, 2, 0], [0, 2, 2, 2, 0], weights="quadratic")
    far = H.cohen_kappa([0, 1, 2, 2, 0], [2, 1, 2, 2, 0], weights="quadratic")
    assert near > far


def test_kappa_rejects_bad_input():
    with pytest.raises(H.GoldError):
        H.cohen_kappa([0, 1], [0])
    with pytest.raises(H.GoldError):
        H.cohen_kappa([0, 3], [0, 1])


def test_pool_is_union_seeded_and_hides_systems():
    rankings = {
        "bm25": {"q1": ["d1", "d2", "d3"]},
        "dense": {"q1": ["d2", "d4", "d5"]},
    }
    pool = H.build_pool(rankings, top_k=2, seed=7)
    assert sorted(pool["q1"]) == ["d1", "d2", "d4"]
    assert pool == H.build_pool(rankings, top_k=2, seed=7)


def test_blind_sheet_has_no_labels_or_system_hints(tmp_path):
    items = H.build_items({"q1": ["d1"]}, {"q1": "why?"}, {"d1": "because"})
    sheet = tmp_path / "a1.jsonl"
    H.write_blind_sheet(items, sheet)
    row = json.loads(sheet.read_text(encoding="utf-8"))
    assert set(row) == {"item_id", "query", "passage", "label"}
    assert row["label"] is None


def test_read_labels_validates(tmp_path):
    path = tmp_path / "labels.jsonl"
    path.write_text('{"item_id": "x", "label": 2}\n{"item_id": "y", "label": 0}\n')
    assert H.read_labels(path, ["x", "y"]) == {"x": 2, "y": 0}
    with pytest.raises(H.GoldError):
        H.read_labels(path, ["x", "y", "z"])
    path.write_text('{"item_id": "x", "label": null}\n')
    with pytest.raises(H.GoldError):
        H.read_labels(path, ["x"])
    path.write_text('{"item_id": "x", "label": true}\n')
    with pytest.raises(H.GoldError):
        H.read_labels(path, ["x"])


def _labels(n_agree, flips):
    ids = [f"i{k}" for k in range(n_agree)]
    a = {i: k % 3 for k, i in enumerate(ids)}
    b = dict(a)
    for i in ids[:flips]:
        b[i] = (a[i] + 1) % 3
    return a, b


def test_reconcile_accepts_only_with_kappa_and_full_adjudication():
    a, b = _labels(200, 2)
    report = H.reconcile(a, b)
    assert report["status"] == "needs_adjudication"
    assert report["gold"] == {}
    adjudication = {i: a[i] for i in report["unadjudicated"]}
    done = H.reconcile(a, b, adjudication)
    assert done["status"] == "accepted"
    assert len(done["gold"]) == 200


def test_reconcile_returns_low_agreement_batch_instead_of_adjudicating_it():
    a, b = _labels(60, 30)
    adjudication = {i: a[i] for i in a if a[i] != b[i]}
    report = H.reconcile(a, b, adjudication)
    assert report["weighted_kappa_quadratic"] < H.DEFAULT_KAPPA_THRESHOLD
    assert report["status"] == "returned_for_guideline_revision"
    assert report["gold"] == {}


def test_unresolved_conflicts_are_excluded_and_bad_adjudication_rejected():
    a, b = _labels(200, 1)
    key = next(i for i in a if a[i] != b[i])
    report = H.reconcile(a, b, {key: H.UNRESOLVED})
    assert report["status"] == "accepted"
    assert key not in report["gold"] and report["unresolved"] == [key]
    with pytest.raises(H.GoldError):
        H.reconcile(a, b, {"i199": 1} if a["i199"] == b["i199"] else {key: 9})


def test_seal_digest_depends_on_guideline_and_labels():
    base = H.seal_digest({"a": 1}, "g1")
    assert base == H.seal_digest({"a": 1}, "g1")
    assert base != H.seal_digest({"a": 2}, "g1")
    assert base != H.seal_digest({"a": 1}, "g2")
