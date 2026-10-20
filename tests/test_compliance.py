import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from agent.compliance import scan, check_user_request

def types(t, **kw):
    return {i["type"] for i in scan(t, **kw)}

def test_absolute():
    assert "absolute" in types("这是最好的轻薄本，续航第一。")
    assert "absolute" in types("100%满足你的需求")

def test_price_and_subsidy():
    assert "price" in types("现在入手立减500元，国补再降一波")
    assert "price" in types("售价5999元")
    assert "price" not in types("现在入手立减500元", allow_price=True)

def test_fake_experience():
    assert "fake_experience" in types("我用了三个月，真的很香")
    assert "fake_experience" in types("亲测不卡顿")

def test_compare_and_disparage():
    assert "compare" in types("续航比MacBook强很多")
    assert "compare" in types("联想的屏幕太差了")

def test_promise_and_urgency():
    assert "promise" in types("保证不卡顿")
    assert "urgency" in types("手慢无，马上抢")

def test_clean_text_passes():
    ok = "14.2 英寸 3:2 屏幕，适合在课堂上同时打开文档和网页。机身厚度 11.9 mm，随身携带更轻松。欢迎到店体验。"
    assert scan(ok) == []

def test_user_request_flags():
    f = check_user_request("帮我写进去国补500元，再说比MacBook强")
    assert f["asks_price"] and f["asks_compare"]
    assert not check_user_request("给大学新生写小红书")["asks_price"]
