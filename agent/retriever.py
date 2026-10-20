"""检索层：把用户的「型号+任务」变成可追溯的资料依据和候选图片。

知识库目录约定（来自赛题手册和本地副本的结构，首次连通后需实测校正）：
  P1-产品参数库/<大类>/<型号文件夹>/ 产品事实.md、卖点与限制.md、图片索引.csv、来源清单.csv、images/…
  P1-产品参数库/06-型号检索卡/<型号>/0x-*.md
  P8-客户场景库/…、P6-营销素材库/…（表达参考，不是产品事实来源）

所有「假设」集中在 FILES_OF_INTEREST 和 _find_model_folder，改这里即可适配实测结果。
"""
from __future__ import annotations

import csv
import io
from dataclasses import dataclass, field

from .catalog import Model
from .ima_client import Evidence, ImaClient, ImaError, Item, is_image_title

P1 = "P1-产品参数库"
FACT_FILES = ("产品事实.md", "卖点与限制.md")
INDEX_FILES = ("图片索引.csv",)
CARD_DIR = "06-型号检索卡"


@dataclass
class ImageCandidate:
    pid: str
    filename: str
    model: str
    description: str
    source_page: str
    origin_url: str
    usage: str
    item: Item | None = None          # ima 中的图片条目；None 表示只在索引里、ima 里没找到
    verified_in_ima: bool = False


@dataclass
class Retrieval:
    model: Model
    docs: list[Evidence] = field(default_factory=list)          # D1, D2 …
    images: list[ImageCandidate] = field(default_factory=list)  # P1, P2 …
    notes: list[str] = field(default_factory=list)              # 检索过程中的提醒/降级说明
    trace: list[str] = field(default_factory=list)              # 给界面展示的检索轨迹


def _find_model_folder(ima: ImaClient, m: Model) -> list[Item]:
    """定位型号文件夹里的条目。先按目录走，走不通再用搜索兜底。"""
    items = ima.find_by_walk([P1, m.group, m.folder])
    if items:
        return items
    # 兜底：按搜索找到该型号的「产品事实」
    for hit in ima.search(f"{m.folder} 产品事实"):
        if hit.is_folder and m.folder in hit.title:
            sub = ima.list_folder(hit.media_id)
            if sub:
                return sub
    return []


def _parse_index(text: str) -> list[dict]:
    text = text.lstrip("﻿")
    return list(csv.DictReader(io.StringIO(text)))


def retrieve(ima: ImaClient, m: Model, task_keywords: list[str] | None = None,
             max_images: int = 12) -> Retrieval:
    r = Retrieval(model=m)
    items = _find_model_folder(ima, m)
    r.trace.append(f"按目录定位型号「{m.name}」：{'成功' if items else '未找到'}")
    if not items:
        r.notes.append(f"知识库中没有找到「{m.name}」的资料目录")
        return r

    by_title = {i.title: i for i in items if not i.is_folder}

    # 1) 产品事实与卖点限制
    for fname in FACT_FILES:
        it = by_title.get(fname)
        if not it:
            r.notes.append(f"缺少 {fname}")
            continue
        ev = ima.read_text(it)
        if ev:
            ev.path = f"{P1}/{m.group}/{m.folder}"
            r.docs.append(ev)
            r.trace.append(f"读取资料：{m.name}/{fname}")
        else:
            r.notes.append(f"{fname} 无法读取原文，已忽略（不使用无法确认的内容）")

    # 2) 与任务相关的检索卡（屏幕/续航/协同/适用人群…），按关键词命中补充
    if task_keywords:
        try:
            cards = ima.find_by_walk([P1, CARD_DIR, m.folder]) or ima.find_by_walk([P1, CARD_DIR, m.name])
        except ImaError:
            cards = []
        for c in cards:
            if c.is_folder or not c.title.endswith(".md"):
                continue
            if any(k and k in c.title for k in task_keywords):
                ev = ima.read_text(c)
                if ev:
                    ev.path = f"{P1}/{CARD_DIR}/{m.folder}"
                    r.docs.append(ev)
                    r.trace.append(f"读取检索卡：{c.title}")

    # 3) 图片：以「图片索引.csv」为准，并在 ima 里确认图片真实存在
    idx_item = next((by_title[f] for f in INDEX_FILES if f in by_title), None)
    image_items = {}
    img_folder = next((i for i in items if i.is_folder and i.title.lower() == "images"), None)
    if img_folder:
        for it in ima.list_folder(img_folder.media_id):
            if not it.is_folder:
                image_items[it.title] = it
    elif any(is_image_title(i.title) for i in items):
        image_items = {i.title: i for i in items if is_image_title(i.title)}

    if idx_item:
        ev = ima.read_text(idx_item)
        rows = _parse_index(ev.text) if ev else []
        r.trace.append(f"读取图片索引：{len(rows)} 条，ima 中确认 {len(image_items)} 张图片")
        n = 0
        for row in rows:
            fname = (row.get("文件名") or "").strip()
            if not fname:
                continue
            it = image_items.get(fname)
            if not it:
                continue       # 索引里有、但 ima 里没有的图，不作为候选（图片必须来自 ima）
            n += 1
            r.images.append(ImageCandidate(
                pid=f"P{n}", filename=fname,
                model=(row.get("产品型号") or "").strip(),
                description=(row.get("画面说明") or row.get("官网图片说明") or "").strip(),
                source_page=(row.get("来源页面") or row.get("页面来源") or "").strip(),
                origin_url=(row.get("原始图片URL") or "").strip(),
                usage=(row.get("建议用途") or "").strip(),
                item=it, verified_in_ima=True,
            ))
            if n >= max_images:
                break
    else:
        r.notes.append("缺少图片索引.csv，无法确认图片与型号的对应关系，本次不使用图片")

    if not r.images:
        r.notes.append("没有可用的、已在 ima 中确认的图片候选")
    return r
