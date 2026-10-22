"""Claude 调用封装：流式、重试、JSON 解析、拒答处理、用量与耗时统计（线程安全，可并行调用）。"""
import json
import re
import threading
import time

import anthropic
import httpx2

from .config import EFFORT, MAX_OUTPUT_TOKENS, MODEL


class LLMError(Exception):
    pass


class LLMRefusal(LLMError):
    pass


def extract_json(text: str):
    """从模型输出中取出第一个完整 JSON 对象（容忍代码围栏和前后说明）。"""
    t = text.strip()
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", t, flags=re.S)
    start = min([i for i in (t.find("{"), t.find("[")) if i >= 0], default=-1)
    if start < 0:
        raise ValueError("输出里没有 JSON")
    decoder = json.JSONDecoder()
    obj, _ = decoder.raw_decode(t[start:])
    return obj


JSON_SUFFIX = "\n\n【输出格式】只输出一个合法 JSON，不要任何解释，不要代码围栏。"


class LLM:
    def __init__(self, model: str = MODEL, effort: str = EFFORT):
        # Accept-Encoding=identity：规避部分环境下解压缩报错（已实测）
        self.client = anthropic.Anthropic(
            max_retries=3, timeout=600.0,
            default_headers={"Accept-Encoding": "identity"},
        )
        self.model = model
        self.effort = effort
        self.usage = {"calls": 0, "input_tokens": 0, "output_tokens": 0}
        self.timings: list[dict] = []          # 每次调用：步骤名、耗时、token
        self._lock = threading.Lock()

    def _once(self, system: str, user: str, max_tokens: int, stream: bool, effort: str,
              on_delta=None):
        kw = dict(model=self.model, max_tokens=max_tokens, system=system,
                  output_config={"effort": effort},
                  messages=[{"role": "user", "content": user}])
        if stream:
            with self.client.messages.stream(**kw) as st:
                if on_delta:
                    for delta in st.text_stream:
                        on_delta(delta)
                return st.get_final_message()
        return self.client.messages.create(**kw)

    def text(self, system: str, user: str, max_tokens: int = 16000,
             effort: str | None = None, label: str = "", on_delta=None, on_reset=None) -> str:
        effort = effort or self.effort
        t0 = time.time()
        # 中转服务偶发在流式输出中途断开：前两次走流式，之后降级为非流式
        transient = (anthropic.APIConnectionError, anthropic.RateLimitError,
                     anthropic.InternalServerError, httpx2.TransportError)
        last, msg = None, None
        successful_stream = False
        for attempt in range(4):
            try:
                if attempt and on_reset:
                    on_reset()
                successful_stream = attempt < 2
                msg = self._once(system, user, min(max_tokens, MAX_OUTPUT_TOKENS),
                                 stream=attempt < 2, effort=effort,
                                 on_delta=on_delta if attempt < 2 else None)
                break
            except transient as e:
                last = e
                time.sleep(2 * (attempt + 1))
        if msg is None:
            raise LLMError(f"Claude 调用失败：{type(last).__name__}")
        with self._lock:
            self.usage["calls"] += 1
            self.usage["input_tokens"] += msg.usage.input_tokens
            self.usage["output_tokens"] += msg.usage.output_tokens
            self.timings.append({"label": label, "effort": effort, "sec": round(time.time() - t0, 1),
                                 "in": msg.usage.input_tokens, "out": msg.usage.output_tokens})
        if msg.stop_reason == "refusal":
            raise LLMRefusal("模型出于安全策略拒绝了该请求")
        if msg.stop_reason == "max_tokens":
            raise LLMError("输出被截断（max_tokens），请缩短输入")
        text = "".join(b.text for b in msg.content if b.type == "text")
        if on_delta and not successful_stream:
            # Attempts 2-3 fall back to non-streaming calls; reveal their response in
            # small chunks during writing, before verification begins.
            for offset in range(0, len(text), 48):
                on_delta(text[offset:offset + 48])
                time.sleep(0.012)
        return text

    def json(self, system: str, user: str, max_tokens: int = 16000,
             effort: str | None = None, label: str = "", on_delta=None, on_reset=None):
        """要求模型只输出 JSON；解析失败时带着错误重试一次。"""
        sys_j = system + JSON_SUFFIX
        out = self.text(sys_j, user, max_tokens, effort, label, on_delta, on_reset)
        try:
            return extract_json(out)
        except ValueError as e:
            if on_reset:
                on_reset()
            retry = user + f"\n\n（上一次输出无法解析为 JSON：{e}。请只输出合法 JSON。）"
            return extract_json(self.text(sys_j, retry, max_tokens, effort, label + "(重试)", on_delta, on_reset))
