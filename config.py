import os
import json

# ──────────────────────────────────────────────
# 池子定义
# ──────────────────────────────────────────────
POOLS = {
    "Dev": {
        "label": "开发/工作流",
        "definition": (
            "涉及 Pipeline 搭建、脚本优化、代码库上下文管理、工具链打通。"
            "需要写代码或具体配置才能落地的任务。"
        ),
    },
    "Deep": {
        "label": "硬核钻研",
        "definition": (
            "底层原理、数学性质、论文精读、需要大块专注时间才能消化的知识。"
            "典型特征：需要阅读文献或做实验。"
        ),
    },
    "Wild": {
        "label": "发散设想",
        "definition": (
            "尚未实证的产品想法、社会观察、跨领域脑洞。"
            "不需要立即执行，但值得记录和等待时机。"
        ),
    },
    "Meta": {
        "label": "元认知/反思",
        "definition": (
            "关于如何做事的反思、工作流 trade-off、心态建设、个人原则提炼。"
            "通常以感悟/问句形式出现，答案需要沉淀为原则而非任务。"
        ),
    },
    "Other": {
        "label": "其他",
        "definition": (
            "信息不足以判断分类，或确实不属于以上任何类别的条目。"
        ),
    },
}

POOL_NAMES = list(POOLS.keys())

# ──────────────────────────────────────────────
# Few-shot 示例（来自手动标注的历史条目）
# ──────────────────────────────────────────────
FEW_SHOT_EXAMPLES = [
    {
        "title": "thought: 一个小pipeline的搭建流程",
        "desc": "naive的想法: 刷课机用动态ip, 刷到了可以通知我。咨询ai并browse自己的工具/经历库: 新工具webshare买动态ip代理，用ai尝试拼接pipeline。",
        "category": "Dev",
        "next_action": "用 webshare + bark 搭建选课通知 MVP",
        "reasoning": "核心是拼接工具链搭建自动化 pipeline，需要写代码实现",
    },
    {
        "title": "naive thought: 有一个重复性的问题",
        "desc": "cursor等agent有没有固定化存储的记忆，这样每次可以通过@记忆模块获取上下文",
        "category": "Dev",
        "next_action": "在项目根目录创建 CONTEXT.md 并配置 .cursorrules",
        "reasoning": "需要具体的文件配置和脚本实现，属于工作流工具化",
    },
    {
        "title": "question: 上下文的膨胀",
        "desc": "如何减少重建上下文的浪费，如何让自己及时吸收流水般的分析输出",
        "category": "Meta",
        "next_action": "提炼原则: 每次对话结束输出100字 context snapshot",
        "reasoning": "本质是对信息处理方式的反思，答案是原则而非代码任务",
    },
    {
        "title": "wild thinking: 人与人之间的交流",
        "desc": "如果可以将自己这一天的事情记录下来，让其它用户的 agent 读取，这样别人发消息时都有 context",
        "category": "Wild",
        "next_action": "存档: 待 LLM Agent 社交形态成熟后重新评估",
        "reasoning": "产品脑洞，目前无法实证，记录即可",
    },
    {
        "title": "thinking(感悟): 没有 solid 的落地, 再宏大美好的想法都是狗屁",
        "desc": "",
        "category": "Meta",
        "next_action": "沉淀为原则: 每个想法必须有一个最小可行动作",
        "reasoning": "纯感悟，需要内化为原则，不是执行任务",
    },
    {
        "title": "想法池: 寻找更适合嵌入脚本/开发的浏览器工具",
        "desc": "",
        "category": "Dev",
        "next_action": "调研 Playwright / Puppeteer，列出选型对比",
        "reasoning": "寻找开发工具，属于工具链搭建范畴",
    },
]


# ──────────────────────────────────────────────
# Prompt 构建
# ──────────────────────────────────────────────
def build_classify_prompt(title: str, desc: str) -> str:
    pool_defs = "\n".join(
        f"- {k}（{v['label']}）：{v['definition']}"
        for k, v in POOLS.items()
    )

    few_shots = ""
    for ex in FEW_SHOT_EXAMPLES:
        answer = json.dumps(
            {
                "category": ex["category"],
                "next_action": ex["next_action"],
                "reasoning": ex["reasoning"],
            },
            ensure_ascii=False,
        )
        few_shots += (
            f"\n标题: {ex['title']}\n"
            f"描述: {ex['desc'] or '（无）'}\n"
            f"输出: {answer}\n"
        )

    return f"""你是一个个人知识管理助手，帮助用户将零散想法分类到思想池中。

[池子定义]
{pool_defs}

[参考示例]
{few_shots}
[待分类条目]
标题: {title}
描述: {desc or '（无描述）'}

[输出要求]
严格输出以下 JSON 格式，不含任何其他内容:
{{
  "category": "{'" | "'.join(POOL_NAMES)}中的一个",
  "short_title": "≤15字的简短标题，像一个话题词，准确概括这个想法的核心（例：微信群聊工作流、RDMA内存连续性）",
  "summary": "2-3句话精炼摘要：这个想法是什么、为什么值得关注、核心洞察是什么",
  "next_action": "动词开头，≤30字，具体可执行的下一步行动",
  "reasoning": "一句话说明分类理由"
}}"""


# ──────────────────────────────────────────────
# Notion 字段名映射（与你的数据库保持一致）
# ──────────────────────────────────────────────
NOTION_FIELDS = {
    "title":        "名称",
    "description":  "描述",
    "done":         "完成",
    "tags":         "标签",
    "date":         "日期",
    "priority":     "优先级",
    "link":         "前往滴答清单",
    # 新增字段（需在 Notion 中手动创建后才能更新）
    "pool":         "池子",
    "next_action":  "下一步行动",
    "status":       "处理状态",
}
