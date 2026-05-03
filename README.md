# idea-pool

从滴答清单的「想法池」列表中自动拉取待处理条目，使用 LLM 进行分类，并将结果同步回 Notion 想法池数据库。

## 工作流

```
滴答清单「想法池」(via Notion 同步库)
        ↓  拉取未处理条目
    LLM 分类（Dev / Deep / Wild / Meta / Other）
        ↓  生成：分类、简短标题、摘要、下一步行动
  回写来源条目（标记完成，归档滴答清单）
        ↓
  写入 Notion 想法池数据库（结构化归档）
```

## 快速开始

```bash
# 安装依赖
pip install -r requirements.txt

# 配置环境变量
cp .env.example .env   # 按注释填写各项 ID 和 Key

# 运行
python3 run.py
```

## 文件结构

| 文件 | 用途 |
|------|------|
| `run.py` | 主入口，串联全流程 |
| `classifier.py` | 调用 LLM 对单条想法分类，返回 `ClassifyResult` |
| `notion_helper.py` | Notion API 封装：拉取条目、回写分类、同步到想法池 |
| `config.py` | 池子定义、few-shot 示例、Prompt 构建、Notion 字段名映射 |
| `requirements.txt` | Python 依赖 |
| `.env` | 本地配置（不提交） |

## 命令行参数

```
python3 run.py                # 正常运行，全自动处理并写回 Notion
python3 run.py --dry-run      # 只打印分类结果，不修改 Notion
python3 run.py --limit 10     # 最多处理 10 条（默认 50）
python3 run.py --no-complete  # 分类后不在来源库打勾（不归档滴答清单）
```

## 池子定义

| 池子 | 标签 | 收录内容 |
|------|------|----------|
| **Dev** | 开发/工作流 | 需要写代码或配置才能落地的任务、工具链搭建 |
| **Deep** | 硬核钻研 | 底层原理、论文精读、需要大块专注时间的知识 |
| **Wild** | 发散设想 | 未经实证的产品想法、跨领域脑洞、社会观察 |
| **Meta** | 元认知/反思 | 工作方式反思、心态建设、需沉淀为原则的感悟 |
| **Other** | 其他 | 信息不足或确实不属于以上类别的条目 |

## .env 配置说明

```ini
NOTION_TOKEN=...               # Notion Integration Token
NOTION_DATABASE_ID=...         # 来源：滴答清单「想法池」的 Notion 同步库 ID
                               # 支持填页面 ID，脚本会自动定位其中的子数据库
NOTION_POOL_DATABASE_ID=...    # 目标：Notion 想法池数据库 ID

OPENAI_API_KEY=...             # OpenAI 或 OpenRouter 的 API Key
OPENAI_BASE_URL=...            # 使用 OpenRouter 时填写（可选）
OPENAI_MODEL=...               # 模型名，如 deepseek/deepseek-v3.2
```

---

Last updated: 2026-05-03
