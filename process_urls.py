"""Batch renderer for fetching arbitrary URLs and producing Markdown output."""

from __future__ import annotations

import argparse
import json
import re
import time
from contextlib import contextmanager
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from html import escape
from pathlib import Path
from typing import Iterable, Iterator, Literal, Optional, Sequence
from urllib.parse import urlparse

try:
    from playwright.sync_api import (  # type: ignore
        Browser,
        Error as PlaywrightError,
        TimeoutError as PlaywrightTimeoutError,
        sync_playwright,
    )
except ImportError as exc:  # pragma: no cover - surfacing missing dependency
    raise SystemExit(
        "Missing dependency 'playwright'. Install with pip install playwright "
        "&& playwright install"
    ) from exc

from config_loader import ConfigError, load_config
from convert_rendered_html_to_md import (
    DEFAULT_CHUNK_CHAR_LIMIT,
    ConversionOptions,
    convert_html_to_md,
    write_domain_aggregates,
)

WaitUntilLiteral = Literal["commit", "domcontentloaded", "load", "networkidle"]
DEFAULT_WAIT_UNTIL: WaitUntilLiteral = "load"
DEFAULT_TIMEOUT_MS = 60_000
FALLBACK_WAIT_UNTIL: WaitUntilLiteral = "domcontentloaded"
FALLBACK_TIMEOUT_MS = DEFAULT_TIMEOUT_MS * 2

FetchAttemptConfig = tuple[WaitUntilLiteral, int]

FETCH_ATTEMPTS: tuple[FetchAttemptConfig, ...] = (
    (DEFAULT_WAIT_UNTIL, DEFAULT_TIMEOUT_MS // 2),
    (FALLBACK_WAIT_UNTIL, DEFAULT_TIMEOUT_MS),
    ("networkidle", int(DEFAULT_TIMEOUT_MS * 1.5)),
)

AGGREGATED_RENDERED_NAME = "rendered_chat.html"
DOMAIN_DATASET_PREFIX = "domain"


def _empty_attempt_list() -> list[FetchAttemptResult]:
    return []


def _empty_url_result_list() -> list["UrlProcessingResult"]:
    return []


# Note: All dataclasses use slots=True for memory efficiency.
# This blocks dynamic attributes and may require tweaking for inheritance.
@dataclass(slots=True)
class FetchAttemptResult:
    """Outcome and metadata for a single Playwright fetch attempt.

    Uses slots for memory efficiency. Do not inherit from this class
    unless the subclass also uses slots=True.
    """

    attempt: int
    wait_until: WaitUntilLiteral
    timeout_ms: int
    status: Literal["success", "timeout", "error"]
    elapsed_ms: Optional[int] = None
    message: Optional[str] = None
    screenshot: Optional[str] = None


@dataclass(slots=True)
class UrlArtifactPaths:
    """Filesystem locations for a single URL processing run.

    Uses slots for memory efficiency. Do not inherit from this class
    unless the subclass also uses slots=True.
    """

    rendered_html: Path
    markdown_dir: Path
    metadata_path: Path


@dataclass(slots=True)
class UrlProcessingFlags:
    """Indicators describing which phases were skipped.

    Uses slots for memory efficiency. Do not inherit from this class
    unless the subclass also uses slots=True.
    """

    skipped_render: bool = False
    skipped_convert: bool = False


@dataclass(slots=True)
class UrlProcessingResult:
    """Per-URL processing record capturing locations and status.

    Uses slots for memory efficiency. Do not inherit from this class
    unless the subclass also uses slots=True.
    """

    url: str
    slug: str
    artifacts: UrlArtifactPaths
    success: bool
    attempts: list[FetchAttemptResult] = field(
        default_factory=_empty_attempt_list
    )
    flags: UrlProcessingFlags = field(default_factory=UrlProcessingFlags)

    @property
    def rendered_html(self) -> Path:
        """Return the rendered HTML path for this URL."""

        return self.artifacts.rendered_html

    @property
    def markdown_dir(self) -> Path:
        """Return the Markdown output directory for this URL."""

        return self.artifacts.markdown_dir

    @property
    def metadata_path(self) -> Path:
        """Return the JSON metadata path associated with this URL."""

        return self.artifacts.metadata_path

    @property
    def skipped_render(self) -> bool:
        """Return True when rendering was skipped for this URL."""

        return self.flags.skipped_render

    @property
    def skipped_convert(self) -> bool:
        """Return True when Markdown conversion was skipped."""

        return self.flags.skipped_convert


@dataclass(slots=True)
class DomainProcessingCounts:
    """Aggregated URL counts for a processed domain.

    Uses slots for memory efficiency. Do not inherit from this class
    unless the subclass also uses slots=True.
    """

    total: int
    successful: int
    failed: int


@dataclass(slots=True)
class DomainArtifactSummary:
    """Aggregate artifact locations generated for a domain batch.

    Uses slots for memory efficiency. Do not inherit from this class
    unless the subclass also uses slots=True.
    """

    rendered: Optional[Path] = None
    markdown_dir: Optional[Path] = None


@dataclass(slots=True)
class DomainProcessingResult:
    """Summary of work completed for a single domain batch.

    Uses slots for memory efficiency. Do not inherit from this class
    unless the subclass also uses slots=True.
    """

    domain: str
    counts: DomainProcessingCounts
    processed_urls: list[UrlProcessingResult] = field(
        default_factory=_empty_url_result_list
    )
    artifacts: DomainArtifactSummary = field(
        default_factory=DomainArtifactSummary
    )
    failures: list[UrlProcessingResult] = field(
        default_factory=_empty_url_result_list
    )

    @property
    def total_urls(self) -> int:
        """Return the number of URLs attempted for this domain."""

        return self.counts.total

    @property
    def successful_urls(self) -> int:
        """Return the number of URLs that rendered successfully."""

        return self.counts.successful

    @property
    def failed_urls(self) -> int:
        """Return the number of URLs that failed to render."""

        return self.counts.failed

    @property
    def aggregate_rendered_path(self) -> Optional[Path]:
        """Return the path to the rendered domain aggregate, if present."""

        return self.artifacts.rendered

    @property
    def aggregate_markdown_dir(self) -> Optional[Path]:
        """Return the directory containing aggregate Markdown outputs."""

        return self.artifacts.markdown_dir


@dataclass(slots=True)
class UrlProcessingOptions:
    """Execution options shared across URL processing tasks.

    Uses slots for memory efficiency. Do not inherit from this class
    unless the subclass also uses slots=True.
    """

    output_root: Path
    chunk_char_limit: int
    overwrite: bool = False
    skip_render: bool = False
    skip_convert: bool = False


@dataclass(slots=True)
class DomainPaths:
    """Filesystem layout for both per-URL and aggregate artifacts.

    Uses slots for memory efficiency. Do not inherit from this class
    unless the subclass also uses slots=True.
    """

    domain: str
    dataset_name: str
    rendered_root: Path
    markdown_root: Path
    aggregate_rendered_root: Path
    aggregate_markdown_root: Path

    @classmethod
    def build(cls, output_root: Path, domain: str) -> "DomainPaths":
        """Return a populated paths object for the provided ``domain``."""

        dataset_name = f"{DOMAIN_DATASET_PREFIX}_{domain}"
        rendered_base = output_root / "rendered"
        markdown_base = output_root / "markdown_output"
        return cls(
            domain=domain,
            dataset_name=dataset_name,
            rendered_root=rendered_base / domain,
            markdown_root=markdown_base / domain,
            aggregate_rendered_root=rendered_base / dataset_name,
            aggregate_markdown_root=markdown_base / dataset_name,
        )

    def ensure_domain_dirs(self) -> None:
        """Create per-domain rendered and Markdown directories."""

        ensure_dir(self.rendered_root)
        ensure_dir(self.markdown_root)

    def ensure_aggregate_dirs(self) -> None:
        """Provision aggregate directories that store domain rollups."""

        ensure_dir(self.aggregate_rendered_root)
        ensure_dir(self.aggregate_markdown_root)

    def slug_artifacts(self, slug: str) -> UrlArtifactPaths:
        """Return artifact paths associated with a specific slug."""

        markdown_dir = self.markdown_root / slug
        ensure_dir(markdown_dir)
        metadata_path = self.rendered_root / f"{slug}.metadata.json"
        return UrlArtifactPaths(
            rendered_html=self.rendered_root / f"{slug}.html",
            markdown_dir=markdown_dir,
            metadata_path=metadata_path,
        )

    def html_artifact_dir(self, slug: str) -> Path:
        """Return the directory used to store intermediate HTML chunks."""

        path = self.rendered_root / slug
        ensure_dir(path)
        return path


RE_NON_SLUG = re.compile(r"[^A-Za-z0-9._-]+")


def parse_args() -> argparse.Namespace:
    """Parse CLI arguments controlling the URL processing pipeline."""

    parser = argparse.ArgumentParser(
        description="Fetch URLs and store rendered HTML + Markdown output.",
    )
    parser.add_argument(
        "--urls-file",
        default="developers.cloudflare.com.txt",
        help="Text file containing newline separated URLs.",
    )
    parser.add_argument(
        "--config",
        default=None,
        help=(
            "Optional config file to reuse split settings "
            "(fallbacks to config.json)"
        ),
    )
    parser.add_argument(
        "--output-root",
        default="data",
        help=(
            "Base directory that holds rendered/ and markdown_output/ "
            "folders."
        ),
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Re-render pages even if rendered HTML already exists.",
    )
    parser.add_argument(
        "--skip-render",
        action="store_true",
        help="Skip the rendering phase and only convert existing HTML.",
    )
    parser.add_argument(
        "--skip-convert",
        action="store_true",
        help="Skip Markdown conversion even if rendered HTML changes.",
    )
    return parser.parse_args()


def _now_iso() -> str:
    """Return a UTC timestamp string suitable for metadata files."""

    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _sanitize_component(value: str, fallback: str) -> str:
    """Convert an arbitrary string into a slug-like component."""

    return RE_NON_SLUG.sub("-", value).strip("-") or fallback


def domain_from_url(url: str) -> str:
    """Extract and sanitize the domain portion of ``url``."""

    parsed = urlparse(url)
    domain = parsed.netloc or "root"
    return _sanitize_component(domain, "root")


def url_to_slug(url: str) -> str:
    """Convert ``url`` into a filesystem-friendly slug."""

    parsed = urlparse(url)
    parts: list[str] = []
    path_segments = [segment for segment in parsed.path.split("/") if segment]
    parts.extend(path_segments)
    if parsed.query:
        parts.append(parsed.query.replace("=", "-").replace("&", "-"))
    slug = "_".join(parts) if parts else "index"
    return _sanitize_component(slug, "page")


def read_urls(path: Path) -> Iterable[str]:
    """Yield URLs from a newline-delimited text file, skipping blanks."""

    raw = path.read_text(encoding="utf-8").splitlines()
    for line in raw:
        url = line.strip()
        if not url:
            continue
        if url.startswith(("'", '"')) and url.endswith(("'", '"')):
            url = url[1:-1]
        url = url.strip('"').strip("'")
        if url and not url.startswith("#"):
            yield url


def ensure_dir(path: Path) -> None:
    """Create ``path`` if missing, mirroring ``mkdir -p`` semantics."""

    path.mkdir(parents=True, exist_ok=True)


def markdown_is_stale(markdown_dir: Path, rendered_html: Path) -> bool:
    """Return True when Markdown output predates the rendered HTML."""

    if not rendered_html.exists():
        return True
    if not markdown_dir.exists():
        return True
    markdown_files = list(markdown_dir.glob("*.md"))
    if not markdown_files:
        return True
    rendered_mtime = rendered_html.stat().st_mtime
    return any(md.stat().st_mtime < rendered_mtime for md in markdown_files)


def _should_regenerate(
    target: Path,
    sources: Sequence[Path],
    *,
    overwrite: bool,
) -> bool:
    """Check whether ``target`` should be regenerated from ``sources``."""

    if overwrite or not target.exists():
        return True
    target_mtime = target.stat().st_mtime
    return any(
        source.stat().st_mtime > target_mtime
        for source in sources
        if source.exists()
    )


def _extract_body(html: str) -> str:
    """Return the <body> contents of the supplied HTML snippet."""

    match = re.search(
        r"<body[^>]*>(.*)</body>", html, re.IGNORECASE | re.DOTALL
    )
    return match.group(1) if match else html


def _write_metadata(metadata_path: Path, payload: dict[str, object]) -> None:
    """Persist metadata JSON next to the rendered HTML artifact."""

    metadata_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _compose_aggregate_html(
    domain: str, url_results: Sequence[UrlProcessingResult]
) -> str:
    """Combine individual rendered HTML bodies into an aggregate page."""

    generated_at = _now_iso()
    parts: list[str] = [
        "<!DOCTYPE html>",
        "<html>",
        "<head>",
        '<meta charset="utf-8" />',
        f"<title>Aggregate: {escape(domain)}</title>",
        f'<meta name="generated_at" content="{generated_at}" />',
        "</head>",
        "<body>",
        f"<h1>Domain aggregate for {escape(domain)}</h1>",
    ]
    for result in url_results:
        try:
            html_text = result.rendered_html.read_text(encoding="utf-8")
        except FileNotFoundError:
            continue
        body = _extract_body(html_text)
        parts.append(
            (
                f'<article id="{result.slug}" '
                f'data-source-url="{escape(result.url)}">\n'
                f"<h2>{escape(result.url)}</h2>\n"
                f"{body}\n"
                "</article>"
            )
        )
    parts.extend(["</body>", "</html>"])
    return "\n".join(parts)


def _generate_domain_aggregate(
    domain_paths: DomainPaths,
    url_results: Sequence[UrlProcessingResult],
    *,
    options: UrlProcessingOptions,
) -> DomainArtifactSummary:
    """Create aggregate HTML/Markdown artifacts for a domain."""

    successful = [
        result
        for result in url_results
        if result.success and result.rendered_html.exists()
    ]
    if not successful:
        return DomainArtifactSummary()

    domain_paths.ensure_aggregate_dirs()

    aggregate_html_path = (
        domain_paths.aggregate_rendered_root / AGGREGATED_RENDERED_NAME
    )
    dependency_paths = [result.rendered_html for result in successful]

    needs_regeneration = _should_regenerate(
        aggregate_html_path, dependency_paths, overwrite=options.overwrite
    )

    if needs_regeneration and not options.skip_render:
        aggregate_html = _compose_aggregate_html(
            domain_paths.domain, successful
        )
        aggregate_html_path.write_text(aggregate_html, encoding="utf-8")
    elif not aggregate_html_path.exists():
        aggregate_html = _compose_aggregate_html(
            domain_paths.domain, successful
        )
        aggregate_html_path.write_text(aggregate_html, encoding="utf-8")

    aggregate_markdown_dir: Optional[Path] = None
    if aggregate_html_path.exists():
        aggregate_markdown_root = domain_paths.aggregate_markdown_root
        if options.skip_convert:
            if any(aggregate_markdown_root.glob("*.md")):
                aggregate_markdown_dir = aggregate_markdown_root
        elif options.overwrite or markdown_is_stale(
            aggregate_markdown_root, aggregate_html_path
        ):
            conversion_options = ConversionOptions(
                source_url=f"domain://{domain_paths.domain}",
                chunk_char_limit=options.chunk_char_limit,
                label=domain_paths.dataset_name,
                html_output_dir=str(domain_paths.aggregate_rendered_root),
                base_filename="rendered_chat",
            )
            convert_html_to_md(
                str(aggregate_html_path),
                str(aggregate_markdown_root),
                options=conversion_options,
            )
            aggregate_markdown_dir = aggregate_markdown_root
        elif any(aggregate_markdown_root.glob("*.md")):
            aggregate_markdown_dir = aggregate_markdown_root

    return DomainArtifactSummary(
        rendered=aggregate_html_path if aggregate_html_path.exists() else None,
        markdown_dir=aggregate_markdown_dir,
    )


@contextmanager
def _launch_browser() -> Iterator[Browser]:
    """Context manager that yields a headless Chromium browser instance."""

    with sync_playwright() as playwright:  # type: ignore[misc]
        browser: Browser = playwright.chromium.launch(headless=True)
        try:
            yield browser
        finally:
            browser.close()


def _process_single_url(
    browser: Browser,
    url: str,
    *,
    domain_paths: DomainPaths,
    options: UrlProcessingOptions,
) -> UrlProcessingResult:
    """Render and convert a single URL using the provided browser."""

    slug = url_to_slug(url)
    artifacts = domain_paths.slug_artifacts(slug)
    html_artifacts_dir = domain_paths.html_artifact_dir(slug)

    attempts: list[FetchAttemptResult] = []
    should_render = not options.skip_render and (
        options.overwrite or not artifacts.rendered_html.exists()
    )
    render_success = False
    if should_render:
        print(f"Rendering {url} -> {artifacts.rendered_html}")
        render_success, attempts = fetch_and_render(
            browser,
            url,
            artifacts.rendered_html,
        )
        if not render_success:
            print(
                f"⚠️ Failed to render {url}; see {artifacts.metadata_path}"
                " for details"
            )
    elif artifacts.rendered_html.exists():
        render_success = True
    else:
        print(
            "⚠️ Skipping render for "
            f"{url} but no HTML exists; cannot convert."
        )

    markdown_files_before = list(artifacts.markdown_dir.glob("*.md"))
    should_convert = (
        render_success
        and not options.skip_convert
        and (
            options.overwrite
            or markdown_is_stale(
                artifacts.markdown_dir, artifacts.rendered_html
            )
        )
    )

    convert_performed = False
    if should_convert:
        conversion_options = ConversionOptions(
            source_url=url,
            chunk_char_limit=options.chunk_char_limit,
            label=slug,
            html_output_dir=str(html_artifacts_dir),
            base_filename=slug,
        )
        convert_html_to_md(
            str(artifacts.rendered_html),
            str(artifacts.markdown_dir),
            options=conversion_options,
        )
        convert_performed = True
    elif options.skip_convert:
        print(
            "Skipping Markdown conversion for " f"{url} due to --skip-convert."
        )
    elif not markdown_files_before:
        print("⚠️ Missing Markdown for " f"{url}; rerun with --overwrite.")

    converted_files = sorted(
        file.name for file in artifacts.markdown_dir.glob("*.md")
    )

    metadata_payload: dict[str, object] = {
        "url": url,
        "slug": slug,
        "domain": domain_paths.domain,
        "rendered_html": str(artifacts.rendered_html),
        "markdown_dir": str(artifacts.markdown_dir),
        "converted_files": converted_files,
        "render_success": render_success,
        "convert_performed": convert_performed,
        "skipped_render": not should_render,
        "skipped_convert": options.skip_convert or not should_convert,
        "attempts": [asdict(attempt) for attempt in attempts],
        "timestamp": _now_iso(),
    }
    _write_metadata(artifacts.metadata_path, metadata_payload)

    flags = UrlProcessingFlags(
        skipped_render=not should_render,
        skipped_convert=options.skip_convert or not should_convert,
    )

    return UrlProcessingResult(
        url=url,
        slug=slug,
        artifacts=artifacts,
        success=render_success,
        attempts=attempts,
        flags=flags,
    )


def fetch_and_render(
    browser: Browser,
    url: str,
    destination: Path,
    *,
    attempts: Sequence[FetchAttemptConfig] = FETCH_ATTEMPTS,
) -> tuple[bool, list[FetchAttemptResult]]:
    """Render ``url`` to ``destination`` capturing attempt metadata."""

    attempt_records: list[FetchAttemptResult] = []
    for attempt_index, (wait_until, timeout_ms) in enumerate(
        attempts, start=1
    ):
        page = browser.new_page()
        start_time = time.perf_counter()
        screenshot_path: Optional[Path] = None
        try:
            page.goto(url, wait_until=wait_until, timeout=timeout_ms)
            html = page.content()
            destination.write_text(html, encoding="utf-8")
            elapsed_ms = int((time.perf_counter() - start_time) * 1000)
            attempt_records.append(
                FetchAttemptResult(
                    attempt=attempt_index,
                    wait_until=wait_until,
                    timeout_ms=timeout_ms,
                    status="success",
                    elapsed_ms=elapsed_ms,
                )
            )
            return True, attempt_records
        except PlaywrightTimeoutError as exc:
            elapsed_ms = int((time.perf_counter() - start_time) * 1000)
            screenshot_path = destination.with_name(
                f"{destination.stem}.attempt{attempt_index}.png"
            )
            try:
                page.screenshot(path=str(screenshot_path), full_page=True)
            except (PlaywrightError, OSError):
                screenshot_path = None
            attempt_records.append(
                FetchAttemptResult(
                    attempt=attempt_index,
                    wait_until=wait_until,
                    timeout_ms=timeout_ms,
                    status="timeout",
                    elapsed_ms=elapsed_ms,
                    message=str(exc),
                    screenshot=(
                        str(screenshot_path)
                        if screenshot_path is not None
                        else None
                    ),
                )
            )
        except (PlaywrightError, OSError) as exc:
            elapsed_ms = int((time.perf_counter() - start_time) * 1000)
            attempt_records.append(
                FetchAttemptResult(
                    attempt=attempt_index,
                    wait_until=wait_until,
                    timeout_ms=timeout_ms,
                    status="error",
                    elapsed_ms=elapsed_ms,
                    message=str(exc),
                )
            )
            return False, attempt_records
        finally:
            page.close()

    return False, attempt_records


def resolve_chunk_char_limit(config_path: Optional[str]) -> int:
    """Calculate the Markdown chunk size using config overrides."""

    try:
        config = load_config(config_path)
    except ConfigError:
        return DEFAULT_CHUNK_CHAR_LIMIT

    if "chunk_char_limit" in config:
        return max(1, int(config["chunk_char_limit"]))

    split_parts = int(config.get("split_parts", 5))
    scaled_limit = max(1, DEFAULT_CHUNK_CHAR_LIMIT * split_parts // 5)
    return scaled_limit


def group_urls_by_domain(urls: Iterable[str]) -> dict[str, list[str]]:
    """Group URLs by sanitized domain for downstream processing."""

    grouped: dict[str, list[str]] = {}
    for url in urls:
        grouped.setdefault(domain_from_url(url), []).append(url)
    return grouped


def process_urls(
    urls: Iterable[str],
    *,
    options: UrlProcessingOptions,
) -> list[DomainProcessingResult]:
    """Render and convert the provided URLs grouped by their domain."""

    rendered_root = options.output_root / "rendered"
    markdown_root = options.output_root / "markdown_output"
    ensure_dir(rendered_root)
    ensure_dir(markdown_root)

    grouped = group_urls_by_domain(urls)
    if not grouped:
        return []

    domain_results: list[DomainProcessingResult] = []

    with _launch_browser() as browser:
        for domain, domain_urls in grouped.items():
            domain_paths = DomainPaths.build(options.output_root, domain)
            domain_paths.ensure_domain_dirs()

            processed = [
                _process_single_url(
                    browser,
                    url,
                    domain_paths=domain_paths,
                    options=options,
                )
                for url in domain_urls
            ]

            artifacts = _generate_domain_aggregate(
                domain_paths,
                processed,
                options=options,
            )

            write_domain_aggregates(
                domain_label=domain,
                rendered_domain_root=domain_paths.rendered_root,
                markdown_domain_root=domain_paths.markdown_root,
                chunk_char_limit=options.chunk_char_limit,
            )

            failures = [result for result in processed if not result.success]
            counts = DomainProcessingCounts(
                total=len(processed),
                successful=len(processed) - len(failures),
                failed=len(failures),
            )

            domain_results.append(
                DomainProcessingResult(
                    domain=domain,
                    counts=counts,
                    processed_urls=processed,
                    artifacts=artifacts,
                    failures=failures,
                )
            )

    return domain_results


def main() -> None:
    """CLI entry point for batch-rendering URLs into Markdown artifacts."""

    args = parse_args()
    urls_path = Path(args.urls_file)
    if not urls_path.exists():
        raise SystemExit(f"URL list not found: {urls_path}")

    chunk_char_limit = resolve_chunk_char_limit(args.config)
    options = UrlProcessingOptions(
        output_root=Path(args.output_root),
        chunk_char_limit=chunk_char_limit,
        overwrite=args.overwrite,
        skip_render=args.skip_render,
        skip_convert=args.skip_convert,
    )
    domain_results = process_urls(
        tuple(read_urls(urls_path)),
        options=options,
    )

    total_urls = sum(result.total_urls for result in domain_results)
    total_failures = sum(result.failed_urls for result in domain_results)

    print(f"Processed {total_urls} URLs across {len(domain_results)} domains.")
    if total_failures:
        print(f"⚠️ {total_failures} URLs failed to render.")


if __name__ == "__main__":
    main()
