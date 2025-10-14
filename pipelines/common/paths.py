"""Deterministic path helpers that mirror the pipeline spec."""

from __future__ import annotations

import os
from pathlib import Path

SPEC_BASE = Path(r"C:\dev\Projects\content-extractor-v1")


def base_dir() -> Path:
    """Return the repo base directory with optional override for tests."""
    override = os.getenv("CONTENT_EXTRACTOR_BASE")
    if override:
        return Path(override).resolve()
    return SPEC_BASE


def openai_input_root() -> Path:
    return base_dir() / "data" / "inputs" / "openai_data_exports"


def openai_output_root(dataset: str) -> Path:
    return base_dir() / "data" / "outputs" / "openai_data_exports" / dataset


def urls_input_root() -> Path:
    return base_dir() / "data" / "inputs" / "urls"


def urls_output_root(domain: str) -> Path:
    return base_dir() / "data" / "outputs" / "urls" / domain


def pdf_input_root() -> Path:
    return base_dir() / "data" / "inputs" / "pdfs"


def pdf_output_root(pdf_name: str) -> Path:
    return base_dir() / "data" / "outputs" / "pdfs" / pdf_name
