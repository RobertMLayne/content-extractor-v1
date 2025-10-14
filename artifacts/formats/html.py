"""Write HTML aggregate and chunk artifacts."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from ..cleanup import prepare_output_dir
from ..chunking import split_text_on_newlines, write_chunks
from ..models import FormatArtifacts


def generate(
    *,
    aggregate_payload: str,
    dest_dir: Path,
    base_name: str,
    label: str,
    chunk_char_limit: int,
    source_url: Optional[str],
) -> FormatArtifacts:
    dest_dir = Path(dest_dir)
    prepare_output_dir(
        dest_dir,
        (
            f"{base_name}.html",
            f"{base_name}_part_*.html",
            "aggregate.html",
            "html_part_*.html",
        ),
    )

    aggregate_path = dest_dir / f"{base_name}.html"
    aggregate_path.write_text(aggregate_payload, encoding="utf-8")
    print(f"✅ Aggregate HTML written: {aggregate_path}")

    html_chunks = split_text_on_newlines(aggregate_payload, chunk_char_limit)
    total_html_chunks = len(html_chunks)
    chunk_payloads: list[str] = []
    for index, html_part in enumerate(html_chunks, start=1):
        lines: list[str] = []
        if source_url:
            lines.append(f"<!-- Source URL: {source_url} -->")
        lines.append(
            f"<!-- HTML Chunk {index}/{total_html_chunks} · {label} -->"
        )
        lines.append(html_part.rstrip())
        chunk_payloads.append("\n".join(lines).rstrip() + "\n")

    chunk_manifest = write_chunks(
        dest_dir=dest_dir,
        base_name=base_name,
        extension=".html",
        payloads=chunk_payloads,
        on_write=lambda path: print(f"✅ HTML chunk written: {path}"),
    )

    return FormatArtifacts(
        aggregate_path=aggregate_path,
        chunk_manifest=chunk_manifest,
    )
