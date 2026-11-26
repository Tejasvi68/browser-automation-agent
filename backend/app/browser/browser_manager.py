"""
BrowserManager – manages the lifecycle of a Playwright browser session.

Responsibilities:
  - Launch and close the Chromium browser
  - Manage multiple open tabs (pages)
  - Track which tab is currently active
  - Automatically register new tabs opened by JavaScript (window.open / target=_blank)
"""

from typing import Dict, List, Optional

from playwright.async_api import Browser, BrowserContext, Page, Playwright, async_playwright

from app.config import agent_yaml_config


class BrowserManager:
    def __init__(self):
        # Playwright internals (set after start() is called)
        self._playwright: Optional[Playwright]      = None
        self._browser:    Optional[Browser]         = None
        self.context:     Optional[BrowserContext]  = None

        # Tab tracking
        self.pages:            List[Page] = []
        self.active_tab_index: int        = 0

        # Read browser settings from agent_config.yaml
        browser_cfg = agent_yaml_config.get("agent", {})
        self.headless:           bool          = browser_cfg.get("headless", True)
        self.viewport:           Dict[str, int] = browser_cfg.get("viewport", {"width": 1280, "height": 720})
        self.default_timeout_ms: int            = browser_cfg.get("step_timeout_seconds", 30) * 1000

    async def start(self) -> Page:
        """
        Launches Chromium, creates a browser context, and opens the first tab.
        Returns the initial page so callers can optionally navigate it right away.
        """
        self._playwright = await async_playwright().start()
        self._browser    = await self._playwright.chromium.launch(
            headless=self.headless,
            args=[
                "--disable-gpu",
                "--no-sandbox",
                "--disable-dev-shm-usage",
            ],
        )

        self.context = await self._browser.new_context(viewport=self.viewport)
        self.context.set_default_timeout(5000)
        self.context.set_default_navigation_timeout(15000)

        # Listen for new tabs opened via JS or target=_blank links
        self.context.on("page", self._on_new_page)

        initial_page = await self.context.new_page()
        self.pages            = [initial_page]
        self.active_tab_index = 0
        return initial_page

    def _on_new_page(self, page: Page) -> None:
        """Called automatically when a new tab opens. Makes it the active tab."""
        if page not in self.pages:
            self.pages.append(page)
            self.active_tab_index = len(self.pages) - 1

    @property
    def active_page(self) -> Page:
        """Returns the currently active tab, skipping any that were closed."""
        if not self.pages:
            raise RuntimeError("No browser tabs open. Call start() first.")

        # Clean out any tabs that were closed by the page itself
        self.pages = [p for p in self.pages if not p.is_closed()]

        # Clamp index in case the active tab was closed
        if self.active_tab_index >= len(self.pages):
            self.active_tab_index = max(0, len(self.pages) - 1)

        return self.pages[self.active_tab_index]

    async def new_tab(self, url: Optional[str] = None) -> Page:
        """Opens a new tab, makes it active, and optionally navigates to a URL."""
        if not self.context:
            raise RuntimeError("Browser context is not initialized.")

        page = await self.context.new_page()
        if page not in self.pages:
            self.pages.append(page)
        self.active_tab_index = self.pages.index(page)

        if url:
            await page.goto(url, wait_until="domcontentloaded", timeout=15000)

        return page

    async def switch_tab(self, tab_index: int) -> Page:
        """Switches focus to the tab at the given index."""
        # Refresh list to remove any closed tabs
        self.pages = [p for p in self.pages if not p.is_closed()]

        if tab_index < 0 or tab_index >= len(self.pages):
            raise IndexError(
                f"Tab index {tab_index} is out of range ({len(self.pages)} tabs open)."
            )

        self.active_tab_index = tab_index
        page = self.pages[tab_index]
        await page.bring_to_front()
        return page

    async def close_tab(self, tab_index: Optional[int] = None) -> None:
        """
        Closes the specified tab (or the active tab if no index is given).
        Refuses to close the last remaining tab.
        """
        target_idx = self.active_tab_index if tab_index is None else tab_index

        if len(self.pages) <= 1:
            raise RuntimeError("Cannot close the last open browser tab.")

        page_to_close = self.pages[target_idx]
        await page_to_close.close()
        self.pages.pop(target_idx)

        # Keep active_tab_index valid after removal
        self.active_tab_index = max(0, min(self.active_tab_index, len(self.pages) - 1))

    async def list_tabs(self) -> List[Dict[str, object]]:
        """Returns metadata for all currently open (non-closed) tabs."""
        return [
            {
                "index":  idx,
                "title":  await page.title(),
                "url":    page.url,
                "active": idx == self.active_tab_index,
            }
            for idx, page in enumerate(self.pages)
            if not page.is_closed()
        ]

    async def close(self) -> None:
        """Cleanly shuts down the browser context, browser, and Playwright."""
        if self.context:
            await self.context.close()
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()
        self.pages = []
