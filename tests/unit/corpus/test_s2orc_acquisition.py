"""Offline tests for the S2ORC filter and shard selection (no network, no training)."""

from laris.research.corpus.acquisition.sources.s2orc import STAGES, filter_record, select_shards

TEXT = "x" * 2500


def _old(license_code, ids):
    return {
        "corpusid": 1,
        "externalids": ids,
        "content": {
            "source": {"oainfo": {"license": license_code}},
            "text": TEXT,
            "annotations": {"paragraph": "[]", "author": "[]"},
        },
    }


def _new(license_code, ids):
    return {
        "corpusid": 2,
        "title": "T",
        "openaccessinfo": {"license": license_code, "externalids": ids},
        "body": {"text": TEXT, "annotations": {"section_header": "[]", "sentence": "[]"}},
    }


def test_both_schemas_are_kept_with_open_license() -> None:
    old = filter_record(_old("CCBY", {"arxiv": "1", "doi": "d"}))
    new = filter_record(_new("CCBYNCSA", {"ArXiv": "2", "DOI": None}))
    assert old is not None and old["source"] == "arxiv" and "paragraph" in old["structure"]
    assert new is not None and new["title"] == "T" and "sectionheader" in new["structure"]
    assert "sentence" not in new["structure"]


def test_drops_are_counted_by_reason() -> None:
    drops: dict = {}
    assert filter_record(_old("CCBY", {"mag": "1"}), drops=drops) is None
    assert filter_record(_new(None, {"ArXiv": "2"}), drops=drops) is None
    assert filter_record(_new("CCBYNCND", {"ArXiv": "2"}), drops=drops) is None
    assert drops == {"no_stem_id": 1, "license_missing_or_closed": 2}


def test_stage_shards_are_disjoint_and_deterministic() -> None:
    first = set(select_shards(751, "01"))
    second = set(select_shards(751, "02"))
    assert not first & second
    assert select_shards(751, "02") == select_shards(751, "02")
    assert set(STAGES) == {"01", "02"}
