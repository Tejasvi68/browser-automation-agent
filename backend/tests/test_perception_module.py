import pytest
from app.browser.browser_manager import BrowserManager
from app.perception.dom_analyzer import DOMAnalyzer


@pytest.mark.asyncio
async def test_dom_analyzer_extracts_interactive_elements():
    manager = BrowserManager()
    page = await manager.start()
    analyzer = DOMAnalyzer()

    html = """
    <html>
      <head><title>Login Portal</title></head>
      <body>
        <h1>Welcome Back</h1>
        <input id="email-input" type="email" placeholder="Enter email" />
        <button data-testid="submit-btn">Sign In</button>
        <button style="display:none">Hidden Button</button>
      </body>
    </html>
    """

    try:
        await page.set_content(html)
        snapshot = await analyzer.inspect(page)

        assert snapshot["title"] == "Login Portal"
        elements = snapshot["interactive_elements"]

        # Hidden button must be excluded; only visible email input + sign-in button returned
        assert len(elements) == 2
        assert elements[0]["selector"] == "#email-input"
        assert elements[1]["selector"] == '[data-testid="submit-btn"]'

        formatted = analyzer.format_for_prompt(snapshot)
        assert "#email-input" in formatted
        assert '[data-testid="submit-btn"]' in formatted
    finally:
        await manager.close()