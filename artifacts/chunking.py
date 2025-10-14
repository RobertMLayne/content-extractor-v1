"""Chunking helpers shared across artifact formats."""

from __future__ import annotations

from pathlib import Path
from typing import Callable, Iterable, Iterator, List, Optional, Sequence

from .models import ChunkManifest


def clear_existing_files(directory: Path, patterns: Iterable[str]) -> None:
    """Delete files that match the provided glob patterns inside directory."""

    for pattern in patterns:
        for target in directory.glob(pattern):
            if target.is_file():
                target.unlink()


def split_text_on_newlines(text: str, max_chars: int) -> List[str]:
    """Split text into chunks no larger than max_chars, preserving newlines."""

    if not text:
        return [""]

    chunks: List[str] = []
    cursor = 0
    length = len(text)
    while cursor < length:
        limit = min(length, cursor + max_chars)
        if limit < length:
            newline_break = text.rfind("\n", cursor, limit)
            if newline_break > cursor + max_chars * 0.5:
                limit = newline_break + 1
        segment = text[cursor:limit]
        if not segment:
            segment = text[cursor:cursor + max_chars]
        chunks.append(segment)
        cursor = limit
    return chunks


def pair_segments(
    html_segments: Sequence[str], markdown_segments: Sequence[str]
) -> Iterator[tuple[int, str, str]]:
    """Zip HTML and Markdown segments while padding shorter sequences."""

    total = max(len(html_segments), len(markdown_segments))
    for idx in range(total):
        html_part = html_segments[idx] if idx < len(html_segments) else ""
        md_part = (
            markdown_segments[idx] if idx < len(markdown_segments) else ""
        )
        yield idx, html_part, md_part


def write_chunks(
    *,
    dest_dir: Path,
    base_name: str,
    extension: str,
    payloads: Sequence[str],
    on_write: Optional[Callable[[Path], None]] = None,
) -> ChunkManifest:
    """Persist chunk payloads using the shared naming convention."""

    total = len(payloads)
    part_paths: List[Path] = []
    for index, payload in enumerate(payloads, start=1):
        filename = f"{base_name}_part_{index}_of_{total}{extension}"
        chunk_path = dest_dir / filename
        chunk_path.write_text(payload, encoding="utf-8")
        if on_write is not None:
            on_write(chunk_path)
        part_paths.append(chunk_path)
    return ChunkManifest(total_parts=total, part_paths=part_paths)
