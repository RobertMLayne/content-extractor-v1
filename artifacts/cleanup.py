"""Cleanup utilities for artifact directories."""

from __future__ import annotations

from pathlib import Path
from typing import Iterable

from .chunking import clear_existing_files


def prepare_output_dir(path: Path, patterns_to_clear: Iterable[str]) -> None:
    """Ensure the output directory exists and remove stale artifacts."""

    path.mkdir(parents=True, exist_ok=True)
    clear_existing_files(path, patterns_to_clear)
