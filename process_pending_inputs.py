"""Process pending inputs located under the inputs/ directory."""

from __future__ import annotations

import argparse
import json
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from artifact_fanout import fan_out_artifacts  # type: ignore[import]
from config_loader import ConfigError, load_config
from convert_rendered_html_to_md import (
    DEFAULT_CHUNK_CHAR_LIMIT,
    ConversionOptions,
    ConversionResult,
    convert_html_to_md,
)
from pdf_renderer import render_pdf_to_html
from process_urls import (
    markdown_is_stale,
    process_urls,
    read_urls,
    UrlProcessingOptions,
)
from render_chat_html import render_html

DATA_ROOT = Path("data")
INPUTS_ROOT = DATA_ROOT / "inputs"
OPENAI_OUTPUT_ROOT = DATA_ROOT / "outputs" / "openai_data_exports"
PDF_OUTPUT_ROOT = DATA_ROOT / "outputs" / "pdfs"
RENDERED_NAME = "rendered_chat.html"

OPENAI_EXPORTS_ROOT = INPUTS_ROOT / "openai_data_exports"
URL_INPUTS_ROOT = INPUTS_ROOT / "urls"
PDF_INPUTS_ROOT = INPUTS_ROOT / "pdfs"


def parse_args() -> argparse.Namespace:
    """Parse CLI switches controlling how pending inputs are processed."""

    parser = argparse.ArgumentParser(
        description=(
            "Process pending inputs discovered under inputs/."
            " OpenAI export zips are unpacked automatically, URL lists"
            " trigger the URL pipeline, and PDF handling will be added"
            " in a later iteration."
        )
    )
    parser.add_argument(
        "--config",
        help=(
            "Optional configuration file used to pull the split_parts value."
            " Defaults to config.json."
        ),
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help=(
            "Re-render and reconvert outputs even when artifacts already"
            " exist."
        ),
    )
    return parser.parse_args()


def ensure_dir(path: Path) -> Path:
    """Create ``path`` if needed and return it for fluent chaining."""

    path.mkdir(parents=True, exist_ok=True)
    return path


@dataclass(slots=True)
class DatasetOutputDirs:
    """Filesystem locations used when generating dataset artifacts."""

    base: Path
    html: Path
    markdown: Path
    json: Path
    pdf: Path
    text: Path

    def ensure(self) -> None:
        """Create all dataset directories when they are absent."""

        for path in (
            self.base,
            self.html,
            self.markdown,
            self.json,
            self.pdf,
            self.text,
        ):
            ensure_dir(path)

    def markdown_aggregate(self, base_name: str) -> Path:
        """Return the aggregate Markdown path for ``base_name``."""

        return self.markdown / f"{base_name}.md"


def _build_output_dirs(base: Path) -> DatasetOutputDirs:
    """Return the canonical directory layout for ``base``."""

    return DatasetOutputDirs(
        base=base,
        html=base / "html",
        markdown=base / "markdown",
        json=base / "json",
        pdf=base / "pdf",
        text=base / "text",
    )


def _extract_conversion_payloads(
    conversion: ConversionResult | None,
    rendered_path: Path,
    markdown_path: Path,
) -> tuple[str | None, str | None]:
    """Return aggregate HTML/Markdown payloads from conversion outputs."""

    if conversion is not None:
        return conversion.aggregate_html, conversion.aggregate_markdown

    html_payload = (
        rendered_path.read_text(encoding="utf-8")
        if rendered_path.exists()
        else None
    )
    markdown_payload = (
        markdown_path.read_text(encoding="utf-8")
        if markdown_path.exists()
        else None
    )
    return html_payload, markdown_payload


@dataclass(slots=True)
class PdfConversionConfig:
    """Parameters required to convert rendered PDF HTML to Markdown."""

    dataset_name: str
    pdf_path: Path
    chunk_char_limit: int
    html_dir: Path
    markdown_dir: Path
    overwrite: bool


@dataclass(slots=True)
class PdfProcessingArtifacts:
    """Artifacts and metadata produced while converting a single PDF."""

    render_success: bool
    render_error: str | None
    conversion: ConversionResult | None
    convert_success: bool
    aggregate_html: str | None
    aggregate_markdown: str | None


def _render_pdf_if_needed(
    pdf_path: Path,
    rendered_html: Path,
    *,
    overwrite: bool,
) -> tuple[bool, str | None]:
    """Render ``pdf_path`` into HTML when required."""

    if not overwrite and rendered_html.exists():
        print(
            (
                f"Skipping render for {pdf_path.name}; rendered HTML "
                "already exists"
            )
        )
        return True, None

    print(f"Rendering {pdf_path.name} -> {rendered_html}")
    success, error = render_pdf_to_html(str(pdf_path), str(rendered_html))
    if not success and error:
        print(f"⚠️ Failed to render {pdf_path.name}: {error}")
    return success, error


def _convert_pdf_if_needed(
    *,
    render_success: bool,
    rendered_html: Path,
    config: PdfConversionConfig,
) -> tuple[ConversionResult | None, bool]:
    """Convert rendered HTML into Markdown when dirty or forced."""

    if not render_success:
        return None, False

    markdown_dir = config.markdown_dir
    if config.overwrite or markdown_is_stale(markdown_dir, rendered_html):
        print(f"Converting {rendered_html} into Markdown at {markdown_dir}")
        options = ConversionOptions(
            source_url=f"pdf://{config.pdf_path.name}",
            chunk_char_limit=config.chunk_char_limit,
            label=config.dataset_name,
            html_output_dir=str(config.html_dir),
            base_filename="rendered_pdf",
        )
        conversion = convert_html_to_md(
            str(rendered_html),
            str(markdown_dir),
            options=options,
        )
        return conversion, True

    if has_markdown(markdown_dir):
        print(
            (
                f"Skipping Markdown conversion for {config.pdf_path.name}; "
                "Markdown files already present"
            )
        )
    else:
        print(
            (
                "⚠️ Missing Markdown for "
                f"{config.pdf_path.name}; rerun with overwrite enabled."
            )
        )

    return None, False


def _gather_pdf_artifacts(
    pdf_path: Path,
    rendered_html: Path,
    *,
    base_name: str,
    config: PdfConversionConfig,
) -> PdfProcessingArtifacts:
    """Return conversion artifacts and status for a single PDF."""

    render_success, render_error = _render_pdf_if_needed(
        pdf_path,
        rendered_html,
        overwrite=config.overwrite,
    )

    conversion, convert_success = _convert_pdf_if_needed(
        render_success=render_success,
        rendered_html=rendered_html,
        config=config,
    )

    aggregate_html, aggregate_markdown = _extract_conversion_payloads(
        conversion,
        rendered_html,
        config.markdown_dir / f"{base_name}.md",
    )

    return PdfProcessingArtifacts(
        render_success=render_success,
        render_error=render_error,
        conversion=conversion,
        convert_success=convert_success,
        aggregate_html=aggregate_html,
        aggregate_markdown=aggregate_markdown,
    )


def has_markdown(markdown_dir: Path) -> bool:
    """Return True when the directory already contains Markdown files."""

    return any(markdown_dir.glob("*.md"))


def _now_iso() -> str:
    """Return the current UTC timestamp formatted for metadata files."""

    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def ensure_input_structure() -> None:
    """Provision all known input and output directories."""

    for path in (
        DATA_ROOT,
        OPENAI_OUTPUT_ROOT,
        PDF_OUTPUT_ROOT,
        INPUTS_ROOT,
        OPENAI_EXPORTS_ROOT,
        URL_INPUTS_ROOT,
        PDF_INPUTS_ROOT,
    ):
        ensure_dir(path)


def load_chunk_char_limit(config_path: str | None) -> int:
    """Determine the character limit per chunk using config fallbacks."""

    try:
        config = load_config(config_path)
    except ConfigError as exc:
        if config_path:
            raise SystemExit(f"Config error: {exc}") from exc
        return DEFAULT_CHUNK_CHAR_LIMIT

    if "chunk_char_limit" in config:
        return max(1, int(config["chunk_char_limit"]))

    split_parts = int(config.get("split_parts", 5))
    scaled_limit = max(1, DEFAULT_CHUNK_CHAR_LIMIT * split_parts // 5)
    return scaled_limit


def find_chat_html(dataset_dir: Path) -> Path | None:
    """Search for the primary chat HTML file inside ``dataset_dir``."""

    direct = dataset_dir / "chat.html"
    if direct.exists():
        return direct

    for candidate in sorted(dataset_dir.rglob("chat.html")):
        if "__MACOSX" in candidate.parts:
            continue
        return candidate

    return None


def process_openai_dataset(
    dataset_dir: Path,
    *,
    chunk_char_limit: int,
    overwrite: bool,
) -> bool:
    """Render, convert, and fan-out artifacts for an OpenAI export."""

    chat_html = find_chat_html(dataset_dir)
    if not chat_html:
        return False

    dataset_name = dataset_dir.name
    outputs = _build_output_dirs(OPENAI_OUTPUT_ROOT / dataset_name)
    outputs.ensure()

    rendered_file = outputs.html / RENDERED_NAME

    if overwrite or not rendered_file.exists():
        print(f"Rendering {chat_html} -> {rendered_file}")
        render_html(str(chat_html), str(rendered_file))
    else:
        print(
            f"Skipping render for {dataset_name}; rendered HTML already"
            " exists"
        )

    conversion: ConversionResult | None = None
    if overwrite or not has_markdown(outputs.markdown):
        print(
            f"Converting {rendered_file} into Markdown at {outputs.markdown}"
        )
        options = ConversionOptions(
            chunk_char_limit=chunk_char_limit,
            label=dataset_name,
            html_output_dir=str(outputs.html),
            base_filename="rendered_chat",
        )
        conversion = convert_html_to_md(
            str(rendered_file),
            str(outputs.markdown),
            options=options,
        )
    else:
        print(
            f"Skipping Markdown conversion for {dataset_name};"
            " Markdown files already present"
        )

    aggregate_html_path = rendered_file
    aggregate_markdown_path = outputs.markdown_aggregate("rendered_chat")
    aggregate_html, aggregate_markdown = _extract_conversion_payloads(
        conversion,
        aggregate_html_path,
        aggregate_markdown_path,
    )

    if aggregate_html is None or aggregate_markdown is None:
        print(
            "⚠️ Unable to locate aggregate HTML/Markdown for"
            f" {dataset_name}; skipping artifact fan-out."
        )
        return True

    fan_out_artifacts(
        dataset_name=dataset_name,
        aggregate_html_payload=aggregate_html,
        aggregate_markdown_payload=aggregate_markdown,
        html_dir=outputs.html,
        markdown_dir=outputs.markdown,
        text_dir=outputs.text,
        json_dir=outputs.json,
        pdf_dir=outputs.pdf,
        chunk_char_limit=chunk_char_limit,
        overwrite=overwrite,
    )

    return True


def expand_new_openai_exports() -> list[Path]:
    """Unpack freshly downloaded OpenAI export ZIPs and relocate them."""

    expanded: list[Path] = []
    for zip_path in sorted(OPENAI_EXPORTS_ROOT.glob("*.zip")):
        dataset_dir = zip_path.with_suffix("")
        ensure_dir(dataset_dir)
        if any(dataset_dir.iterdir()):
            print(
                f"OpenAI export folder {dataset_dir} already contains files;"
                " skipping extraction."
            )
        else:
            try:
                print(
                    "Expanding OpenAI export"
                    f" {zip_path.name} into {dataset_dir}"
                )
                shutil.unpack_archive(str(zip_path), str(dataset_dir))
            except (shutil.ReadError, ValueError) as exc:
                print(f"Failed to unpack {zip_path}: {exc}")
                continue

        destination = dataset_dir / zip_path.name
        try:
            zip_path.replace(destination)
        except OSError as exc:
            print(f"Unable to move {zip_path} into {destination}: {exc}")
        else:
            expanded.append(dataset_dir)

    return expanded


def process_openai_exports(*, chunk_char_limit: int, overwrite: bool) -> bool:
    """Process every OpenAI dataset directory that exists on disk."""

    ensure_dir(OPENAI_EXPORTS_ROOT)
    expand_new_openai_exports()

    processed_any = False
    for dataset_dir in sorted(
        p for p in OPENAI_EXPORTS_ROOT.iterdir() if p.is_dir()
    ):
        print(f"\nInspecting OpenAI export {dataset_dir.name}")
        if process_openai_dataset(
            dataset_dir,
            chunk_char_limit=chunk_char_limit,
            overwrite=overwrite,
        ):
            processed_any = True
        else:
            print("No chat.html found; skipping this export.")

    return processed_any


def process_url_dataset(
    dataset_dir: Path,
    *,
    chunk_char_limit: int,
    overwrite: bool,
) -> bool:
    """Process all URL lists stored within ``dataset_dir``."""

    processed = False
    for url_file in sorted(dataset_dir.glob("*.txt")):
        urls = tuple(read_urls(url_file))
        if not urls:
            continue
        print(f"Processing URL list {url_file} ({len(urls)} URLs)")
        options = UrlProcessingOptions(
            output_root=DATA_ROOT,
            chunk_char_limit=chunk_char_limit,
            overwrite=overwrite,
        )
        process_urls(urls, options=options)
        processed = True
    return processed


def move_into_dataset_folder(file_path: Path) -> Path | None:
    """Move ``file_path`` into a folder named after the stem and return it."""

    dataset_dir = file_path.with_suffix("")
    ensure_dir(dataset_dir)
    destination = dataset_dir / file_path.name
    try:
        file_path.replace(destination)
    except OSError as exc:
        print(f"Unable to organize {file_path} -> {destination}: {exc}")
        return None
    return dataset_dir


def process_url_inputs(*, chunk_char_limit: int, overwrite: bool) -> bool:
    """Handle URL-based datasets found under the inputs directory."""

    ensure_dir(URL_INPUTS_ROOT)

    for loose_file in sorted(URL_INPUTS_ROOT.glob("*.txt")):
        move_into_dataset_folder(loose_file)

    processed = False
    for dataset_dir in sorted(
        p for p in URL_INPUTS_ROOT.iterdir() if p.is_dir()
    ):
        if process_url_dataset(
            dataset_dir,
            chunk_char_limit=chunk_char_limit,
            overwrite=overwrite,
        ):
            processed = True

    return processed


def process_pdf_dataset(
    dataset_dir: Path,
    *,
    chunk_char_limit: int,
    overwrite: bool,
) -> bool:
    """Render and convert PDFs contained in ``dataset_dir``."""

    dataset_name = dataset_dir.name
    pdf_files = sorted(dataset_dir.glob("*.pdf"))
    if not pdf_files:
        return False

    outputs = _build_output_dirs(PDF_OUTPUT_ROOT / dataset_name)
    outputs.ensure()

    processed_any = False
    base_name = "rendered_pdf"
    metadata_path = outputs.base / "metadata.json"

    for pdf_path in pdf_files:
        rendered_html = outputs.html / f"{base_name}.html"

        config = PdfConversionConfig(
            dataset_name=dataset_name,
            pdf_path=pdf_path,
            chunk_char_limit=chunk_char_limit,
            html_dir=outputs.html,
            markdown_dir=outputs.markdown,
            overwrite=overwrite,
        )

        artifacts = _gather_pdf_artifacts(
            pdf_path,
            rendered_html,
            base_name=base_name,
            config=config,
        )

        if (
            artifacts.aggregate_html is None
            or artifacts.aggregate_markdown is None
        ):
            print(
                "⚠️ Unable to locate aggregate HTML/Markdown for"
                f" {pdf_path.name}; skipping artifact fan-out."
            )
        else:
            fan_out_artifacts(
                dataset_name=dataset_name,
                aggregate_html_payload=artifacts.aggregate_html,
                aggregate_markdown_payload=artifacts.aggregate_markdown,
                html_dir=outputs.html,
                markdown_dir=outputs.markdown,
                text_dir=outputs.text,
                json_dir=outputs.json,
                pdf_dir=outputs.pdf,
                chunk_char_limit=chunk_char_limit,
                overwrite=overwrite,
                source_url=f"pdf://{pdf_path.name}",
                base_name=base_name,
            )

        metadata: dict[str, object] = {
            "pdf": str(pdf_path),
            "rendered_html": str(rendered_html),
            "markdown_dir": str(outputs.markdown),
            "json_dir": str(outputs.json),
            "pdf_dir": str(outputs.pdf),
            "text_dir": str(outputs.text),
            "render_success": artifacts.render_success,
            "convert_success": artifacts.convert_success,
            "overwrite": overwrite,
            "timestamp": _now_iso(),
        }
        if artifacts.render_error:
            metadata["error"] = artifacts.render_error

        metadata_path.write_text(
            json.dumps(metadata, indent=2),
            encoding="utf-8",
        )

        if artifacts.render_success or artifacts.convert_success:
            processed_any = True

    return processed_any


def process_pdf_inputs(*, chunk_char_limit: int, overwrite: bool) -> bool:
    """Process every PDF dataset folder discovered in the inputs tree."""

    ensure_dir(PDF_INPUTS_ROOT)
    ensure_dir(PDF_OUTPUT_ROOT)

    for loose_file in sorted(PDF_INPUTS_ROOT.glob("*.pdf")):
        move_into_dataset_folder(loose_file)

    processed = False
    for dataset_dir in sorted(
        p for p in PDF_INPUTS_ROOT.iterdir() if p.is_dir()
    ):
        if process_pdf_dataset(
            dataset_dir,
            chunk_char_limit=chunk_char_limit,
            overwrite=overwrite,
        ):
            processed = True

    return processed


def main() -> None:
    """Entrypoint that drives processing for all supported input types."""

    args = parse_args()
    chunk_char_limit = load_chunk_char_limit(args.config)

    ensure_input_structure()

    any_processed = False

    if process_openai_exports(
        chunk_char_limit=chunk_char_limit,
        overwrite=args.overwrite,
    ):
        any_processed = True

    if process_url_inputs(
        chunk_char_limit=chunk_char_limit,
        overwrite=args.overwrite,
    ):
        any_processed = True

    if process_pdf_inputs(
        chunk_char_limit=chunk_char_limit,
        overwrite=args.overwrite,
    ):
        any_processed = True

    if not any_processed:
        print("No pending inputs required processing.")


if __name__ == "__main__":
    main()
