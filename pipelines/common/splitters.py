"""Part-splitting helpers that honor the spec naming scheme."""

from __future__ import annotations

import io
import json
from pathlib import Path
from typing import Any, Iterable, cast

try:
    from bs4 import BeautifulSoup
except ImportError as exc:  # pragma: no cover - surfaced at runtime
    raise SystemExit(
        "Missing dependency 'beautifulsoup4'. Install with pip install "
        "beautifulsoup4"
    ) from exc

try:
    from PyPDF2 import PdfReader, PdfWriter  # type: ignore[import-not-found]
except ImportError as exc:  # pragma: no cover - surfaced at runtime
    raise SystemExit(
        "Missing dependency 'PyPDF2'. Install with pip install PyPDF2"
    ) from exc

from .checksum import write_if_changed


def _write_chunks(
    path: Path, extension: str, payloads: Iterable[bytes]
) -> list[Path]:
    """Write chunk payloads to disk and return the created paths."""

    base_name = path.stem
    dest_dir = path.parent
    payload_list = list(payloads)
    total_parts = len(payload_list) or 1
    written: list[Path] = []
    for index, payload in enumerate(payload_list or [b""], start=1):
        chunk_path = (
            dest_dir / f"{base_name}_part_{index}_of_{total_parts}{extension}"
        )
        changed = write_if_changed(chunk_path, payload)
        if changed:
            print(f"✅ Chunk written: {chunk_path}")
        else:
            print(f"⏭️ Chunk unchanged: {chunk_path}")
        written.append(chunk_path)
    return written


def split_html(
    path: str | Path,
    *,
    max_bytes: int | None = None,
    max_nodes: int | None = None,
) -> list[Path]:
    """Split raw HTML by nodes or bytes depending on the provided limits."""

    path = Path(path)
    payload = path.read_text(encoding="utf-8")
    if not max_bytes and not max_nodes:
        max_bytes = 200_000
    if max_nodes:
        chunks = _split_html_by_nodes(payload, max_nodes)
    else:
        chunks = _split_by_bytes(payload, max_bytes or 1)
    return _write_chunks(
        path, ".html", (chunk.encode("utf-8") for chunk in chunks)
    )


def _split_html_by_nodes(payload: str, max_nodes: int) -> list[str]:
    """Split HTML into chunks containing at most ``max_nodes`` nodes."""

    soup = BeautifulSoup(payload, "lxml")
    body = soup.body or soup
    nodes = list(body.children)
    if not nodes:
        return [payload]
    chunks: list[str] = []
    cursor = 0
    total = len(nodes)
    while cursor < total:
        segment = nodes[cursor:cursor + max_nodes]
        cursor += max_nodes
        wrapper = BeautifulSoup("", "lxml")
        container = wrapper.new_tag("body")
        wrapper.append(container)
        for node in segment:
            container.append(node)
        chunks.append(wrapper.decode())
    return chunks


def _split_by_bytes(payload: str, limit: int) -> list[str]:
    """Split ``payload`` into byte windows that never exceed ``limit``."""

    if limit <= 0:
        return [payload]
    encoded = payload.encode("utf-8")
    if len(encoded) <= limit:
        return [payload]
    chunks: list[str] = []
    cursor = 0
    total_bytes = len(encoded)
    while cursor < total_bytes:
        window = encoded[cursor:cursor + limit]
        try:
            chunk = window.decode("utf-8")
        except UnicodeDecodeError:
            slice_end = limit
            while slice_end > 0:
                try:
                    chunk = encoded[cursor:cursor + slice_end].decode(
                        "utf-8"
                    )
                except UnicodeDecodeError:
                    slice_end -= 1
                    continue
                cursor += slice_end
                break
            else:
                chunk = encoded[cursor:cursor + limit].decode(
                    "latin-1", "ignore"
                )
                cursor += limit
        else:
            cursor += len(window)
        chunks.append(chunk)
    return chunks


def split_md(path: str | Path, *, max_chars: int) -> list[Path]:
    """Split a Markdown file into parts capped at ``max_chars`` each."""

    path = Path(path)
    payload = path.read_text(encoding="utf-8")
    chunks = _split_text(payload, max_chars)
    return _write_chunks(
        path, ".md", (chunk.encode("utf-8") for chunk in chunks)
    )


def split_txt(path: str | Path, *, max_chars: int) -> list[Path]:
    """Split a plain-text file into parts capped at ``max_chars`` each."""

    path = Path(path)
    payload = path.read_text(encoding="utf-8")
    chunks = _split_text(payload, max_chars)
    return _write_chunks(
        path, ".txt", (chunk.encode("utf-8") for chunk in chunks)
    )


def _split_text(payload: str, max_chars: int) -> list[str]:
    """Split a text payload into evenly sized character windows."""

    if max_chars <= 0 or len(payload) <= max_chars:
        return [payload]
    chunks: list[str] = []
    cursor = 0
    while cursor < len(payload):
        end = min(len(payload), cursor + max_chars)
        chunk = payload[cursor:end]
        chunks.append(chunk)
        cursor = end
    return chunks


def split_json(
    path: str | Path,
    *,
    max_items: int | None = None,
    max_bytes: int | None = None,
) -> list[Path]:
    """Split JSON aggregates by items and optional byte ceilings."""

    path = Path(path)
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict) and "chunks" in data:
        items: list[Any] = list(cast(Iterable[Any], data["chunks"]))
    elif isinstance(data, list):
        items = list(cast(Iterable[Any], data))
    else:
        items = [data]
    if max_items is None:
        max_items = len(items)
    chunks: list[list[Any]] = []
    cursor = 0
    total = len(items)
    while cursor < total:
        subset = items[cursor:cursor + max_items]
        cursor += max_items
        if max_bytes:
            encoded = json.dumps(subset, ensure_ascii=False).encode("utf-8")
            if len(encoded) > max_bytes and len(subset) > 1:
                half = max(1, len(subset) // 2)
                cursor -= len(subset) - half
                subset = subset[:half]
        chunks.append(subset)
    return _write_chunks(
        path,
        ".json",
        (
            json.dumps(chunk, ensure_ascii=False, indent=2).encode("utf-8")
            for chunk in chunks
        ),
    )


def split_pdf(path: str | Path, *, max_pages: int) -> list[Path]:
    """Split a PDF into smaller files, each containing ``max_pages`` pages."""

    path = Path(path)
    reader = cast(Any, PdfReader(str(path)))
    total_pages = len(reader.pages)
    if total_pages == 0:
        return _write_chunks(path, ".pdf", [b""])
    chunks: list[bytes] = []
    for start in range(0, total_pages, max_pages):
        writer = cast(Any, PdfWriter())
        for page_index in range(start, min(total_pages, start + max_pages)):
            writer.add_page(reader.pages[page_index])
        buffer = io.BytesIO()
        writer.write(buffer)
        chunks.append(buffer.getvalue())
    return _write_chunks(path, ".pdf", chunks)


__all__ = [
    "split_html",
    "split_md",
    "split_json",
    "split_pdf",
    "split_txt",
]
