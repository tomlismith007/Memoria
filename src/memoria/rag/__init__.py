"""RAG ingest: parse -> chunk -> embed -> store. Hand-written core (no LCEL)."""

from memoria.rag.answer import Answer, Citation, answer
from memoria.rag.chunk import Chunk, chunk_text
from memoria.rag.embed import Embedder, FakeEmbedder, OpenAICompatibleEmbedder
from memoria.rag.ingest import IngestResult, delete_document, ingest_document
from memoria.rag.parse import Document, load_document
from memoria.rag.retrieve import combined_score, keyword_score, retrieve
from memoria.rag.store import ChromaStore

__all__ = [
    "Answer",
    "Chunk",
    "ChromaStore",
    "Citation",
    "Document",
    "Embedder",
    "FakeEmbedder",
    "IngestResult",
    "OpenAICompatibleEmbedder",
    "answer",
    "chunk_text",
    "combined_score",
    "delete_document",
    "ingest_document",
    "keyword_score",
    "load_document",
    "retrieve",
]
