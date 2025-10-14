"""Shared dataclasses for artifact generation."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import List


@dataclass(slots=True)
class ChunkManifest:
    """Tracks chunk metadata for a given artifact type."""

    total_parts: int
    part_paths: List[Path]


@dataclass(slots=True)
class FormatArtifacts:
    """Represents the aggregate artifact and its chunk manifest."""

    aggregate_path: Path
    chunk_manifest: ChunkManifest


@dataclass(slots=True)
class CombinedArtifacts:
    """Represents combined markdown chunk files (no aggregate artefact)."""

    part_paths: List[Path]
