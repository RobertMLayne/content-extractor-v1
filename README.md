# content-extractor-v1

Utilities for slicing ChatGPT exports and URL batches into manageable Markdown files. All I/O paths are driven through JSON configuration so everything runs on any workstation without code edits.

## 1. Prerequisites

- Python 3.9+
- `pip install -r requirements.txt` (or install the individual runtime deps listed below)
  - `beautifulsoup4`
  - `markdownify`
  - `lxml`
  - `playwright` (only required when using `render_chat_html.py`)
  - After installing Playwright, run `playwright install` to download browser binaries.

## 2. Prepare the OpenAI export

1. Copy your raw ChatGPT export ZIP (for example `20251012.zip`) into `data/input/`.
2. Extract the archive beside the ZIP so the structure becomes `data/input/20251012/...` (the export already contains `chat.html`, `conversations.json`, attachments, etc.).
3. Leave the companion JSON and media folders in place; the tools only require `chat.html`, but keeping everything together makes reruns painless.

## 3. Configure runtime paths

1. Copy `config.example.json` to `config.json` and update the paths so they point to one of your extracted exports (any values work; the automation scripts override them at runtime).
2. Paths can be absolute or relative to the config file. Example snippet targeting the new `data/` layout:

```json
{
  "input_html": "./data/input/20251012/chat.html",
  "rendered_html": "./data/rendered/20251012/rendered_chat.html",
  "markdown_output_dir": "./data/markdown_output/20251012",
  "split_parts": 5
}
```

> Tip: set `CONTENT_EXTRACTOR_CONFIG` to the config file path if you keep it outside the repository.

## 4. Running the scripts

| Script | Purpose | Example |
| --- | --- | --- |
| `process_pending_inputs.py` | Scans `data/inputs/` for exports, URL lists, or PDFs and generates all missing outputs automatically. | `python process_pending_inputs.py --config config.openai.json --overwrite` |
| `render_chat_html.py` | Hydrates `chat.html` into a fully rendered version using Playwright. | `python render_chat_html.py --config config.openai.json` |
| `convert_rendered_html_to_md.py` | Converts a rendered HTML transcript into Markdown slices (invoked internally by the pipelines but can be run directly). | `python convert_rendered_html_to_md.py --rendered-html rendered_chat.html --output-dir markdown_output` |
| `process_urls.py` | Fetches URL lists, groups them by domain, and stores rendered HTML + Markdown parts per page. | `python process_urls.py --urls-file some-list.txt --config config.urls.json` |
| `pdf_renderer.py` | Renders PDFs to HTML snapshots using Playwright. | `python pdf_renderer.py --input some.pdf --output rendered.html` |

You can override paths at runtime without editing the JSON file or swap in the profile that matches your workload (`config.openai.json`, `config.urls.json`, `config.pdfs.json`, `config.sandbox.json`):

```powershell
python convert_rendered_html_to_md.py --rendered-html "C:/exports/rendered_chat.html" --output-dir "C:/exports/md" --chunk-char-limit 40000
```

## 5. Outputs & data layout

- Markdown files for ChatGPT exports land in `data/markdown_output/<export-id>/`.
- Rendered Playwright transcripts for exports are stored in `data/rendered/<export-id>/rendered_chat.html`.
- URLs lists are grouped by base domain. Each domain gets its own folder, e.g. `data/rendered/developers.cloudflare.com/<slug>.html` and matching Markdown parts in `data/markdown_output/developers.cloudflare.com/<slug>/`.
- Regenerate any dataset by rerunning `process_pending_inputs.py --overwrite` (or by invoking the individual scripts).

## 6. Working with URL batches

- Drop any newline-delimited URL list under `data/input/<dataset>/<listname>.txt`.
- Run `python process_pending_inputs.py` (or `python process_urls.py --urls-file path/to/list.txt`) and every URL is fetched. Outputs are grouped by domain so `medium.com` URLs land in `data/rendered/medium.com/` and `data/markdown_output/medium.com/`.
- The slug inside each domain folder mirrors the sanitized path/query, keeping reruns idempotent. Add `--overwrite` to the script to force re-fetches.
- `process_pending_inputs.py` applies the split count from `config.json`; override it with `--overwrite --config-other.json` when needed.

## 7. Troubleshooting

- `Missing dependency ...` → install the listed package with `pip` and retry.
- `Config error: ...` → re-check `config.json`, the paths must exist and be readable.
- Playwright launch failures → make sure `playwright install` completed and Chromium is available.
