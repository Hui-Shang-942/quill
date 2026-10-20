import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from agent.catalog import MODELS
from agent.pipeline import _same_model

M = {m.name: m for m in MODELS}

def test_pro_vs_pro_s_never_mixed():
    pro, pros = M["HUAWEI MateBook Pro"], M["HUAWEI MateBook Pro S"]
    assert _same_model("HUAWEI MateBook Pro", pro)
    assert not _same_model("HUAWEI MateBook Pro S", pro)
    assert _same_model("HUAWEI MateBook Pro S", pros)
    assert not _same_model("HUAWEI MateBook Pro", pros)

def test_d16_vs_se():
    d16, se = M["MateBook D 16"], M["MateBook D 16 SE 版"]
    assert _same_model("HUAWEI MateBook D 16 2024", d16)
    assert not _same_model("HUAWEI MateBook D 16 SE 版 2024", d16)
    assert _same_model("HUAWEI MateBook D 16 SE 版 2024", se)
    assert not _same_model("HUAWEI MateBook D 16 2024", se)

def test_empty_and_other():
    assert not _same_model("", M["MateBook D 14"])
    assert not _same_model("HUAWEI MateBook D 14 2024", M["MateBook D 16"])
