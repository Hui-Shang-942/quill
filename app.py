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

from agent.catalog import MODELS
from agent.config import CACHE_DIR, COMPETITION_PLATFORMS, OUTPUT_DIR
from agent.exporter import export, render_markdown
from agent.pipeline import Agent, Task, WORKFLOW_STAGES
from agent.platform_rules import PLATFORMS, SCENARIOS, SCENARIO_AUDIENCES


REQUIRED_SECRETS = ("ANTHROPIC_API_KEY", "IMA_CLIENT_ID", "IMA_API_KEY")
OTHER_PLATFORMS = [name for name in PLATFORMS if name not in COMPETITION_PLATFORMS]
UI_DIR = Path(__file__).resolve().parent / "UI-frontend-design"
UI_CSS = (UI_DIR / "theme.css").read_text(encoding="utf-8")
HERO_HTML = (UI_DIR / "hero.html").read_text(encoding="utf-8")
AUDIENCES = [
    *SCENARIO_AUDIENCES.values(),
]


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
    yield "正在启动后台流程…", _workflow_html(state), gr.skip(), "", None, fallback_state

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
                status_message = ("模型正在撰写草稿，事实与合规核验待完成。" if draft_preview else
                                  f"正在处理：{current}（已用 {elapsed} 秒）")
                yield status_message, _workflow_html(state), gr.skip(), draft_preview, None, fallback_state
                continue
            if event.get("kind") == "draft_preview":
                draft_preview = event.get("markdown", "")
                yield "模型正在实时撰写草稿，事实与合规核验仍在进行。", _workflow_html(state), gr.skip(), draft_preview, None, fallback_state
                continue
            _apply_workflow_event(state, event)
            status_message = ("草稿已开始实时显示，后台正在继续核验。" if draft_preview else
                              "后台处理中，请查看上方阶段状态。")
            yield status_message, _workflow_html(state), gr.skip(), draft_preview, None, fallback_state

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
        paths = export(result)
        message = ("生成完成，图文内容与配图已按 Markdown 展示。"
                   if result.get("publish_ready") else
                   "生成完成，图文内容与配图已完整展示；部分核验未通过，请查看报告中的提示和待确认项。")
        state = workflow_state or _new_workflow_state()
        return (message, _workflow_html(state), gr.skip(),
                render_markdown(result, web_images=True), paths["md"], result)

    if status == "need_info":
        lines = ["信息还不完整，请补充后重新生成："]
        lines.extend(f"- {item.get('question', '')}" for item in result.get("questions", []))
        message = "\n".join(lines)
    elif status in ("no_evidence", "conflict", "error"):
        message = result.get("message", "本次没有生成文案。")
    else:
        message = "收到未知的生成状态，请稍后重试。"

    state = workflow_state or _new_workflow_state()
    return (message, _workflow_html(state), gr.skip(), render_markdown(result),
            None, fallback_state)


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
        yield "未配置创空间 Secrets：" + "、".join(missing), "", gr.skip(), "", None, None
        return
    if platform == "其他":
        platform = other_platform
    if not model or not audience or not scenario or not platform:
        if not other_platform and platform is None:
            yield "请在“其他”分类中选择具体平台。", "", gr.skip(), "", None, None
            return
        yield "请填写产品型号、目标人群、使用场景和发布平台。", "", gr.skip(), "", None, None
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


def revise_copy(instruction: str, previous: dict | None):
    if not previous or not previous.get("_ctx"):
        yield "请先成功生成一版文案，再提交修改要求。", "", gr.skip(), "", None, None
        return
    instruction = (instruction or "").strip()
    if not instruction:
        yield "请填写具体的修改要求。", "", gr.skip(), "", None, previous
        return

    missing = _missing_secrets()
    if missing:
        yield "未配置创空间 Secrets：" + "、".join(missing), "", gr.skip(), "", None, previous
        return

    platform = None
    if any(word in instruction for word in ("换成", "改成", "改为", "转成", "变成")):
        for name in PLATFORMS:
            if name in instruction:
                platform = name
                break
    yield from _stream_agent_call(
        lambda report, draft: _get_agent().revise(
            previous, instruction, new_platform=platform, progress=report, draft_progress=draft),
        fallback_state=previous,
    )


def clear_results():
    return "", "", gr.skip(), "", None, None, ""


with gr.Blocks(title="华为 PC 营销文案助手", elem_id="frontdesk-app") as demo:
    hero_output = gr.HTML(_hero_html())

    with gr.Row(elem_id="frontdesk-statusbar"):
        status_output = gr.Markdown("尚未检查知识库连接状态。", elem_id="connection-status")
        status_button = gr.Button("检查知识库连接", size="sm", elem_id="connection-check")

    with gr.Column(elem_id="frontdesk-workspace"):
        with gr.Column(elem_id="frontdesk-input", elem_classes=["frontdesk-panel", "input-surface"]):
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

        with gr.Column(elem_id="frontdesk-output", elem_classes=["frontdesk-panel", "result-surface"]):
            gr.HTML('<div class="section-heading output-heading"><span>工作进度</span>'
                    '<h2>生成与核验</h2><p>查看当前处理步骤，以及完成后的文案、依据和配图。</p></div>')
            result_status = gr.Markdown(elem_id="generation-status")
            workflow_output = gr.HTML(label="处理流程", elem_id="workflow-progress")
            report_output = gr.Markdown(label="生成结果（Markdown）", elem_id="copy-report")
            download_output = gr.File(
                label="下载 Markdown 报告",
                value=None,
                interactive=False,
                file_count="single",
                type="filepath",
                elem_id="download-report",
            )
            previous_result = gr.State(value=None)
            with gr.Group(elem_id="revision-box"):
                gr.HTML('<div class="revision-heading"><span>文案修改</span><h3>继续打磨</h3></div>')
                revision_input = gr.Textbox(
                    label="修改要求",
                    placeholder="例如：改成微信朋友圈，语气更口语，缩短正文。",
                    lines=2,
                    elem_id="revision-instructions",
                )
                revise_button = gr.Button("按要求修改", elem_id="revise-copy")

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
        outputs=[result_status, workflow_output, hero_output, report_output, download_output, previous_result],
    )
    revise_button.click(
        revise_copy,
        inputs=[revision_input, previous_result],
        outputs=[result_status, workflow_output, hero_output, report_output, download_output, previous_result],
    )
    clear_button.click(
        clear_results,
        outputs=[result_status, workflow_output, hero_output, report_output, download_output, previous_result, revision_input],
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
