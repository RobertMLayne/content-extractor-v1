"""Placeholder for future plain-text artifact generation."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from ..models import FormatArtifacts


def generate(
    *,
    aggregate_markdown_payload: str,
    dest_dir: Path,
    base_name: str,
    source_url: Optional[str],
) -> FormatArtifacts | None:
    """Return None for now; plain-text generation will be added later."""

    _ = (
        aggregate_markdown_payload,
        dest_dir,
        base_name,
        source_url,
    )
    return None
