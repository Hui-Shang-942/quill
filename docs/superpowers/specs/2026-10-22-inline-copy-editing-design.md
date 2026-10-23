# Inline Copy Editing and Passage Polishing Design

Date: 2026-10-22

## Goal

Let users edit generated publishable copy in the Gradio interface, select a passage for AI polishing with a custom instruction, review the candidate, and replace the selected source only after accepting it. Keep manual edits as the source for later whole-copy revisions and Markdown downloads.

## Existing context

- `app.py` renders the full generated report in a Markdown component and stores the structured result in `previous_result`.
- `Agent.revise()` revises a prior structured result using its `_ctx`; the current UI passes only the revision instruction and result state.
- `render_markdown()` and `export()` generate the on-screen report and downloadable Markdown from the structured result.

## User experience

Keep the existing generated report card and make its original publishable copy editable in place. Do not add a separate copy editor or polishing card. When the user selects a passage in that original copy, open a small floating “AI 润色” popover beside the selection. The popover contains the custom instruction, candidate text, and replace/cancel actions. Show the candidate without changing the source. Accepting it replaces the selected span immediately; canceling leaves the source unchanged. If the source changed while the candidate was being generated, reject the stale replacement and ask the user to select the passage again.

After manual edits or an accepted replacement, refresh the report preview and Markdown download from the current copy. The existing whole-copy revision must use the current edited copy as its starting text, then refresh the editor, preview, and download with its result. Preserve the source evidence and verification report as report metadata; mark a user-edited or AI-polished manuscript as needing human review rather than implying its original checks cover the changed text.

## Design and data flow

1. Derive the publish-copy string from the structured draft when generation finishes. Render it inside the existing report card as the original copy, editable in place, with a contextual popover that appears beside a non-empty text selection.
2. Capture the selection range and source snapshot in the browser. Call the passage-polishing operation from the popover with the selected text, user instruction, nearby copy, and relevant product facts.
3. Have the polishing operation use the existing LLM configuration. Ask it to preserve meaning and avoid unsupported specifications, guarantees, or claims. Return a candidate into the popover; do not mutate the source during generation.
4. On acceptance, verify that the source snapshot and saved range still match. Replace only that range and sync the resulting manuscript to application state. On mismatch, leave the source untouched and ask the user to select the passage again.
5. Update the existing report card and Markdown export using the current manuscript while leaving evidence, imagery, and verification metadata intact. Keep report details and the original copy together in the existing card. Preserve a clear note that edits after generation need human review.
6. Pass the current manuscript into `Agent.revise()` as the basis for whole-copy revision, together with the existing structured context and the user's new instruction. On success, replace the current manuscript with the newly revised copy.

## Error handling

- Disable or reject polishing if no passage is selected, the instruction is blank, or the prior result has no revision context.
- Display model and configuration failures without changing the current copy.
- Never apply a candidate if its source snapshot no longer matches the editor contents.
- Keep copy changes in the current result state so subsequent editing, revision, preview, and download use the same version.

## Acceptance criteria

- The original publishable copy in the existing report card is editable in place; there is no separate editor or polishing card.
- Selecting a passage opens the floating “AI 润色” popover beside that selection.
- Manual edits update the current manuscript and are reflected in report preview and Markdown download.
- A selected passage can be polished using a user instruction; the candidate does not change the source until accepted.
- Accept replaces exactly the selected passage, and cancel leaves the source intact.
- A stale candidate cannot replace text at an outdated position.
- Whole-copy revision starts from the latest manual or accepted edits.
- Existing report evidence and images remain available, and modified copy is clearly marked for human review.
