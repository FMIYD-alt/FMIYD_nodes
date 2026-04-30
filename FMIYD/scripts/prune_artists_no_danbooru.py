# -*- coding: utf-8 -*-
"""
从 artists_with_images.json 中删除「在 Danbooru 上 0 结果」的画师，并删除对应本地图片文件。

方式一（推荐）：先运行 audit 生成列表
  python scripts/audit_danbooru_tag_coverage.py --all --failures-out danbooru_zero_miss_tags.txt
  python scripts/prune_artists_no_danbooru.py --failures-file danbooru_zero_miss_tags.txt

方式二：本脚本联网逐 tag 检测（与 audit 等价，较慢）
  set DANBOORU_LOGIN=...
  set DANBOORU_API_KEY=...
  python scripts/prune_artists_no_danbooru.py --scan

用法：
  python scripts/prune_artists_no_danbooru.py --failures-file danbooru_zero_miss_tags.txt
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
import time
from typing import Any, Dict, List, Set

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 延迟导入 requests
try:
    import requests
except ImportError:
    requests = None  # type: ignore


def normalize_danbooru_tag(tag: str) -> str:
    t = (tag or "").strip()
    if not t:
        return ""
    t = re.sub(r"\s+", "_", t)
    t = re.sub(r"(?<![_])\(", "_(", t)
    return t


def check_zero_posts(
    session: Any,
    raw_tag: str,
    timeout: float,
) -> bool:
    """True = 无帖（应删除）"""
    nt = normalize_danbooru_tag(raw_tag)
    if not nt:
        return True
    tags_q = nt + " order:score"
    try:
        r = session.get(
            "https://danbooru.donmai.us/posts.json",
            params={"tags": tags_q, "limit": 1},
            timeout=timeout,
        )
    except Exception:
        return False
    if r.status_code != 200:
        return False
    try:
        data = r.json()
    except Exception:
        return False
    return not (isinstance(data, list) and len(data) >= 1)


def load_failures_file(path: str) -> Set[str]:
    out: Set[str] = set()
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            t = line.strip()
            if not t or t.startswith("#"):
                continue
            out.add(t)
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db-dir", default="artist_export_catalog")
    ap.add_argument("--failures-file", default="", help="每行一个画师tag（与 JSON 中 画师tag 完全一致）")
    ap.add_argument("--scan", action="store_true", help="联网检测全部 tag（需 DANBOORU_LOGIN/API_KEY）")
    ap.add_argument("--delay", type=float, default=0.35)
    ap.add_argument("--timeout", type=float, default=12.0)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    jp = os.path.join(ROOT, args.db_dir, "artists_with_images.json")
    media = os.path.join(ROOT, "images", "xl", "drawings", "media")
    if not os.path.isfile(jp):
        raise SystemExit(f"找不到 {jp}")

    remove_tags: Set[str] = set()
    if args.failures_file:
        fp = args.failures_file if os.path.isabs(args.failures_file) else os.path.join(ROOT, args.failures_file)
        if not os.path.isfile(fp):
            raise SystemExit(f"找不到 {fp}")
        remove_tags = load_failures_file(fp)
        print("从文件读取待删除 tag 数:", len(remove_tags))
    elif args.scan:
        if not requests:
            raise SystemExit("需要 requests")
        login = (os.environ.get("DANBOORU_LOGIN") or "").strip()
        key = (os.environ.get("DANBOORU_API_KEY") or "").strip()
        if not login or not key:
            raise SystemExit("请设置环境变量 DANBOORU_LOGIN 与 DANBOORU_API_KEY")
        s = requests.Session()
        s.auth = (login, key)
        s.headers.update({"User-Agent": "FMIYD-prune/1.0"})
        with open(jp, "r", encoding="utf-8") as f:
            data = json.load(f)
        tags = sorted({(r.get("画师tag") or "").strip() for r in data if isinstance(r, dict) and r.get("画师tag")})
        for i, t in enumerate(tags):
            if check_zero_posts(s, t, args.timeout):
                remove_tags.add(t)
            if (i + 1) % 50 == 0:
                print(f"  扫描 {i+1}/{len(tags)}，当前待删 {len(remove_tags)}")
            time.sleep(max(0.0, args.delay))
        print("扫描完成，待删除 tag 数:", len(remove_tags))
    else:
        raise SystemExit("请指定 --failures-file <文件> 或 --scan")

    if not remove_tags:
        print("没有需要删除的画师。")
        return

    with open(jp, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, list):
        raise SystemExit("JSON 根应为数组")

    removed_recs = 0
    removed_files = 0
    new_list: List[Dict[str, Any]] = []
    for rec in data:
        if not isinstance(rec, dict):
            continue
        tag = (rec.get("画师tag") or "").strip()
        if tag in remove_tags:
            removed_recs += 1
            for img in rec.get("_images") or []:
                if not isinstance(img, str):
                    continue
                safe = os.path.basename(img)
                path = os.path.join(media, safe)
                if os.path.isfile(path):
                    if not args.dry_run:
                        try:
                            os.remove(path)
                            removed_files += 1
                        except OSError as e:
                            print("删文件失败", path, e)
                    else:
                        removed_files += 1
            continue
        new_list.append(rec)

    print(f"将删除记录数: {removed_recs}，涉及本地文件约: {removed_files}")
    if args.dry_run:
        print("dry-run，未写 JSON")
        return

    bak = jp + ".bak"
    shutil.copy2(jp, bak)
    print("已备份:", bak)
    with open(jp, "w", encoding="utf-8") as f:
        json.dump(new_list, f, ensure_ascii=False)
    print("已写入:", jp, "剩余画师数:", len(new_list))


if __name__ == "__main__":
    main()
