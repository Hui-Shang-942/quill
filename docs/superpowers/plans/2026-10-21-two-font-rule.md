# Two-Font UI Rule Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use inline execution to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Apply 方正大标宋简体 across the interface and AI copy, with 微软雅黑 on the full “创作任务” card.

**Architecture:** Keep the behavior in the existing Gradio theme stylesheet. Define two fallback stacks, apply the default stack at the page/app root, and override the complete input card including controls.

**Tech Stack:** Gradio, CSS

## Global Constraints

- Use 方正大标宋简体 for all interface and generated copy outside `#frontdesk-input`.
- Use 微软雅黑 for all text inside `#frontdesk-input`.
- Keep layout and behavior unchanged; do not bundle font files.

---

### Task 1: Apply page and card font stacks

**Files:**
- Modify: `UI-frontend-design/theme.css`

**Interfaces:**
- Consumes: Existing `#frontdesk-input` ID and shared stylesheet loaded by `app.py`.
- Produces: CSS font variables and scoped font-family rules.

- [x] Define 方正大标宋简体 with a generic serif fallback and 微软雅黑 with a generic sans-serif fallback.
- [x] Apply the default family to page/app content and controls; override the entire `#frontdesk-input` subtree with 微软雅黑.
- [x] Review the stylesheet and confirm the font selector rules only set `font-family`.
