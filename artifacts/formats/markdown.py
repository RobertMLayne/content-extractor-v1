"""Write Markdown aggregate, chunk, and combined artifacts."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from ..cleanup import prepare_output_dir
from ..chunking import (
    clear_existing_files,
    pair_segments,
    split_text_on_newlines,
    write_chunks,
)
from ..models import CombinedArtifacts, FormatArtifacts


def generate(
    *,
    aggregate_payload: str,
    dest_dir: Path,
    base_name: str,
    label: str,
    chunk_char_limit: int,
    source_url: Optional[str],
    html_payload: str,
) -> tuple[FormatArtifacts, CombinedArtifacts]:
    dest_dir = Path(dest_dir)
    prepare_output_dir(
        dest_dir,
        (
            f"{base_name}.md",
            f"{base_name}_part_*.md",
            "aggregate.md",
            "markdown_part_*.md",
        ),
    )

    aggregate_path = dest_dir / f"{base_name}.md"
    aggregate_path.write_text(aggregate_payload, encoding="utf-8")
    print(f"✅ Aggregate Markdown written: {aggregate_path}")

    markdown_chunks = split_text_on_newlines(
        aggregate_payload, chunk_char_limit
    )
    total_markdown_chunks = len(markdown_chunks)
    chunk_payloads: list[str] = []
    for index, markdown_part in enumerate(markdown_chunks, start=1):
        lines: list[str] = []
        if source_url:
            lines.append(f"<!-- Source URL: {source_url} -->")
        lines.append(
            f"# Markdown Chunk {index}/{total_markdown_chunks} · {label}"
        )
        lines.append(markdown_part.strip())
        chunk_payloads.append("\n\n".join(lines).strip() + "\n")

    chunk_manifest = write_chunks(
        dest_dir=dest_dir,
        base_name=base_name,
        extension=".md",
        payloads=chunk_payloads,
        on_write=lambda path: print(f"✅ Markdown chunk written: {path}"),
    )

    combined_artifacts = _write_combined_artifacts(
        dest_dir=dest_dir,
        aggregate_html_payload=html_payload,
        aggregate_markdown_payload=aggregate_payload,
        source_url=source_url,
        chunk_char_limit=chunk_char_limit,
        label=label,
    )

    format_artifacts = FormatArtifacts(
        aggregate_path=aggregate_path,
        chunk_manifest=chunk_manifest,
    )
    return format_artifacts, combined_artifacts


def _write_combined_artifacts(
    *,
    dest_dir: Path,
    aggregate_html_payload: str,
    aggregate_markdown_payload: str,
    source_url: Optional[str],
    chunk_char_limit: int,
    label: str,
) -> CombinedArtifacts:
    half_limit = max(1, chunk_char_limit // 2)
    clear_existing_files(dest_dir, ("combined_part_*.md",))

    combined_html_segments = split_text_on_newlines(
        aggregate_html_payload,
        half_limit,
    )
    combined_markdown_segments = split_text_on_newlines(
        aggregate_markdown_payload,
        half_limit,
    )

    total_chunks = max(
        len(combined_html_segments), len(combined_markdown_segments)
    )

    if total_chunks == 0:
        return CombinedArtifacts(part_paths=[])

    part_paths: list[Path] = []
    total_combined_html = len(combined_html_segments)
    total_combined_md = len(combined_markdown_segments)

    for index, html_part, markdown_part in pair_segments(
        combined_html_segments, combined_markdown_segments
    ):
        chunk_number = index + 1
        chunk_path = dest_dir / f"combined_part_{chunk_number:02d}.md"
        lines: list[str] = []
        if source_url:
            lines.append(f"<!-- Source URL: {source_url} -->")
        lines.append(
            f"# Combined Chunk {chunk_number}/{total_chunks} · {label}"
        )

        if html_part.strip():
            lines.append(
                "## Rendered HTML Segment "
                f"{chunk_number}/{total_combined_html}"
            )
            lines.append("```html")
            lines.append(html_part.rstrip())
            lines.append("```")

        if markdown_part.strip():
            lines.append(
                "## Markdown Segment " f"{chunk_number}/{total_combined_md}"
            )
            lines.append(markdown_part.strip())

        chunk_payload = "\n\n".join(lines).strip() + "\n"
        chunk_path.write_text(chunk_payload, encoding="utf-8")
        part_paths.append(chunk_path)
        print(f"✅ Combined file written: {chunk_path}")

    return CombinedArtifacts(part_paths=part_paths)
