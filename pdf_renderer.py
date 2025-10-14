"""Utility helpers for rendering PDFs into HTML payloads."""

from __future__ import annotations

import io
from pathlib import Path
from typing import Tuple

try:
    from pdfminer.high_level import (  # type: ignore[import-not-found]
        extract_text_to_fp,
    )
    from pdfminer.layout import LAParams  # type: ignore[import-not-found]
    from pdfminer.pdfparser import (  # type: ignore[import-not-found]
        PDFSyntaxError,
    )
except ImportError as exc:  # pragma: no cover - surfaces missing dependency
    raise SystemExit(
        (
            "Missing dependency 'pdfminer.six'. Install with "
            "pip install pdfminer.six"
        )
    ) from exc


def render_pdf_to_html(
    pdf_path: str, output_path: str
) -> Tuple[bool, str | None]:
    """Render ``pdf_path`` into ``output_path`` HTML and report status."""

    source = Path(pdf_path)
    destination = Path(output_path)

    if not source.exists():
        return False, f"PDF not found: {source}"

    try:
        buffer = io.BytesIO()
        with source.open("rb") as pdf_file:
            extract_text_to_fp(
                pdf_file,
                buffer,
                laparams=LAParams(),
                output_type="html",
            )
    except (PDFSyntaxError, OSError) as exc:
        return False, str(exc)

    html_payload = buffer.getvalue().decode("utf-8", errors="ignore").strip()
    if not html_payload:
        return False, "PDF produced empty HTML output"

    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(html_payload, encoding="utf-8")
    return True, None


__all__ = ["render_pdf_to_html"]
