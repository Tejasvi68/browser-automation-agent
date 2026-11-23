from typing import Any, Dict, List, Optional
import chromadb
from chromadb.config import Settings as ChromaSettings


class WorkflowVectorStore:
    def __init__(self, persist_directory: str = "./chroma_db", in_memory: bool = False):
        if in_memory:
            self.client = chromadb.EphemeralClient()
        else:
            self.client = chromadb.PersistentClient(
                path=persist_directory,
                settings=ChromaSettings(anonymized_telemetry=False),
            )

        self.collection = self.client.get_or_create_collection(
            name="workflow_memory",
            metadata={"hnsw:space": "cosine"},
        )

    def upsert_document(
        self,
        doc_id: str,
        text: str,
        metadata: Dict[str, Any],
    ) -> None:
        """Embeds and stores (or updates) a workflow or site-note document in ChromaDB."""
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
        """Performs semantic similarity search and returns scored matches."""
        count = self.collection.count()
        if count == 0:
            return []

        n_results = min(top_k, count)
        results = self.collection.query(
            query_texts=[query_text],
            n_results=n_results,
            where=where_filter,
        )

        matches: List[Dict[str, Any]] = []
        ids = results.get("ids", [[]])[0]
        docs = results.get("documents", [[]])[0]
        metas = results.get("metadatas", [[]])[0]
        distances = results.get("distances", [[]])[0]

        for doc_id, doc_text, meta, dist in zip(ids, docs, metas, distances):
            # Convert cosine distance (0 = identical, 2 = opposite) into a 0..1 similarity score
            similarity = round(max(0.0, 1.0 - float(dist)), 4)
            matches.append(
                {
                    "id": doc_id,
                    "document": doc_text,
                    "metadata": meta or {},
                    "similarity": similarity,
                }
            )

        return matches

    def delete_document(self, doc_id: str) -> None:
        self.collection.delete(ids=[doc_id])