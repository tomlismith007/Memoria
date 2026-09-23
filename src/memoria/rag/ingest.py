"""Ingest pipeline: parse -> chunk -> embed -> store. One doc in, vectors out."""

from __future__ import annotations

from dataclasses import dataclass

from memoria.rag.chunk import chunk_text
from memoria.rag.embed import Embedder
from memoria.rag.parse import load_document
from memoria.rag.store import ChromaStore


@dataclass
class IngestResult:
    doc_id: str
    chunks: int
    text: str = ""  # source text, reused by dual-write (single parse)


def ingest_document(
    source: str,
    store: ChromaStore,
    embedder: Embedder,
    chunk_size: int = 800,
    chunk_overlap: int = 100,
) -> IngestResult:
    doc = load_document(source)
    chunks = chunk_text(doc.text, size=chunk_size, overlap=chunk_overlap)
    vectors = embedder.embed([c.text for c in chunks]) if chunks else []
    store.upsert(doc.doc_id, chunks, vectors)
    return IngestResult(doc_id=doc.doc_id, chunks=len(chunks), text=doc.text)


def delete_document(doc_id: str, store: ChromaStore) -> None:
    """Red line: doc deletion removes every one of its vectors."""
    store.delete_document(doc_id)
