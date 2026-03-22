#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
合并本地画师库中「同一画师、tag 仅空格/下划线/大小写不同」的重复条目，
统一为 Danbooru 风格：小写比较、合并后画师 tag 使用下划线、无空格。

用法：
  python scripts/dedupe_artist_tags.py                    # 写回 catalog（会先备份 .bak）
  python scripts/dedupe_artist_tags.py --dry-run          # 只打印统计
  python scripts/dedupe_artist_tags.py --db path.json    # 指定 JSON
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
from collections import defaultdict
from pathlib import Path
from typing import Any

_JUNK_NAME = re.compile(r"^0\.\d{8,}$")


def normalize_tag_key(tag: str) -> str:
    """用于判重的 key：小写、空白→下划线、连续下划线合并。"""
    if not isinstance(tag, str):
        return ""
    t = tag.strip().lower()
    t = re.sub(r"\s+", "_", t)
    t = re.sub(r"_+", "_", t)
    return t.strip("_")


def get_tag_from_record(rec: dict[str, Any]) -> str:
    v = rec.get("画师tag")
    if isinstance(v, str) and v.strip():
        return v.strip()
    for k, val in rec.items():
        if isinstance(k, str) and "tag" in k.lower() and isinstance(val, str) and val.strip():
            return val.strip()
    return ""


def canonical_tag_for_group(variants: list[str]) -> str:
    """
    在等价组内选一个写入库的 tag：优先与 normalize 后一致的「全下划线」形式；
    否则使用 normalize_tag_key 的结果（已是下划线）。
    """
    variants = [v for v in variants if v and isinstance(v, str)]
    if not variants:
        return ""
    key = normalize_tag_key(variants[0])
    for v in variants:
        if normalize_tag_key(v) != key:
            continue
        if v.lower().replace(" ", "_") == key.replace(" ", "_") and " " not in v:
            return v
    # 优先已有下划线写法且规范化等于 key
    for v in variants:
        if normalize_tag_key(v) == key and "_" in v and " " not in v:
            return v
    # 统一为规范 key（小写+下划线）
    return key


def score_display_name(s: str) -> int:
    if not s or not s.strip():
        return -1
    t = s.strip()
    if _JUNK_NAME.match(t):
        return 0
    return len(t)


def pick_display_name(group: list[dict[str, Any]], canonical_tag: str) -> str:
    names: list[str] = []
    for rec in group:
        n = rec.get("画师名/别名")
        if isinstance(n, str) and n.strip():
            names.append(n.strip())
        elif isinstance(n, (int, float)) and not isinstance(n, bool):
            names.append(str(n))
    names = [n for n in names if n]
    if names:
        names.sort(key=score_display_name, reverse=True)
        return names[0]
    return canonical_tag.replace("_", " ")


def merge_image_lists(group: list[dict[str, Any]]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for rec in group:
        imgs = rec.get("_images")
        if not isinstance(imgs, list):
            continue
        for im in imgs:
            if isinstance(im, str) and im and im not in seen:
                seen.add(im)
                out.append(im)
    return out


def merge_group(group: list[dict[str, Any]]) -> dict[str, Any]:
    variants = [get_tag_from_record(r) for r in group]
    can = canonical_tag_for_group(variants)
    return {
        "画师tag": can,
        "画师名/别名": pick_display_name(group, can),
        "_images": merge_image_lists(group),
    }


def dedupe(data: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """返回 (新列表, 统计)。"""
    empty_rows: list[dict[str, Any]] = []
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    order_keys: list[str] = []

    for rec in data:
        if not isinstance(rec, dict):
            continue
        tag = get_tag_from_record(rec)
        k = normalize_tag_key(tag)
        if not k:
            empty_rows.append(rec)
            continue
        if k not in groups:
            order_keys.append(k)
        groups[k].append(rec)

    out: list[dict[str, Any]] = []
    merged_groups = 0
    removed = 0
    for k in order_keys:
        g = groups[k]
        if len(g) > 1:
            merged_groups += 1
            removed += len(g) - 1
            out.append(merge_group(g))
        else:
            out.append(merge_group(g))

    out.extend(empty_rows)
    stats = {
        "input": len(data),
        "output": len(out),
        "duplicate_groups": merged_groups,
        "removed_rows": removed,
        "empty_tag_kept": len(empty_rows),
    }
    return out, stats


def main() -> None:
    ap = argparse.ArgumentParser(description="Dedupe artist tags (space vs underscore).")
    ap.add_argument(
        "--db",
        type=Path,
        default=Path(__file__).resolve().parent.parent / "artist_export_catalog" / "artists_with_images.json",
        help="Path to artists_with_images.json",
    )
    ap.add_argument("--dry-run", action="store_true", help="Do not write file")
    args = ap.parse_args()
    path: Path = args.db
    if not path.is_file():
        raise SystemExit(f"File not found: {path}")

    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, list):
        raise SystemExit("JSON root must be a list")

    new_data, stats = dedupe(data)
    print("统计:", json.dumps(stats, ensure_ascii=False, indent=2))

    if args.dry_run:
        print("(dry-run，未写入)")
        return

    bak = path.with_suffix(path.suffix + ".bak")
    shutil.copy2(path, bak)
    print(f"已备份: {bak}")
    tmp = path.with_suffix(".tmp.json")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(new_data, f, ensure_ascii=False, indent=2)
        f.write("\n")
    tmp.replace(path)
    print(f"已写回: {path}")


if __name__ == "__main__":
    main()
