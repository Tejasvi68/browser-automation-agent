"""
DOMAnalyzer – extracts structured information from the current browser page.

It runs a JavaScript snippet in the page that:
  1. Finds all visible, interactable elements (links, buttons, inputs, selects)
  2. Stamps each with a unique data-aura-id so the agent can reference them by number
  3. Returns a JSON snapshot the Python side can format for the LLM planner

The formatted output looks like:
  [1] <a>  text="Books"  url="https://example.com/books"
  [2] <input>  type=text  placeholder="Search..."
  [3] <button>  text="Add to cart"
"""

from typing import Any, Dict, List

from playwright.async_api import Page


# ── JavaScript that runs inside the browser page ──────────────────────────────

DOM_EXTRACTION_SCRIPT = """
() => {
  // Clear any stale stamps from previous runs
  document.querySelectorAll('[data-aura-id]').forEach(el => el.removeAttribute('data-aura-id'));

  // Decide whether an element is worth including
  const isInteractable = (el) => {
    const style = window.getComputedStyle(el);
    if (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') return false;
    const rect = el.getBoundingClientRect();
    if (rect.width < 4 || rect.height < 4) return false;
    // Keep off-screen controls too: Playwright can scroll them into view when
    // the planned action runs, and long forms may sit far below the fold.
    return true;
  };

  // Prefer elements inside the main content area first
  const mainRoot   = document.querySelector('main, #search, [role="main"]') || document.body;
  const mainNodes  = Array.from(mainRoot.querySelectorAll('a[href], button, input, select, textarea, [role="button"]'));
  const allNodes   = Array.from(document.querySelectorAll('input, select, textarea, a[href], button, [role="button"]'));
  const formNodes  = allNodes.filter(el => el.closest('form'));
  // Keep authentication controls near the front so they are not dropped when
  // a page has many regular controls.
  const authNodes  = allNodes.filter(el => {
    const label = [el.innerText, el.getAttribute('aria-label'), el.getAttribute('placeholder'), el.getAttribute('href')]
      .filter(Boolean).join(' ').toLowerCase();
    return el.type === 'password' || /login|log\\s*in|sign\\s*in|authenticate/.test(label);
  });

  // Merge both lists, keeping order and removing duplicates
  const seen       = new Set();
  const candidates = [...authNodes, ...formNodes, ...mainNodes, ...allNodes].filter(el => {
    if (seen.has(el)) return false;
    seen.add(el);
    return true;
  });

  const elements = [];
  let index = 1;

  for (const el of candidates) {
    if (!isInteractable(el)) continue;

    const tag         = el.tagName.toLowerCase();
    // Read the effective HTML type. For <button> this is "submit" by default
    // even when the page omits an explicit type attribute.
    const type        = (el.type || el.getAttribute('type') || '').toLowerCase();
    const rawText     = (el.innerText || '').trim().replace(/\\s+/g, ' ').slice(0, 75);
    const valuePresent = Boolean(('value' in el ? el.value : '').trim());
    const placeholder = el.getAttribute('placeholder') || '';
    const ariaLabel   = el.getAttribute('aria-label') || '';
    const name        = el.getAttribute('name') || '';
    const autocomplete = el.getAttribute('autocomplete') || '';
    const labelText   = el.labels ? Array.from(el.labels).map(label => label.innerText.trim()).filter(Boolean).join(' ') : '';
    const fullHref    = tag === 'a' ? (el.href || '') : '';
    const form        = el.closest('form');
    const formKey     = form ? (form.id || form.getAttribute('name') || form.getAttribute('action') || String(Array.from(document.forms).indexOf(form))) : '';
    const isSubmit    = Boolean(form && (
      (tag === 'button' && type === 'submit') ||
      (tag === 'input' && (type === 'submit' || type === 'image'))
    ));

    // Skip links with no visible text or label
    if (tag === 'a') {
      if (!rawText && !ariaLabel) continue;
      if (!fullHref || fullHref.startsWith('javascript:')) continue;
    }

    // Label sponsored search results so the agent knows to avoid them
    const isSponsored = Boolean(el.closest('.AdHolder, [data-component-type="sp-sponsored-result"]'));
    const text        = isSponsored ? `[SPONSORED] ${rawText}` : rawText;

    // Stamp the element with its index so click/type actions can find it
    el.setAttribute('data-aura-id', String(index));

    elements.push({
      element_id: index,
      tag,
      type,
      text,
      value_present: valuePresent,
      placeholder,
      aria_label: ariaLabel,
      name,
      label: labelText.slice(0, 100),
      autocomplete,
      in_form: Boolean(form),
      form_key: formKey,
      is_submit: isSubmit,
      url: fullHref.slice(0, 140),
    });

    index++;
    if (elements.length >= 50) break;   // Include complete forms on long pages
  }

  // Also grab a text snippet of visible page content for the planner
  const textRoot   = document.querySelector('main, #search, [role="main"]') || document.body;
  const pageText   = (textRoot ? textRoot.innerText : '')
    .replace(/\\n{3,}/g, '\\n\\n')
    .trim()
    .slice(0, 1400);

  return {
    title:                document.title,
    url:                  window.location.href,
    interactive_elements: elements,
    visible_text_snippet: pageText,
  };
}
"""


# ── Python wrapper ────────────────────────────────────────────────────────────

class DOMAnalyzer:
    async def inspect(self, page: Page) -> Dict[str, Any]:
        """
        Runs the extraction script in the page and returns a structured snapshot.
        The snapshot includes the page title, URL, interactive elements, and a text snippet.
        """
        return await page.evaluate(DOM_EXTRACTION_SCRIPT)

    def format_for_prompt(self, snapshot: Dict[str, Any]) -> str:
        """
        Converts the raw snapshot into a readable string the LLM can understand.

        Example output:
          URL: https://books.toscrape.com
          Title: Books to Scrape

          Interactive Elements (use element_id for click/type):
          [1] <a>  text="Travel"  url="https://books.toscrape.com/catalogue/category/books/travel_2/index.html"
          [2] <input>  type=text  placeholder="Search..."

          Visible Page Text:
          Welcome to Books to Scrape ...
        """
        lines: List[str] = [
            f"URL: {snapshot.get('url', '')}",
            f"Title: {snapshot.get('title', '')}",
            "\nInteractive Elements (use element_id for click/type):",
        ]

        for el in snapshot.get("interactive_elements", []):
            parts = [f"[{el['element_id']}] <{el['tag']}>"]
            if el.get("type"):        parts.append(f"type={el['type']}")
            if el.get("text"):        parts.append(f'text="{el["text"]}"')
            if el.get("tag") in ("input", "textarea", "select"):
                parts.append(f'value_present={str(bool(el.get("value_present"))).lower()}')
            if el.get("placeholder"): parts.append(f'placeholder="{el["placeholder"]}"')
            if el.get("aria_label"):  parts.append(f'aria="{el["aria_label"]}"')
            if el.get("name"):        parts.append(f'name="{el["name"]}"')
            if el.get("label"):       parts.append(f'label="{el["label"]}"')
            if el.get("autocomplete"):parts.append(f'autocomplete="{el["autocomplete"]}"')
            if el.get("form_key"):    parts.append(f'form="{el["form_key"]}"')
            if el.get("is_submit"):   parts.append("form_submit=true")
            if el.get("url"):         parts.append(f'url="{el["url"]}"')
            lines.append("  " + "  |  ".join(parts))

        lines.append("\nVisible Page Text:")
        lines.append(snapshot.get("visible_text_snippet", ""))

        return "\n".join(lines)
