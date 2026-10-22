"""功能7：导出。按手册「统一输出格式」四块：场景判断 / 知识库依据 / 图文软文 / 核验结果。"""
from __future__ import annotations

import json
import hashlib
import time
from pathlib import Path
from urllib.parse import quote

from .config import OUTPUT_DIR
from .ima_client import safe_name


def _image_markdown_url(res: dict, image: dict, web_images: bool) -> str | None:
    image_data = (res.get("_image_bytes") or {}).get(image.get("filename"))
    if not image_data:
        return None
    raw, mime_type = image_data
    extension = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}.get(mime_type)
    if not extension:
        return None
    image_dir = OUTPUT_DIR / "markdown_images"
    image_dir.mkdir(parents=True, exist_ok=True)
    name = f"{hashlib.sha256(raw).hexdigest()[:20]}.{extension}"
    path = image_dir / name
    if not path.exists():
        path.write_bytes(raw)
    if web_images:
        encoded_path = quote(path.resolve().as_posix(), safe="/:")
        return f"/gradio_api/file={encoded_path}"
    return f"markdown_images/{name}"


def render_markdown(res: dict, *, web_images: bool = False) -> str:
    if res.get("status") != "ok":
        return f"# 未生成\n\n{res.get('message', '')}\n"
    sc, d = res["scene"], res["draft"]
    L: list[str] = []
    L += ["# 一、场景判断", "",
          f"- 目标人群：{sc.get('audience', '')}",
          f"- 使用场景：{sc.get('usage_scene', '') or sc.get('scenario_type', '')}",
          f"- 购买阶段：{sc.get('purchase_stage', '')}",
          f"- 用户问题：{sc.get('main_problem', '')}",
          f"- 内容目标：{sc.get('content_goal', '')}",
          f"- 发布平台：{res.get('platform', '')}",
          f"- 切入点：{res.get('strategy', {}).get('angle', '')}", ""]

    L += ["# 二、知识库依据", "", f"- 产品型号：{res.get('model', '')}"]
    for n, f in enumerate(res.get("facts_used", []), 1):
        cond = f"（{f['condition']}）" if f.get("condition") else ""
        L.append(f"- 事实点 {n}：{f['text']}{cond}　[资料：{_doc_title(res, f.get('doc'))}]")
    L += ["- 资料标题："] + [f"  - {e['title']}（{e['path']}）" for e in res.get("evidence", [])] + [""]

    L += ["# 三、图文软文", ""]
    if not res.get("publish_ready"):
        L += ["> ⚠️ 核验未全部通过。以下内容仍完整展示供查看和修改，请先处理第四部分列出的待确认项，再决定是否发布。", ""]
    publish_title = d.get("publish_title") or next(iter(d.get("titles") or []), "")
    if publish_title:
        L += [f"## {publish_title}", ""]
    poster = d.get("poster") or {}
    if any(poster.values()):
        if poster.get("sub_title"):
            L += [f"### {poster['sub_title']}", ""]
        L += [*poster.get("points", []), ""]
        if poster.get("note"):
            L += [poster["note"], ""]
    if d.get("lead"):
        L += [d["lead"], ""]
    images_by_pid = {image.get("pid"): image for image in d.get("images", [])}
    rendered_pids = set()
    for section in d.get("sections", []):
        if section.get("heading"):
            L.append(f"### {section['heading']}")
        if section.get("text"):
            L.append(section["text"])
        L.append("")
        for pid in section.get("image_pids", []):
            image = images_by_pid.get(pid)
            if image:
                url = _image_markdown_url(res, image, web_images)
                if url:
                    alt = (image.get("caption") or image.get("filename") or "产品配图").replace("]", "）")
                    L += [f"![{alt}]({url})", ""]
                    rendered_pids.add(pid)
    if d.get("cta"):
        L += [d["cta"], ""]
    if d.get("tags"):
        L += [" ".join(d["tags"]), ""]

    if d.get("images"):
        remaining_images = [image for image in d["images"] if image.get("pid") not in rendered_pids]
        if remaining_images:
            L += ["## 其他配图", ""]
            for image in remaining_images:
                url = _image_markdown_url(res, image, web_images)
                if url:
                    alt = (image.get("caption") or image.get("filename") or "产品配图").replace("]", "）")
                    L += [f"![{alt}]({url})", ""]
        L += ["## 配图信息", "", "| 图片名称 | 来源 | 建议插入位置 | 图片说明 |", "|---|---|---|---|"]
        for image in d["images"]:
            L.append(f"| {image['filename']} | {image['source']} | {image['position']} | {image['caption']} |")
        L.append("")

    v, c = res.get("verify", {}), res.get("compliance", {})
    n_ok = sum(1 for x in v.get("claims", []) if x.get("status") == "supported")
    L += ["# 四、核验结果", "",
          f"- 产品事实：共核验 {len(v.get('claims', []))} 条，{n_ok} 条有资料依据；"
          f"{'通过' if v.get('final_pass') else '仍有待确认项'}",
          f"- 图片型号：{'全部与目标型号一致' if all(i.get('model_match') for i in d.get('images', [])) else '存在不一致'}"
          f"（共 {len(d.get('images', []))} 张，均来自 ima）",
          f"- 合规：{'通过' if c.get('pass') else '存在问题'}；自动修订 {res.get('fix_rounds', 0)} 轮"]
    for r in res.get("refusals", []):
        L.append(f"- 已拦截：{r}")
    pending = [x for x in v.get("claims", []) if x.get("status") != "supported"]
    if pending:
        L.append("- 待确认信息：")
        L += [f"  - {x.get('text', '')}（{x.get('status')}：{x.get('evidence', '')}）" for x in pending]
    else:
        L.append("- 待确认信息：无")
    if res.get("timings"):
        L += ["", "## 运行记录（耗时）", "", f"- 总耗时：{res.get('total_sec', '?')} 秒；模型调用 {len(res['timings'])} 次"]
        L += [f"  - {t['label']}：{t['sec']} 秒（effort={t['effort']}）" for t in res["timings"]]
    L += ["", f"> 提示：参数以实际销售版本为准；发布前请按《发布前检查表》复核。"]
    return "\n".join(L)


def _doc_title(res: dict, doc_id: str | None) -> str:
    for e in res.get("evidence", []):
        if e["id"] == doc_id:
            return e["title"]
    return doc_id or ""


def export(res: dict, name: str | None = None) -> dict:
    """写出 .md 与 .json（json 用于留存运行记录；不含任何凭证/内部ID）。"""
    OUTPUT_DIR.mkdir(exist_ok=True)
    stem = safe_name(name or f"{res.get('model', 'result')}_{res.get('platform', '')}_{time.strftime('%H%M%S')}")
    md_path, js_path = OUTPUT_DIR / f"{stem}.md", OUTPUT_DIR / f"{stem}.json"
    md_path.write_text(render_markdown(res), encoding="utf-8")
    safe = {k: v for k, v in res.items() if k not in ("ima_calls", "_ctx", "_image_bytes")}
    js_path.write_text(json.dumps(safe, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"md": str(md_path), "json": str(js_path)}


