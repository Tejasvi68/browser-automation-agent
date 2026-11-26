"""
ScreenshotManager – captures and stores per-step browser screenshots.

Each screenshot is:
  1. Saved to disk at screenshots/{run_id}/step_NN_{timestamp}.png
     so the replay viewer can serve them via /screenshots/<path>
  2. Returned as a base64 string so the LLM can optionally analyze it
     without reading a file from disk.
"""

import base64
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict

from playwright.async_api import Page


class ScreenshotManager:
    def __init__(self, base_dir: str = "screenshots"):
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)

    async def capture(self, page: Page, run_id: str, step_number: int) -> Dict[str, str]:
        """
        Captures a viewport screenshot, saves it to disk, and returns:
          - step:        step number
          - file_path:   path relative to the server root (forward slashes)
          - base64:      base64-encoded PNG for inline display or vision LLM
          - url:         current page URL at the time of capture
        """
        # Each run gets its own subfolder
        run_dir = self.base_dir / run_id
        run_dir.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
        filename  = f"step_{step_number:02d}_{timestamp}.png"
        file_path = run_dir / filename

        # Capture viewport only (full_page=False keeps files small)
        raw_bytes = await page.screenshot(path=str(file_path), full_page=False)
        b64_image = base64.b64encode(raw_bytes).decode("utf-8")

        return {
            "step":      step_number,
            "file_path": str(file_path).replace("\\", "/"),  # Always use forward slashes
            "base64":    b64_image,
            "url":       page.url,
        }
