# -*- coding: utf-8 -*-
"""
统计本地库「画师tag」在 Danbooru 上能否查到至少 1 张图（posts.json）。

用法（FMIYD 根目录）：
  python scripts/audit_danbooru_tag_coverage.py --sample 300
  python scripts/audit_danbooru_tag_coverage.py --all
  python scripts/audit_danbooru_tag_coverage.py --sample 500 --rating rating:general

环境变量（推荐）：DANBOORU_LOGIN、DANBOORU_API_KEY
"""

from __future__ import annotations

import argparse
import json
import os
import random
import re
import sys
import time
from typing import Any, Dict, List, Optional, Set

try:
    import requests
except ImportError:
    print("需要 requests：pip install requests", file=sys.stderr)
    raise SystemExit(1)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
POSTS_URL = "https://danbooru.donmai.us/posts.json"
DEFAULT_UA = "FMIYDArtistCoverageAudit/1.0"


def normalize_danbooru_tag(tag: str) -> str:
    t = (tag or "").strip()
    if not t:
        return ""
    t = re.sub(r"\s+", "_", t)
    t = re.sub(r"(?<![_])\(", "_(", t)
    return t


def build_session(login: Optional[str], api_key: Optional[str], verify_ssl: bool) -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": DEFAULT_UA})
    if login and api_key:
        s.auth = (login, api_key)
    s.verify = verify_ssl
    return s


def check_tag_has_posts(
    session: requests.Session,
    raw_tag: str,
    rating_suffix: str,
    timeout: float,
) -> tuple[bool, str, str]:
    """
    返回 (是否有至少1帖, 规范化后的tag, 备注)
    """
    nt = normalize_danbooru_tag(raw_tag)
    if not nt:
        return False, "", "空tag"

    parts = [nt, "order:score"]
    if rating_suffix.strip():
        parts.append(rating_suffix.strip())
    tags_q = " ".join(parts)

    try:
        r = session.get(POSTS_URL, params={"tags": tags_q, "limit": 1}, timeout=timeout)
    except requests.exceptions.Timeout:
        return False, nt, "timeout"
    except requests.exceptions.RequestException as e:
        return False, nt, f"网络:{e}"

    if r.status_code == 403:
        return False, nt, "403"
    if r.status_code != 200:
        return False, nt, f"HTTP{r.status_code}"

    try:
        data = r.json()
    except Exception:
        return False, nt, "JSON解析失败"

    if not isinstance(data, list):
        return False, nt, "非列表"
    if len(data) >= 1:
        return True, nt, "ok"
    return False, nt, "0结果"


def load_tags_from_catalog(db_path: str) -> List[str]:
    with open(db_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, list):
        return []
    tags: List[str] = []
    for rec in data:
        if not isinstance(rec, dict):
            continue
        t = (rec.get("画师tag") or "").strip()
        if t:
            tags.append(t)
    return tags


def main() -> None:
    ap = argparse.ArgumentParser(description="统计画师tag在 Danbooru 是否有图")
    ap.add_argument("--db-dir", default="artist_export_catalog", help="库目录（相对 FMIYD 根）")
    ap.add_argument(
        "--rating",
        default="",
        help='附加分级 tag，如 rating:general；默认不加（尽量提高命中率）',
    )
    ap.add_argument("--sample", type=int, default=0, help="随机抽样 N 个**不重复** tag（0=不用抽样）")
    ap.add_argument("--all", action="store_true", help="检查全部不重复 tag（可能很慢）")
    ap.add_argument("--delay", type=float, default=0.6, help="请求间隔秒")
    ap.add_argument("--timeout", type=float, default=12.0, help="单请求超时（秒），避免卡死")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument(
        "--failures-out",
        default="",
        help="将「0 结果」的画师 tag 逐行写入该文件（UTF-8），便于核对",
    )
    ap.add_argument("--no-verify-ssl", action="store_true")
    ap.add_argument(
        "--login",
        default=os.environ.get("DANBOORU_LOGIN", "") or "",
    )
    ap.add_argument(
        "--api-key",
        default=os.environ.get("DANBOORU_API_KEY", "") or "",
    )
    args = ap.parse_args()

    json_path = os.path.join(ROOT, args.db_dir, "artists_with_images.json")
    if not os.path.isfile(json_path):
        raise SystemExit(f"找不到 {json_path}")

    all_tags = load_tags_from_catalog(json_path)
    unique: List[str] = sorted(set(all_tags))
    total_records = len(all_tags)
    total_unique = len(unique)

    def p(*a, **k):
        k.setdefault("flush", True)
        print(*a, **k)

    p(f"库记录数: {total_records}")
    p(f"不重复画师tag数: {total_unique}")

    if args.all:
        to_check = unique
    elif args.sample and args.sample > 0:
        random.seed(args.seed)
        k = min(args.sample, total_unique)
        to_check = random.sample(unique, k)
        p(f"抽样: {k} 个不重复 tag（seed={args.seed}）")
    else:
        # 默认：取前 200 个不重复 tag 做快速试跑
        to_check = unique[:200]
        p(f"未指定 --sample/--all，默认检查前 {len(to_check)} 个不重复 tag（按字母排序）")

    login = (args.login or "").strip()
    api_key = (args.api_key or "").strip()
    if not login or not api_key:
        p("提示：未设置 DANBOORU_LOGIN/API_KEY，匿名可能 403 或限流。\n")

    session = build_session(login or None, api_key or None, verify_ssl=not args.no_verify_ssl)
    rating = (args.rating or "").strip()

    hits = 0
    miss = 0
    by_reason: Dict[str, int] = {}
    zero_miss: List[str] = []  # 原始画师tag（Danbooru 0 结果）

    t0 = time.time()
    for i, raw in enumerate(to_check):
        ok, nt, note = check_tag_has_posts(session, raw, rating, args.timeout)
        if ok:
            hits += 1
        else:
            miss += 1
            key = note.split(":")[0] if ":" in note else note
            by_reason[key] = by_reason.get(key, 0) + 1
            if note == "0结果":
                zero_miss.append(raw)

        if (i + 1) % 50 == 0 or (i + 1) == len(to_check):
            p(f"  进度 {i+1}/{len(to_check)} … 当前命中 {hits}")

        time.sleep(max(0.0, args.delay))

    elapsed = time.time() - t0
    n = len(to_check)
    pct = (100.0 * hits / n) if n else 0.0

    p("\n" + "=" * 50)
    p(f"检查数量: {n}")
    p(f"能查到至少 1 张图: {hits}  ({pct:.1f}%)")
    p(f"查不到或失败: {miss}")
    p(f"失败原因分布: {dict(by_reason)}")
    p(f"耗时: {elapsed:.1f}s")
    if not args.all and total_unique:
        est = hits / n * total_unique
        p(f"若样本代表整体，粗略估计全库不重复 tag 可命中约: {est:.0f} / {total_unique}")

    if "403" in by_reason:
        p("\n出现 403 时请配置 API Key 后重试。")

    if zero_miss:
        p(f"\nDanbooru 无帖（0 结果）共 {len(zero_miss)} 个，原始画师tag：")
        for t in zero_miss:
            p(f"  - {t}")
        out = (args.failures_out or "").strip()
        if out:
            outp = out if os.path.isabs(out) else os.path.join(ROOT, out)
            try:
                with open(outp, "w", encoding="utf-8") as f:
                    f.write("\n".join(zero_miss) + "\n")
                p(f"\n已写入: {outp}")
            except OSError as e:
                p(f"\n写入失败 {outp}: {e}")


if __name__ == "__main__":
    main()
