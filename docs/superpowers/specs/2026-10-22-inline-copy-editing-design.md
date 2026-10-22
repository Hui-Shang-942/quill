# Inline Copy Editing and Passage Polishing Design

Date: 2026-10-22

## Goal

Let users edit generated publishable copy in the Gradio interface, select a passage for AI polishing with a custom instruction, review the candidate, and replace the selected source only after accepting it. Keep manual edits as the source for later whole-copy revisions and Markdown downloads.

## Existing context

- `app.py` renders the full generated report in a Markdown component and stores the structured result in `previous_result`.
- `Agent.revise()` revises a prior structured result using its `_ctx`; the current UI passes only the revision instruction and result state.
- `render_markdown()` and `export()` generate the on-screen report and downloadable Markdown from the structured result.

## User experience

Keep the complete report preview and add a separate editable text area containing only publishable copy (title, body, call to action, and tags). Users can edit the text directly. They can select any span in that editor, enter a custom polishing instruction, and request a candidate. Show the candidate without changing the source. Accepting it replaces the selected span immediately; canceling leaves the source unchanged. If the source changed while the candidate was being generated, reject the stale replacement and ask the user to select the passage again.

After manual edits or an accepted replacement, refresh the report preview and Markdown download from the current copy. The existing whole-copy revision must use the current edited copy as its starting text, then refresh the editor, preview, and download with its result. Preserve the source evidence and verification report as report metadata; mark a user-edited or AI-polished manuscript as needing human review rather than implying its original checks cover the changed text.

## Design and data flow

1. Derive an editable publish-copy string from the structured draft when generation finishes. Keep it alongside the structured result in UI state.
2. Capture the selected text and its start/end offsets from the editable text area. Submit those offsets, the source snapshot, selection, user instruction, and relevant surrounding copy to a passage-polishing operation.
3. Have the polishing operation use the existing LLM configuration and the product facts already present in the result context. Ask it to preserve meaning and avoid introducing unsupported specifications, guarantees, or claims. Return a candidate for review; do not mutate the current copy during generation.
4. On acceptance, verify that the saved source snapshot and selected range still match. Replace only that range and set the revised copy as the current manuscript. On mismatch, leave the source untouched and request a fresh selection.
5. Render the full report and Markdown export using the current manuscript for the publish-copy section, while leaving evidence, imagery, and verification metadata intact. Preserve a clear note that edits after generation need human review.
6. Pass the current manuscript into `Agent.revise()` as the basis for whole-copy revision, together with the existing structured context and the user's new instruction. On success, replace the current manuscript with the newly revised copy.

## Error handling

- Disable or reject polishing if no passage is selected, the instruction is blank, or the prior result has no revision context.
- Display model and configuration failures without changing the current copy.
- Never apply a candidate if its source snapshot no longer matches the editor contents.
- Keep copy changes in the current result state so subsequent editing, revision, preview, and download use the same version.

## Acceptance criteria

- Generated publishable copy appears in an editable area alongside the full report preview.
- Manual edits update the current manuscript and are reflected in report preview and Markdown download.
- A selected passage can be polished using a user instruction; the candidate does not change the source until accepted.
- Accept replaces exactly the selected passage, and cancel leaves the source intact.
- A stale candidate cannot replace text at an outdated position.
- Whole-copy revision starts from the latest manual or accepted edits.
- Existing report evidence and images remain available, and modified copy is clearly marked for human review.
