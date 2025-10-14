# Rendered Artifact Expansion – Module Sketch

## Goals

- Add JSON and PDF exports alongside the existing HTML/Markdown/Text outputs with identical directory conventions.
- Centralize chunking so every format uses `rendered_chat_<type>_part_<i>_of_<n>.<ext>` naming without duplicating loops.
- Keep `process_pending_inputs.py` focused on discovery/orchestration by delegating artifact work to a reusable helper.

## Proposed Package Layout

```text
artifacts/
  __init__.py
  pipeline.py          # high-level entrypoint invoked from process_pending_inputs
  render_input.py      # wrappers around render_chat_html to guarantee base HTML exists
  formats/
    __init__.py
    html.py            # html aggregate + chunk logic (migrated from convert_rendered_html_to_md)
    markdown.py        # markdown aggregate + chunk logic
    text.py            # text aggregate + chunk logic
    json.py            # new: DOM/conversations serialization + chunks
    pdf.py             # new: HTML -> PDF conversion + chunks
  chunking.py          # shared chunk writer for any serialized artifact
  cleanup.py           # removes legacy filenames and prepares directories when overwrite
```

- `convert_rendered_html_to_md.py` remains as a compatibility wrapper that forwards to `artifacts.pipeline.generate_all` for external callers.
- `render_chat_html.py` continues to own Playwright rendering; `artifacts.render_input` simply re-exports helpers for consistency.

## Responsibilities by Module

- `artifacts.pipeline.generate_all` orchestrates artifacts for a dataset:
  - Accepts `slug`, `rendered_html_path`, optional `conversations_path`, output directories, `chunk_char_limit`, and `overwrite`.
  - Calls format generators in sequence (HTML → Markdown → Text → JSON → PDF) so later steps can reuse earlier outputs.
- `artifacts.chunking.write_chunks(source_bytes, dest_dir, base_name, extension, max_bytes, overwrite)`:
  - Produces `_part_<i>_of_<n>` files, returns a `ChunkManifest(total_parts, part_paths)` for logging.
  - Performs cleanup of stale chunk files once per invocation when `overwrite` is true.
- Format modules focus on serialization only:
  - `formats.html.generate(...)` writes aggregate HTML and invokes chunking.
  - `formats.markdown.generate(...)` converts HTML → Markdown, saves combined pack, then chunkifies via the shared helper.
  - `formats.text.generate(...)` derives `.txt` from Markdown and chunkifies bytes.
  - `formats.json.generate(...)` outputs the canonical JSON (DOM snapshot or `conversations.json`) and chunkifies it.
  - `formats.pdf.generate(...)` renders a PDF (Playwright `page.pdf` or wkhtmltopdf fallback) and chunkifies the bytes.

## Chunking API Generalization

- Single helper converts string payloads to UTF-8 bytes before chunking; binary formats (PDF) pass bytes directly.
- Naming convention enforced inside `write_chunks` using the pattern `f"{base_name}_{artifact_type}_part_{index:02d}_of_{total:02d}{extension}"`.
- `ChunkManifest` allows `process_pending_inputs.py` to emit consistent success logs and aggregate stats.
- Existing Markdown/Text chunk loops are refactored to call `write_chunks`, eliminating format-specific duplication.

## Orchestration Flow

```text
process_pending_inputs
  └─ artifacts.pipeline.generate_all(slug, dataset_paths, chunk_char_limit, overwrite)
       ├─ render_input.ensure_rendered_html()
       ├─ formats.html.generate()
       ├─ formats.markdown.generate()
       ├─ formats.text.generate()
       ├─ formats.json.generate()
       └─ formats.pdf.generate()
```

- `generate_all` returns a summary dictionary (per-format success flags + chunk manifests) so callers can log or inspect results.
- Directory cleanup happens once upfront in `cleanup.prepare_output_dirs(...)`, guaranteeing idempotent reruns.

## Integration Steps

1. Introduce the `artifacts` package with `chunking.py`, `cleanup.py`, and a thin `pipeline.generate_all` that still calls the existing Markdown/Text helpers (no behavior change yet).
2. Migrate current HTML/Markdown/Text logic from `convert_rendered_html_to_md.py` into `formats/` modules and update callers.
3. Implement `formats.json` to serialize `conversations.json` (or DOM snapshot) and wire it into the pipeline.
4. Implement `formats.pdf` using Playwright PDF export with timeout/viewport options consistent with HTML rendering; reuse chunking.
5. Update `process_pending_inputs.py` to call `artifacts.pipeline.generate_all` and surface summary logs using the returned manifests.
6. Remove legacy chunking utilities once the new structure is validated end-to-end with `--overwrite` runs.

This layout keeps the orchestrator lean, guarantees consistent naming across formats, and makes future artifact additions (e.g., DOCX, embeddings) a matter of adding a new module under `formats/` without touching the pipeline core.
