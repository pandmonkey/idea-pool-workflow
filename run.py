#!/usr/bin/env python3
"""
idea-pool 主入口

用法：
    python run.py              # 拉取所有待处理条目，自动分类并写回 Notion
    python run.py --dry-run    # 只打印分类结果，不修改 Notion
    python run.py --limit 10   # 最多处理 10 条（默认 50）
    python run.py --no-complete  # 分类后不在 Notion 中打勾完成
"""

import sys
import time
import os
import argparse
from dotenv import load_dotenv

load_dotenv()

from notion_helper import NotionIdeaDB
from classifier import IdeaClassifier
from config import POOLS

# ── 颜色输出（终端）─────────────────────────────
POOL_COLORS = {
    "Dev":   "\033[94m",   # 蓝
    "Deep":  "\033[95m",   # 紫
    "Wild":  "\033[93m",   # 黄
    "Meta":  "\033[92m",   # 绿
    "Other": "\033[90m",   # 灰
}
RESET  = "\033[0m"
BOLD   = "\033[1m"
RED    = "\033[91m"
YELLOW = "\033[93m"


def color(text: str, pool: str) -> str:
    return f"{POOL_COLORS.get(pool, '')}{text}{RESET}"


def print_header():
    print(f"\n{BOLD}{'─'*60}{RESET}")
    print(f"{BOLD}  💡 Idea Pool Processor{RESET}")
    print(f"{'─'*60}{RESET}\n")


def print_result(idx: int, idea: dict, result) -> None:
    pool_str = color(f"[{result.category}]", result.category)

    print(f"  {BOLD}{idx}.{RESET} {idea['title'][:60]}")
    print(f"     {pool_str}")
    print(f"     下一步: {result.next_action}")
    print(f"     理由:   {result.reasoning}")
    if idea.get("tags"):
        print(f"     标签:   {', '.join(idea['tags'])}")
    print()


def main():
    parser = argparse.ArgumentParser(description="从 Notion 滴答清单拉取想法并自动分类")
    parser.add_argument("--dry-run", action="store_true", help="只打印结果，不修改 Notion")
    parser.add_argument("--limit", type=int, default=50, help="最多处理条数（默认 50）")
    parser.add_argument("--no-complete", action="store_true", help="分类后不在 Notion 中打勾完成")
    args = parser.parse_args()

    print_header()

    # ── 环境变量调试 ─────────────────────────────────
    print("🔍 [DEBUG] 环境变量检查:")
    env_vars = ["NOTION_TOKEN", "NOTION_DATABASE_ID", "NOTION_POOL_DATABASE_ID", "OPENAI_API_KEY", "OPENAI_BASE_URL", "OPENAI_MODEL"]
    for var in env_vars:
        val = os.environ.get(var, "")
        if val:
            # 只显示前后几位，保护敏感信息
            if len(val) > 10:
                display = f"{val[:4]}...{val[-4:]} (长度: {len(val)})"
            else:
                display = f"{'*' * len(val)} (长度: {len(val)})"
            print(f"  ✅ {var}: {display}")
        else:
            print(f"  ❌ {var}: 未设置")
    print()

    # ── 1. 初始化 ─────────────────────────────────
    try:
        db = NotionIdeaDB()
        clf = IdeaClassifier()
    except ValueError as e:
        print(f"{RED}❌ 初始化失败：{e}{RESET}")
        print("请检查 .env 文件中的配置是否正确。")
        sys.exit(1)

    # ── 2. 拉取待处理条目 ─────────────────────────
    print("📡 正在从 Notion 拉取未处理条目...")
    pages = db.fetch_unprocessed(limit=args.limit)

    if not pages:
        print("✅ 没有未处理的条目，任务完成！\n")
        return

    print(f"📋 找到 {len(pages)} 条待处理条目\n")
    if args.dry_run:
        print(f"{YELLOW}【Dry-run 模式】：只打印结果，不会修改 Notion{RESET}\n")

    # ── 3. 逐条分类 ──────────────────────────────
    results = []
    failed = []

    for idx, page in enumerate(pages, 1):
        idea = db.extract_idea(page)
        title = idea["title"] or "(无标题)"

        try:
            result = clf.classify(title, idea["desc"])
            print_result(idx, idea, result)

            results.append({
                "id":          idea["id"],
                "url":         idea["url"],
                "title":       title,
                "desc":        idea.get("desc", ""),
                "tags":        idea.get("tags") or [],
                "category":    result.category,
                "short_title": result.short_title,
                "summary":     result.summary,
                "next_action": result.next_action,
                "reasoning":   result.reasoning,
            })
        except Exception as e:
            print(f"  {RED}{idx}. ❌ 分类失败 [{title[:40]}]: {e}{RESET}\n")
            failed.append({"title": title, "error": str(e)})

        time.sleep(0.2)

    # ── 4. 统计摘要 ───────────────────────────────
    print(f"{'─'*60}")
    print(f"{BOLD}📊 分类摘要{RESET}")
    pool_counts: dict[str, int] = {}
    for r in results:
        pool_counts[r["category"]] = pool_counts.get(r["category"], 0) + 1

    for pool, count in sorted(pool_counts.items()):
        label = POOLS.get(pool, {}).get("label", "")
        print(f"  {color(pool, pool):<20} {label:<12} {count} 条")

    if failed:
        print(f"\n  {RED}❌ 失败：{len(failed)} 条{RESET}")
    print()

    if not results:
        print("没有成功分类的条目，退出。\n")
        return

    # ── 5. Dry-run 模式直接退出 ──────────────────
    if args.dry_run:
        print(f"{YELLOW}Dry-run 模式，跳过 Notion 更新。{RESET}\n")
        return

    # ── 6. 自动回写 Notion ────────────────────────
    mark_complete = not args.no_complete
    action_desc = "更新分类并标记完成（从滴答清单归档）" if mark_complete else "仅更新分类，不标记完成"
    print(f"{'─'*60}")
    print(f"⏳ 正在将 {len(results)} 条结果写回 Notion（{action_desc}）...\n")

    success_count = 0
    pool_sync_count = 0

    for r in results:
        try:
            db.update_classification(
                page_id=r["id"],
                category=r["category"],
                next_action=r["next_action"],
                mark_complete=mark_complete,
            )
            # 同步到想法池（失败仅打印警告，不中断流程）
            try:
                page = db.sync_to_pool(
                    short_title=r.get("short_title") or r["title"],
                    category=r["category"],
                    next_action=r["next_action"],
                    summary=r.get("summary", ""),
                    original_title=r["title"],
                    original_desc=r.get("desc", ""),
                    tags=r.get("tags"),
                )
                if page:
                    pool_sync_count += 1
            except Exception as e:
                print(f"  {YELLOW}⚠ 想法池同步失败 [{r['title'][:30]}]: {e}{RESET}")

            print(f"  ✅ {r['title'][:50]}")
            success_count += 1
            time.sleep(0.3)  # 避免 Notion API 限流
        except Exception as e:
            print(f"  {RED}❌ 更新失败 [{r['title'][:40]}]: {e}{RESET}")

    msg = f"\n🎉 完成！成功更新 {success_count}/{len(results)} 条。"
    if pool_sync_count:
        msg += f" 想法池已同步 {pool_sync_count} 条。"
    print(msg + "\n")


if __name__ == "__main__":
    main()
