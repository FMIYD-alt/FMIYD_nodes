# -*- coding: utf-8 -*-
"""
将 artists_with_images.json 中误写入的「随机小数」式画师名（如 0.512016191496403）
替换为对应的「画师tag」，与画廊节点/前端展示一致。

用法（在 FMIYD 根目录）：
  python scripts/fix_junk_artist_names.py artist_export_catalog/artists_with_images.json
  python scripts/fix_junk_artist_names.py artist_export_catalog/artists_with_images.json --dry-run
"""

from __future__ import annotations

import argparse
import json
import re
from typing import Any, Dict, List

# 与 JS / __init__.py 中一致：典型 Math.random() 形态 0.xxxxxxxxxxxxxxx
_JUNK_NAME_RE = re.compile(r"^0\.\d{8,}$")


def sanitize_name(name_val: Any, tag_val: str) -> tuple[str, bool]:
    """
    若 name 为垃圾小数串，用 tag 替换。返回 (新名称, 是否发生过替换)。
    """
    t = (tag_val or "").strip() if isinstance(tag_val, str) else ""
    if isinstance(name_val, (int, float)) and not isinstance(name_val, bool):
        try:
            x = float(name_val)
            if 0 < x < 1:
                return (t, True)
        except Exception:
            pass
        return (str(name_val), False)
    if not isinstance(name_val, str):
        return ("", False)
    n = name_val.strip()
    if _JUNK_NAME_RE.match(n):
        return (t if t and not _JUNK_NAME_RE.match(t) else "", True)
    return (n, False)


def fix_records(records: List[Dict[str, Any]]) -> int:
    changed = 0
    for rec in records:
        if not isinstance(rec, dict):
            continue
        tag = rec.get("画师tag") or ""
        name = rec.get("画师名/别名")
        new_name, did = sanitize_name(name, tag)
        if not did:
            continue
        if rec.get("画师名/别名") != new_name:
            rec["画师名/别名"] = new_name
            changed += 1
    return changed


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "json_path",
        nargs="?",
        default="artist_export_catalog/artists_with_images.json",
        help="artists_with_images.json 路径（相对 FMIYD 根或绝对路径）",
    )
    ap.add_argument("--dry-run", action="store_true", help="只统计会修改的条数，不写回文件")
    args = ap.parse_args()

    path = args.json_path
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, list):
        raise SystemExit("JSON 根应为数组")

    before = sum(
        1
        for r in data
        if isinstance(r, dict)
        and _JUNK_NAME_RE.match(str(r.get("画师名/别名") or "").strip())
    )
    print("疑似垃圾小数「画师名」条数（修正前）:", before)

    if args.dry_run:
        would = 0
        for r in data:
            if not isinstance(r, dict):
                continue
            new_name, did = sanitize_name(r.get("画师名/别名"), r.get("画师tag") or "")
            if did and r.get("画师名/别名") != new_name:
                would += 1
        print("dry-run：将改写条数:", would)
        print("（未写回文件）")
        return

    n = fix_records([r for r in data if isinstance(r, dict)])
    print("实际改写条数:", n)

    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    print("已写回:", path)


if __name__ == "__main__":
    main()
