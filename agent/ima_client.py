"""ima OpenAPI 客户端：通过官方脚本 ima_api.cjs 调用，不直接碰凭证。

只用只读接口：search_knowledge_base / get_knowledge_list / search_knowledge / get_media_info。
所有对外展示的字段只用「标题」，内部 ID 不出现在用户可见内容中。
"""
from __future__ import annotations

import hashlib
import json
import pathlib
import re
import subprocess
import time
import urllib.request
from dataclasses import dataclass, field

from .config import CACHE_DIR, IMA_SCRIPT, KB_NAME, MAX_DOC_CHARS, MAX_IMAGE_BYTES

BASE = "openapi/wiki/v1"
IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".webp")
FOLDER_MEDIA_TYPE = 99     # 实测：文件夹条目的 media_type


class ImaError(Exception):
    """ima 调用失败。msg 可直接展示给用户（不含密钥）。"""

    def __init__(self, msg: str, code: int | None = None):
        super().__init__(msg)
        self.code = code


class ImaQuotaExceeded(ImaError):
    """get_media_info 等接口触达每日额度（错误码 220021）。"""


@dataclass
class Item:
    """知识库里的一个条目（文件或文件夹）。media_id 仅内部使用。"""
    title: str
    media_id: str
    is_folder: bool = False
    path: str = ""            # 面包屑，仅用于展示/追溯，如 P1-产品参数库/01-鸿蒙电脑/…
    snippet: str = ""         # 搜索命中片段


@dataclass
class Evidence:
    """一条可追溯的资料依据。"""
    title: str
    path: str
    text: str
    media_id: str = field(repr=False, default="")


class ImaClient:
    def __init__(self, kb_name: str = KB_NAME):
        self.kb_name = kb_name
        self.kb_id: str | None = None
        self.kb_display_name: str | None = None
        self.calls: list[dict] = []          # 调用日志（接口名+结果码，不含凭证/ID），用于现场展示
        CACHE_DIR.mkdir(exist_ok=True)

    # ---------- 底层调用 ----------
    def _call(self, api: str, body: dict, retries: int = 2) -> dict:
        if not IMA_SCRIPT.exists():
            raise ImaError("缺少官方 ima 脚本 vendor/ima-skill/ima_api.cjs")
        last = ""
        for attempt in range(retries + 1):
            p = subprocess.run(
                ["node", str(IMA_SCRIPT), f"{BASE}/{api}", json.dumps(body, ensure_ascii=False)],
                capture_output=True, text=True, encoding="utf-8", timeout=90,
            )
            if p.returncode != 0:
                try:
                    err = json.loads(p.stderr)
                    msg = err.get("msg", "未知错误")
                except Exception:
                    msg = (p.stderr or "未知错误").strip()[:200]
                raise ImaError(msg, -100)
            try:
                resp = json.loads(p.stdout)
            except Exception:
                raise ImaError("ima 返回了无法解析的内容")
            code = resp.get("code", -1)
            self.calls.append({"api": api, "code": code, "t": time.strftime("%H:%M:%S")})
            if code == 0:
                return resp.get("data") or {}
            last = resp.get("msg", "")
            if code in (110010, 110021) and attempt < retries:   # 下游网络错误/频控：可重试
                time.sleep(2 * (attempt + 1))
                continue
            if code == 220021 or "次数已达上限" in last:
                raise ImaQuotaExceeded("ima 今日的资料获取额度已用完，请明天再试；已缓存的资料仍可使用", code)
            if code == 110030:
                raise ImaError("无权限：请确认已用同一账号加入共享知识库", code)
            raise ImaError(last or f"ima 错误码 {code}", code)
        raise ImaError(last or "ima 调用失败")

    # ---------- 账号与知识库 ----------
    def connect(self) -> dict:
        """功能1：找到指定共享知识库，返回连接状态（不含密钥/ID）。"""
        data = self._call("search_knowledge_base", {"query": self.kb_name, "cursor": "", "limit": 20})
        infos = data.get("info_list") or []
        # 字段兼容：手册实测为 kb_id/kb_name，官方文档为 id/name
        cands = [(i.get("kb_id") or i.get("id"), i.get("kb_name") or i.get("name")) for i in infos]
        cands = [(a, b) for a, b in cands if a]
        if not cands:
            # 搜索为空不等于无权限：回退到空查询列出全部可见知识库
            data = self._call("search_knowledge_base", {"query": "", "cursor": "", "limit": 20})
            infos = data.get("info_list") or []
            cands = [(i.get("kb_id") or i.get("id"), i.get("kb_name") or i.get("name")) for i in infos]
            cands = [(a, b) for a, b in cands if a]
        exact = [c for c in cands if c[1] == self.kb_name]
        fuzzy = [c for c in cands if c[1] and self.kb_name.replace("知识库", "") in c[1]]
        pick = (exact or fuzzy or [None])[0]
        if not pick:
            raise ImaError(f"没有找到名为「{self.kb_name}」的知识库，请确认已扫码加入")
        self.kb_id, self.kb_display_name = pick
        return {"connected": True, "kb_name": self.kb_display_name, "visible_kb_count": len(cands)}

    def _need_kb(self):
        if not self.kb_id:
            self.connect()

    # ---------- 浏览与搜索 ----------
    def list_folder(self, folder_id: str | None = None, limit: int = 50) -> list[Item]:
        self._need_kb()
        items, cursor = [], ""
        while True:
            body = {"knowledge_base_id": self.kb_id, "cursor": cursor, "limit": limit}
            if folder_id:
                body["folder_id"] = folder_id
            data = self._call("get_knowledge_list", body)
            path = "/".join(f.get("name", "") for f in (data.get("current_path") or []))
            for k in data.get("knowledge_list") or []:
                # 实测：文件夹也在 knowledge_list 里，media_type=99，其 media_id 即 folder_id
                mt = k.get("media_type")
                items.append(Item(k.get("title") or k.get("name", ""), k.get("media_id", ""),
                                  mt == FOLDER_MEDIA_TYPE, path))
            if data.get("is_end", True):
                break
            cursor = data.get("next_cursor", "")
        return items

    def search(self, query: str, max_pages: int = 2) -> list[Item]:
        self._need_kb()
        out, cursor = [], ""
        for _ in range(max_pages):
            data = self._call("search_knowledge", {"query": query, "knowledge_base_id": self.kb_id, "cursor": cursor})
            for k in data.get("info_list") or []:
                out.append(Item(k.get("title", ""), k.get("media_id", ""), False,
                                k.get("parent_folder_id", ""), k.get("highlight_content", "")))
            if data.get("is_end", True):
                break
            cursor = data.get("next_cursor", "")
        return out

    def kb_root(self) -> list[Item]:
        """知识库的内容根目录。实测：根下先有一层与知识库同名的文件夹，真正的 P1~P8 在它里面。"""
        if getattr(self, "_root_items", None) is None:
            items = self.list_folder()
            if len(items) == 1 and items[0].is_folder:
                items = self.list_folder(items[0].media_id)
            self._root_items = items
        return self._root_items

    def find_by_walk(self, folder_names: list[str]) -> list[Item]:
        """按目录逐层进入（搜索为空时的回退）。folder_names 例如 ['P1-产品参数库','01-鸿蒙电脑']。
        名称先精确匹配，再退到包含匹配。"""
        items = self.kb_root()
        for name in folder_names:
            folders = [i for i in items if i.is_folder]
            hit = next((i for i in folders if i.title == name), None) or                 next((i for i in folders if name in i.title), None)
            if not hit:
                return []
            items = self.list_folder(hit.media_id)
        return items

    # ---------- 磁盘缓存（节省 get_media_info 额度；内容来自 ima，非本地知识库副本） ----------
    @staticmethod
    def _ck(media_id: str, kind: str) -> pathlib.Path:
        h = hashlib.sha256(media_id.encode("utf-8")).hexdigest()[:24]
        return CACHE_DIR / f"{kind}_{h}"

    def _cache_get(self, media_id: str, kind: str):
        f = self._ck(media_id, kind)
        meta = f.with_suffix(".json")
        if f.exists() and meta.exists():
            return f.read_bytes(), json.loads(meta.read_text(encoding="utf-8"))
        return None

    def _cache_put(self, media_id: str, kind: str, data: bytes, title: str):
        f = self._ck(media_id, kind)
        f.write_bytes(data)
        f.with_suffix(".json").write_text(json.dumps(
            {"title": title, "fetched_at": time.strftime("%Y-%m-%d %H:%M:%S"), "source": "ima"},
            ensure_ascii=False), encoding="utf-8")

    # ---------- 取原文 / 图片 ----------
    def media_info(self, media_id: str) -> dict:
        return self._call("get_media_info", {"media_id": media_id})

    def _http_get(self, url: str, headers: dict | None, limit: int) -> bytes:
        req = urllib.request.Request(url, headers=headers or {})
        with urllib.request.urlopen(req, timeout=60) as r:
            data = r.read(limit + 1)
        if len(data) > limit:
            raise ImaError("文件过大，已跳过")
        return data

    def _decode(self, raw: bytes) -> str | None:
        for enc in ("utf-8-sig", "utf-8", "gb18030"):
            try:
                text = raw.decode(enc)
                break
            except UnicodeDecodeError:
                continue
        else:
            return None
        return text.lstrip(chr(0xFEFF)).replace(chr(13) + chr(10), chr(10))

    def read_text(self, item: Item) -> Evidence | None:
        """读取一份文本类资料（md/txt/csv）。先查缓存，未命中才调用 get_media_info。
        取不到返回 None，调用方应视为「无依据」。"""
        hit = self._cache_get(item.media_id, "txt")
        if hit:
            raw, _ = hit
            self.calls.append({"api": "cache", "code": 0, "t": time.strftime("%H:%M:%S")})
        else:
            info = self.media_info(item.media_id)
            ui = info.get("url_info") or {}
            if not ui.get("url"):
                return None
            raw = self._http_get(ui["url"], ui.get("headers"), 4 * 1024 * 1024)
            self._cache_put(item.media_id, "txt", raw, item.title)
        text = self._decode(raw)
        if text is None:
            return None
        return Evidence(item.title, item.path, text[:MAX_DOC_CHARS], item.media_id)

    def fetch_image(self, item: Item) -> tuple[bytes, str] | None:
        """下载图片，返回 (字节, 媒体类型)；先查缓存。"""
        hit = self._cache_get(item.media_id, "img")
        if hit:
            data = hit[0]
        else:
            info = self.media_info(item.media_id)
            ui = info.get("url_info") or {}
            if not ui.get("url"):
                return None
            data = self._http_get(ui["url"], ui.get("headers"), MAX_IMAGE_BYTES)
            kind = _sniff_image(data)
            if not kind:
                return None
            self._cache_put(item.media_id, "img", data, item.title)
        kind = _sniff_image(data)
        return (data, kind) if kind else None


def _sniff_image(data: bytes) -> str | None:
    if data[:8] == bytes([0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A]):
        return "image/png"
    if data[:3] == bytes([0xFF, 0xD8, 0xFF]):
        return "image/jpeg"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def is_image_title(title: str) -> bool:
    return title.lower().endswith(IMAGE_EXTS)


def safe_name(s: str) -> str:
    return re.sub(r'[\\/:*?"<>|]', "_", s)
