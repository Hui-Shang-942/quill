"""Gradio entry point for the Huawei PC copywriting assistant."""
from __future__ import annotations

import io
import os
import threading

import gradio as gr
from PIL import Image

from agent.catalog import MODELS
from agent.config import CACHE_DIR
from agent.exporter import export, render_markdown
from agent.ima_client import ImaError
from agent.llm import LLMError
from agent.pipeline import Agent, Task
from agent.platform_rules import PLATFORMS, SCENARIOS


REQUIRED_SECRETS = ("ANTHROPIC_API_KEY", "IMA_CLIENT_ID", "IMA_API_KEY")
AUDIENCES = [
    "大学新生", "大学新生家长", "商务差旅", "内容创作者", "家庭换新",
    "企业采购", "附近的潜在顾客", "送礼人群",
]

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


def _progress_callback(progress):
    def update(message: str) -> None:
        progress(desc=message)
    return update


def _images_for_gallery(result: dict) -> list[tuple[Image.Image, str]]:
    image_bytes = result.get("_image_bytes") or {}
    descriptions = {
        item.get("filename"): item.get("caption", "")
        for item in (result.get("draft") or {}).get("images", [])
    }
    gallery = []
    for filename, image_data in image_bytes.items():
        try:
            raw, _mime_type = image_data
            with Image.open(io.BytesIO(raw)) as image:
                gallery.append((image.copy(), descriptions.get(filename) or filename))
        except (OSError, TypeError, ValueError):
            continue
    return gallery


def _present_result(result: dict, state_value: dict | None = None):
    status = result.get("status")
    if status == "ok":
        paths = export(result)
        message = "生成完成。发布前请核对资料边界和待确认事项。"
        return message, render_markdown(result), _images_for_gallery(result), paths["md"], result

    if status == "need_info":
        lines = ["信息还不完整，请补充后重新生成："]
        lines.extend(f"- {item.get('question', '')}" for item in result.get("questions", []))
        message = "\n".join(lines)
    elif status in ("no_evidence", "conflict", "error"):
        message = result.get("message", "本次没有生成文案。")
    else:
        message = "收到未知的生成状态，请稍后重试。"

    return message, render_markdown(result), [], None, None


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
                  extra: str, progress=gr.Progress()):
    missing = _missing_secrets()
    if missing:
        return "未配置创空间 Secrets：" + "、".join(missing), "", [], None, None
    if not model or not audience or not scenario or not platform:
        return "请填写产品型号、目标人群、使用场景和发布平台。", "", [], None, None

    try:
        agent = _get_agent()
        task = Task(
            raw=" ".join((model, audience, scenario, platform, extra or "")),
            model_text=model,
            audience=audience,
            scenario=scenario,
            platform=platform,
            extra=(extra or "").strip(),
        )
        result = agent.start(task, progress=_progress_callback(progress))
        return _present_result(result)
    except (ImaError, LLMError) as exc:
        return f"生成失败：{exc}", "", [], None, None
    except Exception as exc:
        return f"生成失败（{type(exc).__name__}）：{exc}", "", [], None, None


def revise_copy(instruction: str, previous: dict | None, progress=gr.Progress()):
    if not previous or not previous.get("_ctx"):
        return "请先成功生成一版文案，再提交修改要求。", "", [], None, None
    instruction = (instruction or "").strip()
    if not instruction:
        return "请填写具体的修改要求。", "", [], None, previous

    missing = _missing_secrets()
    if missing:
        return "未配置创空间 Secrets：" + "、".join(missing), "", [], None, previous

    platform = None
    if any(word in instruction for word in ("换成", "改成", "改为", "转成", "变成")):
        for name in PLATFORMS:
            if name in instruction:
                platform = name
                break
    try:
        result = _get_agent().revise(
            previous,
            instruction,
            new_platform=platform,
            progress=_progress_callback(progress),
        )
        return _present_result(result, previous)
    except (ImaError, LLMError) as exc:
        return f"修改失败：{exc}", "", [], None, previous
    except Exception as exc:
        return f"修改失败（{type(exc).__name__}）：{exc}", "", [], None, previous


def clear_results():
    return "", "", [], None, None, ""


with gr.Blocks(title="华为 PC 营销文案助手") as demo:
    gr.Markdown(
        "# 华为 PC 营销文案助手\n"
        "根据 ima 知识库生成并核验多平台文案。产品参数、价格和权益以知识库资料为准。"
    )

    with gr.Row():
        status_output = gr.Markdown("尚未检查知识库连接状态。")
        status_button = gr.Button("检查连接", size="sm")

    with gr.Row():
        with gr.Column(scale=1):
            model_input = gr.Dropdown(
                choices=[item.name for item in MODELS],
                label="产品型号",
                value=MODELS[0].name,
                filterable=True,
            )
            audience_input = gr.Dropdown(
                choices=AUDIENCES,
                label="目标人群",
                value=AUDIENCES[0],
                allow_custom_value=True,
            )
            scenario_input = gr.Dropdown(
                choices=list(SCENARIOS),
                label="使用场景",
                value="开学季",
                allow_custom_value=True,
            )
            platform_input = gr.Dropdown(
                choices=list(PLATFORMS),
                label="发布平台",
                value="小红书",
            )
            extra_input = gr.Textbox(
                label="补充要求",
                placeholder="例如：突出轻薄便携；避免谈价格；语气更简洁。",
                lines=3,
            )
            with gr.Row():
                generate_button = gr.Button("生成并核验", variant="primary")
                clear_button = gr.Button("清空结果")

        with gr.Column(scale=2):
            result_status = gr.Markdown()
            report_output = gr.Markdown(label="生成结果")
            image_output = gr.Gallery(label="配图", value=[], columns=3, height="auto")
            download_output = gr.File(
                label="下载 Markdown 报告",
                value=None,
                interactive=False,
                file_count="single",
                type="filepath",
            )

    previous_result = gr.State(value=None)
    with gr.Row():
        revision_input = gr.Textbox(
            label="修改要求",
            placeholder="例如：改成门店朋友圈，语气更口语，缩短正文。",
            lines=2,
        )
        revise_button = gr.Button("按要求修改")

    status_button.click(check_status, outputs=status_output)
    generate_button.click(
        generate_copy,
        inputs=[model_input, audience_input, scenario_input, platform_input, extra_input],
        outputs=[result_status, report_output, image_output, download_output, previous_result],
    )
    revise_button.click(
        revise_copy,
        inputs=[revision_input, previous_result],
        outputs=[result_status, report_output, image_output, download_output, previous_result],
    )
    clear_button.click(
        clear_results,
        outputs=[result_status, report_output, image_output, download_output, previous_result, revision_input],
    )


if __name__ == "__main__":
    demo.queue(default_concurrency_limit=1, max_size=20).launch(server_name="0.0.0.0", server_port=7860, share=True)
