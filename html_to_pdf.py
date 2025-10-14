"""Utilities for exporting rendered HTML artifacts to PDF."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Tuple

try:
    from playwright.sync_api import (  # type: ignore[import-not-found]
        Error as PlaywrightError,
        sync_playwright,
    )
except ImportError as exc:  # pragma: no cover - handled at runtime
    raise SystemExit(
        "Missing dependency 'playwright'. Install with pip install"
        " playwright && playwright install"
    ) from exc


def render_pdf_from_html(
    input_html: str, output_pdf: str
) -> Tuple[bool, str | None]:
    """Render a static HTML document to PDF using Playwright."""

    html_path = Path(input_html).resolve()
    pdf_path = Path(output_pdf)
    pdf_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        with sync_playwright() as playwright_context:  # type: ignore[misc]
            chromium = playwright_context.chromium
            browser: Any = chromium.launch(headless=True)
            page: Any = browser.new_page()
            page.goto(html_path.as_uri())
            page.wait_for_load_state("networkidle")
            page.pdf(path=str(pdf_path))
            browser.close()
        return True, None
    except PlaywrightError as exc:  # pragma: no cover - best effort logging
        return False, str(exc)


__all__ = ["render_pdf_from_html"]
