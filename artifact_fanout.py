"""Shared helpers for generating derivative artifacts from aggregate HTML."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

from bs4 import BeautifulSoup  # type: ignore[import-not-found]

from artifacts.chunking import split_text_on_newlines, write_chunks
from artifacts.cleanup import prepare_output_dir

DEFAULT_BASE_NAME = "rendered_chat"
CHUNK_NAME_RE = re.compile(r"_part_(\d+)_of_(\d+)\.")
SOURCE_URL_COMMENT_RE = re.compile(r"^<!--\s*Source URL:\s*(.*?)\s*-->$")

if TYPE_CHECKING:  # pragma: no cover - typing helper only
    from collections.abc import Callable

    RenderPdfCallable = Callable[[str, str], tuple[bool, str | None]]
    render_pdf_from_html: RenderPdfCallable
else:  # pragma: no cover - runtime import
    from html_to_pdf import render_pdf_from_html  # type: ignore[import]


def parse_chunk_indices(name: str) -> tuple[int, int]:
    """Extract chunk index and total parts from an artifact name."""
    match = CHUNK_NAME_RE.search(name)
    if not match:
        return 0, 0
    return int(match.group(1)), int(match.group(2))


def extract_plain_text(html_payload: str) -> str:
    """Return plain text derived from HTML while preserving line breaks."""
    soup = BeautifulSoup(html_payload, "lxml")
    return soup.get_text("\n")


def extract_source_url(payload: str | None) -> str | None:
    """Pull the source URL out of the leading HTML comment, if present."""
    if not payload:
        return None
    first_line = payload.splitlines()[0].strip()
    match = SOURCE_URL_COMMENT_RE.match(first_line)
    if match:
        return match.group(1).strip()
    return None


def generate_text_artifacts(
    *,
    aggregate_html: str,
    text_dir: Path,
    chunk_char_limit: int,
    base_name: str,
) -> None:
    """Write aggregate and chunked plain-text artifacts for the chat."""
    prepare_output_dir(
        text_dir,
        (
            f"{base_name}.text",
            f"{base_name}_part_*.txt",
        ),
    )

    plain_text = extract_plain_text(aggregate_html)
    aggregate_path = text_dir / f"{base_name}.text"
    aggregate_path.write_text(plain_text, encoding="utf-8")
    print(f"✅ Aggregate text written: {aggregate_path}")

    text_chunks = split_text_on_newlines(plain_text, chunk_char_limit)
    chunk_manifest = write_chunks(
        dest_dir=text_dir,
        base_name=base_name,
        extension=".txt",
        payloads=text_chunks,
        on_write=lambda path: print(f"✅ Text chunk written: {path}"),
    )

    for index, path in enumerate(chunk_manifest.part_paths, start=1):
        expected = (
            text_dir
            / f"{base_name}_part_{index}_of_{chunk_manifest.total_parts}.txt"
        )
        if path == expected:
            continue
        path.rename(expected)


def generate_json_artifacts(
    *,
    dataset_name: str,
    aggregate_html: str,
    aggregate_markdown: str,
    text_dir: Path,
    html_dir: Path,
    markdown_dir: Path,
    json_dir: Path,
    chunk_char_limit: int,
    source_url: str | None = None,
    base_name: str,
) -> None:
    """Build JSON aggregates and chunks combining HTML, Markdown, and text."""
    prepare_output_dir(
        json_dir,
        (
            f"{base_name}.json",
            f"{base_name}_part_*.json",
        ),
    )

    aggregate_text_path = text_dir / f"{base_name}.text"
    aggregate_text = (
        aggregate_text_path.read_text(encoding="utf-8")
        if aggregate_text_path.exists()
        else extract_plain_text(aggregate_html)
    )

    html_chunk_paths: dict[int, Path] = {}
    for path in sorted(html_dir.glob(f"{base_name}_part_*_of_*.html")):
        index, _ = parse_chunk_indices(path.name)
        if not index:
            continue
        html_chunk_paths[index] = path

    markdown_chunk_paths: dict[int, Path] = {}
    for path in sorted(markdown_dir.glob(f"{base_name}_part_*_of_*.md")):
        index, _ = parse_chunk_indices(path.name)
        if not index:
            continue
        markdown_chunk_paths[index] = path

    def fallback_html_chunks() -> tuple[int, dict[int, str]]:
        raw_chunks = split_text_on_newlines(aggregate_html, chunk_char_limit)
        total = len(raw_chunks) or 1
        chunks: dict[int, str] = {}
        for index, payload in enumerate(raw_chunks, start=1):
            lines: list[str] = []
            if source_url:
                lines.append(f"<!-- Source URL: {source_url} -->")
            lines.append(
                f"<!-- HTML Chunk {index}/{total} · {dataset_name} -->"
            )
            lines.append(payload.rstrip())
            chunks[index] = "\n".join(lines).rstrip() + "\n"
        return total, chunks

    def fallback_markdown_chunks(total_parts: int) -> dict[int, str]:
        raw_chunks = split_text_on_newlines(
            aggregate_markdown,
            chunk_char_limit,
        )
        chunks: dict[int, str] = {}
        for index, payload in enumerate(raw_chunks, start=1):
            lines: list[str] = []
            if source_url:
                lines.append(f"<!-- Source URL: {source_url} -->")
            lines.append(
                f"# Markdown Chunk {index}/{len(raw_chunks)} · {dataset_name}"
            )
            lines.append(payload.strip())
            chunks[index] = "\n\n".join(lines).strip() + "\n"
        for missing_index in range(1, total_parts + 1):
            chunks.setdefault(missing_index, "")
        return chunks

    total_parts, regenerated_html = fallback_html_chunks()
    regenerated_markdown = fallback_markdown_chunks(total_parts)

    def read_text(path: Path) -> str | None:
        try:
            return path.read_text(encoding="utf-8")
        except OSError as exc:
            print(
                f"⚠️ Unable to read {path.name}: {exc};"
                " regenerating in-memory content."
            )
            return None

    chunk_entries: list[dict[str, object]] = []
    for part_index in range(1, total_parts + 1):
        html_path = html_chunk_paths.get(part_index)
        html_content = read_text(html_path) if html_path else None
        if html_content is None:
            if not html_path:
                print(
                    "⚠️ HTML chunk missing on disk:",
                    f"{base_name}_part_{part_index}_of_{total_parts}.html",
                )
            html_content = regenerated_html.get(part_index, "")

        markdown_path = markdown_chunk_paths.get(part_index)
        markdown_content = read_text(markdown_path) if markdown_path else None
        if markdown_content is None:
            fallback_markdown = regenerated_markdown.get(part_index, "")
            if not markdown_path:
                if fallback_markdown.strip():
                    print(
                        "⚠️ Markdown chunk missing on disk:",
                        f"{base_name}_part_{part_index}_of_{total_parts}.md",
                    )
            markdown_content = fallback_markdown

        text_content = extract_plain_text(html_content)

        chunk_payload: dict[str, object] = {
            "dataset": dataset_name,
            "part": part_index,
            "total_parts": total_parts,
            "html": html_content,
            "markdown": markdown_content,
            "text": text_content,
        }
        chunk_entries.append(chunk_payload)

        chunk_path = (
            json_dir / f"{base_name}_part_{part_index}_of_{total_parts}.json"
        )
        chunk_path.write_text(
            json.dumps(chunk_payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"✅ JSON chunk written: {chunk_path}")

    aggregate_payload: dict[str, object] = {
        "dataset": dataset_name,
        "generated_at": _now_iso(),
        "aggregate": {
            "html": aggregate_html,
            "markdown": aggregate_markdown,
            "text": aggregate_text,
        },
        "chunks": chunk_entries,
    }

    aggregate_path = json_dir / f"{base_name}.json"
    aggregate_path.write_text(
        json.dumps(aggregate_payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"✅ Aggregate JSON written: {aggregate_path}")


def generate_pdf_artifacts(
    *,
    aggregate_html_path: Path,
    html_dir: Path,
    pdf_dir: Path,
    base_name: str,
) -> None:
    """Render aggregate and per-chunk PDFs from the saved HTML artifacts."""
    prepare_output_dir(
        pdf_dir,
        (
            f"{base_name}.pdf",
            f"{base_name}_part_*.pdf",
        ),
    )

    success, error = render_pdf_from_html(
        str(aggregate_html_path),
        str(pdf_dir / f"{base_name}.pdf"),
    )
    if success:
        print(f"✅ Aggregate PDF written: {pdf_dir / f'{base_name}.pdf'}")
    elif error:
        print(f"⚠️ Failed to render aggregate PDF: {error}")

    html_chunks = sorted(html_dir.glob(f"{base_name}_part_*_of_*.html"))
    for html_chunk_path in html_chunks:
        part_index, total_parts = parse_chunk_indices(html_chunk_path.name)
        target_path = (
            pdf_dir / f"{base_name}_part_{part_index}_of_{total_parts}.pdf"
        )
        success, error = render_pdf_from_html(
            str(html_chunk_path),
            str(target_path),
        )
        if success:
            print(f"✅ PDF chunk written: {target_path}")
        elif error:
            print(
                "⚠️ Failed to render PDF chunk"
                f" {html_chunk_path.name}: {error}"
            )


def fan_out_artifacts(
    *,
    dataset_name: str,
    aggregate_html_payload: str | None,
    aggregate_markdown_payload: str | None,
    html_dir: Path,
    markdown_dir: Path,
    text_dir: Path,
    json_dir: Path,
    pdf_dir: Path,
    chunk_char_limit: int,
    overwrite: bool,
    source_url: str | None = None,
    base_name: str = DEFAULT_BASE_NAME,
) -> None:
    """Coordinate fan-out of derivative artifacts for a conversation."""
    for path in (html_dir, markdown_dir, text_dir, json_dir, pdf_dir):
        path.mkdir(parents=True, exist_ok=True)

    aggregate_html_path = html_dir / f"{base_name}.html"
    markdown_aggregate_path = markdown_dir / f"{base_name}.md"

    if aggregate_html_payload is None and aggregate_html_path.exists():
        aggregate_html_payload = aggregate_html_path.read_text(
            encoding="utf-8"
        )

    if aggregate_markdown_payload is None and markdown_aggregate_path.exists():
        aggregate_markdown_payload = markdown_aggregate_path.read_text(
            encoding="utf-8"
        )

    if aggregate_html_payload is None or aggregate_markdown_payload is None:
        print(
            "⚠️ Unable to locate aggregate HTML/Markdown for"
            f" {dataset_name}; skipping artifact fan-out."
        )
        return

    text_aggregate = text_dir / f"{base_name}.text"
    if overwrite or not text_aggregate.exists():
        generate_text_artifacts(
            aggregate_html=aggregate_html_payload,
            text_dir=text_dir,
            chunk_char_limit=chunk_char_limit,
            base_name=base_name,
        )
    else:
        print(
            "Skipping text conversion; rendered chat text artifacts already"
            " present"
        )

    json_aggregate = json_dir / f"{base_name}.json"
    if overwrite or not json_aggregate.exists():
        generate_json_artifacts(
            dataset_name=dataset_name,
            aggregate_html=aggregate_html_payload,
            aggregate_markdown=aggregate_markdown_payload,
            text_dir=text_dir,
            html_dir=html_dir,
            markdown_dir=markdown_dir,
            json_dir=json_dir,
            chunk_char_limit=chunk_char_limit,
            source_url=source_url
            or extract_source_url(aggregate_html_payload),
            base_name=base_name,
        )
    else:
        print(
            "Skipping JSON conversion; rendered chat JSON artifacts already"
            " present"
        )

    pdf_aggregate = pdf_dir / f"{base_name}.pdf"
    if overwrite or not pdf_aggregate.exists():
        generate_pdf_artifacts(
            aggregate_html_path=aggregate_html_path,
            html_dir=html_dir,
            pdf_dir=pdf_dir,
            base_name=base_name,
        )
    else:
        print(
            "Skipping PDF conversion; rendered chat PDF artifacts already"
            " present"
        )


def _now_iso() -> str:
    """Return a zero-microsecond UTC timestamp in RFC 3339 format."""
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


__all__ = [
    "DEFAULT_BASE_NAME",
    "extract_plain_text",
    "extract_source_url",
    "fan_out_artifacts",
    "generate_json_artifacts",
    "generate_pdf_artifacts",
    "generate_text_artifacts",
    "parse_chunk_indices",
]
