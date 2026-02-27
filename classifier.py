import os
import json
import time
from openai import OpenAI
from config import build_classify_prompt, POOL_NAMES


class ClassifyResult:
    def __init__(
        self,
        category: str,
        next_action: str,
        reasoning: str,
        short_title: str = "",
        summary: str = "",
    ):
        self.category = category
        self.next_action = next_action
        self.reasoning = reasoning
        self.short_title = short_title
        self.summary = summary

    def __repr__(self):
        return (
            f"ClassifyResult(category={self.category!r}, "
            f"short_title={self.short_title!r}, "
            f"next_action={self.next_action!r})"
        )


class IdeaClassifier:
    def __init__(self):
        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            raise ValueError("环境变量 OPENAI_API_KEY 未设置")

        # 支持 OpenRouter：设置 OPENAI_BASE_URL=https://openrouter.ai/api/v1 即可
        base_url = os.environ.get("OPENAI_BASE_URL")
        client_kwargs = {"api_key": api_key}
        if base_url:
            client_kwargs["base_url"] = base_url

        self.client = OpenAI(**client_kwargs)
        self.model = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")

    def classify(self, title: str, desc: str, retries: int = 3) -> ClassifyResult:
        """
        调用 LLM 对单条想法进行分类，失败自动重试（最多 retries 次）。
        若 LLM 返回无法解析，抛出 ValueError。
        """
        prompt = build_classify_prompt(title, desc)
        data: dict = {}

        for attempt in range(1, retries + 1):
            try:
                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.2,
                    response_format={"type": "json_object"},
                    max_tokens=512,
                )

                raw = response.choices[0].message.content
                if not raw or not raw.strip():
                    raise ValueError(f"LLM 返回空响应（finish_reason={response.choices[0].finish_reason!r}）")

                data = json.loads(raw)
                break  # 成功，跳出重试循环

            except (ValueError, json.JSONDecodeError) as e:
                if attempt < retries:
                    time.sleep(2 ** attempt)  # 指数退避：2s、4s
                else:
                    raise ValueError(f"分类失败（重试 {retries} 次）：{e}") from e

        # 校验必要字段
        category = data.get("category", "").strip()
        if category not in POOL_NAMES:
            # 宽松处理：尝试找最接近的池子名
            category = self._fuzzy_match_pool(category)

        next_action = data.get("next_action", "").strip() or "待补充"
        reasoning = data.get("reasoning", "").strip()
        short_title = data.get("short_title", "").strip()
        summary = data.get("summary", "").strip()

        return ClassifyResult(
            category=category,
            next_action=next_action,
            reasoning=reasoning,
            short_title=short_title,
            summary=summary,
        )

    @staticmethod
    def _fuzzy_match_pool(raw: str) -> str:
        """当 LLM 返回非标准池子名时，尝试模糊匹配"""
        raw_lower = raw.lower()
        mapping = {
            "dev": "Dev", "develop": "Dev", "开发": "Dev",
            "deep": "Deep", "研究": "Deep", "钻研": "Deep",
            "wild": "Wild", "想法": "Wild", "脑洞": "Wild",
            "meta": "Meta", "反思": "Meta", "元": "Meta",
            "other": "Other", "其他": "Other",
        }
        for key, pool in mapping.items():
            if key in raw_lower:
                return pool
        return "Other"  # 兜底
