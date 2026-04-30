# -*- coding: utf-8 -*-
"""
【离线灌库工具】从 Danbooru 拉图并**直接写入本仓库的本地画师库目录**（不是 ComfyUI 在线功能）。

重要区分：
- **ComfyUI / 画师图鉴画廊**：只读取本地 artist_export_catalog/（或回退目录）里的
  artists_with_images.json 与 images/xl/drawings/media/*，**运行时不会访问 Danbooru**。
- **本脚本**：仅在你本机手动执行时联网，把新图片保存到上述 media 文件夹，并改 JSON。
  灌库完成后，数据就是普通本地文件，可备份、拷盘、随项目走。

规则：
- 每个画师本地图片总数不超过 --max-per-artist（默认 3）；已有 N 张则只再补 (3-N) 张。
- 图片保存到：<库目录>/images/xl/drawings/media/
- 更新同目录下的 artists_with_images.json 的 _images 列表。

说明：
- 匿名访问可能被限流或 403，建议在 https://danbooru.donmai.us/profile 创建 API key，
  并设置环境变量：DANBOORU_LOGIN、DANBOORU_API_KEY，或使用命令行 --login / --api-key。
- 默认仅拉取 rating:general；需要其它分级可改 --rating（传空字符串表示不按分级过滤）。
- 若需代理：先设置环境变量 HTTPS_PROXY。

用法（在 FMIYD 根目录）：
  python scripts/fetch_danbooru_artist_images.py
  python scripts/fetch_danbooru_artist_images.py --db-dir artist_export_catalog --max-artists 50
  python scripts/fetch_danbooru_artist_images.py --dry-run
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
import time
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

try:
    import requests
except ImportError:
    print("请先安装 requests：pip install requests", file=sys.stderr)
    raise SystemExit(1)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

DEFAULT_UA = "FMIYDArtistFetcher/1.0 (local gallery enricher; contact: local)"
POSTS_URL = "https://danbooru.donmai.us/posts.json"


def _media_dir(db_dir: str) -> str:
    """本地图片统一写入扩展根目录 images/xl/drawings/media（与 db_dir 中的 JSON 分离）。"""
    return os.path.join(ROOT, "images", "xl", "drawings", "media")


def _json_path(db_dir: str) -> str:
    return os.path.join(ROOT, db_dir, "artists_with_images.json")


def normalize_danbooru_tag(tag: str) -> str:
    """
    本地库里的「画师tag」可能是「空格 + 括号别名」；Danbooru 多为下划线，且括注前常带 _。
    例：14sai bishoujo(shoutarou) -> 14sai_bishoujo_(shoutarou)
    """
    t = (tag or "").strip()
    if not t:
        return ""
    t = re.sub(r"\s+", "_", t)
    # 非 _ 后的左括号：补成 _( 以匹配站点上的 artist tag
    t = re.sub(r"(?<![_])\(", "_(", t)
    return t


def ext_from_url(url: str) -> str:
    try:
        path = urlparse(url).path or ""
        base = os.path.basename(path)
        if "." in base:
            e = base.rsplit(".", 1)[-1].lower()
            if e in ("jpg", "jpeg", "png", "webp", "gif"):
                return e
    except Exception:
        pass
    return "jpg"


def build_session(
    login: Optional[str],
    api_key: Optional[str],
    verify_ssl: bool,
) -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": DEFAULT_UA})
    if login and api_key:
        s.auth = (login, api_key)
    s.verify = verify_ssl
    return s


def fetch_posts_for_artist(
    session: requests.Session,
    artist_tag: str,
    limit: int,
    rating_tag: str,
    timeout: float,
) -> List[Dict[str, Any]]:
    """
    返回 Danbooru posts 列表（字典），按 score 降序（通过 tag order:score）。
    """
    nt = normalize_danbooru_tag(artist_tag)
    if not nt:
        return []
    parts = [nt, "order:score"]
    if rating_tag.strip():
        parts.append(rating_tag.strip())
    tags_q = " ".join(parts)

    try:
        r = session.get(
            POSTS_URL,
            params={"tags": tags_q, "limit": min(limit, 100)},
            timeout=timeout,
        )
    except requests.exceptions.RequestException as e:
        print(f"  [网络错误] {artist_tag}: {e}")
        return []

    if r.status_code == 403:
        print(f"  [403] {artist_tag}：可能被拒绝，请配置 DANBOORU_LOGIN + DANBOORU_API_KEY")
        return []
    if r.status_code != 200:
        print(f"  [HTTP {r.status_code}] {artist_tag}")
        return []

    try:
        data = r.json()
    except Exception:
        return []
    if not isinstance(data, list):
        return []
    return [p for p in data if isinstance(p, dict)]


def pick_image_url(post: Dict[str, Any]) -> Optional[str]:
    """优先 large，其次原图。"""
    for key in ("large_file_url", "file_url"):
        u = post.get(key)
        if isinstance(u, str) and u.startswith("http"):
            return u
    return None


def download_binary(session: requests.Session, url: str, timeout: float) -> Optional[bytes]:
    try:
        r = session.get(url, timeout=timeout, stream=True)
        if r.status_code != 200:
            return None
        return r.content
    except requests.exceptions.RequestException:
        return None


def load_db(path: str) -> List[Dict[str, Any]]:
    with open(path, "r", encoding="utf-8") as f:
        raw = json.load(f)
    if not isinstance(raw, list):
        return []
    return [x for x in raw if isinstance(x, dict)]


def save_db(path: str, data: List[Dict[str, Any]]) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    os.replace(tmp, path)


def main() -> None:
    ap = argparse.ArgumentParser(
        description="离线灌库：从 Danbooru 下载图片并写入本地 artist_export 目录（ComfyUI 画廊仍只读本地文件，不联网）"
    )
    ap.add_argument("--db-dir", default="artist_export_catalog", help="库目录名（相对 FMIYD 根）")
    ap.add_argument("--max-per-artist", type=int, default=3, help="每个画师本地图片总数上限")
    ap.add_argument(
        "--rating",
        default="rating:general",
        help="Danbooru 分级 tag，默认仅 general；不需要则传空字符串 \"\"",
    )
    ap.add_argument("--delay", type=float, default=1.2, help="每位画师请求之间的间隔（秒）")
    ap.add_argument("--timeout", type=float, default=45.0, help="单次 HTTP 超时（秒）")
    ap.add_argument("--max-artists", type=int, default=0, help="最多处理多少位画师（0=不限制）")
    ap.add_argument("--skip", type=int, default=0, help="跳过前 N 位画师（用于续跑）")
    ap.add_argument("--dry-run", action="store_true", help="只打印计划，不下载、不写库")
    ap.add_argument("--no-verify-ssl", action="store_true", help="关闭 SSL 校验（不推荐）")
    ap.add_argument(
        "--login",
        default=os.environ.get("DANBOORU_LOGIN", "") or "",
        help="Danbooru 登录名（或环境变量 DANBOORU_LOGIN）",
    )
    ap.add_argument(
        "--api-key",
        default=os.environ.get("DANBOORU_API_KEY", "") or "",
        help="Danbooru API Key（或环境变量 DANBOORU_API_KEY）",
    )
    ap.add_argument("--backup-json", action="store_true", help="运行前备份 artists_with_images.json 为 .bak")
    args = ap.parse_args()

    jp = _json_path(args.db_dir)
    media = _media_dir(args.db_dir)

    if not os.path.isfile(jp):
        raise SystemExit(f"找不到数据库：{jp}")

    login = (args.login or "").strip()
    api_key = (args.api_key or "").strip()
    if not login or not api_key:
        print(
            "提示：未设置 Danbooru 账号 API，匿名可能 403/限流。"
            "请在个人资料页创建 API Key，并设置 DANBOORU_LOGIN / DANBOORU_API_KEY。\n"
        )

    session = build_session(login or None, api_key or None, verify_ssl=not args.no_verify_ssl)
    db = load_db(jp)

    if args.backup_json and not args.dry_run:
        bak = jp + ".bak"
        shutil.copy2(jp, bak)
        print("已备份:", bak)

    os.makedirs(media, exist_ok=True)

    rating_suffix = (args.rating or "").strip()

    processed = 0
    new_downloads = 0
    json_reconciled = 0
    skipped_full = 0
    idx_artist = 0

    for rec in db:
        tag = (rec.get("画师tag") or "").strip()
        if not tag:
            continue

        idx_artist += 1
        if idx_artist <= args.skip:
            continue

        images = rec.get("_images") or []
        if not isinstance(images, list):
            images = []
        images = [os.path.basename(str(x)) for x in images if x]

        have = len(images)
        cap = max(0, args.max_per_artist)
        need = cap - have
        if need <= 0:
            skipped_full += 1
            continue

        if args.max_artists and processed >= args.max_artists:
            break

        processed += 1
        print(f"[{processed}] {tag} 已有 {have} 张，尝试补 {need} 张…")

        posts = fetch_posts_for_artist(
            session,
            tag,
            limit=max(need * 3, 10),
            rating_tag=rating_suffix,
            timeout=args.timeout,
        )
        if not posts:
            print("    （Danbooru 无结果：tag 可能不匹配或分级过滤过严）")

        added = 0
        for post in posts:
            if added >= need:
                break
            pid = post.get("id")
            if pid is None:
                continue
            img_url = pick_image_url(post)
            if not img_url:
                continue
            fname = f"danbooru_{pid}.{ext_from_url(img_url)}"
            if fname in images:
                continue

            dest = os.path.join(media, fname)
            if os.path.isfile(dest):
                if fname not in images:
                    images.append(fname)
                    added += 1
                    json_reconciled += 1
                    print(f"    已存在磁盘，已写入列表 {fname}")
                continue

            if args.dry_run:
                print(f"    dry-run: 将下载 post#{pid} -> {fname}")
                added += 1
                continue

            raw = download_binary(session, img_url, args.timeout)
            if not raw or len(raw) < 200:
                print(f"    跳过 post#{pid}：下载失败或过小")
                continue

            try:
                with open(dest, "wb") as out:
                    out.write(raw)
            except OSError as e:
                print(f"    写入失败 {fname}: {e}")
                continue

            images.append(fname)
            added += 1
            new_downloads += 1
            print(f"    + {fname}")

        rec["_images"] = images

        if not args.dry_run:
            save_db(jp, db)

        time.sleep(max(0.0, args.delay))

    print(
        f"\n完成：处理画师 {processed} 位；"
        f"跳过已满({args.max_per_artist}张) {skipped_full} 位；"
        f"新下载图片 {new_downloads} 张；"
        f"仅补全 JSON（磁盘已有）{json_reconciled} 张。"
    )
    if args.dry_run:
        print("（dry-run：未写入磁盘）")


if __name__ == "__main__":
    main()
