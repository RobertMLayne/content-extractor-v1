"""Execution wrapper for the OpenAI export rendering pipeline."""

from __future__ import annotations

import shutil
from pathlib import Path

from artifact_fanout import fan_out_artifacts  # type: ignore[import]
from convert_rendered_html_to_md import (  # type: ignore[import]
    ConversionOptions,
    convert_html_to_md,
)
from pipelines.common import paths  # type: ignore[import]
from pipelines.openai_export.spec import Spec  # type: ignore[import]
from render_chat_html import render_html

BASE_NAME = "rendered_chat"


def run(spec: Spec) -> Path:
    """Execute the OpenAI export pipeline for a single ZIP payload."""

    zip_path = spec.zip_path
    if not zip_path.exists():
        raise FileNotFoundError(f"OpenAI export ZIP not found: {zip_path}")

    dataset_name = zip_path.stem
    input_root = paths.openai_input_root()
    output_root = paths.openai_output_root(dataset_name)

    dataset_dir = input_root / dataset_name
    if spec.overwrite and dataset_dir.exists():
        shutil.rmtree(dataset_dir)
    dataset_dir.mkdir(parents=True, exist_ok=True)

    _unpack_export(zip_path, dataset_dir, overwrite=spec.overwrite)
    _relocate_zip(zip_path, dataset_dir)

    chat_html = _find_chat_html(dataset_dir)
    if chat_html is None:
        raise FileNotFoundError(
            f"chat.html not found under extracted export: {dataset_dir}"
        )

    html_dir = output_root / "html"
    markdown_dir = output_root / "markdown"
    json_dir = output_root / "json"
    pdf_dir = output_root / "pdf"
    text_dir = output_root / "text"

    for path in (html_dir, markdown_dir, json_dir, pdf_dir, text_dir):
        path.mkdir(parents=True, exist_ok=True)

    rendered_html_path = html_dir / f"{BASE_NAME}.html"
    if spec.overwrite or not rendered_html_path.exists():
        print(
            "Rendering HTML via Playwright:"
            f" {chat_html} -> {rendered_html_path}"
        )
        render_html(str(chat_html), str(rendered_html_path))
    else:
        print("Skipping HTML render; rendered_chat.html already present")

    aggregate_html_payload: str | None = None
    aggregate_markdown_payload: str | None = None

    if spec.overwrite or not _has_markdown(markdown_dir):
        print(
            "Generating Markdown chunks using convert_html_to_md at"
            f" {markdown_dir}"
        )
        options = ConversionOptions(
            chunk_char_limit=spec.chunk_char_limit,
            label=dataset_name,
            html_output_dir=str(html_dir),
            base_filename=BASE_NAME,
        )
        conversion = convert_html_to_md(
            str(rendered_html_path),
            str(markdown_dir),
            options=options,
        )
        aggregate_html_payload = conversion.aggregate_html
        aggregate_markdown_payload = conversion.aggregate_markdown
    else:
        print("Skipping Markdown conversion; chunks already exist")

    if aggregate_html_payload is None and rendered_html_path.exists():
        aggregate_html_payload = rendered_html_path.read_text(encoding="utf-8")

    aggregate_markdown_path = markdown_dir / f"{BASE_NAME}.md"
    if aggregate_markdown_payload is None and aggregate_markdown_path.exists():
        aggregate_markdown_payload = aggregate_markdown_path.read_text(
            encoding="utf-8"
        )

    if aggregate_html_payload is None or aggregate_markdown_payload is None:
        raise RuntimeError(
            "Aggregate HTML/Markdown payloads unavailable; "
            "cannot fan out artifacts"
        )

    fan_out_artifacts(
        dataset_name=dataset_name,
        aggregate_html_payload=aggregate_html_payload,
        aggregate_markdown_payload=aggregate_markdown_payload,
        html_dir=html_dir,
        markdown_dir=markdown_dir,
        text_dir=text_dir,
        json_dir=json_dir,
        pdf_dir=pdf_dir,
        chunk_char_limit=spec.chunk_char_limit,
        overwrite=spec.overwrite,
    )

    return output_root


def _unpack_export(
    zip_path: Path, dataset_dir: Path, *, overwrite: bool
) -> None:
    contents = tuple(dataset_dir.iterdir())
    if contents and not overwrite:
        print(
            "Skipping extraction for "
            f"{zip_path.name}; dataset folder already populated"
        )
        return

    if contents and overwrite:
        for entry in contents:
            if entry.is_dir():
                shutil.rmtree(entry)
            else:
                entry.unlink()

    print(f"Expanding {zip_path} into {dataset_dir}")
    try:
        shutil.unpack_archive(str(zip_path), str(dataset_dir))
    except (shutil.ReadError, ValueError) as exc:
        raise RuntimeError(
            f"Unable to unpack OpenAI export {zip_path}: {exc}"
        ) from exc


def _relocate_zip(zip_path: Path, dataset_dir: Path) -> None:
    destination = dataset_dir / zip_path.name
    if destination == zip_path:
        return
    try:
        zip_path.replace(destination)
    except OSError:
        try:
            shutil.copy2(zip_path, destination)
        except OSError as exc:
            print(f"⚠️ Unable to place ZIP inside dataset directory: {exc}")
        else:
            try:
                zip_path.unlink()
            except OSError:
                pass


def _find_chat_html(dataset_dir: Path) -> Path | None:
    direct = dataset_dir / "chat.html"
    if direct.exists():
        return direct
    for candidate in sorted(dataset_dir.rglob("chat.html")):
        if "__MACOSX" in candidate.parts:
            continue
        return candidate
    return None


def _has_markdown(markdown_dir: Path) -> bool:
    return any(markdown_dir.glob("*.md"))


__all__ = ["run"]
