"""High-level orchestration for artifact generation."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

try:
    from bs4 import BeautifulSoup  # type: ignore[import-not-found]
except ImportError as exc:
    raise SystemExit(
        "Missing dependency 'beautifulsoup4'. Install with pip install"
        " beautifulsoup4"
    ) from exc

try:
    from markdownify import markdownify as md  # type: ignore[import-not-found]
except ImportError as exc:
    raise SystemExit(
        "Missing dependency 'markdownify'. Install with pip install"
        " markdownify"
    ) from exc

from .formats import html as html_format
from .formats import markdown as markdown_format
from .models import CombinedArtifacts, FormatArtifacts

DEFAULT_CHUNK_CHAR_LIMIT = 40_000


@dataclass(slots=True)
class ConversionSummary:
    """Represents the outputs of generate_all for callers."""

    aggregate_html: str
    aggregate_markdown: str
    html: FormatArtifacts
    markdown: FormatArtifacts
    combined: CombinedArtifacts
    text: FormatArtifacts | None


def generate_all(
    *,
    rendered_html_path: Path | str,
    markdown_output_dir: Path | str,
    chunk_char_limit: int,
    label: str,
    source_url: Optional[str],
    html_output_dir: Path | str | None,
    base_filename: Optional[str],
) -> ConversionSummary:
    """Produce aggregate and chunk artifacts for Markdown and HTML outputs."""

    rendered_html_path = Path(rendered_html_path)
    markdown_output_dir = Path(markdown_output_dir)
    html_output_dir = (
        Path(html_output_dir)
        if html_output_dir is not None
        else markdown_output_dir
    )
    base_name = base_filename or label or rendered_html_path.stem

    with rendered_html_path.open("r", encoding="utf-8") as file:
        soup = BeautifulSoup(file, "lxml")

    soup_text = str(soup)

    aggregate_html_payload = soup_text
    if source_url:
        aggregate_html_payload = (
            f"<!-- Source URL: {source_url} -->\n" + aggregate_html_payload
        )

    aggregate_markdown_payload = md(
        soup_text,
        heading_style="ATX",
    )
    if source_url and not aggregate_markdown_payload.startswith(
        "<!-- Source URL"
    ):
        aggregate_markdown_payload = (
            f"<!-- Source URL: {source_url} -->\n" + aggregate_markdown_payload
        )

    html_artifacts = html_format.generate(
        aggregate_payload=aggregate_html_payload,
        dest_dir=html_output_dir,
        base_name=base_name,
        label=label,
        chunk_char_limit=chunk_char_limit,
        source_url=source_url,
    )

    markdown_artifacts, combined_artifacts = markdown_format.generate(
        aggregate_payload=aggregate_markdown_payload,
        dest_dir=markdown_output_dir,
        base_name=base_name,
        label=label,
        chunk_char_limit=chunk_char_limit,
        source_url=source_url,
        html_payload=aggregate_html_payload,
    )

    text_artifacts = None

    return ConversionSummary(
        aggregate_html=aggregate_html_payload,
        aggregate_markdown=aggregate_markdown_payload,
        html=html_artifacts,
        markdown=markdown_artifacts,
        combined=combined_artifacts,
        text=text_artifacts,
    )


def write_domain_aggregates(
    *,
    domain_label: str,
    rendered_domain_root: Path,
    markdown_domain_root: Path,
    chunk_char_limit: int,
) -> None:
    """Build domain-level aggregate artifacts spanning all URL slugs."""

    slug_render_dirs = sorted(
        path
        for path in rendered_domain_root.iterdir()
        if path.is_dir() and path.name != "_domain"
    )
    slug_markdown_dirs = sorted(
        path
        for path in markdown_domain_root.iterdir()
        if path.is_dir() and path.name != "_domain"
    )

    if not slug_render_dirs or not slug_markdown_dirs:
        return

    domain_html_fragments: list[str] = []
    for slug_dir in slug_render_dirs:
        aggregate_path = slug_dir / "aggregate.html"
        if not aggregate_path.exists():
            continue
        html_payload = aggregate_path.read_text(encoding="utf-8").strip()
        domain_html_fragments.append(
            "\n".join(
                [
                    f"<!-- Start: {slug_dir.name} -->",
                    html_payload,
                    f"<!-- End: {slug_dir.name} -->",
                ]
            ).strip()
        )

    domain_markdown_fragments: list[str] = []
    for slug_dir in slug_markdown_dirs:
        aggregate_path = slug_dir / "aggregate.md"
        if not aggregate_path.exists():
            continue
        md_payload = aggregate_path.read_text(encoding="utf-8").strip()
        domain_markdown_fragments.append(
            f"# Source · {slug_dir.name}\n\n{md_payload}"
        )

    if not domain_html_fragments or not domain_markdown_fragments:
        return

    aggregate_html_payload = "\n\n".join(domain_html_fragments).strip() + "\n"
    aggregate_markdown_payload = (
        "\n\n".join(domain_markdown_fragments).strip() + "\n"
    )

    html_output_path = rendered_domain_root / "_domain"
    markdown_output_path = markdown_domain_root / "_domain"

    html_format.generate(
        aggregate_payload=aggregate_html_payload,
        dest_dir=html_output_path,
        base_name=domain_label,
        label=f"{domain_label} aggregate",
        chunk_char_limit=chunk_char_limit,
        source_url=None,
    )

    markdown_format.generate(
        aggregate_payload=aggregate_markdown_payload,
        dest_dir=markdown_output_path,
        base_name=domain_label,
        label=f"{domain_label} aggregate",
        chunk_char_limit=chunk_char_limit,
        source_url=None,
        html_payload=aggregate_html_payload,
    )
