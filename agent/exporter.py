"""功能7：导出。按手册「统一输出格式」四块：场景判断 / 知识库依据 / 图文软文 / 核验结果。"""
from __future__ import annotations

import json
import hashlib
import re
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


def _image_section_placements(images: list[dict], sections: list[dict]) -> dict[int, list[dict]]:
    """Bind each selected image to a body section, filling missing model links sensibly."""
    if not sections:
        return {}

    by_pid = {image.get("pid"): image for image in images if image.get("pid")}
    placements: dict[int, list[dict]] = {}
    assigned: set[str] = set()
    for index, section in enumerate(sections):
        for pid in section.get("image_pids") or []:
            image = by_pid.get(pid)
            if image and pid not in assigned:
                placements.setdefault(index, []).append(image)
                assigned.add(pid)

    def position_index(image: dict) -> int | None:
        position = str(image.get("position") or "")
        ordinal = re.search(r"第\s*(\d+)\s*(?:段|节|部分|个段落)", position)
        if ordinal:
            return max(0, min(len(sections) - 1, int(ordinal.group(1)) - 1))
        for numeral, value in (("一", 1), ("二", 2), ("三", 3), ("四", 4), ("五", 5), ("六", 6)):
            if f"第{numeral}段" in position or f"第{numeral}部分" in position:
                return min(len(sections) - 1, value - 1)

        searchable_position = position.strip().casefold()
        for index, section in enumerate(sections):
            heading = str(section.get("heading") or "").strip().casefold()
            if heading and heading in searchable_position:
                return index

        # Match distinctive words in the image rationale/position to section copy.
        context = f"{position} {image.get('reason') or ''}".casefold()
        terms = set(re.findall(r"[a-z0-9]{3,}", context))
        for phrase in re.findall(r"[\u4e00-\u9fff]+", context):
            terms.update(phrase[offset:offset + 2] for offset in range(len(phrase) - 1))
        scored = []
        for index, section in enumerate(sections):
            text = f"{section.get('heading') or ''} {section.get('text') or ''}".casefold()
            score = sum(1 for term in terms if term in text)
            scored.append((score, index))
        best_score, best_index = max(scored, default=(0, 0))
        return best_index if best_score else None

    for image in images:
        pid = image.get("pid")
        if pid and pid in assigned:
            continue
        index = position_index(image)
        if index is None:
            # Spread unlinked images across the body instead of collecting them at its end.
            index = min(range(len(sections)), key=lambda item: len(placements.get(item, [])))
        placements.setdefault(index, []).append(image)
        if pid:
            assigned.add(pid)
    return placements


def _image_markup(res: dict, image: dict, web_images: bool) -> str | None:
    url = _image_markdown_url(res, image, web_images)
    if not url:
        return None
    alt = (image.get("caption") or image.get("filename") or "产品配图").replace("]", "）")
    return f"![{alt}]({url})"


def _copy_with_inline_images(copy: str, sections: list[dict], placements: dict[int, list[dict]],
                             res: dict, web_images: bool) -> str:
    paragraphs = [part.strip() for part in re.split(r"\n\s*\n", copy.strip()) if part.strip()]
    if not paragraphs:
        return copy
    by_paragraph: dict[int, list[str]] = {}
    for section_index, images in placements.items():
        section = sections[section_index]
        anchor = None
        for candidate in (section.get("text"), section.get("heading")):
            candidate = str(candidate or "").strip()
            if candidate:
                anchor = next((i for i, paragraph in enumerate(paragraphs)
                               if paragraph == candidate or candidate in paragraph), None)
                if anchor is not None:
                    break
        if anchor is None:
            # Edited copy may no longer match the original section text; keep its
            # corresponding image near the same relative point in the body.
            anchor = min(len(paragraphs) - 1,
                         max(0, round((section_index + 1) * (len(paragraphs) - 1) /
                                      max(1, len(sections)))))
        for image in images:
            markup = _image_markup(res, image, web_images)
            if markup:
                by_paragraph.setdefault(anchor, []).append(markup)
    rendered = []
    for index, paragraph in enumerate(paragraphs):
        rendered.append(paragraph)
        rendered.extend(by_paragraph.get(index, []))
    return "\n\n".join(rendered)


def render_markdown(res: dict, *, web_images: bool = False, copy_override: str | None = None,
                    copy_needs_review: bool = False) -> str:
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
    if copy_needs_review:
        L += ["> 人工或 AI 润色后的文案尚未重新执行原有事实与合规核验，发布前请人工复核。", ""]
    poster = d.get("poster") or {}
    sections = d.get("sections") or []
    placement_sections = sections or [{
        "text": d.get("lead") or poster.get("note") or
                next(iter(reversed(poster.get("points") or [])), "")
    }]
    image_placements = _image_section_placements(d.get("images", []), placement_sections)
    if copy_override is None:
        publish_title = d.get("publish_title") or next(iter(d.get("titles") or []), "")
        if publish_title:
            L += [f"## {publish_title}", ""]
        if any(poster.values()):
            if poster.get("sub_title"):
                L += [f"### {poster['sub_title']}", ""]
            L += [*poster.get("points", []), ""]
            if poster.get("note"):
                L += [poster["note"], ""]
        if d.get("lead"):
            L += [d["lead"], ""]
        for section_index, section in enumerate(sections):
            if section.get("heading"):
                L.append(f"### {section['heading']}")
            if section.get("text"):
                L.append(section["text"])
            L.append("")
            for image in image_placements.get(section_index, []):
                markup = _image_markup(res, image, web_images)
                if markup:
                    L += [markup, ""]
        if not sections:
            for image in image_placements.get(0, []):
                markup = _image_markup(res, image, web_images)
                if markup:
                    L += [markup, ""]
        if d.get("cta"):
            L += [d["cta"], ""]
        if d.get("tags"):
            L += [" ".join(d["tags"]), ""]

    else:
        L += ["", _copy_with_inline_images(copy_override, placement_sections,
                                            image_placements, res, web_images), ""]

    if d.get("images"):
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


def export(res: dict, name: str | None = None, *, copy_override: str | None = None,
           copy_needs_review: bool = False) -> dict:
    """写出 .md 与 .json（json 用于留存运行记录；不含任何凭证/内部ID）。"""
    OUTPUT_DIR.mkdir(exist_ok=True)
    stem = safe_name(name or f"{res.get('model', 'result')}_{res.get('platform', '')}_{time.strftime('%H%M%S')}")
    md_path, js_path = OUTPUT_DIR / f"{stem}.md", OUTPUT_DIR / f"{stem}.json"
    md_path.write_text(render_markdown(res, copy_override=copy_override,
                                       copy_needs_review=copy_needs_review), encoding="utf-8")
    safe = {k: v for k, v in res.items() if k not in ("ima_calls", "_ctx", "_image_bytes")}
    js_path.write_text(json.dumps(safe, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"md": str(md_path), "json": str(js_path)}


