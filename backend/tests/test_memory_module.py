from app.memory.vector_store import WorkflowVectorStore
from app.memory.workflow_memory import WorkflowMemory


def test_workflow_memory_storage_and_retrieval():
    store = WorkflowVectorStore(in_memory=True)
    memory = WorkflowMemory(vector_store=store)

    # 1. Save a successful e-commerce search workflow
    memory.save_successful_run(
        run_id="run_001",
        user_id="user_tejasvi",
        task="Search Amazon for laptops under 60000 and extract top 5 prices",
        steps=[
            {"action": "navigate", "params": {"url": "https://www.amazon.in"}, "url": "https://www.amazon.in"},
            {"action": "type", "params": {"selector": "#twotabsearchtextbox", "text": "laptops under 60000", "press_enter": True}},
            {"action": "extract_text", "params": {"selector": ".s-result-item"}},
        ],
        site_notes="Use #twotabsearchtextbox for the main search bar.",
    )

    # 2. Save a site-specific note
    memory.save_site_note(
        note_id="amz_cookie",
        user_id="user_tejasvi",
        url="https://www.amazon.in",
        note="Dismiss location popup if it overlays the search bar.",
    )

    # 3. Query with a related task
    matches = memory.retrieve_relevant_workflows(
        task="Find gaming laptops on Amazon and compare prices",
        user_id="user_tejasvi",
        top_k=2,
        min_similarity=0.1,
    )

    assert len(matches) >= 1
    assert matches[0]["domain"] == "www.amazon.in"
    assert len(matches[0]["steps"]) == 3

    formatted = memory.format_for_planner_prompt(matches)
    assert "#twotabsearchtextbox" in formatted

    # 4. Ensure user isolation (different user should not see user_tejasvi's private runs)
    other_user_matches = memory.retrieve_relevant_workflows(
        task="Find gaming laptops on Amazon",
        user_id="another_user",
        top_k=2,
        min_similarity=0.1,
    )
    assert len(other_user_matches) == 0