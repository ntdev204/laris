"""A passage of a document: the unit that ingestion, retrieval and the vault exchange."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Chunk:
    chunk_id: str
    doc_id: str
    source: str
    title: str
    text: str
    start: int  # character span of `text` inside the cleaned document
    end: int
