"""Update config.json to point at the next unprocessed data/input export."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional

DATA_ROOT = Path("data")
CONFIG_PATH = Path("config.json")
RENDERED_NAME = "rendered_chat.html"


def load_current_config(path: Path) -> Dict[str, Any]:
    """Read the current JSON config data from the provided path."""
    if not path.exists():
        raise SystemExit(
            "config.json not found. Create one from "
            "config.example.json first."
        )
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def has_markdown_output(output_dir: Path) -> bool:
    """Return True when the output directory already contains Markdown."""
    return output_dir.exists() and any(output_dir.glob("*.md"))


def find_next_dataset() -> Optional[str]:
    """Locate the next dataset directory that still needs processing."""
    input_root = DATA_ROOT / "input"
    if not input_root.exists():
        return None

    for candidate in sorted(p for p in input_root.iterdir() if p.is_dir()):
        chat_html = candidate / "chat.html"
        if not chat_html.exists():
            continue

        dataset_name = candidate.name
        markdown_dir = DATA_ROOT / "markdown_output" / dataset_name
        rendered_file = DATA_ROOT / "rendered" / dataset_name / RENDERED_NAME

        if has_markdown_output(markdown_dir) and rendered_file.exists():
            continue

        return dataset_name

    return None


def update_config(config: Dict[str, Any], dataset: str) -> Dict[str, Any]:
    """Return a new config mapping updated to point at ``dataset`` paths."""
    updated: Dict[str, Any] = dict(config)
    updated["input_html"] = f"./data/input/{dataset}/chat.html"
    updated["rendered_html"] = f"./data/rendered/{dataset}/{RENDERED_NAME}"
    updated["markdown_output_dir"] = f"./data/markdown_output/{dataset}"
    return updated


def write_config(path: Path, data: Dict[str, Any]) -> None:
    """Persist the config dictionary to disk with pretty formatting."""
    with path.open("w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=4)
        handle.write("\n")


def main() -> None:
    """Update ``config.json`` to point at the next incomplete dataset."""
    config = load_current_config(CONFIG_PATH)
    dataset = find_next_dataset()
    if not dataset:
        print("No pending datasets found. config.json left unchanged.")
        return

    updated = update_config(config, dataset)
    write_config(CONFIG_PATH, updated)
    print(f"config.json updated to target dataset: {dataset}")


if __name__ == "__main__":
    main()
