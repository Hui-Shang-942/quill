# Two-Font UI Rule Design

Date: 2026-10-21

## Goal

Apply two typefaces consistently across the Gradio interface: 方正大标宋简体 for all interface text and AI-generated copy, except the full “创作任务” card, which uses 微软雅黑.

## Current structure

The interface is defined in `app.py` and styled by `UI-frontend-design/theme.css`. The creation task card is the `#frontdesk-input` column. The generated copy is rendered in `#copy-report` in the separate `#frontdesk-output` card. The shared CSS is passed to Gradio at launch, so rules can cover both static markup and dynamically rendered component content.

## Design

Define named font stacks in the shared stylesheet. Set 方正大标宋简体 as the page-wide stack on the document and Gradio root, with a generic serif fallback. Apply 微软雅黑 with a generic sans-serif fallback to `#frontdesk-input` and all descendants, including form controls and buttons. Let the remaining interface and generated report inherit the page-wide stack; explicitly cover `#copy-report` if Gradio component styles override inheritance.

No layout, content, or generation behavior changes are in scope. The rule requests local/system fonts by family name; font files will not be bundled.

## Acceptance criteria

- The page, header, status and progress text, result card, and generated AI copy use 方正大标宋简体 when available.
- All text and controls inside the complete “创作任务” card use 微软雅黑 when available.
- Generic serif/sans-serif fallbacks are used if the requested local font is unavailable.
- No other visual or application behavior is changed.
