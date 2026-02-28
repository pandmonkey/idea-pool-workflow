#!/usr/bin/env python3
"""
idea-pool 主入口

用法：
    python run.py              # 拉取所有待处理条目，自动分类并写回 Notion
    python run.py --dry-run    # 只打印分类结果，不修改 Notion
    python run.py --limit 10   # 最多处理 10 条（默认 50）
    python run.py --no-complete  # 分类后不在 Notion 中打勾完成
    python run.py --desensitize   # 脱敏输出（CI/公开环境默认开启）
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


def _should_desensitize(args) -> bool:
    """CI 或公开环境默认脱敏，避免想法内容被爬取。可通过 DESENSITIZE=0 或 --no-desensitize 关闭。"""
    if hasattr(args, "desensitize") and args.desensitize is not None:
        return args.desensitize
    if os.environ.get("DESENSITIZE", "").lower() in ("0", "false", "no"):
        return False
    return bool(os.environ.get("GITHUB_ACTIONS") or os.environ.get("DESENSITIZE", "").lower() in ("1", "true", "yes"))


def print_result(idx: int, idea: dict, result, desensitize: bool = False) -> None:
    pool_str = color(f"[{result.category}]", result.category)

    if desensitize:
        title_display = f"条目 #{idx}"
        next_display = "[已脱敏]"
        reason_display = "[已脱敏]"
        tags_display = "[已脱敏]"
    else:
        title_display = idea["title"][:60]
        next_display = result.next_action
        reason_display = result.reasoning
        tags_display = ", ".join(idea["tags"]) if idea.get("tags") else ""

    print(f"  {BOLD}{idx}.{RESET} {title_display}")
    print(f"     {pool_str}")
    print(f"     下一步: {next_display}")
    print(f"     理由:   {reason_display}")
    if tags_display:
        print(f"     标签:   {tags_display}")
    print()


def main():
    parser = argparse.ArgumentParser(description="从 Notion 滴答清单拉取想法并自动分类")
    parser.add_argument("--dry-run", action="store_true", help="只打印结果，不修改 Notion")
    parser.add_argument("--limit", type=int, default=50, help="最多处理条数（默认 50）")
    parser.add_argument("--no-complete", action="store_true", help="分类后不在 Notion 中打勾完成")
    parser.add_argument("--desensitize", dest="desensitize", action="store_true", help="脱敏输出（隐藏想法内容，适用于公开 CI）")
    parser.add_argument("--no-desensitize", dest="desensitize", action="store_false", help="关闭脱敏（本地调试时查看完整内容）")
    parser.set_defaults(desensitize=None)
    args = parser.parse_args()

    desensitize = _should_desensitize(args)

    print_header()
    if desensitize:
        print(f"{YELLOW}🔒 脱敏模式：想法内容已隐藏{RESET}\n")

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
            print_result(idx, idea, result, desensitize=desensitize)

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
            fail_label = f"条目 #{idx}" if desensitize else title[:40]
            print(f"  {RED}{idx}. ❌ 分类失败 [{fail_label}]: {e}{RESET}\n")
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

    for idx, r in enumerate(results, 1):
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
                sync_fail_label = f"条目 #{idx}" if desensitize else r["title"][:30]
                print(f"  {YELLOW}⚠ 想法池同步失败 [{sync_fail_label}]: {e}{RESET}")

            success_label = f"条目 #{idx}" if desensitize else r["title"][:50]
            print(f"  ✅ {success_label}")
            success_count += 1
            time.sleep(0.3)  # 避免 Notion API 限流
        except Exception as e:
            update_fail_label = f"条目 #{idx}" if desensitize else r["title"][:40]
            print(f"  {RED}❌ 更新失败 [{update_fail_label}]: {e}{RESET}")

    msg = f"\n🎉 完成！成功更新 {success_count}/{len(results)} 条。"
    if pool_sync_count:
        msg += f" 想法池已同步 {pool_sync_count} 条。"
    print(msg + "\n")


if __name__ == "__main__":
    main()
