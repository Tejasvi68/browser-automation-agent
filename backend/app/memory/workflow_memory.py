import json
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse
from app.memory.vector_store import WorkflowVectorStore


class WorkflowMemory:
    def __init__(self, vector_store: Optional[WorkflowVectorStore] = None):
        self.store = vector_store or WorkflowVectorStore()

    @staticmethod
    def _extract_domain(url: str) -> str:
        if not url:
            return "general"
        parsed = urlparse(url if "://" in url else f"https://{url}")
        return parsed.netloc.lower() or "general"

    def save_successful_run(
        self,
        run_id: str,
        user_id: str,
        task: str,
        steps: List[Dict[str, Any]],
        site_notes: str = "",
    ) -> None:
        """Indexes a completed automation run (steps + domain + notes) for future RAG retrieval."""
        first_url = ""
        for step in steps:
            url = step.get("url") or step.get("params", {}).get("url", "")
            if url:
                first_url = url
                break

        domain = self._extract_domain(first_url)

        # Build a clean action summary for semantic embedding
        step_summary = " -> ".join(
            f"{s.get('action')}({s.get('params', {}).get('selector') or s.get('params', {}).get('url', '')})"
            for s in steps
        )

        document_text = (
            f"Task: {task}\n"
            f"Domain: {domain}\n"
            f"Action Sequence: {step_summary}\n"
            f"Site Notes: {site_notes or 'Completed successfully.'}"
        )

        # Store only safe, masked step actions (never raw secrets)
        sanitized_steps = [
            {
                "action": s.get("action"),
                "params": s.get("params", {}),
                "url": s.get("url", ""),
            }
            for s in steps
        ]

        metadata = {
            "user_id": user_id,
            "domain": domain,
            "task": task[:500],
            "step_count": len(sanitized_steps),
            "steps_json": json.dumps(sanitized_steps),
            "entry_type": "workflow_run",
        }

        self.store.upsert_document(doc_id=f"run_{run_id}", text=document_text, metadata=metadata)

    def save_site_note(self, note_id: str, user_id: str, url: str, note: str) -> None:
        """Stores a site-specific selector hint or pop-up handling tip for RAG retrieval."""
        domain = self._extract_domain(url)
        document_text = f"Site-Specific Note for {domain}: {note}"
        metadata = {
            "user_id": user_id,
            "domain": domain,
            "task": f"Site note for {domain}",
            "step_count": 0,
            "steps_json": "[]",
            "entry_type": "site_note",
        }
        self.store.upsert_document(doc_id=f"note_{note_id}", text=document_text, metadata=metadata)

    def retrieve_relevant_workflows(
        self,
        task: str,
        user_id: Optional[str] = None,
        top_k: int = 3,
        min_similarity: float = 0.25,
    ) -> List[Dict[str, Any]]:
        """Retrieves similar past runs and site notes above the similarity threshold."""
        where_filter = {"user_id": user_id} if user_id else None
        raw_matches = self.store.query_similar(query_text=task, top_k=top_k, where_filter=where_filter)

        results: List[Dict[str, Any]] = []
        for match in raw_matches:
            if match["similarity"] < min_similarity:
                continue
            meta = match["metadata"]
            try:
                parsed_steps = json.loads(meta.get("steps_json", "[]"))
            except json.JSONDecodeError:
                parsed_steps = []

            results.append(
                {
                    "id": match["id"],
                    "similarity": match["similarity"],
                    "domain": meta.get("domain", "general"),
                    "task": meta.get("task", ""),
                    "entry_type": meta.get("entry_type", "workflow_run"),
                    "steps": parsed_steps,
                    "summary": match["document"],
                }
            )

        return results

    def format_for_planner_prompt(self, matches: List[Dict[str, Any]]) -> str:
        """Formats retrieved RAG memories into grounded context for the LangGraph planner."""
        if not matches:
            return "No prior similar workflows found in memory."

        lines = ["Relevant Past Workflows & Site Notes (RAG Memory):"]
        for idx, m in enumerate(matches, start=1):
            lines.append(
                f"{idx}. [Similarity: {m['similarity']}] ({m['domain']}) {m['task']}\n"
                f"   Steps: {json.dumps(m['steps'])}"
            )
        return "\n".join(lines)