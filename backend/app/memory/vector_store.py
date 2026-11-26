"""
WorkflowVectorStore – persists workflow embeddings in ChromaDB for RAG retrieval.

ChromaDB automatically handles:
  - Embedding generation (using its default sentence-transformers model)
  - Cosine similarity search
  - Persistent storage to disk (./chroma_db/)
"""

from typing import Any, Dict, List, Optional

import chromadb
from chromadb.config import Settings as ChromaSettings


class WorkflowVectorStore:
    def __init__(self, persist_directory: str = "./chroma_db", in_memory: bool = False):
        # Use an ephemeral in-memory client for tests; persistent disk client for production
        if in_memory:
            self.client = chromadb.EphemeralClient()
        else:
            self.client = chromadb.PersistentClient(
                path=persist_directory,
                settings=ChromaSettings(anonymized_telemetry=False),
            )

        # One collection holds all workflow and site-note documents
        self.collection = self.client.get_or_create_collection(
            name="workflow_memory",
            metadata={"hnsw:space": "cosine"},  # Use cosine similarity
        )

    def upsert_document(self, doc_id: str, text: str, metadata: Dict[str, Any]) -> None:
        """
        Adds or updates a document. If doc_id already exists, it is overwritten.
        ChromaDB embeds the text automatically.
        """
        self.collection.upsert(
            ids=[doc_id],
            documents=[text],
            metadatas=[metadata],
        )

    def query_similar(
        self,
        query_text: str,
        top_k: int = 3,
        where_filter: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        """
        Returns the top_k documents most similar to query_text.
        Each result includes:
          - id:         document identifier
          - document:   the original text
          - metadata:   stored metadata dict
          - similarity: float in [0, 1] (1 = identical, 0 = unrelated)
        """
        total_docs = self.collection.count()
        if total_docs == 0:
            return []

        n_results = min(top_k, total_docs)
        raw = self.collection.query(
            query_texts=[query_text],
            n_results=n_results,
            where=where_filter,
        )

        results = []
        ids       = raw.get("ids",       [[]])[0]
        docs      = raw.get("documents", [[]])[0]
        metas     = raw.get("metadatas", [[]])[0]
        distances = raw.get("distances", [[]])[0]

        for doc_id, doc_text, meta, dist in zip(ids, docs, metas, distances):
            # ChromaDB returns cosine *distance* (0 = identical, 2 = opposite)
            # Convert to similarity score in [0, 1]
            similarity = round(max(0.0, 1.0 - float(dist)), 4)
            results.append({
                "id":         doc_id,
                "document":   doc_text,
                "metadata":   meta or {},
                "similarity": similarity,
            })

        return results

    def delete_document(self, doc_id: str) -> None:
        """Removes a single document by its ID."""
        self.collection.delete(ids=[doc_id])
