from typing import Dict, List, Optional
from playwright.async_api import async_playwright, Playwright, Browser, BrowserContext, Page
from app.config import agent_yaml_config


class BrowserManager:
    def __init__(self):
        self._playwright: Optional[Playwright] = None
        self._browser: Optional[Browser] = None
        self.context: Optional[BrowserContext] = None
        self.pages: List[Page] = []
        self.active_tab_index: int = 0

        browser_cfg = agent_yaml_config.get("agent", {})
        self.headless: bool = browser_cfg.get("headless", True)
        self.viewport: Dict[str, int] = browser_cfg.get("viewport", {"width": 1280, "height": 720})
        self.default_timeout_ms: int = browser_cfg.get("step_timeout_seconds", 30) * 1000

    async def start(self) -> Page:
        """Launches Chromium, creates an isolated BrowserContext, and opens the initial tab."""
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(headless=self.headless)
        self.context = await self._browser.new_context(viewport=self.viewport)
        self.context.set_default_timeout(self.default_timeout_ms)

        # Automatically track new tabs/popups opened via target="_blank" or window.open()
        self.context.on("page", self._on_new_page)

        initial_page = await self.context.new_page()
        self.pages = [initial_page]
        self.active_tab_index = 0
        return initial_page

    def _on_new_page(self, page: Page) -> None:
        if page not in self.pages:
            self.pages.append(page)
            self.active_tab_index = len(self.pages) - 1

    @property
    def active_page(self) -> Page:
        if not self.pages:
            raise RuntimeError("No active browser tabs available. Call start() first.")
        # Clean up any closed tabs safely
        self.pages = [p for p in self.pages if not p.is_closed()]
        if self.active_tab_index >= len(self.pages):
            self.active_tab_index = max(0, len(self.pages) - 1)
        return self.pages[self.active_tab_index]

    async def new_tab(self, url: Optional[str] = None) -> Page:
        """Opens a new tab and makes it active."""
        if not self.context:
            raise RuntimeError("BrowserContext is not initialized.")
        page = await self.context.new_page()
        if page not in self.pages:
            self.pages.append(page)
        self.active_tab_index = self.pages.index(page)
        if url:
            await page.goto(url, wait_until="domcontentloaded")
        return page

    async def switch_tab(self, tab_index: int) -> Page:
        """Switches active focus to the specified tab index."""
        self.pages = [p for p in self.pages if not p.is_closed()]
        if tab_index < 0 or tab_index >= len(self.pages):
            raise IndexError(f"Tab index {tab_index} out of range (open tabs: {len(self.pages)}).")
        self.active_tab_index = tab_index
        page = self.pages[tab_index]
        await page.bring_to_front()
        return page

    async def close_tab(self, tab_index: Optional[int] = None) -> None:
        """Closes a specific tab (or the current tab) while keeping at least one tab open."""
        target_idx = self.active_tab_index if tab_index is None else tab_index
        if len(self.pages) <= 1:
            raise RuntimeError("Cannot close the last remaining browser tab.")
        page_to_close = self.pages[target_idx]
        await page_to_close.close()
        self.pages.pop(target_idx)
        self.active_tab_index = max(0, min(self.active_tab_index, len(self.pages) - 1))

    async def list_tabs(self) -> List[Dict[str, object]]:
        """Returns metadata for all currently open tabs."""
        tabs = []
        for idx, p in enumerate(self.pages):
            if not p.is_closed():
                tabs.append({
                    "index": idx,
                    "title": await p.title(),
                    "url": p.url,
                    "active": idx == self.active_tab_index,
                })
        return tabs

    async def close(self) -> None:
        """Cleanly shuts down context, browser, and Playwright."""
        if self.context:
            await self.context.close()
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()
        self.pages = []