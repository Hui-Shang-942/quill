# Gradio 创空间适配 Implementation Plan

> **For agentic workers:** Execute the tasks inline in order. Keep the existing Agent pipeline as the source of generation and verification behavior.

**Goal:** Add a Gradio app entry point and deployment metadata so `quill-of-Huawei` can run as a public ModelScope Gradio Studio.

**Architecture:** `app.py` creates a Gradio Blocks UI and calls `Agent.start` / `Agent.revise` directly. Gradio is the only UI and application entry point. Python requirements install Gradio, existing backend libraries, and a Node.js runtime package used by the bundled ima API client.

**Tech Stack:** Python, Gradio, existing Agent / ima API client, ModelScope Studio README metadata.

## Global Constraints

- Keep all API credentials in Studio Secrets or local environment variables; never commit credentials.
- Preserve current Agent behavior for retrieval, fact checks, compliance checks, revision and image attachment.
- Use Gradio as the only application entry point; remove the legacy Flask service and static frontend.
- Public visitors share the deployed upstream API quotas.
- Do not add or run tests unless the user requests testing.

---

## File Structure

- `app.py`: Gradio UI, callback functions, Agent lifecycle, result rendering and image gallery conversion.
- `requirements.txt`: pinned compatible Gradio, Anthropic SDK, `httpx2`, and Node.js runtime dependency.
- `README.md`: ModelScope Gradio metadata plus brief app description and dependency note.
- `docs/deployment-modelscope.md`: Create Studio, configure Secrets, upload the project, deploy and diagnose startup errors.
- `docs/superpowers/specs/2026-10-20-gradio-space-design.md`: approved design, updated to use Python-managed Node.js runtime.

### Task 1: Create the Gradio application

**Files:**
- Create: `app.py`

**Interfaces:**
- Inputs: product model, audience, scenario, platform, extra requirements.
- State: the latest successful structured result for revisions.
- Actions: `generate_copy(model, audience, scenario, platform, extra, progress)` creates `Task` and calls `Agent.start`; `revise_copy(instruction, previous)` calls `Agent.revise`.
- Outputs: formatted report Markdown, generated image gallery, and status text.

- [x] Build Gradio Blocks with all current platform choices and searchable product models.
- [x] Check required environment variables before constructing `Agent`; report missing names only, never values.
- [x] Add explicit status, generation, revision and reset controls.
- [x] Format success results using `render_markdown`; display images from `res['_image_bytes']` as Gradio gallery items.
- [x] Show `need_info`, `no_evidence`, `conflict`, and `error` states as readable messages and clear stale result state.
- [x] Enable a one-job queue and wire `Agent.start`/`Agent.revise` progress callbacks to `gr.Progress`.

### Task 2: Add Python dependencies and ModelScope metadata

**Files:**
- Create: `requirements.txt`
- Create: `README.md`

**Interfaces:**
- `requirements.txt` is consumed by ModelScope Studio Gradio build.
- README metadata selects the Gradio SDK and points to `app.py`.

- [x] Pin Gradio 6.2.0, `anthropic`, `httpx2`, and `nodejs-wheel` 24.16.0.
- [x] Declare ModelScope Gradio metadata for application name, `app.py`, and SDK version 6.2.0.
- [x] Document that secrets are configured in Studio Settings and are not stored in repository files.

### Task 3: Write ModelScope deployment instructions

**Files:**
- Create: `docs/deployment-modelscope.md`

**Interfaces:**
- The document guides a user from a local folder to a running Gradio Studio.

- [x] List the exact required Secrets: `ANTHROPIC_API_KEY`, `IMA_CLIENT_ID`, `IMA_API_KEY`.
- [x] Explain uploading the project root (so `app.py`, `agent/`, and `vendor/` are at the repository root).
- [x] Explain public visitors share the owner's Anthropic and ima quota and how to keep the app private until ready.
- [x] Include startup diagnosis for missing credentials, missing Node executable and model API failures.

### Task 4: Inspect generated deployment files

**Files:**
- Review: `app.py`, `requirements.txt`, `README.md`, `docs/deployment-modelscope.md`

- [x] Read the final files to confirm exact secret names match app checks and the README entry file is `app.py`.
- [x] Confirm docs point at the project root and do not direct users to upload local `.cache`, `.env`, `outputs`, or knowledge-base source documents.
- [x] Do not run tests unless requested; Python syntax compilation completed successfully.

## Self-Review

- Spec target: Gradio entry, current Agent reuse, secret handling, serialized generation, revision and images are covered in Tasks 1–3.
- Deployment artifacts and user steps are covered in Tasks 2–3.
- Validation is limited to source inspection because the user has not requested tests.
