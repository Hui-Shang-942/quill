"""主流水线：场景解析 → 平台策略 → ima 检索 → 事实点提取 → 图文编排 → 软文生成
→ 事实与图片核验 → 合规检查 → 导出。

对外只暴露 Agent.start() / Agent.revise()，返回结构化结果 dict（界面与导出共用）。
"""
from __future__ import annotations

import json
import re
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

from . import compliance, prompts
from .catalog import Model, resolve_model
from .config import MAX_OUTPUT_TOKENS, STEP_EFFORT, SUPPORTED_PLATFORMS
from .ima_client import ImaClient, ImaError
from .llm import LLM, LLMError, LLMRefusal
from .platform_rules import PLATFORMS, SCENARIOS, clamp_images, describe
from .retriever import Retrieval, retrieve

SCENE_KEYWORDS = {
    "开学季": ["便携", "续航", "协同", "适用人群"],
    "职场办公": ["便携", "续航", "协同", "接口", "适用人群"],
    "内容创作": ["屏幕", "性能", "协同"],
    "家庭换新": ["系统", "协同", "适用人群"],
    "企业采购": ["系统", "兼容", "适用人群"],
    "门店到访": ["屏幕", "便携"],
    "新品首发": ["身份", "屏幕", "性能"],
    "节日营销": ["适用人群", "便携"],
}
INTERNAL_WORDS = ("发布前需人工", "需人工核对", "人工核对画面", "索引未提供", "资料没有给出", "资料里没有", "知识库里没有", "知识库没有")
BODY_LIMITS = {
    "小红书": (300, 800), "微信朋友圈": (80, 180), "公众号": (1200, 2200),
    "微博图文": (80, 300), "新闻稿图文": (800, 1600), "知乎图文": (1500, 3000),
}
MAX_FIX_ROUNDS = 1       # 最多自动修订 1 轮；仍有规则命中的句子由代码直接删除
WORKFLOW_STAGES = [
    {"id": "understand", "label": "理解需求并检索资料"},
    {"id": "strategy", "label": "平台规则与卖点规划"},
    {"id": "layout", "label": "图文编排与选图"},
    {"id": "write", "label": "撰写文案"},
    {"id": "verify", "label": "事实核验与合规检查"},
    {"id": "finish", "label": "加载配图并整理结果"},
]


@dataclass
class Task:
    raw: str = ""
    model_text: str = ""
    audience: str = ""
    scenario: str = ""
    platform: str = ""
    extra: str = ""


def _j(x) -> str:
    return json.dumps(x, ensure_ascii=False, separators=(',', ':'))


NL = chr(10)


_DRAFT_FIELD_RE = re.compile(r'(?<!\\)"(publish_title|lead|heading|text|cta|main_title|sub_title)"\s*:\s*"')


def _partial_json_string(source: str, offset: int) -> tuple[str, bool]:
    """Decode a possibly incomplete JSON string value without exposing its syntax."""
    chars = []
    i = offset
    escapes = {"\"": "\"", "\\": "\\", "/": "/", "b": "\b", "f": "\f",
               "n": "\n", "r": "\r", "t": "\t"}
    while i < len(source):
        char = source[i]
        if char == '"':
            return "".join(chars), True
        if char != "\\":
            chars.append(char)
            i += 1
            continue
        if i + 1 >= len(source):
            break
        escaped = source[i + 1]
        if escaped in escapes:
            chars.append(escapes[escaped])
            i += 2
            continue
        if escaped == "u":
            digits = source[i + 2:i + 6]
            if len(digits) != 4 or not re.fullmatch(r"[0-9a-fA-F]{4}", digits):
                break
            codepoint = int(digits, 16)
            if 0xD800 <= codepoint <= 0xDBFF:
                next_escape = source[i + 6:i + 8]
                low_digits = source[i + 8:i + 12]
                if next_escape != "\\u" or len(low_digits) != 4 or not re.fullmatch(r"[0-9a-fA-F]{4}", low_digits):
                    break
                low = int(low_digits, 16)
                if not 0xDC00 <= low <= 0xDFFF:
                    break
                codepoint = 0x10000 + ((codepoint - 0xD800) << 10) + (low - 0xDC00)
                i += 12
            elif 0xDC00 <= codepoint <= 0xDFFF:
                i += 6
                continue
            else:
                i += 6
            chars.append(chr(codepoint))
            continue
        break
    return "".join(chars), False


class DraftPreviewStream:
    """Convert partial JSON deltas into safe, readable Markdown draft updates."""
    BANNER = (
        "## 文案生成中\n\n"
        "> 当前内容为模型实时草稿，事实与合规核验仍在进行；完成后将自动更新为核验版本。\n\n"
    )

    def __init__(self, publish):
        self.publish = publish
        self.raw = ""
        self.last_visible_count = 0
        self.last_complete_count = 0

    def reset(self):
        self.raw = ""
        self.last_visible_count = 0
        self.last_complete_count = 0
        self.publish(self.BANNER)

    def feed(self, delta: str):
        self.raw += delta
        fields = []
        for match in _DRAFT_FIELD_RE.finditer(self.raw):
            value, complete = _partial_json_string(self.raw, match.end())
            fields.append((match.group(1), value, complete))

        lines = [self.BANNER.rstrip()]
        for key, value, _ in fields:
            value = value.strip() if key in ("publish_title", "main_title", "sub_title", "heading") else value
            if not value:
                continue
            if key in ("publish_title", "main_title"):
                lines.extend(["", f"### {value}"])
            elif key == "sub_title":
                lines.extend(["", f"#### {value}"])
            elif key == "lead":
                lines.extend(["", value])
            elif key == "heading":
                lines.extend(["", f"#### {value}"])
            elif key == "text":
                lines.extend(["", value])
            elif key == "cta":
                lines.extend(["", value])
        preview = "\n".join(lines)
        visible_count = len(preview)
        complete_count = sum(1 for _, _, complete in fields if complete)
        # Batch small model deltas for a smooth effect without flooding the Gradio queue.
        if visible_count - self.last_visible_count >= 10 or complete_count > self.last_complete_count:
            self.last_visible_count = visible_count
            self.last_complete_count = complete_count
            self.publish(preview)


class Agent:
    def __init__(self, ima: ImaClient | None = None, llm: LLM | None = None):
        self.ima = ima or ImaClient()
        self.llm = llm or LLM()

    # ------------------------------------------------------------------ 状态检查
    def health(self) -> dict:
        """功能1：账号与知识库连接状态（不含任何密钥/内部ID）。"""
        try:
            info = self.ima.connect()
            return {"ok": True, **info}
        except ImaError as e:
            return {"ok": False, "error": str(e)}

    # ------------------------------------------------------------------ 第一步：场景解析
    def parse_scene(self, task: Task) -> dict:
        user = (f"用户原始需求：{task.raw}\n表单已填：产品={task.model_text}，人群={task.audience}，"
                f"场景={task.scenario}，平台={task.platform}，补充={task.extra}")
        scene = self.llm.json(prompts.CORE_SYSTEM + prompts.SCENE_TASK, user, 4000, STEP_EFFORT["scene"], "场景解析")
        # 表单优先于模型推断
        for key, val in (("product_text", task.model_text), ("audience", task.audience),
                         ("scenario_type", task.scenario), ("platform", task.platform)):
            if val:
                scene[key] = val
        if task.extra:
            scene.setdefault("extra_requests", []).append(task.extra)
        return scene

    def missing_info(self, scene: dict) -> list[dict]:
        """功能2：信息不足时给出追问（不是报错）。"""
        q = []
        model, cands = resolve_model(scene.get("product_text", ""))
        if not scene.get("product_text"):
            q.append({"field": "product", "question": "要写哪一款产品？", "options": [m for m in _model_options()]})
        elif model is None and cands:
            q.append({"field": "product", "question": f"「{scene['product_text']}」可能对应多个型号，请确认是哪一款：",
                      "options": [m.name for m in cands]})
        elif model is None:
            q.append({"field": "product", "question": f"知识库里没有找到「{scene['product_text']}」，请从已有型号中选择：",
                      "options": _model_options()})
        if not scene.get("audience"):
            q.append({"field": "audience", "question": "目标人群是谁？（如：大学新生、经常出差的职场人、家庭用户）", "options": []})
        if scene.get("platform") not in SUPPORTED_PLATFORMS:
            q.append({"field": "platform", "question": "发布在哪个平台？", "options": SUPPORTED_PLATFORMS})
        if not scene.get("scenario_type") and not scene.get("usage_scene"):
            q.append({"field": "scenario", "question": "主要的使用场景或业务场景是什么？", "options": list(SCENARIOS)})
        return q

    # ------------------------------------------------------------------ 主流程
    def start(self, task: Task, progress=lambda s: None, draft_progress=None) -> dict:
        res: dict = {"status": "ok", "steps": []}

        t_start = time.time()

        def step(stage, detail=""):
            name = next(item["label"] for item in WORKFLOW_STAGES if item["id"] == stage)
            res["steps"].append({"step": name, "detail": detail, "at_sec": round(time.time() - t_start, 1)})
            progress({"stage": stage, "label": name, "detail": detail,
                      "elapsed_sec": round(time.time() - t_start, 1)})

        try:
            step("understand", "正在解析需求，并行预取目标型号资料")
            pre_model, _ = resolve_model(task.model_text) if task.model_text else (None, [])
            pre_kw = SCENE_KEYWORDS.get(task.scenario, ["适用人群"])
            with ThreadPoolExecutor(max_workers=2) as pool:
                f_scene = pool.submit(self.parse_scene, task)
                f_ret = pool.submit(retrieve, self.ima, pre_model, pre_kw) if pre_model else None
                scene = f_scene.result()
                pre_ret = f_ret.result() if f_ret else None
            res["scene"] = scene

            req_flags = compliance.check_user_request(task.raw + " " + task.extra)
            res["user_request_flags"] = req_flags

            questions = self.missing_info(scene)
            if questions:
                res["status"] = "need_info"
                res["questions"] = questions
                return res

            model, _ = resolve_model(scene["product_text"])
            platform = scene["platform"]
            res["model"] = model.name
            res["platform"] = platform

            res["platform_rules"] = {k: v for k, v in PLATFORMS[platform].items()}

            if pre_ret is not None and pre_model == model:
                ret = pre_ret
            else:
                kw = SCENE_KEYWORDS.get(scene.get("scenario_type", ""), ["适用人群"])
                ret = retrieve(self.ima, model, kw)
            res["steps"].append({"step": "知识库资料检索", "detail": model.name,
                                 "at_sec": round(time.time() - t_start, 1)})
            res["retrieval_trace"] = ret.trace
            res["retrieval_notes"] = ret.notes
            if not ret.docs:
                res["status"] = "no_evidence"
                res["message"] = "知识库里没有找到这款产品可用的资料，无法生成（避免凭空编造）。" + "；".join(ret.notes)
                return res
            res["evidence"] = [{"id": f"D{i+1}", "title": d.title, "path": d.path} for i, d in enumerate(ret.docs)]

            step("strategy", f"{platform}：{PLATFORMS[platform]['structure']}")
            strat = self._strategy(scene, platform, ret)
            res["strategy"] = strat
            if strat.get("conflicts"):
                res["status"] = "conflict"
                res["message"] = "资料之间存在冲突，已停止输出，请人工确认：" + "；".join(
                    c.get("description", "") for c in strat["conflicts"])
                return res

            step("layout", "按平台要求筛选匹配型号的图片")
            images = self._pick_images(scene, platform, strat, ret)
            res["images"] = images

            step("write", "根据场景策略、资料事实和平台规则撰写")
            draft = self._write(scene, platform, strat, images, req_flags, draft_progress=draft_progress)
            draft["images"] = images

            step("verify", "逐项核对事实、型号、配图和合规规则")
            draft, verify, comp, rounds = self._verify_and_fix(
                scene, platform, strat, ret, images, draft, req_flags, draft_progress=draft_progress)
            res.update(draft=draft, verify=verify, compliance=comp, publish_ready=verify.get("publish_ready", False),
                       fix_rounds=rounds)
            res["refusals"] = self._refusals(req_flags)
            res["facts_used"] = self._facts_used(strat, draft)
            res["usage"] = dict(self.llm.usage)
            res["timings"] = list(self.llm.timings)
            res["total_sec"] = round(time.time() - t_start, 1)
            res["ima_calls"] = list(self.ima.calls)
            res["_ctx"] = {"scene": scene, "platform": platform, "strat": strat, "ret": ret}
            step("finish", "加载配图并整理可下载的结果")
            self.attach_images(res)
            return res
        except LLMRefusal as e:
            res["status"] = "error"; res["message"] = str(e); return res
        except (LLMError, ImaError) as e:
            res["status"] = "error"; res["message"] = str(e); return res

    def attach_images(self, res: dict) -> None:
        """把配图字节取回（走缓存，不额外耗 ima 额度）。取不到的图在界面上显示占位说明。"""
        ctx = res.get("_ctx")
        if not ctx:
            return
        by_name = {c.filename: c for c in ctx["ret"].images}
        out = {}
        for im in (res.get("draft") or {}).get("images", []):
            cand = by_name.get(im["filename"])
            if not cand or not cand.item:
                continue
            try:
                got = self.ima.fetch_image(cand.item)
            except ImaError as e:
                im["fetch_error"] = str(e)
                continue
            if got:
                out[im["filename"]] = got
        res["_image_bytes"] = out

    # ------------------------------------------------------------------ 子步骤
    def _docs_text(self, ret: Retrieval) -> str:
        return "\n\n".join(f"【D{i+1}】{d.title}（{d.path}）\n{d.text}" for i, d in enumerate(ret.docs))

    def _strategy(self, scene, platform, ret: Retrieval) -> dict:
        user = (f"场景判断：\n{_j(scene)}\n\n{describe(platform)}\n"
                f"场景指引：{SCENARIOS.get(scene.get('scenario_type',''), '按人群与使用场景自行判断')}\n\n"
                f"知识库资料（只能使用这些）：\n{self._docs_text(ret)}")
        return self.llm.json(prompts.CORE_SYSTEM + prompts.STRATEGY_TASK, user, 12000, STEP_EFFORT["strategy"], "事实点与策略")

    def _pick_images(self, scene, platform, strat, ret: Retrieval) -> list[dict]:
        lo, hi = PLATFORMS[platform]["image_range"]
        # 型号核对：图片索引里的「产品型号」必须与目标型号一致；不一致的直接剔除
        cands = [i for i in ret.images if i.verified_in_ima and _same_model(i.model, ret.model)]
        if not cands:
            return []
        listing = "\n".join(f"{c.pid} | {c.filename} | 画面：{c.description} | 建议用途：{c.usage}" for c in cands)
        task = prompts.IMAGE_TASK.replace("@@N_MIN@@", str(lo)).replace("@@N_MAX@@", str(hi))
        user = f"策略：\n{_j(strat)}\n\n平台：{platform}\n候选图片：\n{listing}"
        out = self.llm.json(prompts.CORE_SYSTEM + task, user, 4000, STEP_EFFORT["images"], "选图")
        by_pid = {c.pid: c for c in cands}
        picked, seen = [], set()
        for im in out.get("images", []):
            c = by_pid.get(im.get("pid"))
            if not c or c.pid in seen:
                continue
            seen.add(c.pid)
            picked.append({
                "pid": c.pid, "filename": c.filename, "model": c.model,
                "source": f"ima 知识库 / {ret.model.group}/{ret.model.folder}/images",
                "origin_page": c.source_page, "description_in_index": c.description,
                "position": im.get("position", ""), "reason": im.get("reason", ""),
                "caption": im.get("caption", "") or c.description,
                "model_match": True,
            })
        return picked[:clamp_images(platform, len(picked))]

    def _write(self, scene, platform, strat, images, req_flags, extra_instruction: str = "",
               draft_progress=None) -> dict:
        task = prompts.WRITE_TASK.replace("@@PLATFORM@@", platform)
        user = (f"场景判断：\n{_j(scene)}\n\n{describe(platform)}\n策略与事实点：\n{_j(strat)}\n\n"
                f"配图方案（只能引用这些图片）：\n{_j(images)}\n"
                f"用户特别要求：{scene.get('extra_requests', [])}\n"
                f"{self._boundary_text(req_flags)}{extra_instruction}")
        max_tokens = MAX_OUTPUT_TOKENS if platform == "B站中长视频" else 16000
        parser = DraftPreviewStream(draft_progress) if draft_progress else None
        if parser:
            parser.reset()
            return self.llm.json(prompts.CORE_SYSTEM + task, user, max_tokens, STEP_EFFORT["write"], "写作",
                                 on_delta=parser.feed, on_reset=parser.reset)
        return self.llm.json(prompts.CORE_SYSTEM + task, user, max_tokens, STEP_EFFORT["write"], "写作")

    def _boundary_text(self, req_flags: dict) -> str:
        notes = []
        if req_flags.get("asks_price"):
            notes.append("用户提到了价格/补贴/优惠。知识库没有对应依据，正文不得出现任何价格、补贴、优惠、赠品信息；如需活动说明只写“以门店实际为准”。")
        if req_flags.get("asks_fake_experience"):
            notes.append("用户要求个人使用体验。不得编造亲身体验，改用场景化描述。")
        if req_flags.get("asks_compare"):
            notes.append("用户要求与其他品牌对比。没有依据时不做对比，不贬低任何竞品。")
        if req_flags.get("asks_absolute"):
            notes.append("用户要求使用绝对化用语。不得使用，改写成有资料依据的具体描述。")
        return ("\n【边界提醒】\n" + "\n".join(notes) + "\n") if notes else ""

    def _refusals(self, req_flags: dict) -> list[str]:
        out = []
        if req_flags.get("asks_price"):
            out.append("已拒绝写入价格/补贴/优惠：知识库中没有可核验的依据（价格、补贴均为动态信息，需官方渠道当日确认）。")
        if req_flags.get("asks_fake_experience"):
            out.append("已拒绝伪造个人使用体验，改为场景化描述。")
        if req_flags.get("asks_compare"):
            out.append("已不做无依据的品牌对比，也不贬低其他品牌。")
        if req_flags.get("asks_absolute"):
            out.append("已不使用绝对化用语，改为有资料依据的具体描述。")
        return out

    def _facts_used(self, strat: dict, draft: dict) -> list[dict]:
        used = {fid for s in draft.get("sections") or [] for fid in s.get("fact_ids", [])}
        return [f for f in strat.get("facts", []) if f.get("id") in used]

    # ------------------------------------------------------------------ 核验 + 合规 + 自动修复
    def _verify_and_fix(self, scene, platform, strat, ret, images, draft, req_flags, draft_progress=None):
        allow_exp = PLATFORMS[platform]["first_person_experience"]
        verify, comp, rounds = {}, {}, 0
        for rounds in range(MAX_FIX_ROUNDS + 1):
            rule_hits = compliance.check_draft(draft, allow_price=False, allow_first_person=allow_exp)
            with ThreadPoolExecutor(max_workers=2) as pool:      # 事实核验与合规复查互不依赖，并行
                fv = pool.submit(self._verify, draft, strat, ret, platform)
                fc = pool.submit(self._comp_llm, draft, platform)
                verify, llm_comp = fv.result(), fc.result()
            bad_claims = [c for c in verify.get("claims", []) if c.get("status") != "supported"]
            hard_claims = [c for c in bad_claims if c.get("status") in ("unsupported", "conflict")]
            comp = {"rule_hits": rule_hits, "llm_issues": llm_comp.get("issues", []),
                    "pass": not rule_hits and llm_comp.get("pass", True)}
            problems = bool(hard_claims or rule_hits or llm_comp.get("issues") or verify.get("model_mixup")
                            or verify.get("image_issues") or self._structure_issues(draft, platform, images))
            if not problems:
                break
            if rounds >= MAX_FIX_ROUNDS:
                break
            fb = {"事实核验问题": bad_claims, "型号混用": verify.get("model_mixup", []),
                  "配图问题": verify.get("image_issues", []), "规则命中": rule_hits,
                  "合规复查": llm_comp.get("issues", []), "结构问题": self._structure_issues(draft, platform, images)}
            user = (f"上一版稿件：\n{_j(draft)}\n\n反馈：\n{_j(fb)}\n\n策略与事实点：\n{_j(strat)}\n\n"
                    f"{describe(platform)}\n配图方案：\n{_j(images)}\n{self._boundary_text(req_flags)}")
            max_tokens = MAX_OUTPUT_TOKENS if platform == "B站中长视频" else 16000
            parser = DraftPreviewStream(draft_progress) if draft_progress else None
            if parser:
                parser.reset()
                new = self.llm.json(prompts.CORE_SYSTEM + prompts.REVISE_TASK, user, max_tokens,
                                    STEP_EFFORT["revise"], "修订", on_delta=parser.feed, on_reset=parser.reset)
            else:
                new = self.llm.json(prompts.CORE_SYSTEM + prompts.REVISE_TASK, user, max_tokens,
                                    STEP_EFFORT["revise"], "修订")
            new["images"] = images
            draft = new
        verify["final_pass"] = not [c for c in verify.get("claims", []) if c.get("status") != "supported"] \
            and not verify.get("model_mixup") and not verify.get("image_issues")
        # 兜底：多轮后仍有规则命中，则把命中的句子直接删除（宁可少写，不留违规）
        if comp.get("rule_hits"):
            draft = _strip_sentences(draft, [h["text"] for h in comp["rule_hits"]])
            comp["auto_removed"] = [h["text"] for h in comp["rule_hits"]]
            comp["rule_hits_after"] = compliance.check_draft(draft, False, allow_exp)
            comp["pass"] = not comp["rule_hits_after"] and not comp.get("llm_issues")
        structure_issues = self._structure_issues(draft, platform, images)
        verify["structure_issues"] = structure_issues
        verify["publish_ready"] = bool(verify.get("final_pass") and comp.get("pass")
                                       and not comp.get("llm_issues") and not structure_issues)
        return draft, verify, comp, rounds

    def _verify(self, draft, strat, ret, platform) -> dict:
        """独立核验：核验员看到全部资料原文（不只是作者引用的），保证独立性；
        事实点列表去掉与稿件无关的，减少输入量。"""
        text = compliance.draft_to_text(draft)
        imgs = [{"pid": i["pid"], "caption": i["caption"], "index": i["description_in_index"]}
                for i in draft.get("images", [])]
        user = (
            "待核验稿件：" + NL + text + NL + NL
            + "事实点（作者整理，供参考；以资料原文为准）：" + NL + _j(strat.get("facts", [])) + NL + NL
            + "资料原文：" + NL + self._docs_text(ret) + NL + NL
            + "目标型号：" + ret.model.name + NL
            + "配图索引描述：" + NL + _j(imgs))
        max_tokens = MAX_OUTPUT_TOKENS if platform == "B站中长视频" else 12000
        return self.llm.json(prompts.CORE_SYSTEM + prompts.VERIFY_TASK, user, max_tokens,
                             STEP_EFFORT["verify"], "事实核验")

    def _comp_llm(self, draft, platform) -> dict:
        view = {"publish_title": draft.get("publish_title"), "titles": draft.get("titles"), "lead": draft.get("lead"), "sections": [
            {"heading": x.get("heading"), "text": x.get("text")} for x in draft.get("sections") or []],
            "cta": draft.get("cta"), "tags": draft.get("tags"), "poster": draft.get("poster"),
            "images": [{"filename": i["filename"], "caption": i["caption"]} for i in draft.get("images", [])]}
        user = ("平台规则：" + chr(10) + describe(platform) + chr(10)
                + "稿件（JSON）：" + chr(10) + _j(view))
        return self.llm.json(prompts.CORE_SYSTEM + prompts.COMPLIANCE_TASK, user, 6000, STEP_EFFORT["compliance"], "合规复查")

    def _structure_issues(self, draft, platform, images) -> list[str]:
        out, lo_hi = [], PLATFORMS[platform]["image_range"]
        n = len(images)
        if not (lo_hi[0] <= n <= lo_hi[1]):
            out.append(f"配图数量 {n} 不符合{platform}要求 {lo_hi[0]}-{lo_hi[1]} 张")
        if platform == "门店海报":
            poster = draft.get("poster") or {}
            title = poster.get("main_title") or ""
            if not title:
                out.append("海报缺少主标题")
            elif not 12 <= len("".join(title.split())) <= 22:
                out.append(f"海报主标题为{len(''.join(title.split()))}字，应为12-22字")
            if not poster.get("sub_title"):
                out.append("海报缺少副标题")
            pts = poster.get("points") or []
            if len(pts) > 3:
                out.append("海报卖点超过3个")
            body = "".join([
                poster.get("sub_title") or "",
                *[str(point) for point in pts],
                poster.get("note") or "",
                draft.get("cta") or "",
            ])
            body_length = len("".join(body.split()))
            if not 40 <= body_length <= 90:
                out.append(f"海报正文为{body_length}字，应为40-90字（含副标题、卖点、活动说明和行动引导）")
        elif platform != "微信朋友圈" and not draft.get("publish_title"):
            out.append("缺少唯一选定的最终发布标题，不能提供可直接复制的成稿")
        if platform == "小红书" and not draft.get("tags"):
            out.append("小红书需要话题标签")
        if not draft.get("cta"):
            out.append("缺少行动引导")
        full = compliance.draft_to_text(draft)
        for w in INTERNAL_WORDS:
            if w in full:
                out.append(f"成稿里出现了内部话术「{w}」，面向读者的文字不能写这个")
        body = "".join((x.get("text") or "") for x in draft.get("sections") or []) + (draft.get("lead") or "")
        limit = BODY_LIMITS.get(platform)
        if limit and len(body) > limit[1]:
            out.append(f"正文约 {len(body)} 字，超过{platform}上限 {limit[1]} 字，请删减到 {limit[0]}-{limit[1]} 字")
        return out

    # ------------------------------------------------------------------ 修改与重新生成
    def revise(self, prev: dict, instruction: str, new_platform: str | None = None,
               progress=lambda s: None, draft_progress=None) -> dict:
        """功能7：根据临时要求重新生成（删减/换渠道/替换卖点）。复用已检索的资料，不改动事实边界。"""
        last = prev.get("_ctx")
        if not last:
            return {"status": "error", "message": "没有可修改的上一版结果，请先生成"}
        t_start = time.time()
        steps = []

        def step(stage, detail=""):
            name = next(item["label"] for item in WORKFLOW_STAGES if item["id"] == stage)
            steps.append({"step": name, "detail": detail, "at_sec": round(time.time() - t_start, 1)})
            progress({"stage": stage, "label": name, "detail": detail,
                      "elapsed_sec": round(time.time() - t_start, 1)})

        scene = dict(last["scene"])
        platform, strat, ret = last["platform"], last["strat"], last["ret"]
        flags = compliance.check_user_request(instruction)
        res = {"status": "ok", "steps": steps, "scene": scene, "model": ret.model.name,
               "evidence": prev.get("evidence"), "retrieval_trace": prev.get("retrieval_trace"),
               "retrieval_notes": prev.get("retrieval_notes"), "strategy": strat}
        try:
            step("understand", "解析修改要求，检查人群、使用场景和购买阶段是否变化")
            update_user = (f"上一版场景信息：\n{_j(scene)}\n\n"
                           f"本次修改要求：\n{instruction}")
            update = self.llm.json(prompts.CORE_SYSTEM + prompts.SCENE_REVISION_TASK, update_user,
                                   5000, STEP_EFFORT["scene"], "改稿场景解析")
            updated_scene = update.get("updated_scene") or {}
            allowed_fields = {"audience", "scenario_type", "usage_scene", "purchase_stage",
                              "main_problem", "content_goal", "extra_requests"}
            requested_fields = set(update.get("changed_fields") or []) & allowed_fields
            changed_fields = set()
            for field_name in requested_fields:
                if field_name in updated_scene:
                    scene[field_name] = updated_scene[field_name]
                    changed_fields.add(field_name)

            # 已知业务场景被明确点名时，以明确的用户指令兜底模型漏判。
            scenario_markers = ("改成", "改为", "换成", "转成", "调整到", "调整为",
                                "切换成", "切换到", "场景改")
            if any(marker in instruction for marker in scenario_markers):
                explicit_scenarios = [name for name in SCENARIOS if name in instruction]
                if len(explicit_scenarios) == 1 and scene.get("scenario_type") != explicit_scenarios[0]:
                    scene["scenario_type"] = explicit_scenarios[0]
                    changed_fields.add("scenario_type")

            questions = update.get("needs_clarification") or []
            scene_intent_cues = (
                "场景", "人群", "受众", "目标客户", "目标人群", "购买阶段", "用户问题", "主要问题",
                "大学生", "职场", "差旅", "出差", "家庭用户", "创作者", "企业采购", "到店体验", "送礼",
            )
            if not questions and not changed_fields and any(cue in instruction for cue in scene_intent_cues):
                questions = ["请补充希望更换到的目标人群、业务场景或具体使用场景。"]
            if questions:
                res.update(status="need_info", questions=[{"field": "scenario", "question": q, "options": []}
                                                            for q in questions])
                return res

            platform_changed = bool(new_platform and new_platform != platform)
            if platform_changed:
                platform = new_platform
            scene["platform"] = platform
            scene["product_text"] = ret.model.name
            scene_changed = bool(changed_fields & {
                "audience", "scenario_type", "usage_scene", "purchase_stage", "main_problem", "content_goal"
            })

            if scene_changed:
                step("strategy", "场景已更新，按新场景重新检索资料并规划卖点")
                model, _ = resolve_model(ret.model.name)
                keywords = SCENE_KEYWORDS.get(scene.get("scenario_type", ""), ["适用人群"])
                ret = retrieve(self.ima, model, keywords)
                if not ret.docs:
                    res.update(status="no_evidence", scene=scene,
                               message="新场景下没有检索到可用的产品资料，已停止改稿，避免沿用旧场景卖点。")
                    return res
                strat = self._strategy(scene, platform, ret)
                if strat.get("conflicts"):
                    res.update(status="conflict", scene=scene, strategy=strat,
                               message="新场景检索到的资料存在冲突，已停止输出，请人工确认：" + "；".join(
                                   c.get("description", "") for c in strat["conflicts"]))
                    return res
            else:
                step("strategy", f"场景未改变，沿用{platform}规则和已核验的卖点策略")

            step("layout", "按更新后的场景或平台规则重新筛选配图"
                 if scene_changed or platform_changed else "场景与平台未改变，沿用上一版配图")
            if scene_changed or platform_changed:
                images = self._pick_images(scene, platform, strat, ret)
            else:
                images = prev.get("images", [])

            res.update(scene=scene, model=ret.model.name, platform=platform,
                       evidence=[{"id": f"D{i+1}", "title": doc.title, "path": doc.path}
                                 for i, doc in enumerate(ret.docs)],
                       retrieval_trace=ret.trace, retrieval_notes=ret.notes, strategy=strat)
            res.update(images=images)
            task = prompts.WRITE_TASK.replace("@@PLATFORM@@", platform)
            user = (f"场景判断：\n{_j(scene)}\n\n{describe(platform)}\n策略与事实点：\n{_j(strat)}\n\n"
                    f"配图方案：\n{_j(images)}\n\n上一版稿件(供参考，可大改)：\n{_j(prev.get('draft', {}))}\n\n"
                    f"用户的修改要求：{instruction}\n{self._boundary_text(flags)}")
            step("write", "根据修改要求重新组织文案")
            max_tokens = MAX_OUTPUT_TOKENS if platform == "B站中长视频" else 16000
            parser = DraftPreviewStream(draft_progress) if draft_progress else None
            if parser:
                parser.reset()
                draft = self.llm.json(prompts.CORE_SYSTEM + task, user, max_tokens, STEP_EFFORT["write"], "改稿",
                                     on_delta=parser.feed, on_reset=parser.reset)
            else:
                draft = self.llm.json(prompts.CORE_SYSTEM + task, user, max_tokens, STEP_EFFORT["write"], "改稿")
            draft["images"] = images
            step("verify", "重新核对事实、型号、配图和合规规则")
            draft, verify, comp, rounds = self._verify_and_fix(
                scene, platform, strat, ret, images, draft, flags, draft_progress=draft_progress)
            res.update(draft=draft, verify=verify, compliance=comp, publish_ready=verify.get("publish_ready", False),
                       fix_rounds=rounds,
                       refusals=self._refusals(flags), facts_used=self._facts_used(strat, draft),
                       user_request_flags=flags, usage=dict(self.llm.usage), ima_calls=list(self.ima.calls))
            res["_ctx"] = {**last, "scene": scene, "platform": platform, "strat": strat, "ret": ret}
            step("finish", "加载配图并整理可下载的结果")
            res["total_sec"] = round(time.time() - t_start, 1)
            res["timings"] = list(self.llm.timings)
            self.attach_images(res)
            return res
        except (LLMError, ImaError) as e:
            return {"status": "error", "message": str(e), "steps": steps}


def _norm_m(s: str) -> str:
    return s.replace("HUAWEI", "").replace("（", "(").replace("）", ")").replace(" ", "").lower()


# 系列名与图片索引里「产品型号」写法不一致的型号，显式列出（来自知识库真实索引）
INDEX_ALIASES: dict[str, tuple[str, ...]] = {
    "HUAWEI MateBook 14（鸿蒙版）": ("MateBook 14", "MateBook 14（鸿蒙版）"),
    "MateBook GT 系列": ("HUAWEI MateBook GT 14",),
    "MateBook X 系列": ("HUAWEI MateBook X Pro 酷睿 Ultra 微绒典藏版",),
}


def _same_model(index_model: str, m: Model) -> bool:
    """图片索引里的「产品型号」是否就是目标型号。

    规则：归一化后完全相等，或「目标名 + 年份后缀」(如 D 16 → D 16 2024)。
    Pro 与 Pro S、D 16 与 D 16 SE 版互不相等，也不互为前缀+年份，因此不会混用。
    """
    a = _norm_m(index_model)
    if not a:
        return False
    names = {_norm_m(m.name), _norm_m(m.folder)}
    # 鸿蒙版 14 在索引里可能写作 "MateBook 14" / "MateBook 14 HarmonyOS"
    names |= {_norm_m(x) for x in INDEX_ALIASES.get(m.name, ())}
    for n in names:
        if a == n:
            return True
        if a.startswith(n):
            rest = a[len(n):]
            if rest.isdigit() and len(rest) == 4:          # 年份后缀
                return True
    return False


def _model_options() -> list[str]:
    from .catalog import model_names
    return model_names()


def _strip_sentences(draft: dict, bad: list[str]) -> dict:
    def clean(t: str) -> str:
        for b in bad:
            t = t.replace(b, "")
        return t.strip()

    d = json.loads(json.dumps(draft))
    d["titles"] = [t for t in (clean(x) for x in d.get("titles", [])) if t]
    d["lead"] = clean(d.get("lead") or "")
    for s in d.get("sections") or []:
        s["text"] = clean(s.get("text") or "")
        s["heading"] = clean(s.get("heading") or "")
    d["sections"] = [s for s in d.get("sections") or [] if s["text"] or s["heading"]]
    d["cta"] = clean(d.get("cta") or "") or "欢迎到店实际体验，详情以门店为准。"
    return d
