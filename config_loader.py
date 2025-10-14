"""Helpers for resolving configuration files and runtime paths."""

import json
import os
from typing import Any, Dict, Optional

DEFAULT_CONFIG_NAME = "config.json"


class ConfigError(Exception):
    """Raised when runtime configuration cannot be loaded."""


def _resolve_config_path(path: Optional[str]) -> str:
    """Return the absolute config path, honoring overrides and defaults."""
    env_override = os.environ.get("CONTENT_EXTRACTOR_CONFIG")
    candidate = path or env_override or DEFAULT_CONFIG_NAME
    expanded = os.path.expanduser(candidate)
    if os.path.isabs(expanded) and os.path.isfile(expanded):
        return expanded

    search_roots = [os.getcwd(), os.path.dirname(__file__)]
    for root in search_roots:
        resolved = os.path.abspath(os.path.join(root, expanded))
        if os.path.isfile(resolved):
            return resolved

    raise ConfigError(f"Configuration file not found: {candidate}")


def _resolve_path(value: str, base_dir: str) -> str:
    """Resolve ``value`` into an absolute path relative to ``base_dir``."""
    expanded = os.path.expanduser(value)
    if os.path.isabs(expanded):
        return expanded
    return os.path.abspath(os.path.join(base_dir, expanded))


def load_config(path: Optional[str] = None) -> Dict[str, Any]:
    """Load a JSON config file and normalize any filesystem paths."""
    config_path = _resolve_config_path(path)
    with open(config_path, "r", encoding="utf-8") as config_file:
        data = json.load(config_file)

    base_dir = os.path.dirname(config_path)
    resolved: Dict[str, Any] = {}
    for key, value in data.items():
        if isinstance(value, str) and key.endswith(("_html", "_dir", "_path")):
            resolved[key] = _resolve_path(value, base_dir)
        else:
            resolved[key] = value

    return resolved


def resolve_runtime_paths(
    *,
    config_path: Optional[str] = None,
    input_html: Optional[str] = None,
    rendered_html: Optional[str] = None,
    output_dir: Optional[str] = None,
    parts: Optional[int] = None,
) -> Dict[str, Any]:
    """Resolve runtime arguments by combining CLI overrides with config."""
    config = load_config(config_path)

    resolved_input = input_html or config.get("input_html")
    resolved_rendered = rendered_html or config.get("rendered_html")
    resolved_output = output_dir or config.get("markdown_output_dir")
    resolved_parts = parts or config.get("split_parts", 5)

    if not resolved_input:
        raise ConfigError("Missing input_html configuration.")
    if not resolved_output:
        raise ConfigError("Missing markdown_output_dir configuration.")

    result: Dict[str, Any] = {
        "input_html": (
            _resolve_path(resolved_input, os.getcwd())
            if not os.path.isabs(resolved_input)
            else resolved_input
        ),
        "markdown_output_dir": (
            _resolve_path(resolved_output, os.getcwd())
            if not os.path.isabs(resolved_output)
            else resolved_output
        ),
        "split_parts": int(resolved_parts),
    }

    if resolved_rendered:
        result["rendered_html"] = (
            _resolve_path(resolved_rendered, os.getcwd())
            if not os.path.isabs(resolved_rendered)
            else resolved_rendered
        )

    return result
