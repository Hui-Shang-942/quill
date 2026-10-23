"""Gradio entry point for the Huawei PC copywriting assistant."""
from __future__ import annotations

import html
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from queue import Empty, Queue

import gradio as gr
from markdown_it import MarkdownIt

from agent.catalog import MODELS
from agent.config import CACHE_DIR, COMPETITION_PLATFORMS, OUTPUT_DIR
from agent.exporter import export, render_markdown
from agent.pipeline import Agent, Task, WORKFLOW_STAGES, render_copy_text
from agent.platform_rules import PLATFORMS, SCENARIOS, SCENARIO_AUDIENCES


REQUIRED_SECRETS = ("ANTHROPIC_API_KEY", "IMA_CLIENT_ID", "IMA_API_KEY")
OTHER_PLATFORMS = [name for name in PLATFORMS if name not in COMPETITION_PLATFORMS]
UI_DIR = Path(__file__).resolve().parent / "UI-frontend-design"
UI_CSS = (UI_DIR / "theme.css").read_text(encoding="utf-8")
HERO_HTML = (UI_DIR / "hero.html").read_text(encoding="utf-8")
AUDIENCES = [
    *SCENARIO_AUDIENCES.values(),
]
REPORT_MARKDOWN = MarkdownIt("default", {"html": False}).enable("table")


def _render_report(markdown: str) -> str:
    """Render report Markdown safely for the editable report HTML component."""
    return REPORT_MARKDOWN.render(markdown or "")

COPY_CONTROLLER_TEMPLATE = """
<span>${String(value || "").replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;").replace(/\\n/g, "<br>")}</span>
"""
COPY_EDITOR_JS = """
let popup = null;
let savedRange = null;
let sourceSnapshot = "";
let selectedText = "";

const getEditor = () => document.querySelector("#copy-report .publish-copy-editor") || document.querySelector(".publish-copy-editor");
const hidePopup = () => { if (popup) popup.remove(); popup = null; savedRange = null; };

function ensureEditableCopy() {
  const report = document.querySelector("#copy-report") || document;
  if (!report) return null;
  const existing = report.querySelector(".publish-copy-editor");
  if (existing) return existing;
  const headings = Array.from(report.querySelectorAll("h1"));
  const section = headings.find((heading) => heading.innerText.replace(/\\s/g, "").includes("三、图文软文"));
  if (!section) return null;
  let first = section.nextElementSibling;
  while (first && first.tagName === "BLOCKQUOTE") first = first.nextElementSibling;
  if (!first) return null;
  const nodes = [];
  let node = first;
  while (node && !(node.tagName === "H1" && node.innerText.replace(/\\s/g, "").includes("四、核验结果"))
      && !(node.tagName === "H2" && node.innerText.replace(/\\s/g, "").includes("配图信息"))) {
    nodes.push(node);
    node = node.nextElementSibling;
  }
  if (!nodes.length) return null;
  const editor = document.createElement("div");
  editor.className = "publish-copy-editor";
  editor.contentEditable = "true";
  editor.setAttribute("role", "textbox");
  editor.setAttribute("aria-multiline", "true");
  editor.setAttribute("spellcheck", "true");
  first.parentNode.insertBefore(editor, first);
  nodes.forEach((child) => editor.appendChild(child));
  editor.querySelectorAll("img").forEach((image) => { image.contentEditable = "false"; });
  return editor;
}

function extractCopyText(editor) {
  if (!editor) return "";
  const copy = editor.cloneNode(true);
  copy.querySelectorAll("img").forEach((image) => image.remove());
  return copy.innerText.replace(/\\u00a0/g, " ").replace(/\\r/g, "").replace(/\\n+/g, "\\n\\n").trim();
}

function commitText() {
  const editor = getEditor();
  if (!editor) return;
  const text = extractCopyText(editor);
  if (text !== String(props.value || "")) {
    props.value = text;
    trigger("submit");
  }
}

function placePopup(rect) {
  if (!popup) return;
  const margin = 12;
  const width = Math.min(360, window.innerWidth - margin * 2);
  const left = Math.max(margin, Math.min(rect.left, window.innerWidth - width - margin));
  popup.style.left = left + "px";
  popup.style.top = Math.min(rect.bottom + 10, window.innerHeight - popup.offsetHeight - margin) + "px";
}

function showPopup() {
  const editor = ensureEditableCopy();
  const selection = window.getSelection();
  if (!editor || !selection || selection.isCollapsed || !selection.rangeCount) { hidePopup(); return; }
  const range = selection.getRangeAt(0);
  if (!editor.contains(range.commonAncestorContainer)) { hidePopup(); return; }
  const text = selection.toString();
  if (!text.trim()) { hidePopup(); return; }
  selectedText = text;
  sourceSnapshot = extractCopyText(editor);
  hidePopup();
  savedRange = range.cloneRange();
  popup = document.createElement("div");
  popup.className = "ai-polish-popover";
  popup.innerHTML = `<div class="ai-polish-title">AI 润色</div>
    <div class="ai-polish-message">已选中 ${Array.from(text).length} 个字符</div>
    <textarea class="ai-polish-prompt" placeholder="输入你希望如何修改这段文案"></textarea>
    <button type="button" class="ai-polish-generate">生成润色稿</button>
    <div class="ai-polish-message ai-polish-status"></div>
    <div class="ai-polish-candidate" hidden></div>
    <div class="ai-polish-actions" hidden>
      <button type="button" class="ai-polish-cancel">取消</button>
      <button type="button" class="ai-polish-primary ai-polish-accept">替换原文</button>
    </div>`;
  document.body.appendChild(popup);
  placePopup(range.getBoundingClientRect());
  popup.querySelector(".ai-polish-generate").addEventListener("click", async () => {
    const prompt = popup.querySelector(".ai-polish-prompt").value.trim();
    const status = popup.querySelector(".ai-polish-status");
    if (!prompt) { status.textContent = "请先填写润色要求。"; return; }
    const generate = popup.querySelector(".ai-polish-generate");
    generate.disabled = true;
    status.textContent = "正在生成润色稿…";
    try {
      const result = await server.polish_passage_server(sourceSnapshot, selectedText, prompt, props.copy_context || {});
      if (!result || !result.ok) { status.textContent = result?.message || "润色失败，请重试。"; generate.disabled = false; return; }
      popup.querySelector(".ai-polish-candidate").textContent = result.candidate;
      popup.querySelector(".ai-polish-candidate").hidden = false;
      popup.querySelector(".ai-polish-actions").hidden = false;
      status.textContent = "候选文案已生成，原文尚未更改。";
      requestAnimationFrame(() => { if (savedRange) placePopup(savedRange.getBoundingClientRect()); });
      generate.disabled = false;
    } catch (error) {
      status.textContent = "润色失败，请稍后重试。";
      generate.disabled = false;
    }
  });
  popup.querySelector(".ai-polish-cancel").addEventListener("click", () => { hidePopup(); commitText(); });
  popup.querySelector(".ai-polish-accept").addEventListener("click", () => {
    const currentEditor = getEditor();
    const replacement = popup.querySelector(".ai-polish-candidate").textContent;
    if (!currentEditor || extractCopyText(currentEditor) !== sourceSnapshot || !savedRange || savedRange.toString() !== selectedText) {
      popup.querySelector(".ai-polish-status").textContent = "原文已变化，请重新选择并润色。";
      return;
    }
    savedRange.deleteContents();
    savedRange.insertNode(document.createTextNode(replacement));
    const updated = extractCopyText(currentEditor);
    hidePopup();
    props.value = updated;
    trigger("submit");
  });
}

if (!window.__copyPolishEventsAttached) {
  window.__copyPolishEventsAttached = true;
  document.addEventListener("mouseup", (event) => {
    if (popup && popup.contains(event.target)) return;
    const editor = getEditor();
    if (editor && editor.contains(event.target)) setTimeout(showPopup, 0);
  });
  document.addEventListener("keyup", (event) => {
    const editor = getEditor();
    const selectAll = (event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "a";
    if (editor && editor.contains(event.target) && (event.shiftKey || selectAll || event.key.startsWith("Arrow"))) setTimeout(showPopup, 0);
  });
  document.addEventListener("focusout", () => setTimeout(() => {
    if (popup && popup.contains(document.activeElement)) return;
    commitText();
  }, 0), true);
  document.addEventListener("mousedown", (event) => {
    if (popup && popup.contains(event.target)) return;
    const editor = getEditor();
    if (!editor || !editor.contains(event.target)) { hidePopup(); commitText(); }
  }, true);
  const observer = new MutationObserver(() => requestAnimationFrame(ensureEditableCopy));
  observer.observe(document.body, { childList: true, subtree: true });
  const initialReportCheck = setInterval(() => {
    if (ensureEditableCopy()) clearInterval(initialReportCheck);
  }, 150);
}

function addPopupStyles() {
  if (document.getElementById("ai-polish-popup-style")) return;
  const style = document.createElement("style");
  style.id = "ai-polish-popup-style";
  style.textContent = `.ai-polish-popover{position:fixed;z-index:99999;width:min(360px,calc(100vw - 24px));padding:14px;border:1px solid #c5d2ce;border-radius:12px;background:#fff;color:#142124;box-shadow:0 14px 42px rgba(20,33,36,.2);font:14px/1.5 sans-serif}.ai-polish-popover *{box-sizing:border-box}.ai-polish-title{margin-bottom:8px;color:#176b63;font-weight:700}.ai-polish-prompt,.ai-polish-candidate{display:block;width:100%;margin:8px 0;padding:9px 10px;border:1px solid #dce4e1;border-radius:8px;color:#142124;background:#fff;font:inherit}.ai-polish-prompt{min-height:76px;resize:vertical}.ai-polish-candidate{max-height:180px;overflow:auto;white-space:pre-wrap;background:#f5f8f6}.ai-polish-actions{display:flex;justify-content:flex-end;gap:8px;margin-top:10px}.ai-polish-actions button,.ai-polish-generate{padding:7px 11px;border:1px solid #c5d2ce;border-radius:7px;color:#142124;background:#fff;cursor:pointer;font:inherit}.ai-polish-actions .ai-polish-primary{border-color:#c7000b;color:#fff;background:#c7000b}.ai-polish-message{margin:7px 0;color:#3e5052;font-size:12px}`;
  document.head.appendChild(style);
}
addPopupStyles();

// The MutationObserver above handles report rerenders in Gradio. `watch` is not
// part of the js_on_load runtime and caused initialization to abort here.
"""


def update_other_platform_visibility(platform_category: str | None):
    return gr.Dropdown(
        choices=OTHER_PLATFORMS,
        value=None,
        visible=platform_category == "其他",
    )


def update_audience_for_scenario(scenario: str | None, current_audience: str | None):
    """场景切换时预填赛题对应人群，同时保留自定义场景下的当前值。"""
    return gr.Dropdown(
        choices=AUDIENCES,
        value=SCENARIO_AUDIENCES.get(scenario, current_audience),
        allow_custom_value=True,
    )

_AGENT: Agent | None = None
_AGENT_LOCK = threading.Lock()


def _missing_secrets() -> list[str]:
    return [name for name in REQUIRED_SECRETS if not os.environ.get(name)]


def _get_agent() -> Agent:
    global _AGENT
    missing = _missing_secrets()
    if missing:
        raise RuntimeError("请先在创空间 Secrets 中配置：" + "、".join(missing))
    with _AGENT_LOCK:
        if _AGENT is None:
            CACHE_DIR.mkdir(parents=True, exist_ok=True)
            _AGENT = Agent()
        return _AGENT


def _new_workflow_state() -> dict:
    return {"active": None, "completed": [], "details": {}, "terminal": None}


def _apply_workflow_event(state: dict, event: dict) -> None:
    stage = event.get("stage")
    known = {item["id"] for item in WORKFLOW_STAGES}
    if stage not in known:
        return
    active = state.get("active")
    if active and active != stage and active not in state["completed"]:
        state["completed"].append(active)
    state["active"] = stage
    state["details"][stage] = event.get("detail", "")


def _workflow_html(state: dict) -> str:
    stages = WORKFLOW_STAGES
    completed = set(state.get("completed", []))
    active = state.get("active")
    terminal = state.get("terminal") or {}
    success = terminal.get("status") == "ok"
    if success:
        completed.update(item["id"] for item in stages)
        active = None
    done_count = sum(item["id"] in completed for item in stages)
    current_number = next((i + 1 for i, item in enumerate(stages) if item["id"] == active), None)
    progress_number = len(stages) if success else max(done_count, current_number or 0)
    if success:
        headline = "处理完成"
        detail = "所有阶段均已完成"
    elif active and not terminal:
        headline = "正在处理"
        detail = state.get("details", {}).get(active, "")
    elif terminal:
        headline = terminal.get("label", "处理已停止")
        detail = terminal.get("message", "")
    else:
        headline = "等待开始"
        detail = ""

    step_markup = []
    for item in stages:
        stage = item["id"]
        if stage in completed or success:
            css_state, state_label = "done", "已完成"
        elif stage == active:
            css_state, state_label = ("stopped", "已停止") if terminal else ("active", "进行中")
        else:
            css_state, state_label = "pending", "待处理"
        step_markup.append(
            f'<div class="workflow-step is-{css_state}" title="{html.escape(state_label)}">'
            f'<span class="workflow-step-mark" aria-hidden="true"></span>'
            f'<span class="workflow-step-label">{html.escape(item["label"])}</span></div>'
        )
    segments = []
    for item in stages:
        stage = item["id"]
        state_class = "is-done" if stage in completed or success else (
            "is-stopped" if stage == active and terminal else
            "is-active" if stage == active else "is-pending")
        segments.append(f'<span class="workflow-segment {state_class}" aria-hidden="true"></span>')
    return (
        '<div class="workflow-view">'
        '<div class="workflow-summary">'
        f'<span class="workflow-summary-title">{html.escape(headline)}</span>'
        f'<span class="workflow-summary-count">{progress_number}<i>/</i>{len(stages)}</span>'
        '</div>'
        f'<div class="workflow-track" role="img" aria-label="处理进度 {progress_number}/{len(stages)}">'
        f'{"".join(segments)}</div>'
        f'<div class="workflow-current">{html.escape(detail)}</div>'
        f'<div class="workflow-steps">{"".join(step_markup)}</div>'
        '</div>'
    )


HEADER_PATHS = [
    ("理解场景", {"understand"}),
    ("查找资料", {"strategy", "layout"}),
    ("撰写内容", {"write"}),
    ("事实核验", {"verify", "finish"}),
]


def _header_path_html() -> str:
    """构建不依赖实际任务状态、由 CSS 循环演示的生成路径。"""
    route_parts = []
    for index, (label, _stage_ids) in enumerate(HEADER_PATHS):
        route_parts.append(
            f'<span class="route-step" style="--route-delay:{index * 1.6}s">'
            f'<i aria-hidden="true"></i>{html.escape(label)}</span>'
        )
        if index < len(HEADER_PATHS) - 1:
            route_parts.append(
                f'<span class="route-connector" style="--route-delay:{index * 1.6}s" aria-hidden="true"></span>'
            )

    route = "".join(route_parts)
    return (f'<div class="workflow-map-title">内容生成路径</div>'
            f'<div class="workflow-route" aria-label="内容生成路径演示">{route}</div>')


def _hero_html() -> str:
    return HERO_HTML.replace("{{WORKFLOW_PATH}}", _header_path_html())


def _initial_workflow_state() -> dict:
    state = _new_workflow_state()
    state["active"] = WORKFLOW_STAGES[0]["id"]
    state["details"][state["active"]] = "正在启动任务"
    return state


def _stream_agent_call(call, fallback_state=None):
    events: Queue = Queue()
    state = _initial_workflow_state()
    draft_preview = ""
    started_at = time.monotonic()
    yield "正在启动后台流程…", _workflow_html(state), gr.skip(), "", None, fallback_state, gr.skip()

    with ThreadPoolExecutor(max_workers=1, thread_name_prefix="gradio-agent") as executor:
        future = executor.submit(
            call,
            lambda event: events.put(event),
            lambda markdown: events.put({"kind": "draft_preview", "markdown": markdown}),
        )
        while not future.done() or not events.empty():
            try:
                event = events.get(timeout=1.0)
            except Empty:
                elapsed = int(time.monotonic() - started_at)
                current = next((item["label"] for item in WORKFLOW_STAGES
                                if item["id"] == state.get("active")), "后台处理")
                status_message = (f"模型正在撰写草稿，事实与合规核验仍在进行（已用 {elapsed} 秒）。" if draft_preview else
                                  f"正在处理：{current}（已用 {elapsed} 秒）")
                yield status_message, _workflow_html(state), gr.skip(), _render_report(draft_preview), None, fallback_state, gr.skip()
                continue
            if event.get("kind") == "draft_preview":
                draft_preview = event.get("markdown", "")
                yield "模型正在实时撰写草稿，事实与合规核验仍在进行。", _workflow_html(state), gr.skip(), _render_report(draft_preview), None, fallback_state, gr.skip()
                continue
            _apply_workflow_event(state, event)
            status_message = ("草稿已开始实时显示，后台正在继续事实与合规核验。" if draft_preview else
                              "后台处理中，请查看上方阶段状态。")
            yield status_message, _workflow_html(state), gr.skip(), _render_report(draft_preview), None, fallback_state, gr.skip()

        try:
            result = future.result()
        except Exception as exc:
            result = {"status": "error", "message": f"生成失败（{type(exc).__name__}）：{exc}"}

    status = result.get("status")
    if status == "ok":
        state["terminal"] = {"status": "ok"}
    else:
        labels = {"need_info": "需要补充信息", "no_evidence": "缺少可用资料",
                  "conflict": "资料存在冲突，流程已停止", "error": "流程发生错误"}
        state["terminal"] = {"status": status, "label": labels.get(status, "流程已停止"),
                             "message": result.get("message", "")}
    yield _present_result(result, state, fallback_state)


def _present_result(result: dict, workflow_state: dict | None = None, fallback_state: dict | None = None):
    status = result.get("status")
    if status == "ok":
        copy_text = result.get("_current_copy") or render_copy_text(result.get("draft", {}))
        result["_current_copy"] = copy_text
        result.setdefault("_copy_needs_review", False)
        paths = export(result, copy_override=copy_text,
                       copy_needs_review=result["_copy_needs_review"])
        message = ("生成完成，图文内容与配图已按 Markdown 展示。"
                   if result.get("publish_ready") else
                   "生成完成，图文内容与配图已完整展示；部分核验未通过，请查看报告中的提示和待确认项。")
        state = workflow_state or _new_workflow_state()
        return (message, _workflow_html(state), gr.skip(),
                _render_report(render_markdown(result, web_images=True,
                                               copy_needs_review=result["_copy_needs_review"])),
                paths["md"], result,
                gr.HTML(value=copy_text, copy_context=_copy_context(result)))

    if status == "need_info":
        lines = ["信息还不完整，请补充后重新生成："]
        lines.extend(f"- {item.get('question', '')}" for item in result.get("questions", []))
        message = "\n".join(lines)
    elif status in ("no_evidence", "conflict", "error"):
        message = result.get("message", "本次没有生成文案。")
    else:
        message = "收到未知的生成状态，请稍后重试。"

    state = workflow_state or _new_workflow_state()
    return (message, _workflow_html(state), gr.skip(), _render_report(render_markdown(result)),
            None, fallback_state, gr.skip())


def check_status():
    missing = _missing_secrets()
    if missing:
        return "未配置以下创空间 Secrets：" + "、".join(missing)
    try:
        health = _get_agent().health()
    except Exception as exc:  # show configuration/runtime issue without exposing secret values
        return f"无法连接知识库：{exc}"
    if health.get("ok"):
        return f"已连接知识库：{health.get('kb_name', '已连接')}"
    return f"知识库连接失败：{health.get('error', '未知错误')}"


def generate_copy(model: str, audience: str, scenario: str, platform: str,
                  other_platform: str | None, extra: str):
    missing = _missing_secrets()
    if missing:
        yield "未配置创空间 Secrets：" + "、".join(missing), "", gr.skip(), "", None, None, gr.skip()
        return
    if platform == "其他":
        platform = other_platform
    if not model or not audience or not scenario or not platform:
        if not other_platform and platform is None:
            yield "请在“其他”分类中选择具体平台。", "", gr.skip(), "", None, None, gr.skip()
            return
        yield "请填写产品型号、目标人群、使用场景和发布平台。", "", gr.skip(), "", None, None, gr.skip()
        return

    task = Task(
        raw=" ".join((model, audience, scenario, platform, extra or "")),
        model_text=model,
        audience=audience,
        scenario=scenario,
        platform=platform,
        extra=(extra or "").strip(),
    )
    yield from _stream_agent_call(
        lambda report, draft: _get_agent().start(task, progress=report, draft_progress=draft))


def _save_manuscript(current_copy: str, previous: dict | None, *, force_review: bool = False):
    if not previous or previous.get("status") != "ok":
        raise ValueError("请先生成一版文案。")
    updated = dict(previous)
    updated["_current_copy"] = current_copy or ""
    updated["_copy_needs_review"] = (
        force_review or updated["_current_copy"] != render_copy_text(updated.get("draft", {}))
    )
    paths = export(updated, copy_override=updated["_current_copy"],
                   copy_needs_review=updated["_copy_needs_review"])
    return updated, paths["md"]


def save_copy_edits(current_copy: str, previous: dict | None):
    try:
        updated, path = _save_manuscript(current_copy or "", previous)
    except ValueError as exc:
        return str(exc), gr.skip(), gr.skip(), previous
    message = "文案修改已同步到报告和下载文件。"
    if updated["_copy_needs_review"]:
        message += "修改后的文案尚未重新核验，请发布前人工复核。"
    report = _render_report(render_markdown(
        updated,
        web_images=True,
        copy_override=updated["_current_copy"],
        copy_needs_review=updated["_copy_needs_review"],
    ))
    return message, report, path, updated


def _copy_context(result: dict | None) -> dict:
    if not result:
        return {}
    return {
        "model": result.get("model", ""),
        "platform": result.get("platform", ""),
        "facts_used": result.get("facts_used") or [],
    }


def polish_passage_server(source: str, selected: str, instruction: str, context: dict | None):
    instruction = (instruction or "").strip()
    if not source or not selected or not instruction:
        return {"ok": False, "message": "请选择文案并填写润色要求。"}
    missing = _missing_secrets()
    if missing:
        return {"ok": False, "message": "未配置创空间 Secrets：" + "、".join(missing)}
    try:
        candidate = _get_agent().polish_passage(
            context or {}, selected, instruction, source)
    except Exception as exc:
        return {"ok": False, "message": f"润色失败（{type(exc).__name__}）：{exc}"}
    return {"ok": True, "candidate": candidate}


def clear_results():
    return "", "", gr.skip(), "", None, gr.HTML(value="", copy_context={})


with gr.Blocks(title="华为 PC 营销文案助手", elem_id="frontdesk-app") as demo:
    hero_output = gr.HTML(_hero_html())

    with gr.Row(elem_id="frontdesk-statusbar"):
        status_output = gr.Markdown("尚未检查知识库连接状态。", elem_id="connection-status")
        status_button = gr.Button("检查知识库连接", size="sm", elem_id="connection-check")

    with gr.Row(elem_id="frontdesk-workspace"):
        with gr.Column(elem_id="frontdesk-input", elem_classes=["frontdesk-panel", "input-surface"], scale=5, min_width=320):
            gr.HTML('<div class="section-heading"><span>创作任务</span><h2>从场景开始</h2>'
                    '<p>选择业务场景，系统会先匹配赛题中的典型人群。</p></div>')
            with gr.Row(elem_id="scenario-row", elem_classes=["form-row"]):
                scenario_input = gr.Dropdown(
                    choices=list(SCENARIOS),
                    label="使用场景",
                    value="开学季",
                    allow_custom_value=True,
                    elem_id="business-scenario",
                )
                audience_input = gr.Dropdown(
                    choices=AUDIENCES,
                    label="目标人群（随场景预填，可改选或自定义）",
                    value=SCENARIO_AUDIENCES["开学季"],
                    allow_custom_value=True,
                    elem_id="target-audience",
                )
            with gr.Row(elem_id="product-row", elem_classes=["form-row"]):
                model_input = gr.Dropdown(
                    choices=[item.name for item in MODELS],
                    label="产品型号",
                    value=MODELS[0].name,
                    filterable=True,
                    elem_id="product-model",
                )
                platform_input = gr.Dropdown(
                    choices=COMPETITION_PLATFORMS + ["其他"],
                    label="发布平台",
                    value="小红书",
                    elem_id="publish-platform",
                )
                other_platform_input = gr.Dropdown(
                    choices=OTHER_PLATFORMS,
                    label="选择其他平台",
                    value=None,
                    visible=False,
                    elem_id="other-platform",
                )
            with gr.Row(elem_id="extra-row", elem_classes=["form-row"]):
                extra_input = gr.Textbox(
                    label="补充要求",
                    placeholder="例如：突出轻薄便携；避免谈价格；语气更简洁。",
                    lines=3,
                    elem_id="extra-requests",
                )
            with gr.Row(elem_id="action-row", elem_classes=["form-row"]):
                generate_button = gr.Button("生成并核验", variant="primary", elem_id="generate-copy")
                clear_button = gr.Button("清空结果", elem_id="clear-results")

        with gr.Column(elem_id="frontdesk-output", elem_classes=["frontdesk-panel", "result-surface"], scale=7, min_width=420):
            gr.HTML('<div class="section-heading output-heading"><span>工作进度</span>'
                    '<h2>生成与核验</h2><p>查看当前处理步骤，以及完成后的文案、依据和配图。</p></div>')
            result_status = gr.Markdown(elem_id="generation-status")
            workflow_output = gr.HTML(label="处理流程", elem_id="workflow-progress")
            copy_controller = gr.HTML(
                value="",
                html_template=COPY_CONTROLLER_TEMPLATE,
                js_on_load=COPY_EDITOR_JS,
                server_functions=[polish_passage_server],
                copy_context={},
                elem_id="copy-controller",
                apply_default_css=False,
            )
            report_output = gr.HTML(
                value="",
                html_template="${value}",
                label="资料依据与核验报告",
                elem_id="copy-report",
                apply_default_css=False,
            )
            download_output = gr.File(
                label="下载 Markdown 报告",
                value=None,
                interactive=False,
                file_count="single",
                type="filepath",
                elem_id="download-report",
            )
            previous_result = gr.State(value=None)

    status_button.click(check_status, outputs=status_output)
    platform_input.input(
        fn=update_other_platform_visibility,
        inputs=platform_input,
        outputs=other_platform_input,
    )
    scenario_input.change(
        fn=update_audience_for_scenario,
        inputs=[scenario_input, audience_input],
        outputs=audience_input,
    )
    generate_button.click(
        generate_copy,
        inputs=[model_input, audience_input, scenario_input, platform_input, other_platform_input, extra_input],
        outputs=[result_status, workflow_output, hero_output, report_output, download_output, previous_result,
                 copy_controller],
    )
    copy_controller.submit(
        save_copy_edits,
        inputs=[copy_controller, previous_result],
        outputs=[result_status, report_output, download_output, previous_result],
    )
    clear_button.click(
        clear_results,
        outputs=[result_status, workflow_output, hero_output, report_output, download_output, previous_result,
                 copy_controller],
    )


if __name__ == "__main__":
    (OUTPUT_DIR / "markdown_images").mkdir(parents=True, exist_ok=True)
    demo.queue(default_concurrency_limit=1, max_size=20).launch(
        css=UI_CSS,
        allowed_paths=[str((OUTPUT_DIR / "markdown_images").resolve())],
        server_name="0.0.0.0",
        server_port=7860,
        share=True,
    )
