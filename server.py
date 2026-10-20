"""HTTP 服务：实现 frontend/js/api.js 约定的 5 个接口，并托管前端静态文件。前端代码不改。

  GET  /api/status    账号与知识库连接状态（密钥只返回打码后的前 4 位）
  GET  /api/options   下拉选项
  POST /api/check     信息是否足够；不足时返回追问
  POST /api/generate  生成
  POST /api/revise    修改 / 换平台后重新生成
  GET  /api/image     经后端（带鉴权）取回 ima 图片并转发

启动：python server.py        浏览器打开 http://127.0.0.1:8765（端口可用环境变量 COPYWRITER_PORT 修改）
安全：默认只监听本机。本服务没有登录认证，公网部署前必须加访问控制。密钥只在后端读取，绝不下发给前端。
"""
from __future__ import annotations

import hashlib
import pathlib
import re
import sys
import threading
import time
import uuid

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from flask import Flask, Response, jsonify, request, send_from_directory

from agent.catalog import MODELS, resolve_model
from agent.config import CACHE_DIR
from agent.ima_client import ImaError, ImaQuotaExceeded
from agent.pipeline import Agent, Task
from agent.platform_rules import PLATFORMS, SCENARIOS

import os
PORT = int(os.environ.get("COPYWRITER_PORT", "8765"))
ROOT = pathlib.Path(__file__).resolve().parent
FRONT = ROOT / "frontend"
app = Flask(__name__, static_folder=None)
app.json.ensure_ascii = False

AGENT = Agent()
RUN_LOCK = threading.Lock()          # 同一时刻只跑一个生成：避免并发耗尽 ima 额度与模型限速
SESSIONS: dict[str, dict] = {}       # 会话上下文（检索结果等不可序列化对象），按 token 存取
SESSION_TTL = 3600

# 前端平台 id <-> 后端平台名
PLAT_ID = {"wechat": "公众号", "xhs": "小红书", "moments": "门店朋友圈", "poster": "门店海报"}
PLAT_HINT = {
    "wechat": "标题、导语、分段正文、结尾引导。配图 2–4 张。",
    "xhs": "口语化标题、短段落、话题标签。配图 3–6 张。不得伪造个人体验。",
    "moments": "短文案,只讲 1 个核心卖点,引导咨询或到店。配图 1–3 张。",
    "poster": "主标题、副标题、不超过 3 个卖点。1 张主视觉。",
}
AUDIENCES = ["大学新生", "大学新生家长", "商务差旅", "内容创作者", "家庭换新", "企业采购", "附近的潜在顾客", "送礼的人"]
SCENES = ["开学季", "职场办公", "出差途中", "剪辑与设计", "全家共用", "批量部署", "门店到访", "新品首发", "节日送礼"]
SCENE_TO_TYPE = {                       # 前端自由输入的场景 -> 后端业务场景类型（用于选检索关键词/场景指引）
    "开学": "开学季", "新生": "开学季", "职场": "职场办公", "办公": "职场办公", "出差": "职场办公", "差旅": "职场办公",
    "剪辑": "内容创作", "设计": "内容创作", "创作": "内容创作", "摄影": "内容创作", "家": "家庭换新", "换新": "家庭换新",
    "采购": "企业采购", "部署": "企业采购", "企业": "企业采购", "门店": "门店到访", "到店": "门店到访",
    "新品": "新品首发", "首发": "新品首发", "节": "节日营销", "送礼": "节日营销",
}


def scene_type(text: str) -> str:
    for k, v in SCENE_TO_TYPE.items():
        if k in (text or ""):
            return v
    return ""


# ---------------------------------------------------------------- 型号选项
def model_id(m) -> str:
    return hashlib.md5(m.name.encode("utf-8")).hexdigest()[:8]


MODEL_BY_ID = {model_id(m): m for m in MODELS}
SYSTEM_OF = lambda m: "HarmonyOS" if m.group.startswith("01") else "Windows"
CONFUSE_HINT = {
    "HUAWEI MateBook Pro": "与 Pro S 参数不同",
    "HUAWEI MateBook Pro S": "与 Pro 参数不同,请勿混用",
    "MateBook D 16": "与 D 16 SE 版不是同一型号",
    "MateBook D 16 SE 版": "与 D 16 不是同一型号,勿套用其配置",
    "HUAWEI MateBook 14（鸿蒙版）": "与 14 酷睿 Ultra 不是同一型号",
    "MateBook 14 酷睿 Ultra": "与 14(鸿蒙版)不是同一型号",
}


@app.get("/api/options")
def options():
    return jsonify({
        "models": [{"id": model_id(m), "name": m.name, "system": SYSTEM_OF(m), "hint": CONFUSE_HINT.get(m.name, "")}
                   for m in MODELS],
        "audiences": AUDIENCES, "scenes": SCENES,
        "platforms": [{"id": pid, "name": name, "hint": PLAT_HINT[pid]} for pid, name in PLAT_ID.items()],
    })


# ---------------------------------------------------------------- 状态
def mask(s: str) -> str:
    return (s[:4] + "****") if s else ""


def read_client_id() -> str:
    import os
    v = os.environ.get("IMA_OPENAPI_CLIENTID") or os.environ.get("IMA_CLIENT_ID") or ""
    if not v:
        f = pathlib.Path.home() / ".config" / "ima" / "client_id"
        v = f.read_text(encoding="utf-8").strip() if f.exists() else ""
    return v


@app.get("/api/status")
def status():
    h = AGENT.health()
    if h["ok"]:
        return jsonify({"connected": True, "kb_name": h["kb_name"], "key_masked": mask(read_client_id())})
    return jsonify({"connected": False, "kb_name": "", "key_masked": mask(read_client_id()), "message": h["error"]})


# ---------------------------------------------------------------- 任务转换
def to_task(d: dict) -> Task:
    m = MODEL_BY_ID.get(d.get("model", ""))
    plat = PLAT_ID.get(d.get("platform", ""), "")
    scene = (d.get("scene") or "").strip()
    return Task(raw=" ".join(x for x in (d.get("audience"), scene, plat, d.get("extra")) if x),
                model_text=m.name if m else "", audience=d.get("audience", ""),
                scenario=scene_type(scene), platform=plat,
                extra=((d.get("extra") or "") + (f"；使用场景：{scene}" if scene else "")).strip("；"))


@app.post("/api/check")
def check():
    d = request.get_json(silent=True) or {}
    q = []
    if not d.get("model") or d.get("model") not in MODEL_BY_ID:
        q.append("请选择产品型号。")
    if not d.get("audience"):
        q.append("目标人群是谁?例如大学新生、商务差旅。")
    if not (d.get("scene") or "").strip():
        q.append("主要使用场景是什么?例如开学季、出差。")
    if d.get("platform") not in PLAT_ID:
        q.append("要发布到哪个平台?")
    return jsonify({"ok": not q, "questions": q})


# ---------------------------------------------------------------- 结果转换（后端结构 -> 前端 Result）
def _sess_put(ctx: dict) -> str:
    now = time.time()
    for k in [k for k, v in SESSIONS.items() if now - v["t"] > SESSION_TTL]:
        SESSIONS.pop(k, None)
    token = uuid.uuid4().hex
    SESSIONS[token] = {"ctx": ctx, "t": now}
    return token


def image_url(sess: str, filename: str) -> str:
    # 前端只允许 http(s) 开头的 url，因此用同源绝对路径之外再带上 http 前缀由前端 Api.imageUrl 处理：
    # 这里返回 http://local/<token>/<name>，/api/image 解析 query 里的 url 取出 token 与文件名。
    return f"http://ima.local/{sess}/{filename}"


STATUS_MAP = {"supported": "ok", "weakened": "todo", "unsupported": "no", "conflict": "no"}


def mark_pending(text: str, pending_sentences: list[str]) -> str:
    for s in pending_sentences:
        if s and s in text:
            text = text.replace(s, f"[[待确认:{s}]]", 1)
    return text


def to_result(res: dict, task_d: dict) -> dict:
    sc, dr, v, c = res["scene"], res["draft"], res.get("verify", {}), res.get("compliance", {})
    sess = _sess_put(res["_ctx"])
    SESSIONS[sess]["prev"] = {"draft": res.get("draft"), "images": res.get("images", []),
                              "evidence": res.get("evidence", []), "retrieval_trace": res.get("retrieval_trace", []),
                              "retrieval_notes": res.get("retrieval_notes", [])}
    res["_sess"] = sess
    pending_claims = [x for x in v.get("claims", []) if x.get("status") in ("weakened", "unsupported", "conflict")]
    pend_texts = [x.get("text", "") for x in pending_claims]

    # 事实点 -> 依据表
    doc_title = {e["id"]: e for e in res.get("evidence", [])}
    facts = []
    for f in res.get("facts_used", []):
        d = doc_title.get(f.get("doc"), {})
        facts.append({"point": f["text"] + (f"（{f['condition']}）" if f.get("condition") else ""),
                      "title": d.get("title", ""), "media_id": "", "url": ""})

    # 正文：每个 section 合并为一段（含小标题）；图片按 image_pids 挂到所在段之后
    body, after_of = [], {}
    lead = dr.get("lead") or ""
    poster = dr.get("poster") or {}
    if any(poster.values()):
        body.append(f"{poster.get('main_title', '')}")
        if poster.get("sub_title"):
            body.append(poster["sub_title"])
        body += [f"· {p}" for p in poster.get("points", [])]
        if poster.get("note"):
            body.append(poster["note"])
    for s in dr.get("sections", []):
        txt = ((s.get("heading") + "\n") if s.get("heading") else "") + (s.get("text") or "")
        body.append(mark_pending(txt, pend_texts))
        for pid in s.get("image_pids", []):
            after_of[pid] = len(body)
    images = []
    for i, im in enumerate(dr.get("images", [])):
        images.append({
            "name": im["filename"], "source": im["source"], "url": image_url(sess, im["filename"]),
            "position": im["position"], "caption": im["caption"],
            "after": after_of.get(im["pid"], min(i, len(body))),
        })
    titles = dr.get("titles") or [""]
    article = {"title": titles[0] + (("  （备选：" + " / ".join(titles[1:]) + "）") if len(titles) > 1 else ""),
               "lead": lead, "body": body or [""], "cta": dr.get("cta", ""),
               "tags": dr.get("tags") or [], "images": images}

    # 核验
    vfacts = [{"claim": x.get("text", ""), "status": STATUS_MAP.get(x.get("status"), "todo"),
               "evidence": x.get("evidence", "")} for x in v.get("claims", [])]
    vimgs = [{"name": im["filename"], "status": "ok" if im.get("model_match") else "no",
              "note": f"型号与「{res.get('model')}」一致,来自 ima 知识库" if im.get("model_match") else "型号不一致"}
             for im in dr.get("images", [])]
    comp = []
    hits = c.get("rule_hits", []) + c.get("llm_issues", [])
    if not hits:
        comp += [{"status": "ok", "text": "未使用绝对化用语"}, {"status": "ok", "text": "未出现无依据的价格、补贴、库存承诺"},
                 {"status": "ok", "text": "未与其他品牌作无依据对比或贬低"}]
    for h in hits:
        comp.append({"status": "no", "text": f"{h.get('text', '')[:60]}：{h.get('fix', '')}"})
    for r in c.get("auto_removed", []):
        comp.append({"status": "no", "text": f"已自动删除违规句：{r[:60]}"})
    for r in res.get("refusals", []):
        comp.append({"status": "no", "text": r})
    pending = [f"{x.get('text', '')[:50]}（{x.get('evidence', '')[:80]}）" for x in pending_claims]
    pending += [f"检索提示：{n}" for n in res.get("retrieval_notes", [])]

    return {
        "scene": {"audience": sc.get("audience", ""), "scene": sc.get("usage_scene") or sc.get("scenario_type", ""),
                  "problem": sc.get("main_problem", ""), "goal": sc.get("content_goal", ""),
                  "platform": res.get("platform", ""),
                  "reason": res.get("strategy", {}).get("angle", "")},
        "evidence": {"model": res.get("model", ""), "facts": facts,
                     "rejected": [f"已排除相近型号：{CONFUSE_HINT[res['model']]}"] if res.get("model") in CONFUSE_HINT else []},
        "article": article,
        "verify": {"facts": vfacts, "images": vimgs, "compliance": comp, "pending": pending},
        "_sess": sess,
        "_meta": {"total_sec": res.get("total_sec"), "fix_rounds": res.get("fix_rounds"),
                  "model_calls": res.get("usage", {}).get("calls")},
    }


def error(msg: str, code: int = 500):
    return jsonify({"error": msg}), code


def explain(res: dict):
    st = res.get("status")
    if st == "need_info":
        return error("；".join(q["question"] for q in res["questions"]), 400)
    if st in ("no_evidence", "conflict", "error"):
        return error(res.get("message", "未生成"), 422 if st != "error" else 502)
    return None


@app.post("/api/generate")
def generate():
    d = request.get_json(silent=True) or {}
    if d.get("model") not in MODEL_BY_ID:
        return error("请选择产品型号", 400)
    if not RUN_LOCK.acquire(timeout=1):
        return error("上一个任务还在生成中,请稍后再试", 429)
    try:
        res = AGENT.start(to_task(d))
        bad = explain(res)
        if bad:
            return bad
        return jsonify(to_result(res, d))
    except ImaQuotaExceeded as e:
        return error(str(e), 503)
    except ImaError as e:
        return error(f"知识库访问失败：{e}", 502)
    finally:
        RUN_LOCK.release()


@app.post("/api/revise")
def revise():
    d = request.get_json(silent=True) or {}
    task, instruction, prev = d.get("task") or {}, (d.get("instruction") or "").strip(), d.get("previous") or {}
    sess = SESSIONS.get(prev.get("_sess", ""))
    if not sess:
        return error("上一版结果的会话已过期,请重新生成", 410)
    new_plat = None
    for name, pid in (("朋友圈", "moments"), ("公众号", "wechat"), ("小红书", "xhs"), ("海报", "poster")):
        if name in instruction and re.search(r"换成|改成|改为|转成|变成", instruction):
            new_plat = pid
    prev_res = {"_ctx": sess["ctx"], **sess.get("prev", {})}
    if not RUN_LOCK.acquire(timeout=1):
        return error("上一个任务还在生成中,请稍后再试", 429)
    try:
        res = AGENT.revise(prev_res, instruction or "按平台要求重新改写", PLAT_ID.get(new_plat) if new_plat else None)
        bad = explain(res)
        if bad:
            return bad
        out = to_result(res, task)
        if new_plat:
            out["_task"] = {**task, "platform": new_plat}          # 前端据此同步左侧表单
        return jsonify(out)
    except ImaQuotaExceeded as e:
        return error(str(e), 503)
    except ImaError as e:
        return error(f"知识库访问失败：{e}", 502)
    finally:
        RUN_LOCK.release()



# ---------------------------------------------------------------- 图片代理
@app.get("/api/image")
def image():
    u = request.args.get("url", "")
    m = re.fullmatch(r"http://ima\.local/([0-9a-f]{32})/(.+)", u)
    if not m:
        return error("不支持的图片地址", 400)
    sess = SESSIONS.get(m.group(1))
    if not sess:
        return error("会话已过期", 410)
    name = m.group(2)
    cand = next((c for c in sess["ctx"]["ret"].images if c.filename == name and c.item), None)
    if not cand:
        return error("图片不在本次检索结果中", 404)
    try:
        got = AGENT.ima.fetch_image(cand.item)
    except ImaQuotaExceeded as e:
        return error(str(e), 503)
    except ImaError as e:
        return error(str(e), 502)
    if not got:
        return error("图片无法获取", 404)
    return Response(got[0], mimetype=got[1], headers={"Cache-Control": "private, max-age=3600"})


# ---------------------------------------------------------------- 静态前端
@app.get("/")
def index():
    return send_from_directory(FRONT, "index.html")


@app.get("/<path:p>")
def static_files(p):
    if p.startswith("api/"):
        return error("not found", 404)
    if p in ("css/custom.css", "js/custom.js") and not (FRONT / p).exists():
        return Response("", mimetype="text/css" if p.endswith(".css") else "application/javascript")   # 前端预留的定制入口，暂无内容
    return send_from_directory(FRONT, p)


if __name__ == "__main__":
    # threaded：允许 /api/image 在生成期间并发取图；生成本身由 RUN_LOCK 串行
    app.run(host="127.0.0.1", port=PORT, threaded=True)
