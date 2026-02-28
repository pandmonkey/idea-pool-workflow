import os
from typing import Optional

from notion_client import Client
from notion_client.errors import APIResponseError
from config import NOTION_FIELDS


class NotionIdeaDB:
    def __init__(self):
        token = os.environ.get("NOTION_TOKEN")
        self.db_id = os.environ.get("NOTION_DATABASE_ID")
        if not token:
            raise ValueError("环境变量 NOTION_TOKEN 未设置")
        if not self.db_id:
            raise ValueError("环境变量 NOTION_DATABASE_ID 未设置")
        self.client = Client(auth=token)
        self._available_fields = None  # 缓存字段信息
        self.db_id = self._resolve_db_id(self.db_id)

    def _resolve_db_id(self, raw_id: str) -> str:
        """
        如果 raw_id 是页面而非数据库，自动查找该页面下第一个子数据库并返回其 ID。
        """
        try:
            self.client.databases.retrieve(database_id=raw_id)
            return raw_id  # 本身就是数据库，直接返回
        except APIResponseError as e:
            if "is a page" not in str(e):
                raise
        # 是页面：遍历子块找第一个 child_database
        try:
            children = self.client.blocks.children.list(block_id=raw_id)
            for block in children.get("results", []):
                if block.get("type") == "child_database":
                    db_id = block["id"]
                    print(f"  ℹ️  检测到页面 ID，自动定位到子数据库：{db_id}")
                    return db_id
        except Exception:
            pass
        raise ValueError(
            f"ID {raw_id!r} 是一个页面，且其中找不到子数据库。"
            "请在 .env 中直接填写数据库的 ID（在 Notion 数据库页面的 URL 中获取）。"
        )

    # ──────────────────────────────────────────────
    # 查询
    # ──────────────────────────────────────────────

    def fetch_unprocessed(self, limit: int = 50) -> list[dict]:
        """
        拉取需要处理的条目。
        方案 A：按"处理状态 == 未处理"过滤（字段存在时）
        方案 B：按"完成 == False"过滤（字段存在时）
        方案 C：兜底，拉取全部条目（适用于字段极简的滴答清单同步库）
        """
        status_field = NOTION_FIELDS["status"]
        done_field = NOTION_FIELDS["done"]

        # 方案 A：按处理状态过滤
        if self._field_exists(status_field):
            try:
                resp = self.client.databases.query(
                    database_id=self.db_id,
                    filter={
                        "property": status_field,
                        "select": {"equals": "未处理"},
                    },
                    page_size=limit,
                )
                return resp.get("results", [])
            except APIResponseError:
                pass

        # 方案 B：按完成状态过滤
        if self._field_exists(done_field):
            try:
                resp = self.client.databases.query(
                    database_id=self.db_id,
                    filter={
                        "property": done_field,
                        "checkbox": {"equals": False},
                    },
                    page_size=limit,
                )
                return resp.get("results", [])
            except APIResponseError:
                pass

        # 方案 C：直接拉取全部（兜底）
        resp = self.client.databases.query(
            database_id=self.db_id,
            page_size=limit,
        )
        return resp.get("results", [])

    def _get_database_schema(self) -> dict:
        db = self.client.databases.retrieve(database_id=self.db_id)
        return db.get("properties", {})

    # ──────────────────────────────────────────────
    # 更新
    # ──────────────────────────────────────────────

    def update_classification(
        self,
        page_id: str,
        category: str,
        next_action: str,
        mark_complete: bool = True,
    ) -> dict:
        """
        将分类结果回写 Notion。
        - 若新字段（池子/下一步行动/处理状态）存在则更新，不存在则跳过
        - mark_complete=True 时把"完成"打勾，触发滴答清单归档
        返回更新后的 page 对象。
        """
        print(f"  🔍 [DEBUG] 开始更新分类，页面 ID: {page_id[:8]}...")
        props = {}
        schema = self._get_cached_schema()

        # --- 池子（Select 类型）---
        pool_field = NOTION_FIELDS["pool"]
        if pool_field in schema:
            props[pool_field] = {"select": {"name": category}}
            print(f"  🔍 [DEBUG] 字段 '{pool_field}' 存在，设置为: {category}")
        else:
            print(f"  ⚠️  [DEBUG] 字段 '{pool_field}' 不存在，跳过")

        # --- 下一步行动（Rich Text 类型）---
        action_field = NOTION_FIELDS["next_action"]
        if action_field in schema:
            props[action_field] = {
                "rich_text": [{"text": {"content": next_action}}]
            }
            print(f"  🔍 [DEBUG] 字段 '{action_field}' 存在")
        else:
            print(f"  ⚠️  [DEBUG] 字段 '{action_field}' 不存在，跳过")

        # --- 处理状态（Select 类型）---
        status_field = NOTION_FIELDS["status"]
        if status_field in schema:
            props[status_field] = {"select": {"name": "已分类"}}
            print(f"  🔍 [DEBUG] 字段 '{status_field}' 存在，设置为: 已分类")
        else:
            print(f"  ⚠️  [DEBUG] 字段 '{status_field}' 不存在，跳过")

        # --- 完成（Checkbox）→ 触发滴答清单归档 ---
        done_field = NOTION_FIELDS["done"]
        if mark_complete and done_field in schema:
            props[done_field] = {"checkbox": True}
            print(f"  🔍 [DEBUG] 字段 '{done_field}' 存在，标记为完成")
        else:
            print(f"  ⚠️  [DEBUG] 字段 '{done_field}' {'不存在' if done_field not in schema else '跳过（未标记完成）'}")

        if not props:
            print(f"  ⚠️  [DEBUG] 没有可更新的属性，跳过")
            return {}

        print(f"  🔍 [DEBUG] 准备更新 {len(props)} 个属性")
        try:
            result = self.client.pages.update(page_id=page_id, properties=props)
            print(f"  ✅ [DEBUG] 更新成功")
            return result
        except APIResponseError as e:
            print(f"  ❌ [DEBUG] Notion API 错误: {e}")
            raise
        except Exception as e:
            print(f"  ❌ [DEBUG] 未知错误: {type(e).__name__}: {e}")
            raise

    # ──────────────────────────────────────────────
    # 字段提取辅助
    # ──────────────────────────────────────────────

    def extract_idea(self, page: dict) -> dict:
        """从 Notion page 对象中提取核心字段，返回干净的字典"""
        props = page.get("properties", {})
        page_id = page["id"]

        # 属性中的描述字段
        desc_prop = self._get_text(props, NOTION_FIELDS["description"])
        # 页面正文（支持多列布局自动拼接）
        body = self._extract_page_body(page_id)
        # 合并属性描述与正文
        desc = "\n\n".join(filter(None, [desc_prop, body]))

        return {
            "id": page_id,
            "url": page.get("url", ""),
            "title": self._get_title(props, NOTION_FIELDS["title"]),
            "desc": desc,
            "tags": self._get_multiselect(props, NOTION_FIELDS["tags"]),
        }

    def _extract_page_body(self, page_id: str) -> str:
        """获取页面正文块内容，column_list 各列拼接不丢失"""
        try:
            resp = self.client.blocks.children.list(block_id=page_id)
            return self._blocks_to_text(resp.get("results", []))
        except Exception:
            return ""

    def _blocks_to_text(self, blocks: list) -> str:
        """递归提取 blocks 纯文本；column_list 横向各列竖向拼接"""
        parts = []
        for block in blocks:
            btype = block.get("type", "")

            if btype == "column_list":
                try:
                    cols = self.client.blocks.children.list(block_id=block["id"])
                    for col in cols.get("results", []):
                        try:
                            col_children = self.client.blocks.children.list(block_id=col["id"])
                            col_text = self._blocks_to_text(col_children.get("results", []))
                            if col_text:
                                parts.append(col_text)
                        except Exception:
                            pass
                except Exception:
                    pass

            elif btype in (
                "paragraph", "heading_1", "heading_2", "heading_3",
                "bulleted_list_item", "numbered_list_item",
                "quote", "callout", "toggle",
            ):
                rich = block.get(btype, {}).get("rich_text", [])
                line = "".join(r.get("plain_text", "") for r in rich)
                if line:
                    parts.append(line)

            elif btype == "code":
                rich = block.get("code", {}).get("rich_text", [])
                line = "".join(r.get("plain_text", "") for r in rich)
                if line:
                    parts.append(f"```\n{line}\n```")

        return "\n".join(parts)

    # ──────────────────────────────────────────────
    # 内部辅助
    # ──────────────────────────────────────────────

    def _get_cached_schema(self) -> dict:
        if self._available_fields is None:
            self._available_fields = self._get_database_schema()
        return self._available_fields

    def _field_exists(self, field_name: str) -> bool:
        return field_name in self._get_cached_schema()

    @staticmethod
    def _get_title(props: dict, key: str) -> str:
        items = props.get(key, {}).get("title", [])
        return "".join(t.get("plain_text", "") for t in items).strip()

    @staticmethod
    def _get_text(props: dict, key: str) -> str:
        items = props.get(key, {}).get("rich_text", [])
        return "".join(t.get("plain_text", "") for t in items).strip()

    @staticmethod
    def _get_multiselect(props: dict, key: str) -> list[str]:
        return [o["name"] for o in props.get(key, {}).get("multi_select", [])]

    @staticmethod
    def _get_checkbox(props: dict, key: str) -> bool:
        return props.get(key, {}).get("checkbox", False)

    # ──────────────────────────────────────────────
    # 同步到想法池数据库
    # ──────────────────────────────────────────────

    def sync_to_pool(
        self,
        short_title: str,
        category: str,
        next_action: str,
        summary: str = "",
        original_title: str = "",
        original_desc: str = "",
        tags: Optional[list] = None,
    ) -> Optional[dict]:
        """
        在想法池数据库中创建新条目。

        - short_title: AI 生成的简短标题（作为 Notion 页面名称）
        - summary: AI 对原内容的 2-3 句摘要
        - original_title / original_desc: 原始标题与内容（一字不漏写入描述）
        需在 .env 中设置 NOTION_POOL_DATABASE_ID。若未设置则返回 None。
        """
        pool_db_id = os.environ.get("NOTION_POOL_DATABASE_ID")
        print(f"  🔍 [DEBUG] NOTION_POOL_DATABASE_ID: {'已设置' if pool_db_id else '❌ 未设置'}")
        if pool_db_id:
            print(f"  🔍 [DEBUG] Pool DB ID: {pool_db_id[:8]}...{pool_db_id[-4:]}")
        if not pool_db_id:
            print("  ⚠️  NOTION_POOL_DATABASE_ID 未设置，跳过同步到想法池")
            return None

        print(f"  🔄 [DEBUG] 正在同步到想法池: {short_title[:30]}...")
        
        # 构建两段式描述：AI 摘要 + 原内容
        parts = []
        if summary:
            parts.append(f"【AI 摘要】\n{summary}")
        original_parts = [p for p in [original_title, original_desc] if p]
        if original_parts:
            parts.append("【原内容】\n" + "\n\n".join(original_parts))
        desc_text = "\n\n---\n\n".join(parts)

        # Notion rich_text 每个 block 最多 2000 字符，超长则分块
        def _rich_text_blocks(content: str) -> list[dict]:
            if not content:
                return []
            blocks = []
            for i in range(0, len(content), 2000):
                blocks.append({"text": {"content": content[i:i + 2000]}})
            return blocks

        props = {
            "名称": {"title": [{"text": {"content": (short_title or original_title or "无标题")[:2000]}}]},
            "池子": {"select": {"name": category}},
            "下一步行动": {"rich_text": _rich_text_blocks(next_action[:2000])},
            "描述": {"rich_text": _rich_text_blocks(desc_text)},
            "完成": {"checkbox": False},
        }
        if tags:
            props["标签"] = {"multi_select": [{"name": t} for t in tags[:100]]}

        print(f"  🔍 [DEBUG] 准备创建页面，属性键: {list(props.keys())}")
        
        try:
            result = self.client.pages.create(
                parent={"database_id": pool_db_id},
                properties=props,
            )
            print(f"  ✅ [DEBUG] 想法池同步成功，页面 ID: {result['id'][:8]}...")
            return result
        except APIResponseError as e:
            print(f"  ❌ [DEBUG] Notion API 错误: {e}")
            raise
        except Exception as e:
            print(f"  ❌ [DEBUG] 未知错误: {type(e).__name__}: {e}")
            raise
