from typing import Any, Dict, List
from playwright.async_api import Page


DOM_EXTRACTION_SCRIPT = """
() => {
  const isVisible = (el) => {
    const style = window.getComputedStyle(el);
    if (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') {
      return false;
    }
    const rect = el.getBoundingClientRect();
    return rect.width > 0 && rect.height > 0;
  };

  const buildSelector = (el) => {
    if (el.id) return `#${CSS.escape(el.id)}`;
    if (el.getAttribute('data-testid')) return `[data-testid="${el.getAttribute('data-testid')}"]`;
    if (el.name) return `${el.tagName.toLowerCase()}[name="${el.name}"]`;
    if (el.getAttribute('aria-label')) return `${el.tagName.toLowerCase()}[aria-label="${el.getAttribute('aria-label')}"]`;
    if (el.placeholder) return `${el.tagName.toLowerCase()}[placeholder="${el.placeholder}"]`;

    // Fallback: nth-of-type path
    const parts = [];
    let current = el;
    while (current && current.nodeType === Node.ELEMENT_NODE && current.tagName.toLowerCase() !== 'html') {
      let selector = current.tagName.toLowerCase();
      if (current.id) {
        parts.unshift(`#${CSS.escape(current.id)}`);
        break;
      }
      let sibling = current;
      let nth = 1;
      while ((sibling = sibling.previousElementSibling)) {
        if (sibling.tagName === current.tagName) nth++;
      }
      selector += `:nth-of-type(${nth})`;
      parts.unshift(selector);
      current = current.parentElement;
    }
    return parts.join(' > ');
  };

  const candidates = Array.from(
    document.querySelectorAll('a, button, input, select, textarea, [role="button"], [role="link"], [role="tab"]')
  );

  const elements = [];
  let index = 1;

  for (const el of candidates) {
    if (!isVisible(el)) continue;
    const tag = el.tagName.toLowerCase();
    const type = el.getAttribute('type') || '';
    const text = (el.innerText || el.value || '').trim().replace(/\\s+/g, ' ').slice(0, 80);
    const placeholder = el.getAttribute('placeholder') || '';
    const ariaLabel = el.getAttribute('aria-label') || '';
    const href = tag === 'a' ? (el.getAttribute('href') || '') : '';

    elements.push({
      id: index++,
      tag,
      type,
      selector: buildSelector(el),
      text,
      placeholder,
      aria_label: ariaLabel,
      href: href.slice(0, 120),
    });

    if (elements.length >= 60) break;
  }

  const pageText = (document.body ? document.body.innerText : '')
    .replace(/\\n{3,}/g, '\\n\\n')
    .trim()
    .slice(0, 2500);

  return {
    title: document.title,
    url: window.location.href,
    interactive_elements: elements,
    visible_text_snippet: pageText,
  };
}
"""


class DOMAnalyzer:
    async def inspect(self, page: Page) -> Dict[str, Any]:
        """Extracts compact, token-efficient interactive DOM elements and visible text."""
        snapshot = await page.evaluate(DOM_EXTRACTION_SCRIPT)
        return snapshot

    def format_for_prompt(self, snapshot: Dict[str, Any]) -> str:
        """Formats the DOM snapshot into a compact text block for the Planner LLM."""
        lines: List[str] = [
            f"URL: {snapshot.get('url', '')}",
            f"Title: {snapshot.get('title', '')}",
            "\nInteractive Elements:",
        ]
        for el in snapshot.get("interactive_elements", []):
            desc_parts = [f"[{el['id']}] <{el['tag']}>", f"selector=`{el['selector']}`"]
            if el.get("type"):
                desc_parts.append(f"type={el['type']}")
            if el.get("text"):
                desc_parts.append(f"text=\"{el['text']}\"")
            if el.get("placeholder"):
                desc_parts.append(f"placeholder=\"{el['placeholder']}\"")
            if el.get("aria_label"):
                desc_parts.append(f"aria=\"{el['aria_label']}\"")
            lines.append(" | ".join(desc_parts))

        lines.append("\nVisible Page Text (Truncated):")
        lines.append(snapshot.get("visible_text_snippet", ""))
        return "\n".join(lines)