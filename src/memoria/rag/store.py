"""Chroma-backed vector store. Metadata carries citations: doc_id + chunk offsets."""

from __future__ import annotations

import chromadb

from memoria.rag.chunk import Chunk


class ChromaStore:
    def __init__(self, path: str = "./data/chroma", collection: str = "memoria") -> None:
        self.client = chromadb.PersistentClient(path=path)
        self.collection = self.client.get_or_create_collection(
            collection, metadata={"hnsw:space": "cosine"}
        )

    def upsert(self, doc_id: str, chunks: list[Chunk], vectors: list[list[float]]) -> None:
        # Delete-then-add: re-ingesting the same origin replaces vectors (no orphans on update).
        self.delete_document(doc_id)
        if not chunks:
            return
        self.collection.add(
            ids=[f"{doc_id}:{c.index}" for c in chunks],
            embeddings=vectors,
            documents=[c.text for c in chunks],
            metadatas=[
                {"doc_id": doc_id, "chunk": c.index, "start": c.start, "end": c.end}
                for c in chunks
            ],
        )

    def delete_document(self, doc_id: str) -> None:
        """Red line: deleting a doc deletes ALL of its vectors."""
        self.collection.delete(where={"doc_id": doc_id})

    def documents(self) -> dict[str, int]:
        """doc_id -> chunk count across the whole collection."""
        res = self.collection.get(include=["metadatas"])
        counts: dict[str, int] = {}
        for meta in res.get("metadatas") or []:
            doc = (meta or {}).get("doc_id")
            if doc:
                counts[doc] = counts.get(doc, 0) + 1
        return counts

    def search(self, vector: list[float], k: int = 5) -> list[dict]:
        res = self.collection.query(query_embeddings=[vector], n_results=k)
        hits = []
        for i in range(len(res["ids"][0])):
            hits.append(
                {
                    "text": res["documents"][0][i],
                    "doc_id": res["metadatas"][0][i]["doc_id"],
                    "chunk": res["metadatas"][0][i]["chunk"],
                    "start": res["metadatas"][0][i]["start"],
                    "distance": res["distances"][0][i],
                }
            )
        return hits

    def count(self) -> int:
        return self.collection.count()
