"""CLI adapter that preserves the legacy HTML-to-Markdown workflow."""

from config_loader import ConfigError, resolve_runtime_paths
from content_extractor import convert_html_to_md_files, parse_args


if __name__ == '__main__':
    args = parse_args()
    try:
        runtime = resolve_runtime_paths(
            config_path=args.config,
            input_html=args.input_html,
            output_dir=args.output_dir,
            parts=args.parts,
        )
    except ConfigError as exc:
        raise SystemExit(f"Config error: {exc}") from exc

    convert_html_to_md_files(
        runtime["input_html"],
        runtime["markdown_output_dir"],
        parts=runtime["split_parts"],
    )
