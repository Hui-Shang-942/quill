# Inline Copy Editing and Passage Polishing Implementation Plan

> **For agentic workers:** Implement the tasks in order in this session. Keep each change focused and preserve unrelated working-tree edits.

**Goal:** Make the original generated copy editable in its existing report card, add contextual AI passage polishing with accept/reject replacement, and make edited copy flow into downloads and later whole-copy revisions.

**Architecture:** Keep the structured generation result for facts, images, and verification metadata. Maintain the current publishable manuscript as a separate string in the result state. Add a passage-polishing operation on `Agent`, and let the UI replace an exact editor selection only after validating its source snapshot and offsets.

**Tech Stack:** Python, Gradio 6.2.0 (the local environment currently reports Gradio 5.50.0), existing Anthropic-backed `LLM`, Markdown rendering/export.

## Global Constraints

- Preserve the current structured result, its evidence, images, and verification metadata.
- Keep the current edited copy as the basis for future whole-copy revisions.
- A polish candidate never changes the manuscript until the user accepts it.
- Do not claim the original verification covers content edited after generation; visibly mark edited copy for human review.
- Do not alter unrelated files with existing working-tree changes.
- No test files or test runs are included in this plan.

## File map

- Modify `agent/pipeline.py`: add copy-text derivation, passage polishing, and optional current-copy input to `Agent.revise()`.
- Modify `agent/exporter.py`: render/export a current-copy override while preserving the rest of the report.
- Modify `app.py`: attach selection and edit handling to the original report card copy, add its contextual floating popover, and carry current copy through generate/revise/clear flows.
- Modify `UI-frontend-design/theme.css`: hide the nonvisual event controller and keep inline editing integrated in the existing report card.

---

### Task 1: Add manuscript and passage-polishing operations

**Files:**
- Modify: `agent/pipeline.py`

**Interfaces:**
- Add `render_copy_text(draft: dict) -> str` to create a plain-text manuscript from the draft title, poster headings/points, lead, section headings/body, call to action, and tags.
- Add `Agent.polish_passage(previous: dict, passage: str, instruction: str, surrounding_copy: str = "") -> str`.
- Extend `Agent.revise(previous, instruction, new_platform=None, progress=..., draft_progress=None, current_copy=None)`; include `current_copy` as the latest manuscript in the writing request when provided.

- [ ] Build the plain-text manuscript in the same order as the publishable draft; exclude evidence and verification metadata.
- [ ] Implement passage polishing with the existing `self.llm.text()` client, product/context facts from `previous`, and instructions to preserve the selected passage's meaning and avoid unsupported product claims.
- [ ] Include the current manuscript in the whole-revision writing request so the latest manual edits and accepted passage replacements are the revision source.
- [ ] Review the resulting diff for preservation of default behavior when `current_copy` is omitted.

### Task 2: Render the current manuscript in report and export

**Files:**
- Modify: `agent/exporter.py`

**Interfaces:**
- Extend `render_markdown(res: dict, *, web_images: bool = False, copy_override: str | None = None) -> str`.
- Extend `export(res: dict, name: str | None = None, *, copy_override: str | None = None) -> dict`.

- [ ] When `copy_override` is present, render it as the publish-copy content in the report and retain the evidence, image list, and verification sections.
- [ ] Render the original copy within the existing on-screen report card as editable text; keep downloadable Markdown complete and conventional.
- [ ] Add a clear human-review note for changed manuscripts.
- [ ] Continue using the existing structured draft rendering when `copy_override` is absent.
- [ ] Ensure the download file is generated from the same `copy_override` shown in the report preview.

### Task 3: Add in-place editing and selection-anchored polishing

**Files:**
- Modify: `app.py`
- Modify: `UI-frontend-design/theme.css`

**Interfaces:**
- UI state stores `current_copy` in `previous_result["_current_copy"]`.
- Attach editing and selection handling to the original copy inside the existing report card; use a nonvisual HTML controller for browser events and a contextual popover only while text is selected.
- Call `polish_passage_server(source, selected, instruction, context)` from the popover through Gradio `gr.HTML.server_functions`.

- [ ] Keep publishable text within the original generated report card, editable in place; do not add a separate editor or polishing card. Attach a selection listener that positions the popover beside the selected range.
- [ ] Put the custom instruction, generated candidate, accept, and cancel actions inside that popover.
- [ ] Call the server polishing operation with the selected passage, source snapshot, instruction, and compact product context. Return model/configuration errors in the popover without replacing text.
- [ ] On accept, verify the source snapshot and saved DOM range still match; replace only that range.
- [ ] On manual edit or accepted replacement, update `previous_result["_current_copy"]`, report preview, Markdown download, and human-review status together.
- [ ] Wire whole-copy revision to pass the editor's latest text into `Agent.revise()` and refresh the editor/preview/download on success.
- [ ] Populate the original report card after generation; clear its copy and candidate state when clearing results.
- [ ] Keep editing directly in the original copy and show only the small contextual popover after selection.
- [ ] Review callback output counts and event wiring against the current Gradio component order.

## Self-review

- Spec coverage: editor and passage candidate behavior are in Task 3; safe exact replacement and stale-candidate rejection are in Task 3; manuscript state and whole-copy revisions are in Tasks 1 and 3; report/download synchronization and review note are in Task 2; preservation of existing metadata and failure behavior is in Tasks 1–3.
- Placeholder scan: no TODO/TBD steps or unspecified implementation decisions remain.
- Type consistency: `render_copy_text`, `polish_passage`, `current_copy`, and exporter `copy_override` signatures are consistent across tasks.

Implementation review will use source/diff inspection only; no test files or test commands are planned.
