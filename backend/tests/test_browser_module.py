import pytest
from app.browser.browser_manager import BrowserManager
from app.browser.browser_actions import BrowserActions


@pytest.mark.asyncio
async def test_browser_navigation_and_multitab():
    manager = BrowserManager()
    await manager.start()
    actions = BrowserActions(manager)

    page_1_url = "data:text/html,<html><head><title>Page One</title></head><body><h1>Example Domain</h1></body></html>"
    page_2_url = "data:text/html,<html><head><title>Page Two</title></head><body><p>Second Tab</p></body></html>"

    try:
        # 1. Navigate
        res1 = await actions.execute("navigate", {"url": page_1_url}, run_id="test_run", step_number=1)
        assert res1["success"] is True, res1.get("error")
        assert "Page One" in res1["data"]["title"]

        # 2. Extract text
        res2 = await actions.execute("extract_text", {"selector": "h1"}, run_id="test_run", step_number=2)
        assert res2["success"] is True, res2.get("error")
        assert res2["data"]["extracted"] == ["Example Domain"]

        # 3. Open second tab & switch back
        res3 = await actions.execute("new_tab", {"url": page_2_url}, run_id="test_run", step_number=3)
        assert res3["success"] is True, res3.get("error")
        assert len(res3["tabs"]) == 2

        res4 = await actions.execute("switch_tab", {"tab_index": 0}, run_id="test_run", step_number=4)
        assert res4["success"] is True, res4.get("error")
        assert res4["data"]["active_tab"] == 0
    finally:
        await manager.close()