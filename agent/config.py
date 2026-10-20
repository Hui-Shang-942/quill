"""全局配置。凭证只从环境变量或 ~/.config/ima/ 读取，绝不写进代码。"""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
IMA_SCRIPT = ROOT / "vendor" / "ima-skill" / "ima_api.cjs"
CACHE_DIR = ROOT / ".cache"          # 已在 .gitignore 中；缓存知识库内容，禁止提交
OUTPUT_DIR = ROOT / "outputs"

KB_NAME = os.environ.get("IMA_KB_NAME", "任德耀新建华为PC知识库")
MODEL = os.environ.get("COPYWRITER_MODEL", "claude-opus-5-5")
EFFORT = os.environ.get("COPYWRITER_EFFORT", "medium")   # 默认档位：low | medium | high
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

SUPPORTED_PLATFORMS = ["公众号", "小红书", "门店朋友圈", "门店海报"]
MAX_DOC_CHARS = 60000        # 单份资料最多读取的字符数
MAX_IMAGE_BYTES = 8 * 1024 * 1024
