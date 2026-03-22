"""
合并两个本地画师导出库：
- artist_export_1000
- artist_export_2000

输出到一个新的库目录（默认 artist_export_catalog），用于“画师图鉴画廊”节点。

合并策略：
- 以“画师tag”作为唯一键合并（同 tag 合并图片列表）
- 图片以文件名（basename）去重
- 输出：artists_with_images.json；图片拷贝到扩展根目录 images/xl/drawings/media/
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
from typing import Any, Dict, List, Optional, Tuple


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

_JUNK_NAME_RE = re.compile(r"^0\.\d{8,}$")


def _sanitize_display_name(name_val: Any, tag_val: str) -> str:
    t = (tag_val or "").strip() if isinstance(tag_val, str) else ""
    if isinstance(name_val, (int, float)) and not isinstance(name_val, bool):
        try:
            x = float(name_val)
            if 0 < x < 1:
                return t if t and not _JUNK_NAME_RE.match(t) else ""
        except Exception:
            pass
        return str(name_val)
    if not isinstance(name_val, str):
        return ""
    n = name_val.strip()
    if _JUNK_NAME_RE.match(n):
        return t if t and not _JUNK_NAME_RE.match(t) else ""
    return n


def _safe_filename(s: str) -> str:
    return os.path.basename(s)


def normalize_record(rec: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    从输入库的记录里提取：
    - 画师名/别名
    - 画师tag
    - _images（basename 列表）

    兼容你之前导出过程中出现的“键名乱码”：
    - tag 键名：包含 'tag'（小写/大写不敏感）
    - name 键名：键名中包含 '/' 字符
    """
    if not isinstance(rec, dict):
        return None

    tag_val = ""
    name_val = ""

    if isinstance(rec.get("画师tag"), str):
        tag_val = rec["画师tag"].strip()
    if isinstance(rec.get("画师名/别名"), str):
        name_val = rec["画师名/别名"].strip()
    elif isinstance(rec.get("画师名/别名"), (int, float)) and not isinstance(rec.get("画师名/别名"), bool):
        name_val = str(rec["画师名/别名"])

    if not tag_val or not name_val:
        for k, v in rec.items():
            if not isinstance(k, str):
                continue
            if k.startswith("_"):
                continue
            if not tag_val and isinstance(v, str) and ("tag" in k.lower()):
                tag_val = v.strip()
            if not name_val and isinstance(v, str) and ("/" in k):
                name_val = v.strip()

    name_val = _sanitize_display_name(name_val, tag_val)

    images = rec.get("_images") or []
    if not isinstance(images, list):
        images = []

    images = [_safe_filename(x) for x in images if isinstance(x, str)]
    if not tag_val:
        return None

    return {"画师名/别名": name_val, "画师tag": tag_val, "_images": images}


def load_db(db_dir: str) -> List[Dict[str, Any]]:
    db_path = os.path.join(db_dir, "artists_with_images.json")
    with open(db_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    out: List[Dict[str, Any]] = []
    if isinstance(data, list):
        for rec in data:
            nr = normalize_record(rec)
            if nr:
                out.append(nr)
    return out


def merge_dbs(db1: List[Dict[str, Any]], db2: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """
    返回以 tag 为 key 的映射：tag -> {画师名/别名, 画师tag, _images}
    """
    m: Dict[str, Dict[str, Any]] = {}

    def add_rec(r: Dict[str, Any]):
        tag = (r.get("画师tag") or "").strip()
        if not tag:
            return
        if tag not in m:
            m[tag] = {"画师名/别名": r.get("画师名/别名") or "", "画师tag": tag, "_images": []}
        else:
            # 同 tag 下补全更完整名字
            if not m[tag]["画师名/别名"] and r.get("画师名/别名"):
                m[tag]["画师名/别名"] = r.get("画师名/别名")

        # merge images (basename)
        seen = set(m[tag]["_images"])
        for img in r.get("_images") or []:
            if img and img not in seen:
                seen.add(img)
                m[tag]["_images"].append(img)

    for r in db1:
        add_rec(r)
    for r in db2:
        add_rec(r)
    return m


def copy_media_for_tags(
    out_dir: str,
    merged: Dict[str, Dict[str, Any]],
    src_dirs: List[str],
) -> None:
    # 与 __init__.py 一致：统一写入扩展根目录 images/
    out_media = os.path.join(ROOT, "images", "xl", "drawings", "media")
    os.makedirs(out_media, exist_ok=True)

    # 建立 src basename -> 实际文件路径索引
    src_index: Dict[str, List[str]] = {}
    for sd in src_dirs:
        media_dir = os.path.join(sd, "images", "xl", "drawings", "media")
        if not os.path.isdir(media_dir):
            continue
        for fn in os.listdir(media_dir):
            fp = os.path.join(media_dir, fn)
            if not os.path.isfile(fp):
                continue
            if fn not in src_index:
                src_index[fn] = []
            src_index[fn].append(fp)

    # 拷贝所有需要的图片
    needed = set()
    for r in merged.values():
        for img in r.get("_images") or []:
            needed.add(img)

    copied = 0
    for fn in needed:
        dst = os.path.join(out_media, fn)
        if os.path.exists(dst):
            continue
        src_list = src_index.get(fn) or []
        if not src_list:
            continue
        # 任意一个源目录的同名文件即可
        shutil.copy2(src_list[0], dst)
        copied += 1

    print("  需要拷贝图片：", len(needed))
    print("  实际拷贝图片：", copied)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--a", default="artist_export_1000", help="基础库目录名（相对 FMIYD 根目录）")
    ap.add_argument("--b", default="artist_export_2000", help="补充库目录名（相对 FMIYD 根目录）")
    ap.add_argument("--out", default="artist_export_catalog", help="输出库目录名（相对 FMIYD 根目录）")
    ap.add_argument("--force", action="store_true", help="强制覆盖输出目录")
    args = ap.parse_args()

    dir_a = os.path.join(ROOT, args.a)
    dir_b = os.path.join(ROOT, args.b)
    out_dir = os.path.join(ROOT, args.out)

    if args.force and os.path.isdir(out_dir):
        shutil.rmtree(out_dir)

    if not os.path.isdir(dir_a):
        raise SystemExit(f"库不存在：{dir_a}")
    if not os.path.isdir(dir_b):
        raise SystemExit(f"库不存在：{dir_b}")

    db1 = load_db(dir_a)
    db2 = load_db(dir_b)
    print("load:")
    print("  a:", len(db1))
    print("  b:", len(db2))

    merged = merge_dbs(db1, db2)
    merged_list = list(merged.values())
    merged_list.sort(key=lambda x: (x.get("画师tag") or ""))

    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "artists_with_images.json"), "w", encoding="utf-8") as f:
        json.dump(merged_list, f, ensure_ascii=False)

    copy_media_for_tags(out_dir, merged, [dir_a, dir_b])

    print("done:")
    print("  merged artists:", len(merged_list))
    print("  out:", os.path.join(out_dir, "artists_with_images.json"))


if __name__ == "__main__":
    main()

