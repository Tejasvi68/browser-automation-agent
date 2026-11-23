import pytest
from app.agent.graph import BrowserAgentOrchestrator
from app.agent.state import AgentState
from app.browser.browser_manager import BrowserManager
from app.memory.vector_store import WorkflowVectorStore
from app.memory.workflow_memory import WorkflowMemory


class MockPlanner:
    def __init__(self, script):
        self.script = list(script)
        self.calls = 0

    async def decide_next_action(self, state, callbacks=None):
        action = self.script[min(self.calls, len(self.script) - 1)]
        self.calls += 1
        return action


@pytest.mark.asyncio
async def test_langgraph_agent_completes_task_and_saves_rag_memory():
    manager = BrowserManager()
    await manager.start()

    store = WorkflowVectorStore(in_memory=True)
    memory = WorkflowMemory(vector_store=store)

    html = "data:text/html;charset=utf-8,<html><head><title>Store</title></head><body><h2 class='price'>₹49,999</h2></body></html>"
    planner = MockPlanner(
        [
            {"thought": "Open store page", "action": "navigate", "params": {"url": html}, "is_sensitive": False},
            {"thought": "Extract product price", "action": "extract_text", "params": {"selector": ".price"}, "is_sensitive": False},
            {"thought": "Done", "action": "finish", "params": {}, "is_sensitive": False, "final_answer": "Price is ₹49,999"},
        ]
    )

    orchestrator = BrowserAgentOrchestrator(
        browser_manager=manager,
        planner=planner,
        workflow_memory=memory,
    )

    initial_state: AgentState = {
        "run_id": "run_demo_1",
        "user_id": "user_tejasvi",
        "task": "Check laptop price on Store",
        "status": "running",
        "step_count": 0,
        "max_steps": 10,
        "retry_count": 0,
        "max_retries_per_step": 2,
        "rag_context": "",
        "available_credentials": [],
        "dom_snapshot": {},
        "formatted_dom": "",
        "latest_screenshot": None,
        "next_action": None,
        "approval_approved": None,
        "pending_approval_reason": None,
        "steps_history": [],
        "extracted_data": [],
        "final_summary": "",
        "last_error": None,
    }

    try:
        final_state = await orchestrator.graph.ainvoke(initial_state)
        assert final_state["status"] == "completed"
        assert "₹49,999" in final_state["extracted_data"]
        assert "₹49,999" in final_state["final_summary"]

        # Verify RAG memory automatically indexed the successful run
        matches = memory.retrieve_relevant_workflows("Check laptop price", user_id="user_tejasvi", min_similarity=0.1)
        assert len(matches) == 1
    finally:
        await manager.close()


@pytest.mark.asyncio
async def test_langgraph_agent_pauses_on_sensitive_submit():
    manager = BrowserManager()
    await manager.start()

    html = "data:text/html,<html><body><form><button id='submit-order' type='submit'>Place Order</button></form></body></html>"
    planner = MockPlanner(
        [
            {"thought": "Open checkout", "action": "navigate", "params": {"url": html}, "is_sensitive": False},
            {"thought": "Click place order", "action": "click", "params": {"selector": "#submit-order"}, "is_sensitive": True},
        ]
    )

    orchestrator = BrowserAgentOrchestrator(browser_manager=manager, planner=planner)

    initial_state: AgentState = {
        "run_id": "run_approval_test",
        "user_id": "user_tejasvi",
        "task": "Place order",
        "status": "running",
        "step_count": 0,
        "max_steps": 10,
        "retry_count": 0,
        "max_retries_per_step": 2,
        "rag_context": "",
        "available_credentials": [],
        "dom_snapshot": {},
        "formatted_dom": "",
        "latest_screenshot": None,
        "next_action": None,
        "approval_approved": None,
        "pending_approval_reason": None,
        "steps_history": [],
        "extracted_data": [],
        "final_summary": "",
        "last_error": None,
    }

    try:
        paused_state = await orchestrator.graph.ainvoke(initial_state)
        assert paused_state["status"] == "awaiting_approval"
        assert "requires human approval" in (paused_state["pending_approval_reason"] or "")
    finally:
        await manager.close()