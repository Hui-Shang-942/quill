"""全局配置。凭证只从环境变量或 ~/.config/ima/ 读取，绝不写进代码。"""
import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env", override=True)

IMA_SCRIPT = ROOT / "agent" / "ima_api.cjs"
CACHE_DIR = ROOT / ".cache"          # 已在 .gitignore 中；缓存知识库内容，禁止提交
OUTPUT_DIR = ROOT / "outputs"

KB_NAME = os.environ.get("IMA_KB_NAME", "任德耀新建华为PC知识库")
MODEL = os.environ.get("COPYWRITER_MODEL", "deepseek-flash")
EFFORT = os.environ.get("COPYWRITER_EFFORT", "medium")   # 默认档位：low | medium | high
# DeepSeek Flash 的单次输出上限；切换模型服务时可通过环境变量调整。
MAX_OUTPUT_TOKENS = int(os.environ.get("COPYWRITER_MAX_OUTPUT_TOKENS", "393216"))
# 分步 effort：简单的结构化任务用 low（快），写作用 medium（质量），核验用 medium（不能放松）
STEP_EFFORT = {
    "scene": "low",        # 场景解析：抽取字段
    "strategy": "medium",  # 事实点提取+卖点策略
    "images": "low",       # 选图：从候选里挑
    "write": "medium",     # 软文写作
    "verify": "medium",    # 事实核验
    "compliance": "low",   # 合规复查（规则层已做硬拦截）
    "revise": "medium",
}

COMPETITION_PLATFORMS = ["公众号", "小红书", "微信朋友圈", "门店海报"]
SUPPORTED_PLATFORMS = COMPETITION_PLATFORMS + [
    "B站中长视频", "企业采购方案", "微信视频号", "微博图文", "抖音短视频",
    "新闻稿图文", "直播讲解", "知乎图文", "短视频口播图文",
]
MAX_DOC_CHARS = 60000        # 单份资料最多读取的字符数
MAX_IMAGE_BYTES = 8 * 1024 * 1024
