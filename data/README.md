# Data Directory

Use this folder to stage your own OpenAI chat exports and URL batches.

- Drop each raw ZIP (for example `20251012.zip`) into `input/` and extract it alongside the archive so the folder path becomes `input/20251012/`.
- Place newline-delimited URL lists in their own folders, e.g. `input/20251012_urls/20251012_urls.txt`. The automation scripts split them by domain automatically.
- Generated Playwright transcripts land in `rendered/<export-id>/` (for example `rendered/20251012/`).
- Markdown slices land in `markdown_output/<export-id>/` (for example `markdown_output/20251012/`).

The `.gitkeep` files keep these directories in version control while empty. Remove them once you add your own data.
