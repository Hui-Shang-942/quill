import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from agent.catalog import resolve_model

def names(t):
    m, c = resolve_model(t)
    return (m.name if m else None), [x.name for x in c]

def test_exact():
    assert names("MateBook Pro S")[0] == "HUAWEI MateBook Pro S"
    assert names("HUAWEI MateBook Pro")[0] == "HUAWEI MateBook Pro"
    assert names("MateBook D 16 SE 版")[0] == "MateBook D 16 SE 版"
    assert names("MateBook 14 酷睿 Ultra")[0] == "MateBook 14 酷睿 Ultra"
    assert names("MateBook 14（鸿蒙版）")[0] == "HUAWEI MateBook 14（鸿蒙版）"
    assert names("非凡大师")[0] == "HUAWEI MateBook Fold 非凡大师"

def test_confusable_requires_confirmation():
    for t in ("Pro", "pro", "D16", "matebook 14", "MateBook14"):
        m, c = names(t)
        assert m is None and len(c) >= 2, (t, m, c)

def test_in_sentence():
    assert names("给大学生写一篇 MateBook Pro S 的小红书")[0] == "HUAWEI MateBook Pro S"

def test_unknown():
    assert names("轻薄本") == (None, [])
    assert names("") == (None, [])
