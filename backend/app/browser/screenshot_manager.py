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
        """Captures a screenshot, saves it to disk for replay, and returns base64 + file path."""
        run_dir = self.base_dir / run_id
        run_dir.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
        filename = f"step_{step_number:02d}_{timestamp}.png"
        file_path = run_dir / filename

        raw_bytes = await page.screenshot(path=str(file_path), full_page=False)
        b64_image = base64.b64encode(raw_bytes).decode("utf-8")

        return {
            "step": step_number,
            "file_path": str(file_path).replace("\\", "/"),
            "base64": b64_image,
            "url": page.url,
        }