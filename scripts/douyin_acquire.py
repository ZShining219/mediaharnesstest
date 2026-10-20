#!/usr/bin/env python3
"""抖音素材获取 CLI — 供 Agent / 人工直接调用。

示例:
    .venv/bin/python scripts/douyin_acquire.py \
      --account "都市丽人服饰内衣旗舰店" --keywords "文胸,高开衩" \
      --max-videos 20 --dry-run

    .venv/bin/python scripts/douyin_acquire.py \
      --account "都市丽人服饰内衣旗舰店" --keywords "冰丝,三角" \
      --max-videos 10

    .venv/bin/python scripts/douyin_acquire.py \
      --queries "都市丽人 文胸,都市丽人 聚拢内衣" \
      --author-filter "都市丽人" --keywords "文胸" --max-videos 10
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from orchestrator.app import douyin_materials  # noqa: E402


def _list(v: str | None) -> list[str]:
    return [x.strip() for x in (v or "").split(",") if x.strip()]


def main():
    ap = argparse.ArgumentParser(description="抖音素材获取")
    ap.add_argument("--account", default=None, help="抖音账号昵称")
    ap.add_argument("--sec-uid", default=None, help="已知 sec_uid，优先于 account")
    ap.add_argument("--resolve-name", default=None, help="只解析账号，不下载")
    ap.add_argument("--queries", default=None, help="关键词搜索，逗号分隔")
    ap.add_argument("--author-filter", default=None, help="搜索结果作者包含该字符串")
    ap.add_argument("--keywords", default=None, help="标题/商品关键词，逗号分隔")
    ap.add_argument("--exclude-keywords", default=None, help="排除关键词，逗号分隔")
    ap.add_argument("--max-videos", type=int, default=50)
    ap.add_argument("--tags", default=None, help="额外参考池标签，逗号分隔")
    ap.add_argument("--with-details", action="store_true",
                    help="逐条打开作品页补商品锚点(慢)")
    ap.add_argument("--dry-run", action="store_true", help="只列清单，不下载")
    ap.add_argument("--no-download", action="store_true", help="不下载")
    ap.add_argument("--no-pool", action="store_true", help="不写入参考池")
    ap.add_argument("--json", action="store_true", help="格式化 JSON 输出")
    a = ap.parse_args()

    if a.resolve_name:
        res = douyin_materials.resolve_user(a.resolve_name)
    else:
        res = douyin_materials.acquire(
            account=a.account, sec_uid=a.sec_uid,
            queries=_list(a.queries) or None,
            author_filter=a.author_filter,
            keywords=_list(a.keywords) or None,
            exclude_keywords=_list(a.exclude_keywords) or None,
            max_videos=a.max_videos,
            download=not a.no_download,
            add_to_pool=not a.no_pool,
            tags=_list(a.tags) or None,
            with_details=a.with_details,
            dry_run=a.dry_run,
        )

    print(json.dumps(res, ensure_ascii=False, indent=2 if a.json else None))
    if res.get("error"):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
