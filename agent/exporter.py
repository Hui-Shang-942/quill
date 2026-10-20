"""功能7：导出。按手册「统一输出格式」四块：场景判断 / 知识库依据 / 图文软文 / 核验结果。"""
from __future__ import annotations

import json
import time
from pathlib import Path

from .config import OUTPUT_DIR
from .ima_client import safe_name


def render_markdown(res: dict) -> str:
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
    if d.get("titles"):
        L += ["## 标题", *[f"{i+1}. {t}" for i, t in enumerate(d["titles"])], ""]
    poster = d.get("poster") or {}
    if any(poster.values()):
        L += ["## 海报文案", f"- 主标题：{poster.get('main_title', '')}", f"- 副标题：{poster.get('sub_title', '')}"]
        L += [f"- 卖点：{p}" for p in poster.get("points", [])]
        L += [f"- 活动说明：{poster.get('note', '')}", ""]
    if d.get("lead"):
        L += ["## 导语", d["lead"], ""]
    imgs = {i["pid"]: i for i in d.get("images", [])}
    for s in d.get("sections", []):
        if s.get("heading"):
            L.append(f"## {s['heading']}")
        L.append(s.get("text", ""))
        for pid in s.get("image_pids", []):
            if pid in imgs:
                L.append(f"\n> 【配图】{imgs[pid]['filename']}　{imgs[pid]['caption']}")
        L.append("")
    L += ["## 行动引导", d.get("cta", ""), ""]
    if d.get("tags"):
        L += ["## 平台标签", " ".join(d["tags"]), ""]

    L += ["## 配图清单", "", "| 图片名称 | 来源 | 建议插入位置 | 图片说明 |", "|---|---|---|---|"]
    for i in d.get("images", []):
        L.append(f"| {i['filename']} | {i['source']} | {i['position']} | {i['caption']} |")
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


def plain_text(res: dict) -> str:
    """纯文本版本，便于一键复制发布。"""
    if res.get("status") != "ok":
        return res.get("message", "")
    d = res["draft"]
    out = []
    if d.get("titles"):
        out.append(d["titles"][0])
    poster = d.get("poster") or {}
    if any(poster.values()):
        out += [poster.get("main_title", ""), poster.get("sub_title", ""), *poster.get("points", []), poster.get("note", "")]
    if d.get("lead"):
        out.append(d["lead"])
    for s in d.get("sections", []):
        if s.get("heading"):
            out.append(s["heading"])
        out.append(s.get("text", ""))
    out.append(d.get("cta", ""))
    if d.get("tags"):
        out.append(" ".join(d["tags"]))
    return "\n\n".join(x for x in out if x)
