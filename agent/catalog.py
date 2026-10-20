"""型号目录与型号识别。

目录来自知识库 P1-产品参数库 的实际结构（10 个系列）。用于：
1) 把用户的口语（"pro s"、"D16"）识别成唯一型号；
2) 相近型号（Pro / Pro S，D 16 / D 16 SE）出现歧义时，要求用户确认，而不是猜。
"""
from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Model:
    name: str            # 展示名
    folder: str          # 知识库里的型号文件夹名
    group: str           # 所在大类文件夹
    aliases: tuple       # 归一化后的别名（小写、无空格）
    confusable: tuple    # 容易混淆的型号展示名


MODELS: list[Model] = [
    Model("HUAWEI MateBook Pro", "HUAWEI MateBook Pro", "01-鸿蒙电脑",
          ("matebookpro", "鸿蒙pro", "pro"), ("HUAWEI MateBook Pro S",)),
    Model("HUAWEI MateBook Pro S", "HUAWEI MateBook Pro S", "01-鸿蒙电脑",
          ("matebookpros", "pros", "鸿蒙pros"), ("HUAWEI MateBook Pro",)),
    Model("HUAWEI MateBook 14（鸿蒙版）", "HUAWEI MateBook 14", "01-鸿蒙电脑",
          ("matebook14鸿蒙", "鸿蒙matebook14", "matebook14鸿蒙版"), ("MateBook 14 酷睿 Ultra",)),
    Model("HUAWEI MateBook Fold 非凡大师", "HUAWEI MateBook Fold 非凡大师", "01-鸿蒙电脑",
          ("matebookfold", "fold", "非凡大师", "折叠"), ()),
    Model("MateBook 14 酷睿 Ultra", "MateBook 14 酷睿 Ultra", "02-MateBook-Windows",
          ("matebook14酷睿ultra", "14酷睿ultra", "matebook142024", "matebook14酷睿"),
          ("HUAWEI MateBook 14（鸿蒙版）",)),
    Model("MateBook D 14", "MateBook D 14", "02-MateBook-Windows",
          ("matebookd14", "d14"), ()),
    Model("MateBook D 16", "MateBook D 16", "02-MateBook-Windows",
          ("matebookd16", "d16"), ("MateBook D 16 SE 版",)),
    Model("MateBook D 16 SE 版", "MateBook D 16 SE 版", "02-MateBook-Windows",
          ("matebookd16se", "d16se", "d16se版"), ("MateBook D 16",)),
    Model("MateBook GT 系列", "MateBook GT 系列", "02-MateBook-Windows",
          ("matebookgt", "gt14", "gt系列", "gt"), ()),
    Model("MateBook X 系列", "MateBook X系列", "02-MateBook-Windows",
          ("matebookx", "matebookxpro", "x系列", "xpro"), ()),
]


def _norm(s: str) -> str:
    return re.sub(r"[\s\-_（）()·\.]+", "", s.lower())


# 宽泛说法 -> 可能的型号。命中这些词必须让用户确认，不能替用户选。
LOOSE: dict[str, list[str]] = {
    "pro": ["HUAWEI MateBook Pro", "HUAWEI MateBook Pro S"],
    "matebookpro": ["HUAWEI MateBook Pro", "HUAWEI MateBook Pro S"],
    "d16": ["MateBook D 16", "MateBook D 16 SE 版"],
    "matebookd16": ["MateBook D 16", "MateBook D 16 SE 版"],
    "14": ["HUAWEI MateBook 14（鸿蒙版）", "MateBook 14 酷睿 Ultra"],
    "matebook14": ["HUAWEI MateBook 14（鸿蒙版）", "MateBook 14 酷睿 Ultra"],
    "x": ["MateBook X 系列"],
}
_BY_NAME = {m.name: m for m in MODELS}


def resolve_model(text: str) -> tuple[Model | None, list[Model]]:
    """返回 (唯一命中, 候选列表)。唯一命中为 None 且候选非空 => 需要用户确认。

    规则：展示名/文件夹名完全一致才算唯一；其次是精确别名；
    "Pro"、"D16"、"MateBook 14" 这类可对应多个型号的说法，一律返回候选让用户确认。
    """
    n = _norm(text)
    if not n:
        return None, []
    # 先做「带 HUAWEI 前缀的完整名称」精确匹配；缺前缀的说法交给下面的歧义规则
    for m in MODELS:
        if n in (_norm(m.name), _norm(m.folder)):
            if "huawei" in n or m.name == m.folder or not m.confusable:
                return m, [m]
    n = n.replace("huawei", "")
    if n in LOOSE:
        return None, [_BY_NAME[x] for x in LOOSE[n]]
    exact = [m for m in MODELS if n in m.aliases and n not in LOOSE]
    if len(exact) == 1:
        return exact[0], exact
    # 句子里夹带型号（如"给大学生写 MateBook Pro S 的小红书"）：取最长别名命中
    hits = []
    for m in MODELS:
        for a in (_norm(m.name).replace("huawei", ""), *m.aliases):
            if len(a) >= 3 and a in n and a not in LOOSE:
                hits.append((len(a), m))
    if hits:
        hits.sort(key=lambda x: -x[0])
        top = [m for l, m in hits if l == hits[0][0]]
        if len(set(top)) == 1:
            return top[0], top[:1]
        return None, list(dict.fromkeys(top))
    return None, []


def model_names() -> list[str]:
    return [m.name for m in MODELS]
