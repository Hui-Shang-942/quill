"""仅用于单元/集成测试的 ima 替身：按 ima 接口的返回结构，用本地知识库副本模拟。
不属于交付功能；交付运行只走真实 ima（agent/ima_client.py）。"""
from __future__ import annotations

import pathlib

from agent.ima_client import ImaClient, ImaError, Item, Evidence

KB = pathlib.Path(r"D:/浙客松/华为PC全板块深度知识库_v7")


class FakeIma(ImaClient):
    def __init__(self):
        super().__init__()
        self._paths: dict[str, pathlib.Path] = {}

    def connect(self):
        self.kb_id, self.kb_display_name = "fake", "任德耀新建华为PC知识库（测试替身）"
        return {"connected": True, "kb_name": self.kb_display_name, "visible_kb_count": 1}

    def _reg(self, p: pathlib.Path) -> str:
        k = str(p)
        self._paths[k] = p
        return k

    def list_folder(self, folder_id=None, limit=50):
        base = pathlib.Path(folder_id) if folder_id else KB
        out = []
        for p in sorted(base.iterdir()):
            out.append(Item(p.name, self._reg(p), p.is_dir(), str(base.relative_to(KB))))
        return out

    def search(self, query, max_pages=2):
        return []

    def read_text(self, item):
        p = pathlib.Path(item.media_id)
        if not p.exists() or p.is_dir():
            return None
        return Evidence(item.title, item.path, p.read_text(encoding="utf-8-sig")[:60000], item.media_id)

    def fetch_image(self, item):
        p = pathlib.Path(item.media_id)
        return (p.read_bytes(), "image/png") if p.exists() else None
