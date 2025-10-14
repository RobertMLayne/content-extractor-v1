"""Compatibility wrapper around the artifacts pipeline."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from artifacts import (
    DEFAULT_CHUNK_CHAR_LIMIT,
    ConversionSummary,
    generate_all,
    write_domain_aggregates,
)


@dataclass(slots=True)
class ConversionResult:
    """Backwards-compatible result returned by convert_html_to_md."""

    aggregate_html: str
    aggregate_markdown: str


@dataclass(slots=True)
class ConversionOptions:
    """Optional knobs that control how conversion work executes."""

    source_url: Optional[str] = None
    chunk_char_limit: int = DEFAULT_CHUNK_CHAR_LIMIT
    label: Optional[str] = None
    html_output_dir: Optional[str] = None
    base_filename: Optional[str] = None


def convert_html_to_md(
    input_html: str,
    output_dir: str,
    *,
    options: ConversionOptions | None = None,
) -> ConversionResult:
    """Render Markdown artifacts using the new pipeline implementation."""

    resolved = options or ConversionOptions()
    label = resolved.label or Path(input_html).stem

    summary: ConversionSummary = generate_all(
        rendered_html_path=Path(input_html),
        markdown_output_dir=Path(output_dir),
        chunk_char_limit=resolved.chunk_char_limit,
        label=label,
        source_url=resolved.source_url,
        html_output_dir=(
            Path(resolved.html_output_dir)
            if resolved.html_output_dir
            else None
        ),
        base_filename=resolved.base_filename,
    )

    return ConversionResult(
        aggregate_html=summary.aggregate_html,
        aggregate_markdown=summary.aggregate_markdown,
    )


def parse_args() -> argparse.Namespace:
    """Return CLI arguments for the rendered HTML conversion tool."""

    parser = argparse.ArgumentParser(
        description="Convert rendered HTML exports into Markdown chunks.",
    )
    parser.add_argument("input_html", help="Input rendered HTML file.")
    parser.add_argument("output_dir", help="Directory for Markdown output.")
    parser.add_argument(
        "--chunk-char-limit",
        type=int,
        default=DEFAULT_CHUNK_CHAR_LIMIT,
        help="Maximum characters per chunk (defaults to 40k).",
    )
    parser.add_argument(
        "--label",
        help="Optional label used in log headers and chunk metadata.",
    )
    parser.add_argument(
        "--source-url",
        help="Optional URL annotation appended to each artifact.",
    )
    parser.add_argument(
        "--html-output-dir",
        help="Override directory for HTML aggregates/chunks.",
    )
    parser.add_argument(
        "--base-filename",
        help="Base name for aggregate/chunk artifacts (default derived).",
    )
    return parser.parse_args()


def main() -> None:
    """Entry point for the ``convert_rendered_html_to_md`` CLI."""

    args = parse_args()
    input_html = Path(args.input_html)
    output_dir = Path(args.output_dir)

    if not input_html.exists():
        raise SystemExit(f"Input HTML not found: {input_html}")

    options = ConversionOptions(
        source_url=args.source_url,
        chunk_char_limit=args.chunk_char_limit,
        label=args.label,
        html_output_dir=args.html_output_dir,
        base_filename=args.base_filename,
    )

    convert_html_to_md(str(input_html), str(output_dir), options=options)


__all__ = [
    "ConversionResult",
    "ConversionOptions",
    "DEFAULT_CHUNK_CHAR_LIMIT",
    "convert_html_to_md",
    "write_domain_aggregates",
]


if __name__ == "__main__":
    main()
