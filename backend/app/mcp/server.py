from typing import Any, Dict
from fastmcp import FastMCP
from app.browser.browser_actions import BrowserActions
from app.browser.browser_manager import BrowserManager
from app.database.database import SessionLocal, init_db
from app.database.models import SavedWorkflow
from app.services.automation_service import automation_service

mcp = FastMCP("Browser Automation Agent")


@mcp.tool()
async def run_web_task(task: str, user_id: str = "mcp_client", max_steps: int = 12) -> Dict[str, Any]:
    """Executes a plain-English web automation task and returns extracted results and step logs."""
    init_db()
    db = SessionLocal()
    try:
        return await automation_service.start_task(
            db=db,
            user_id=user_id,
            task=task,
            max_steps=max_steps,
        )
    finally:
        db.close()


@mcp.tool()
async def extract_page_data(url: str, css_selector: str = "body") -> Dict[str, Any]:
    """Navigates to a JavaScript-rendered webpage and extracts text matching the CSS selector."""
    manager = BrowserManager()
    await manager.start()
    actions = BrowserActions(manager)
    try:
        nav = await actions.execute("navigate", {"url": url}, run_id="mcp_extract", step_number=1)
        if not nav["success"]:
            return nav
        ext = await actions.execute("extract_text", {"selector": css_selector}, run_id="mcp_extract", step_number=2)
        return {
            "url": url,
            "selector": css_selector,
            "extracted": (ext.get("data") or {}).get("extracted", []),
            "success": ext["success"],
        }
    finally:
        await manager.close()


@mcp.tool()
async def replay_workflow(workflow_id: str, user_id: str = "mcp_client") -> Dict[str, Any]:
    """Replays a previously saved reusable workflow by its workflow ID."""
    init_db()
    db = SessionLocal()
    try:
        wf = db.query(SavedWorkflow).filter(SavedWorkflow.id == workflow_id).first()
        if not wf:
            return {"success": False, "error": f"Workflow '{workflow_id}' not found."}
        return await automation_service.start_task(db=db, user_id=user_id, task=wf.task_prompt)
    finally:
        db.close()


if __name__ == "__main__":
    mcp.run()