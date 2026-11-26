"""
BrowserActions – executes individual browser actions using Playwright.

Each method maps directly to one action name that the LLM planner can return.
Every action captures a screenshot after it runs (or fails) for the replay viewer.

Supported actions:
  navigate      – go to a URL
  click         – click an element (by element_id or CSS selector)
  type          – fill a text field
  scroll        – scroll the page up or down
  press_key     – press a keyboard key (e.g. Enter, Tab, Escape)
  extract_text  – extract visible text from a page area
  new_tab       – open a new browser tab
  switch_tab    – switch to a specific tab by index
  close_tab     – close a tab
"""

from typing import Any, Dict, Optional

from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from app.browser.browser_manager import BrowserManager
from app.browser.screenshot_manager import ScreenshotManager


class BrowserActions:
    def __init__(self, manager: BrowserManager, screenshot_manager: Optional[ScreenshotManager] = None):
        self.manager = manager
        self.screenshots = screenshot_manager or ScreenshotManager()

    def _get_locator(self, page, params: Dict[str, Any]):
        """
        Returns a Playwright locator.
        Prefers element_id (the data-aura-id stamp set by DOMAnalyzer),
        falls back to a plain CSS selector.
        """
        if params.get("element_id") is not None:
            return page.locator(f'[data-aura-id="{params["element_id"]}"]').first
        return page.locator(params["selector"]).first

    async def execute(
        self,
        action: str,
        params: Dict[str, Any],
        run_id: str,
        step_number: int,
    ) -> Dict[str, Any]:
        """
        Dispatches the action to the right handler and always returns a result dict:
          { success, action, data, screenshot, tabs }  on success
          { success, action, error, screenshot }        on failure
        """
        page = self.manager.active_page
        result_data: Any = None

        try:
            # ── navigate ──────────────────────────────────────────────────────
            if action == "navigate":
                url = params["url"]
                # Auto-prepend https:// if the URL has no scheme
                if not url.startswith(("http://", "https://", "data:")):
                    url = f"https://{url}"
                response = await page.goto(url, wait_until="domcontentloaded", timeout=20000)
                await page.wait_for_timeout(800)   # Brief pause for JS to settle
                if response is not None and response.status >= 400:
                    raise RuntimeError(f"Navigation to {page.url} returned HTTP {response.status}")
                result_data = {"url": page.url, "title": await page.title()}

            # ── click ─────────────────────────────────────────────────────────
            elif action == "click":
                locator = self._get_locator(page, params)
                original_url = page.url
                form_submission = await page.evaluate("""(elementId) => {
                    const el = [...document.querySelectorAll('[data-aura-id]')]
                      .find(node => node.getAttribute('data-aura-id') === String(elementId));
                    if (!el) return false;
                    const form = el.closest('form');
                    const label = `${el.innerText || ''} ${el.getAttribute('aria-label') || ''} ${el.getAttribute('name') || ''}`.toLowerCase();
                    if (!form) return false;
                    const contactLike = form.querySelector('textarea') || /\\b(contact|message|inquiry)\\b/i.test(form.innerText || '');
                    return Boolean(contactLike && (
                      el.matches('button[type="submit"], input[type="submit"], input[type="image"]') ||
                      /\\b(send|submit)\\b/.test(label)
                    ));
                }""", str(params.get("element_id", ""))) if params.get("element_id") is not None else False
                login_form_before_click = await page.evaluate("""() => {
                    const visible = (el) => {
                      const s = getComputedStyle(el), r = el.getBoundingClientRect();
                      return s.display !== 'none' && s.visibility !== 'hidden' && r.width > 0 && r.height > 0;
                    };
                    const fields = [...document.querySelectorAll('input')].filter(visible);
                    return fields.some(el => el.type === 'password');
                }""")
                form_submission = form_submission and not login_form_before_click
                label = params.get("target_label") or params.get("selector") or "target element"
                candidates = [locator]
                target_tag = str(params.get("target_tag", "")).lower()
                if params.get("target_label"):
                    if target_tag == "a":
                        candidates.append(page.get_by_role("link", name=params["target_label"], exact=True).first)
                    elif target_tag == "button":
                        candidates.append(page.get_by_role("button", name=params["target_label"], exact=True).first)
                    candidates.append(page.get_by_text(params["target_label"], exact=True).first)

                clicked = False
                click_error = None
                seen_candidates = set()
                for candidate in candidates:
                    # The element-id and semantic locators can point to the same
                    # control; avoid retrying that locator twice.
                    candidate_key = str(candidate)
                    if candidate_key in seen_candidates:
                        continue
                    seen_candidates.add(candidate_key)
                    try:
                        await candidate.wait_for(state="visible", timeout=1200)
                        await candidate.scroll_into_view_if_needed(timeout=2500)
                        await candidate.click(timeout=3000)
                        locator = candidate
                        clicked = True
                        break
                    except Exception as exc:
                        click_error = exc

                # Last resort: activate the exact visible text node from the DOM.
                # This still uses the observed label and never fabricates a URL.
                if not clicked and params.get("target_label"):
                    clicked = await page.evaluate("""(label) => {
                        const norm = value => (value || '').replace(/\\s+/g, ' ').trim().toLowerCase();
                        const wanted = norm(label);
                        const nodes = [...document.querySelectorAll('a, button, [role="button"]')];
                        const target = nodes.find(el => {
                          const r = el.getBoundingClientRect(), s = getComputedStyle(el);
                          return norm(el.innerText || el.getAttribute('aria-label')) === wanted &&
                            s.display !== 'none' && s.visibility !== 'hidden' && r.width > 0 && r.height > 0;
                        });
                        if (!target) return false;
                        target.scrollIntoView({block: 'center', inline: 'nearest'});
                        target.click();
                        return true;
                    }""", params["target_label"])

                if not clicked:
                    raise RuntimeError(f"Could not click the visible '{label}' control: {click_error}")
                await page.wait_for_timeout(900)

                # A completed click only means the control was activated. Verify
                # login submissions against the resulting page before reporting
                # success so the planner does not continue into gated features.
                click_text = (await locator.inner_text(timeout=1000) if await locator.count() else "")
                click_text = " ".join(click_text.lower().split())
                if login_form_before_click and any(word in click_text for word in ("login", "log in", "sign in", "submit")):
                    still_requires_login = await self.manager.active_page.evaluate("""() => {
                        const visible = (el) => {
                          const s = getComputedStyle(el), r = el.getBoundingClientRect();
                          return s.display !== 'none' && s.visibility !== 'hidden' && r.width > 0 && r.height > 0;
                        };
                        const fields = [...document.querySelectorAll('input')].filter(visible);
                        const password = fields.some(el => el.type === 'password');
                        const loginCopy = /please\\s+log\\s+in|login\\s+to\\s+(generate|continue)|sign\\s+in\\s+to/i.test(document.body.innerText || '');
                        const loginForm = password && fields.some(el => /email|user/i.test((el.placeholder || '') + ' ' + (el.name || '') + ' ' + (el.type || '')));
                        return loginCopy || loginForm;
                    }""")
                    if still_requires_login:
                        login_error = await self.manager.active_page.evaluate("""() => {
                            const selectors = [
                              '[role="alert"]', '[aria-live="assertive"]',
                              '.error', '.error-message', '.text-danger',
                              '[class*="error"]', '[class*="invalid"]'
                            ];
                            for (const selector of selectors) {
                              const el = [...document.querySelectorAll(selector)].find(node => {
                                const s = getComputedStyle(node), r = node.getBoundingClientRect();
                                return s.display !== 'none' && s.visibility !== 'hidden' && r.width > 0 && r.height > 0;
                              });
                              const text = el?.innerText?.trim();
                              if (text) return text.slice(0, 240);
                            }
                            return '';
                        }""")
                        if login_error:
                            raise RuntimeError(f"Login was not accepted by the website: {login_error}")
                        raise RuntimeError("Login was submitted, but the page still shows a login form. The site did not confirm a successful login; verify the vault entry and try again.")

                result_data = {"clicked": label, "url": self.manager.active_page.url}
                if form_submission:
                    # A successful Playwright click does not prove the website
                    # accepted a form. Give client-side sends time to finish,
                    # then look for a success or error before planning again.
                    confirmation = None
                    for _ in range(60):  # Up to 30 seconds for the site's send request
                        confirmation = await page.evaluate("""(previousUrl) => {
                        const text = (document.body?.innerText || '').toLowerCase();
                        const successText = /message (was |has been )?sent|sent successfully|submission (was )?successful|submitted successfully|we (have )?received your message|thank you for (your )?(message|reaching|contacting)/.test(text);
                        const errorNode = [...document.querySelectorAll('[role="alert"], [aria-live="assertive"], [class*="error"], [class*="invalid"]')]
                          .find(node => {
                            const s = getComputedStyle(node), r = node.getBoundingClientRect();
                            return s.display !== 'none' && s.visibility !== 'hidden' && r.width > 0 && r.height > 0 && (node.innerText || '').trim();
                          });
                        const errorText = (errorNode?.innerText || '').trim().slice(0, 240);
                        const sendControl = [...document.querySelectorAll('button, input[type="submit"]')]
                          .find(node => /send|submit|sending/i.test(node.innerText || node.value || ''));
                        const sending = /sending|please wait/i.test(sendControl?.innerText || sendControl?.value || '');
                        const forms = [...document.querySelectorAll('form')].filter(form => {
                          const s = getComputedStyle(form), r = form.getBoundingClientRect();
                          return s.display !== 'none' && s.visibility !== 'hidden' && r.width > 0 && r.height > 0;
                        });
                        return {
                          confirmed: successText || location.href !== previousUrl || forms.length === 0,
                          confirmation_text: successText,
                          error_text: errorText,
                          sending,
                          url_changed: location.href !== previousUrl,
                          form_still_visible: forms.length > 0
                        };
                    }""", original_url)
                        if (
                            confirmation["confirmed"]
                            or confirmation["error_text"]
                            or not confirmation["sending"]
                        ):
                            break
                        await page.wait_for_timeout(500)
                    result_data.update({
                        "form_submission": True,
                        "submission_confirmed": bool(confirmation["confirmed"]),
                        "confirmation_text": bool(confirmation["confirmation_text"]),
                        "submission_error": confirmation["error_text"],
                        "submission_still_sending": bool(confirmation["sending"]),
                        "url_changed": bool(confirmation["url_changed"]),
                        "form_still_visible": bool(confirmation["form_still_visible"]),
                    })

            # ── type ──────────────────────────────────────────────────────────
            elif action == "type":
                locator = self._get_locator(page, params)
                text    = params["text"]

                # fill() clears and replaces; type() appends character by character
                if params.get("clear", True):
                    await locator.fill(text, timeout=4000)
                else:
                    await locator.type(text, timeout=4000)

                # Optionally press Enter after typing (e.g. to submit a search)
                if params.get("press_enter", False):
                    await locator.press("Enter")
                    await page.wait_for_timeout(1200)

                # Never return the entered text: it may be a decrypted vault
                # field, and execution history is persisted for the run.
                result_data = {"typed": True, "character_count": len(text)}

            # ── scroll ────────────────────────────────────────────────────────
            elif action == "scroll":
                direction = params.get("direction", "down")
                pixels    = int(params.get("amount", 650))
                delta_y   = pixels if direction == "down" else -pixels
                await page.mouse.wheel(0, delta_y)
                await page.wait_for_timeout(600)
                result_data = {"scrolled": direction, "pixels": pixels}

            # ── press_key ─────────────────────────────────────────────────────
            elif action == "press_key":
                key = params.get("key", "Enter")
                await page.keyboard.press(key)
                await page.wait_for_timeout(1000)
                result_data = {"pressed": key}

            # ── extract_text ──────────────────────────────────────────────────
            elif action == "extract_text":
                raw_selector = params.get("selector", "main, #search, [role='main'], body")
                # Strip Scrapy-style ::text / ::attr() suffixes which Playwright doesn't support
                selector = raw_selector.split("::")[0].strip() or "main, #search, [role='main'], body"

                # Extract clean, deduplicated visible text from the target element
                cleaned = await page.evaluate("""(sel) => {
                    const target = document.querySelector(sel) || document.body;
                    const clone  = target.cloneNode(true);
                    // Remove chrome elements that add noise
                    clone.querySelectorAll('header, nav, footer, aside, script, style, noscript').forEach(el => el.remove());
                    const lines = (clone.innerText || '')
                        .split('\\n')
                        .map(l => l.trim())
                        .filter(l => l.length > 1);
                    // Remove consecutive duplicate lines
                    const deduped = lines.filter((l, i) => i === 0 || l !== lines[i - 1]);
                    return [deduped.join('\\n').slice(0, 4500)];
                }""", selector)

                result_data = {"extracted": cleaned}

            # ── new_tab ───────────────────────────────────────────────────────
            elif action == "new_tab":
                new_page = await self.manager.new_tab(params.get("url"))
                result_data = {"opened_tab": self.manager.active_tab_index, "url": new_page.url}

            # ── switch_tab ────────────────────────────────────────────────────
            elif action == "switch_tab":
                tab_index = int(params["tab_index"])
                switched  = await self.manager.switch_tab(tab_index)
                result_data = {"active_tab": tab_index, "url": switched.url}

            # ── close_tab ─────────────────────────────────────────────────────
            elif action == "close_tab":
                await self.manager.close_tab(params.get("tab_index"))
                result_data = {"remaining_tabs": len(self.manager.pages)}

            # ── unsupported ───────────────────────────────────────────────────
            else:
                screenshot = await self.screenshots.capture(self.manager.active_page, run_id, step_number)
                return {
                    "success":    False,
                    "action":     action,
                    "error":      f"Unsupported action: '{action}'",
                    "screenshot": screenshot,
                }

            # Capture a screenshot after every successful action
            screenshot = await self.screenshots.capture(self.manager.active_page, run_id, step_number)
            return {
                "success":    True,
                "action":     action,
                "data":       result_data,
                "screenshot": screenshot,
                "tabs":       await self.manager.list_tabs(),
            }

        except (PlaywrightTimeoutError, Exception) as exc:
            # Always try to capture a failure screenshot for debugging
            screenshot = None
            try:
                screenshot = await self.screenshots.capture(self.manager.active_page, run_id, step_number)
            except Exception:
                pass

            return {
                "success":    False,
                "action":     action,
                "error":      f"Error in '{action}': {str(exc)}",
                "screenshot": screenshot,
            }
