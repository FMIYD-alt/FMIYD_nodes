"""
导入「画师2000」精选目录图片，按图片文件名匹配画师：
1) 先按文件名解析出疑似画师 tag（以及显示名）并去本地 db 里匹配
2) 如果本地没有该画师（tag 不存在），则可选联网搜索 Danbooru tags API 补全 tag
3) 生成/更新本地库：artist_export_2000 的 artists_with_images.json；图片写入扩展根目录 images/xl/drawings/media/

用法示例（推荐）：
  python scripts\\import_artist2000.py --base-db artist_export_1000 --in-dir 画师2000\\精选 --out artist_export_2000 --online
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import shutil
from typing import Any, Dict, Iterable, List, Optional, Tuple

import requests


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
    # filenames 里保留原样即可，防穿越交给服务端安全处理
    return os.path.basename(s)


def parse_artist_from_filename(filename: str) -> Tuple[str, str, str]:
    """
    从文件名解析出（display_name, tag_candidate, alias_candidate）

    规则（启发式）：
    - 若文件名形如：<prefix>(<alias>) 或 <prefix>_(<alias>）则：
        alias = 括号内最后一段
        prefix_clean = '(' 前的部分去掉结尾 '_' 与多余空格
        tag_candidate = prefix_clean + '(' + alias + ')'（prefix_clean 为空则 tag_candidate=alias）
        display_name = prefix_clean 或 alias
    - 否则：
        display_name=tag_candidate=文件名（去后缀）
    """
    base = os.path.splitext(os.path.basename(filename))[0].strip()
    m = list(re.finditer(r"\(([^()]*)\)", base))
    if m:
        last = m[-1]
        alias = last.group(1).strip()
        prefix = base[: last.start()].rstrip()
        prefix = prefix.rstrip("_").strip()
        display = prefix if prefix else alias
        tag_candidate = f"{prefix}({alias})" if prefix else alias
        return display, tag_candidate, alias
    return base, base, base


def normalize_artist_record(rec: Dict[str, Any]) -> Dict[str, Any]:
    """
    兼容你现有导出文件里列名编码可能导致的「键名乱码」：
    - tag key：key 包含 'tag'（小写 ASCII）
    - name key：key 包含 '/'（画师名/别名）
    - images：取 rec['_images']
    """
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
            if k.startswith("_"):
                continue
            if not tag_val and isinstance(v, str) and ("tag" in k.lower()):
                tag_val = v.strip()
            if not name_val and isinstance(v, str) and ("/" in k):
                name_val = v.strip()

    name_val = _sanitize_display_name(name_val, tag_val)

    images = rec.get("_images") or []
    # images 里只保留 basename（防止混入路径）
    images = [_safe_filename(x) for x in images if isinstance(x, str)]
    return {"画师名/别名": name_val, "画师tag": tag_val, "_images": images}


def load_base_db(db_dir: str) -> List[Dict[str, Any]]:
    path = os.path.join(ROOT, db_dir, "artists_with_images.json")
    with open(path, "r", encoding="utf-8") as f:
        raw = json.load(f)
    return [normalize_artist_record(r) for r in raw if isinstance(r, dict)]


def build_tag_index(artists: Iterable[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    for a in artists:
        tag = (a.get("画师tag") or "").strip()
        if not tag:
            continue
        out[tag] = a
    return out


def danbooru_tag_search(q: str, timeout_s: int = 15) -> Optional[str]:
    """
    在 Danbooru 搜索 tags，返回 canonical name（若存在且为 artist 分类尽量匹配）。
    不保证一定找到，失败返回 None。
    """
    if not q:
        return None
    # Danbooru tags endpoint：/tags.json?search[name_matches]=...
    # 用 * 包含通配，避免候选里空格/下划线差异导致找不到
    url = "https://danbooru.donmai.us/tags.json"
    params = {
        "search[name_matches]": q,
        "limit": 5,
    }
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; x64)"}
    try:
        r = requests.get(url, params=params, headers=headers, timeout=timeout_s)
    except requests.exceptions.RequestException:
        return None
    if r.status_code != 200:
        return None
    try:
        data = r.json()
    except Exception:
        return None
    if not isinstance(data, list) or not data:
        # fallback：模糊
        params["search[name_matches]"] = q + "*"
        try:
            r = requests.get(url, params=params, headers=headers, timeout=timeout_s)
        except requests.exceptions.RequestException:
            return None
        if r.status_code != 200:
            return None
        try:
            data = r.json()
        except Exception:
            return None
    if isinstance(data, list) and data:
        # 优先 category == artist
        for item in data:
            if isinstance(item, dict) and item.get("category") == "artist" and item.get("name"):
                return str(item["name"])
        for item in data:
            if isinstance(item, dict) and item.get("name"):
                return str(item["name"])
    return None


def try_online_canonical_tag(tag_candidate: str, alias_candidate: str, display: str) -> str:
    """
    尝试用多个候选去联网搜索 canonical tag。
    """
    candidates: List[str] = []
    if tag_candidate:
        candidates.append(tag_candidate)
    if alias_candidate and alias_candidate not in candidates:
        candidates.append(alias_candidate)
    if display and display not in candidates:
        candidates.append(display)

    # space -> underscore 变体
    candidates2: List[str] = []
    for c in candidates:
        if " " in c:
            candidates2.append(c.replace(" ", "_"))
        if "(" in c and ")" in c:
            # 尝试只替换括号内容里的空格
            c2 = re.sub(r"\(([^()]*)\)", lambda m: "(" + m.group(1).replace(" ", "_") + ")", c)
            candidates2.append(c2)
    for c in candidates2:
        if c not in candidates:
            candidates.append(c)

    for q in candidates:
        found = danbooru_tag_search(q)
        if found:
            return found
    return tag_candidate or alias_candidate or display or ""


def iter_images(in_dir: str) -> List[str]:
    exts = (".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp")
    out: List[str] = []
    for name in os.listdir(in_dir):
        p = os.path.join(in_dir, name)
        if os.path.isfile(p) and name.lower().endswith(exts):
            out.append(name)
    return sorted(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-db", default="artist_export_1000", help="现有基础库目录名（相对 FMIYD 根目录）")
    ap.add_argument("--in-dir", default="画师2000\\精选", help="精选图片目录（相对 FMIYD 根目录）")
    ap.add_argument("--out", default="artist_export_2000", help="输出库目录名（相对 FMIYD 根目录）")
    ap.add_argument("--online", action="store_true", help="缺失画师时联网补全 tag（Danbooru）")
    ap.add_argument("--max-online", type=int, default=300, help="最多联网搜索多少次（避免太慢/被限流）")
    args = ap.parse_args()

    base_db_dir = os.path.join(ROOT, args.base_db)
    in_dir = os.path.join(ROOT, args.in_dir)
    out_dir = os.path.join(ROOT, args.out)
    out_images_dir = os.path.join(ROOT, "images", "xl", "drawings", "media")
    out_json_path = os.path.join(out_dir, "artists_with_images.json")

    if not os.path.isdir(in_dir):
        raise SystemExit(f"输入目录不存在：{in_dir}")
    if not os.path.isdir(base_db_dir):
        raise SystemExit(f"基础库目录不存在：{base_db_dir}")

    os.makedirs(out_images_dir, exist_ok=True)

    artists = load_base_db(args.base_db)
    tag_index = build_tag_index(artists)

    images = iter_images(in_dir)
    if not images:
        raise SystemExit(f"输入目录没有图片：{in_dir}")

    online_cnt = 0
    online_cache: Dict[str, str] = {}

    for img_name in images:
        display, tag_candidate, alias_candidate = parse_artist_from_filename(img_name)
        if not tag_candidate:
            continue
        tag = tag_candidate

        if tag in tag_index:
            # 直接追加图片
            tag_index[tag]["_images"].append(img_name)
        else:
            # 尝试匹配：tag candidate 可能只是别名或 prefix
            matched = False
            for key in [tag_candidate, alias_candidate]:
                key = (key or "").strip()
                if key and key in tag_index:
                    tag = key
                    tag_index[tag]["_images"].append(img_name)
                    matched = True
                    break
            if not matched:
                # 新画师：可选联网补全 canonical tag
                if args.online and online_cnt < args.max_online:
                    cache_key = f"{tag_candidate}|{alias_candidate}|{display}"
                    if cache_key in online_cache:
                        new_tag = online_cache[cache_key]
                    else:
                        new_tag = try_online_canonical_tag(tag_candidate, alias_candidate, display)
                        online_cache[cache_key] = new_tag
                        online_cnt += 1
                else:
                    new_tag = tag_candidate

                disp = _sanitize_display_name(display, new_tag) or (new_tag or tag_candidate or display)
                new_artist = {"画师名/别名": disp, "画师tag": new_tag, "_images": [img_name]}
                if new_tag:
                    tag_index[new_tag] = new_artist
                artists.append(new_artist)

        # 复制图片到输出库媒体目录
        src = os.path.join(in_dir, img_name)
        dst = os.path.join(out_images_dir, img_name)
        if not os.path.exists(dst):
            shutil.copy2(src, dst)

    # 去重 images
    for a in tag_index.values():
        ims = a.get("_images") or []
        # 去重保持顺序
        seen = set()
        out_list = []
        for x in ims:
            if x in seen:
                continue
            seen.add(x)
            out_list.append(x)
        a["_images"] = out_list

    # 写出 json
    os.makedirs(out_dir, exist_ok=True)
    artists_out = list(tag_index.values())
    # 稳定排序：按 tag 字符串
    artists_out.sort(key=lambda x: x.get("画师tag") or "")
    with open(out_json_path, "w", encoding="utf-8") as f:
        json.dump(artists_out, f, ensure_ascii=False)

    print("完成：")
    print("  输入图片数：", len(images))
    print("  输出画师数：", len(artists_out))
    print("  联网搜索次数：", online_cnt)
    print("  输出 JSON：", out_json_path)


if __name__ == "__main__":
    main()

