from laris.client.application.workspace import Chunk
from laris.client.vault.hooks import record_ingest
from laris.shared.harness.runtime import HarnessRuntime
from laris.shared.vault.entities import document_text, stable_id
from laris.shared.vault.index import VaultIndex
from laris.shared.vault.schema import lint_schema

DOC1 = (
    "We propose a novel perovskite design. We trained a Transformer with AdamW on the SQuAD "
    "dataset. We show that annealing improves crystallinity. The cell achieves an accuracy of "
    "0.91. A limitation of this study is that stability was only tested for 100 hours."
)
DOC2 = (
    "Our baseline is a Transformer evaluated on SQuAD as well. "
    "Our results indicate that longer training helps."
)


def chunks_of(doc_id, source, text, size=90):
    out, pos, n = [], 0, 0
    while pos < len(text):
        end = min(len(text), pos + size)
        out.append(Chunk(f"{doc_id}-{n}", doc_id, source, source, text[pos:end], pos, end))
        pos, n = end, n + 1
    return out


def test_document_text_rebuilds_offsets_with_gaps_and_overlap():
    a = Chunk("1", "d", "s", "s", "hello world", 0, 11)
    b = Chunk("2", "d", "s", "s", "world again", 6, 17)  # overlaps a
    c = Chunk("3", "d", "s", "s", "tail", 20, 24)  # gap
    assert document_text([c, b, a]) == "hello world again   tail"


def test_entity_notes_have_spans_that_match_source_text_and_lint_clean(project):
    runtime = HarnessRuntime.load(project)
    out = record_ingest(runtime, chunks_of("d1", "docs/one.txt", DOC1))
    assert out.get("vault_entities", 0) >= 3
    index = VaultIndex.build(project / "vault")
    text = document_text(chunks_of("d1", "docs/one.txt", DOC1))
    statements = [n for n in index.notes.values() if n.props.get("type") in {"claim", "limitation"}]
    assert statements
    for note in statements:
        start, end = int(note.props["char_start"]), int(note.props["char_end"])
        assert text[start:end].strip()
        quote = note.body.split("> ", 1)[1].split("\n")[0].rstrip("…")
        assert " ".join(text[start:end].split()).startswith(quote.strip()[:40])
        assert note.props["source_ref"] == "[[one (source)]]"
        assert index.find("one (source)") is not None
    assert lint_schema(index) == []
    kinds = {n.props.get("type") for n in index.notes.values()}
    assert {"method", "dataset"} & kinds


def test_same_entity_in_two_documents_merges_by_stable_id(project):
    runtime = HarnessRuntime.load(project)
    record_ingest(runtime, chunks_of("d1", "docs/one.txt", DOC1))
    record_ingest(runtime, chunks_of("d2", "docs/two.txt", DOC2))
    index = VaultIndex.build(project / "vault")
    methods = [n for n in index.notes.values() if n.props.get("type") == "method"]
    ids = [n.props["entity_id"] for n in methods]
    assert len(ids) == len(set(ids))  # one note per entity
    shared = [n for n in methods if "[[one (source)]]" in n.body and "[[two (source)]]" in n.body]
    assert shared and shared[0].props["entity_id"] == stable_id(
        "method", shared[0].title.split(" (")[0]
    )
    record_ingest(runtime, chunks_of("d2", "docs/two.txt", DOC2))  # re-ingest adds nothing new
    again = VaultIndex.build(project / "vault")
    assert sorted(again.notes) == sorted(index.notes)
