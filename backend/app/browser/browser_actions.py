from typing import Any, Dict, Optional
from playwright.async_api import TimeoutError as PlaywrightTimeoutError
from app.browser.browser_manager import BrowserManager
from app.browser.screenshot_manager import ScreenshotManager


class BrowserActions:
    def __init__(self, manager: BrowserManager, screenshot_manager: Optional[ScreenshotManager] = None):
        self.manager = manager
        self.screenshots = screenshot_manager or ScreenshotManager()

    async def execute(
        self,
        action: str,
        params: Dict[str, Any],
        run_id: str,
        step_number: int,
    ) -> Dict[str, Any]:
        """Executes a single browser action and captures a step screenshot."""
        page = self.manager.active_page
        result_data: Any = None

        try:
            if action == "navigate":
                url = params["url"]
                if not url.startswith(("http://", "https://", "data:")):
                    url = f"https://{url}"
                await page.goto(url, wait_until="load")
                result_data = {"url": page.url, "title": await page.title()}

            elif action == "click":
                selector = params["selector"]
                await page.locator(selector).first.click()
                await page.wait_for_load_state("domcontentloaded")
                result_data = {"clicked": selector, "url": page.url}

            elif action == "type":
                selector = params["selector"]
                text = params["text"]
                clear_first = params.get("clear", True)
                locator = page.locator(selector).first
                if clear_first:
                    await locator.fill(text)
                else:
                    await locator.type(text)
                if params.get("press_enter", False):
                    await locator.press("Enter")
                    await page.wait_for_load_state("domcontentloaded")
                result_data = {"typed_into": selector}

            elif action == "scroll":
                direction = params.get("direction", "down")
                amount = int(params.get("amount", 600))
                delta_y = amount if direction == "down" else -amount
                await page.mouse.wheel(0, delta_y)
                await page.wait_for_timeout(500)
                result_data = {"scrolled": direction, "pixels": amount}

            elif action == "press_key":
                key = params.get("key", "Enter")
                await page.keyboard.press(key)
                await page.wait_for_load_state("domcontentloaded")
                result_data = {"pressed": key}

            elif action == "extract_text":
                selector = params.get("selector", "body")
                locator = page.locator(selector)
                await locator.first.wait_for(state="attached", timeout=5000)
                elements = await locator.all_inner_texts()
                result_data = {"extracted": [t.strip() for t in elements if t.strip()]}

            elif action == "new_tab":
                new_page = await self.manager.new_tab(params.get("url"))
                result_data = {"opened_tab": self.manager.active_tab_index, "url": new_page.url}

            elif action == "switch_tab":
                tab_idx = int(params["tab_index"])
                switched = await self.manager.switch_tab(tab_idx)
                result_data = {"active_tab": tab_idx, "url": switched.url}

            elif action == "close_tab":
                await self.manager.close_tab(params.get("tab_index"))
                result_data = {"remaining_tabs": len(self.manager.pages)}

            else:
                return {
                    "success": False,
                    "action": action,
                    "error": f"Unsupported action: '{action}'",
                }

            # Capture live screenshot after successful action
            shot = await self.screenshots.capture(self.manager.active_page, run_id, step_number)

            return {
                "success": True,
                "action": action,
                "data": result_data,
                "screenshot": shot,
                "tabs": await self.manager.list_tabs(),
            }

        except PlaywrightTimeoutError as e:
            return {
                "success": False,
                "action": action,
                "error": f"Timeout executing '{action}': {str(e)}",
            }
        except Exception as e:
            return {
                "success": False,
                "action": action,
                "error": f"Error executing '{action}': {str(e)}",
            }