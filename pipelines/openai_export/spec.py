from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from convert_rendered_html_to_md import (  # type: ignore[import]
    DEFAULT_CHUNK_CHAR_LIMIT,
)


@dataclass(slots=True)
class Spec:
    """Inputs controlling the OpenAI export pipeline."""

    zip_path: Path
    chunk_char_limit: int = DEFAULT_CHUNK_CHAR_LIMIT
    overwrite: bool = False
