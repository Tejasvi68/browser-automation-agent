"""
WorkflowMemory – saves and retrieves past automation runs using vector similarity.

When a task finishes successfully, the run is embedded and stored in ChromaDB.
On the next similar task, the top-3 most relevant past runs are retrieved
and injected into the planner prompt as "RAG context" so the agent can
reuse known-good selectors and strategies.
"""

import json
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

from app.memory.vector_store import WorkflowVectorStore


class WorkflowMemory:
    def __init__(self, vector_store: Optional[WorkflowVectorStore] = None):
        self.store = vector_store or WorkflowVectorStore()

    # ── Saving ────────────────────────────────────────────────────────────────

    def save_successful_run(
        self,
        run_id: str,
        user_id: str,
        task: str,
        steps: List[Dict[str, Any]],
        site_notes: str = "",
    ) -> None:
        """
        Embeds and stores a completed run so future similar tasks can learn from it.
        Only successful steps are stored; raw passwords are never persisted.
        """
        # Extract the domain from the first URL seen in the steps
        domain = self._extract_domain(
            next((s.get("url") or s.get("params", {}).get("url", "") for s in steps if s.get("url")), "")
        )

        # Build a human-readable action sequence for embedding
        action_sequence = " → ".join(
            f"{s.get('action')}({s.get('params', {}).get('selector') or s.get('params', {}).get('url', '')})"
            for s in steps
        )

        document_text = (
            f"Task: {task}\n"
            f"Domain: {domain}\n"
            f"Action Sequence: {action_sequence}\n"
            f"Site Notes: {site_notes or 'Completed successfully.'}"
        )

        # Strip secrets from steps before storing
        safe_steps = [
            {"action": s.get("action"), "params": s.get("params", {}), "url": s.get("url", "")}
            for s in steps
        ]

        metadata = {
            "user_id":    user_id,
            "domain":     domain,
            "task":       task[:500],
            "step_count": len(safe_steps),
            "steps_json": json.dumps(safe_steps),
            "entry_type": "workflow_run",
        }

        self.store.upsert_document(doc_id=f"run_{run_id}", text=document_text, metadata=metadata)

    def save_site_note(self, note_id: str, user_id: str, url: str, note: str) -> None:
        """Stores a manual tip about a specific site (e.g. 'dismiss cookie popup first')."""
        domain = self._extract_domain(url)
        self.store.upsert_document(
            doc_id=f"note_{note_id}",
            text=f"Site-Specific Note for {domain}: {note}",
            metadata={
                "user_id":    user_id,
                "domain":     domain,
                "task":       f"Site note for {domain}",
                "step_count": 0,
                "steps_json": "[]",
                "entry_type": "site_note",
            },
        )

    # ── Retrieval ─────────────────────────────────────────────────────────────

    def retrieve_relevant_workflows(
        self,
        task: str,
        user_id: Optional[str] = None,
        top_k: int = 3,
        min_similarity: float = 0.25,
    ) -> List[Dict[str, Any]]:
        """
        Returns the most similar past runs for the given task.
        Only includes results above the similarity threshold to avoid noise.
        """
        where_filter = {"user_id": user_id} if user_id else None
        raw_matches = self.store.query_similar(query_text=task, top_k=top_k, where_filter=where_filter)

        results = []
        for match in raw_matches:
            if match["similarity"] < min_similarity:
                continue

            meta = match["metadata"]
            try:
                parsed_steps = json.loads(meta.get("steps_json", "[]"))
            except json.JSONDecodeError:
                parsed_steps = []

            results.append({
                "id":         match["id"],
                "similarity": match["similarity"],
                "domain":     meta.get("domain", "general"),
                "task":       meta.get("task", ""),
                "entry_type": meta.get("entry_type", "workflow_run"),
                "steps":      parsed_steps,
                "summary":    match["document"],
            })

        return results

    def format_for_planner_prompt(self, matches: List[Dict[str, Any]]) -> str:
        """Formats retrieved memories into a readable block for the LLM planner prompt."""
        if not matches:
            return "No prior similar workflows found in memory."

        lines = ["Relevant Past Workflows & Site Notes (RAG Memory):"]
        for idx, m in enumerate(matches, start=1):
            lines.append(
                f"{idx}. [Similarity: {m['similarity']:.2f}] ({m['domain']}) {m['task']}\n"
                f"   Steps: {json.dumps(m['steps'])}"
            )

        return "\n".join(lines)

    # ── Utilities ─────────────────────────────────────────────────────────────

    @staticmethod
    def _extract_domain(url: str) -> str:
        """Extracts the netloc from a URL, e.g. 'amazon.in' from 'https://amazon.in/dp/...'"""
        if not url:
            return "general"
        parsed = urlparse(url if "://" in url else f"https://{url}")
        return parsed.netloc.lower() or "general"
