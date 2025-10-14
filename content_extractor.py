"""Legacy HTML to Markdown splitter that predates the artifacts pipeline."""

import argparse
import os
from typing import Any, List

try:
    from bs4 import BeautifulSoup  # type: ignore[import-not-found]
except ImportError as exc:
    raise SystemExit(
        "Missing dependency 'beautifulsoup4'. Install with pip install"
        " beautifulsoup4"
    ) from exc

try:
    from markdownify import markdownify as md  # type: ignore[import-not-found]
except ImportError as exc:
    raise SystemExit(
        "Missing dependency 'markdownify'. Install with pip install"
        " markdownify"
    ) from exc

from config_loader import ConfigError, resolve_runtime_paths


def split_markdown(markdown_text: str, parts: int = 5) -> List[str]:
    """Split Markdown text into the requested number of parts."""

    lines = markdown_text.split("\n")
    avg_len = len(lines) // parts
    splits: List[str] = []
    for i in range(parts):
        start = i * avg_len
        end = (i + 1) * avg_len if i < parts - 1 else len(lines)
        splits.append("\n".join(lines[start:end]))
    return splits


def convert_html_to_md_files(
    input_html: str, output_dir: str, parts: int = 5
) -> None:
    """Convert the source HTML into Markdown chunks in ``output_dir``."""

    os.makedirs(output_dir, exist_ok=True)

    with open(input_html, "r", encoding="utf-8") as file:
        soup: Any = BeautifulSoup(file, "lxml")

    soup_text: str = str(soup)

    markdown_text: str = md(
        soup_text,
        heading_style="ATX",
    )

    markdown_parts: List[str] = split_markdown(markdown_text, parts)

    for idx, part in enumerate(markdown_parts, 1):
        file_path = os.path.join(output_dir, f"chat_part_{idx}.md")
        with open(file_path, "w", encoding="utf-8") as md_file:
            md_file.write(part)
        print(f"Written: {file_path}")


def parse_args() -> argparse.Namespace:
    """Build and return the CLI argument parser for the legacy script."""

    parser = argparse.ArgumentParser(
        description="Convert ChatGPT HTML transcripts into Markdown chunks."
    )
    parser.add_argument("--config", help="Path to config JSON file.")
    parser.add_argument("--input-html", help="Override input HTML path.")
    parser.add_argument(
        "--output-dir", help="Override Markdown output directory."
    )
    parser.add_argument(
        "--parts", type=int, help="Override number of Markdown parts."
    )
    return parser.parse_args()


if __name__ == '__main__':
    args = parse_args()
    try:
        runtime = resolve_runtime_paths(
            config_path=args.config,
            input_html=args.input_html,
            output_dir=args.output_dir,
            parts=args.parts,
        )
    except ConfigError as exc:
        raise SystemExit(f"Config error: {exc}") from exc

    convert_html_to_md_files(
        runtime["input_html"],
        runtime["markdown_output_dir"],
        parts=runtime["split_parts"],
    )
