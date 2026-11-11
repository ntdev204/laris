"""Local application: ingestion, BM25 search and the JSON API (no model, no network)."""

import base64

import pytest

from laris.application.server import handle_api
from laris.application.service import SearchService
from laris.application.workspace import IngestError, Workspace, chunks_from_text, decode_upload


def _service(tmp_path):
    return SearchService(Workspace(tmp_path / "ws"))


def test_chunks_keep_exact_character_spans():
    text = "\n\n".join(f"Paragraph {i} " + "word " * 60 for i in range(5))
    chunks = chunks_from_text("doc.txt", text)
    assert len(chunks) > 1
    cleaned = " ".join(text.split(" "))  # clean_text only normalises runs of blanks
    for chunk in chunks:
        assert chunk.text in cleaned or chunk.text.replace("  ", " ") in cleaned


def test_empty_and_unsupported_input_rejected():
    with pytest.raises(IngestError):
        chunks_from_text("a.txt", "   \n ")
    with pytest.raises(IngestError):
        decode_upload("a.exe", None, base64.b64encode(b"x").decode())


def test_reingesting_replaces_document_and_drops_dense_index(tmp_path):
    ws = Workspace(tmp_path / "ws")
    ws.add(chunks_from_text("a.txt", "alpha beta gamma"))
    (ws.root / "embeddings.npy").write_bytes(b"x")
    counts = ws.add(chunks_from_text("a.txt", "alpha beta gamma delta"))
    assert counts["total"] == 1 and not (ws.root / "embeddings.npy").exists()


def test_bm25_search_vietnamese_and_english(tmp_path):
    service = _service(tmp_path)
    service.workspace.add(chunks_from_text("vi.txt", "Hà Nội là thủ đô của Việt Nam."))
    service.workspace.add(chunks_from_text("en.txt", "Paris is the capital of France."))
    top = service.search("thủ đô Việt Nam")["hits"][0]
    assert top["source"] == "vi.txt"
    assert service.search("capital France")["hits"][0]["source"] == "en.txt"


def test_api_errors_and_modes(tmp_path):
    service = _service(tmp_path)
    assert handle_api(service, "GET", "/api/status", {})[1]["passages"] == 0
    assert handle_api(service, "POST", "/api/search", {"query": "x"})[0] == 400  # no documents
    code, counts = handle_api(
        service, "POST", "/api/ingest", {"name": "n.txt", "text": "solar energy"}
    )
    assert code == 200 and counts["passages"] == 1
    assert handle_api(service, "POST", "/api/search", {"query": ""})[0] == 400
    assert handle_api(service, "POST", "/api/search", {"query": "solar", "mode": "x"})[0] == 400
    assert handle_api(service, "POST", "/api/search", {"query": "solar", "mode": "dense"})[0] == 400
    assert handle_api(service, "POST", "/api/answer", {"query": "solar"})[0] == 400  # no model
    assert handle_api(service, "GET", "/api/nope", {})[0] == 404
