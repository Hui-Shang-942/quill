"""平台规则表：结构、语气、篇幅、图片数量、行动引导全部随平台变化（不是只改字数）。
代码侧用它做硬约束（图片数量、必填字段），提示词侧用它描述写法。"""

PLATFORMS: dict[str, dict] = {
    "公众号": {
        "reader_action": "连续阅读、收藏、转发",
        "image_range": (2, 4),
        "length": "1200-2000 字",
        "structure": "标题 → 导语(80-120字，抛出读者的真实问题) → 3-4个带小标题的段落(场景问题—判断逻辑—事实证据—版本边界) → 结尾行动引导",
        "tone": "沉稳、专业、有温度；像一位懂产品的朋友在讲道理；可以有适度的小标题和过渡句",
        "title_rule": "20-30字，点出人群+问题，不用感叹号堆叠；给出3个备选",
        "cta": "引导阅读者到店体验、预约咨询或查看官方页面；不制造紧迫感",
        "tags": False,
        "first_person_experience": False,
        "need_sections": True,
    },
    "小红书": {
        "reader_action": "快速翻页、收藏、评论",
        "image_range": (3, 6),
        "length": "正文 300-800 字",
        "structure": "封面承诺(一个结果或冲突) → 问题卡 → 证据卡(每段解决一个问题) → 适合/不适合 → 核对清单 → 评论区提问",
        "tone": "口语化、短段落、一段不超过3句、可适量使用表情符号；轻松但不浮夸",
        "title_rule": "不超过20字，口语化，不堆感叹号和空泛形容词；给出3个备选",
        "cta": "引导收藏、评论区提问或到店实际体验；不写“私信我领优惠”这类无依据的承诺",
        "tags": True,
        "first_person_experience": False,     # 不得伪造个人使用体验
        "need_sections": True,
    },
    "门店朋友圈": {
        "reader_action": "快速浏览、私聊咨询",
        "image_range": (1, 3),
        "length": "60-140 字",
        "structure": "一个人群 + 一个阻碍 + 一个核心卖点(最多两条事实) + 一个行动",
        "tone": "门店导购的口吻，像真实的熟人沟通；短句；不堆参数",
        "title_rule": "无标题；第一句即钩子，不超过25字",
        "cta": "明确一个动作：到店体验或微信咨询，二选一",
        "tags": False,
        "first_person_experience": False,
        "need_sections": False,
    },
    "门店海报": {
        "reader_action": "远距离扫读、到店核验",
        "image_range": (1, 1),
        "length": "总文字不超过 60 字",
        "structure": "主标题(≤12字) → 副标题(≤20字) → 不超过3个卖点(每条≤15字) → 活动说明(无依据时写“详情以门店为准”) → 到店动作",
        "tone": "极简、可远距离阅读；一个视觉焦点",
        "title_rule": "主标题≤12字，副标题≤20字",
        "cta": "到店体验 / 扫码咨询",
        "tags": False,
        "first_person_experience": False,
        "need_sections": False,
    },
}

SCENARIOS = {
    "开学季": "大学新生、家长：学习、携带、续航、多设备协同；不要把所有学生需求归结为单一性能指标",
    "职场办公": "商务人士、移动办公者：会议、差旅、文档处理、多任务协同、安全需求",
    "内容创作": "设计、摄影、视频创作者：屏幕、性能、素材流转、创作流程；不得虚构软件测试结果",
    "家庭换新": "家庭用户、旧机换新者：易用性、全家使用、数据迁移、长期使用体验",
    "企业采购": "中小企业、团队采购：部署、管理、稳定性、服务信息；知识库未出现的政策不得承诺",
    "门店到访": "附近潜在顾客：一个明确卖点、到店体验理由、咨询引导；避免信息堆叠",
    "新品首发": "关注新品的用户：新品变化、适合人群、购买建议；价格与权益必须有资料依据",
    "节日营销": "送礼、家庭购机：使用场景和选择建议；不得虚构优惠、补贴或库存",
}


def clamp_images(platform: str, n: int) -> int:
    lo, hi = PLATFORMS[platform]["image_range"]
    return max(lo, min(hi, n))


def describe(platform: str) -> str:
    r = PLATFORMS[platform]
    lo, hi = r["image_range"]
    return (
        f"平台：{platform}\n- 读者动作：{r['reader_action']}\n- 篇幅：{r['length']}\n"
        f"- 结构：{r['structure']}\n- 语气：{r['tone']}\n- 标题：{r['title_rule']}\n"
        f"- 配图数量：{lo}-{hi} 张\n- 行动引导：{r['cta']}\n"
        f"- 话题标签：{'需要，5-8个' if r['tags'] else '不需要'}\n"
        + ("- 禁止第一人称使用体验（如“我用了三个月”）；可用第二人称或“以…为例”的场景化写法\n"
           if not r["first_person_experience"] else "")
    )
