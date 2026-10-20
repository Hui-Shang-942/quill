"""合规检查的确定性规则层（不依赖大模型，评委换样本也稳定）。

大模型复查在 pipeline 里作为第二层；这里先做硬拦截。
命中即记录「原句 + 类型 + 建议」，并可自动给出替换。"""
from __future__ import annotations

import re

# (正则, 类型, 建议)  —— 绝对化与夸大
ABSOLUTE = [
    (r"第一|唯一|最(?:好|强|佳|快|薄|轻|牛|优|顶)|史上|顶级|顶配|无与伦比|无可替代|遥遥领先|全面领先|绝无仅有|前所未有",
     "absolute", "删除或改成可由资料支持的具体描述"),
    (r"100\s*%|百分之百|绝对|完全不会|永不|零风险|零延迟|终身", "absolute", "避免绝对化表述，写明条件"),
    (r"碾压|吊打|秒杀|吊炸天|完爆", "exaggeration", "删除夸张表述"),
    (r"国内首|全球首|行业首|首款|首创", "absolute", "无资料依据的“首”类表述需删除"),
]

PROMISE = [
    (r"保证|承诺|一定(?:能|会)|必定|包(?:你|您)?(?:满意|好用)|无条件退换|零差评", "promise", "删除承诺类措辞"),
    (r"绝对兼容|全部兼容|任何(?:软件|设备|外设).{0,4}(?:都能|均可)", "promise", "兼容性须绑定具体软件/外设并建议到店验证"),
]

PRICE = [
    (r"[¥￥]\s*\d+|\d+\s*元|\d+\s*块钱|(?:售价|价格|到手价|立省|直降|立减|补贴|国补|优惠|折扣|折|赠品|赠送|分期|以旧换新|秒杀价|限时|限量|库存|现货)",
     "price", "无资料依据的价格/活动信息一律删除"),
]

COMPARE = [
    (r"(?:比|胜过|超越|吊打|优于|领先)\s*(?:苹果|MacBook|联想|小米|戴尔|惠普|华硕|ThinkPad|荣耀|三星|微软)", "compare", "删除无依据对比"),
    (r"(?:苹果|MacBook|联想|小米|戴尔|惠普|华硕|ThinkPad|荣耀)\S{0,6}(?:不行|太差|垃圾|落后|不如)", "compare", "删除竞品贬低"),
]

FAKE_EXPERIENCE = [
    (r"我(?:用了|已经用了|用过|入手|自己买|亲测|实测|体验了)|用了\s*[一二三四五六七八九十\d]+\s*(?:天|周|个月|年)|亲测|实测|我的使用体验|博主|买家秀",
     "fake_experience", "不得伪造个人体验，改为场景化描述"),
]

URGENCY = [
    (r"手慢无|最后\s*\d+|仅剩|错过(?:就)?(?:没|再等)|马上抢|抢购|疯抢|不买后悔|闭眼入", "urgency", "删除制造紧迫感的话术"),
]

ALL_RULES = ABSOLUTE + PROMISE + COMPARE + FAKE_EXPERIENCE + URGENCY
PRICE_RULES = PRICE


def split_sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[。！？!?；;\n])", text)
    return [p.strip() for p in parts if p.strip()]


def scan(text: str, allow_price: bool = False, allow_first_person: bool = False) -> list[dict]:
    """返回命中列表：[{text, type, fix, match}]。"""
    rules = list(ALL_RULES)
    if allow_first_person:
        rules = [r for r in rules if r[1] != "fake_experience"]
    if not allow_price:
        rules += PRICE_RULES
    issues, seen = [], set()
    for sent in split_sentences(text):
        for pat, typ, fix in rules:
            m = re.search(pat, sent)
            if m and (sent, typ) not in seen:
                seen.add((sent, typ))
                issues.append({"text": sent, "type": typ, "fix": fix, "match": m.group(0)})
    return issues


def draft_to_text(draft: dict) -> str:
    """把结构化稿件拼成待扫描文本（含标题、导语、正文、行动引导、海报字段、图片说明）。"""
    parts = list(draft.get("titles") or [])
    parts.append(draft.get("lead") or "")
    for s in draft.get("sections") or []:
        parts.append(s.get("heading") or "")
        parts.append(s.get("text") or "")
    parts.append(draft.get("cta") or "")
    poster = draft.get("poster") or {}
    for k in ("main_title", "sub_title", "note"):
        parts.append(poster.get(k) or "")
    parts += list(poster.get("points") or [])
    for im in draft.get("images") or []:
        parts.append(im.get("caption") or "")
    return "\n".join(p for p in parts if p)


def check_draft(draft: dict, allow_price: bool = False, allow_first_person: bool = False) -> list[dict]:
    return scan(draft_to_text(draft), allow_price, allow_first_person)


def check_user_request(user_text: str) -> dict:
    """用户的原始需求里是否在要求违规内容。返回 {asks_price, asks_fake_experience, asks_compare, details}。"""
    asks_price = bool(re.search(PRICE[0][0], user_text))
    asks_fake = bool(re.search(FAKE_EXPERIENCE[0][0], user_text))
    asks_cmp = bool(re.search("|".join(p for p, _, _ in COMPARE), user_text)) or bool(
        re.search(r"对比|比较|PK|pk|碾压|贬低", user_text) and re.search(r"苹果|MacBook|联想|小米|戴尔|惠普|华硕|荣耀", user_text))
    absolute = bool(re.search(ABSOLUTE[0][0], user_text))
    return {"asks_price": asks_price, "asks_fake_experience": asks_fake,
            "asks_compare": asks_cmp, "asks_absolute": absolute}
