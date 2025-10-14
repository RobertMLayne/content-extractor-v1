"""Render ChatGPT transcripts with Playwright to capture dynamic content."""

# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false

import argparse
from typing import Any, Optional

try:
    from playwright.sync_api import (  # type: ignore[import-not-found]
        sync_playwright,
    )
except ImportError as exc:
    raise SystemExit(
        "Missing dependency 'playwright'. Install with pip install"
        " playwright && playwright install"
    ) from exc

from config_loader import ConfigError, resolve_runtime_paths


def render_html(input_path: str, output_path: str) -> None:
    """Render ``input_path`` via Playwright and persist the HTML result."""

    with sync_playwright() as playwright_context:  # type: ignore[misc]
        playwright_api: Any = playwright_context
        launch = playwright_api.chromium.launch  # type: ignore[attr-defined]
        browser: Any = launch(headless=True)
        page: Any = browser.new_page()  # type: ignore[call-arg]
        page.goto(f'file:///{input_path}')
        page.wait_for_load_state('networkidle')
        content: str = str(page.content())
        with open(output_path, 'w', encoding='utf-8') as output_file:
            output_file.write(content)
        browser.close()


def parse_args() -> argparse.Namespace:
    """Parse CLI arguments for the HTML rendering helper."""

    parser = argparse.ArgumentParser(
        description=(
            "Generate a fully rendered ChatGPT transcript via Playwright."
        )
    )
    parser.add_argument("--config", help="Path to config JSON file.")
    parser.add_argument(
        "--input-html", help="Override source chat HTML export path."
    )
    parser.add_argument(
        "--rendered-html", help="Override rendered HTML destination path."
    )
    return parser.parse_args()


def main() -> None:
    """Entry point for the HTML rendering CLI."""

    args = parse_args()
    try:
        runtime = resolve_runtime_paths(
            config_path=args.config,
            input_html=args.input_html,
            rendered_html=args.rendered_html,
        )
    except ConfigError as exc:
        raise SystemExit(f"Config error: {exc}") from exc

    rendered_path: Optional[str] = runtime.get("rendered_html")
    if not rendered_path:
        raise SystemExit(
            "Config error: rendered_html path missing. Set it in config or"
            " supply --rendered-html."
        )

    render_html(runtime["input_html"], rendered_path)
    print(f"Rendered HTML saved to {rendered_path}")


if __name__ == "__main__":
    main()
