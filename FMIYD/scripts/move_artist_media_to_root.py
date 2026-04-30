# -*- coding: utf-8 -*-
"""
将本地画师图片从 artist_export_catalog/images/.../media 迁移到项目根目录：
  <FMIYD>/images/xl/drawings/media/

迁移后 artists_with_images.json 仍只存文件名（basename），由 __init__.py 指向新目录。

用法（FMIYD 根目录）：
  python scripts/move_artist_media_to_root.py
  python scripts/move_artist_media_to_root.py --dry-run
"""

from __future__ import annotations

import argparse
import os
import shutil

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    src = os.path.join(ROOT, "artist_export_catalog", "images", "xl", "drawings", "media")
    dst = os.path.join(ROOT, "images", "xl", "drawings", "media")

    if not os.path.isdir(src):
        print("源目录不存在，跳过：", src)
        return

    os.makedirs(dst, exist_ok=True)
    names = [f for f in os.listdir(src) if os.path.isfile(os.path.join(src, f))]
    moved = 0
    for fn in names:
        s = os.path.join(src, fn)
        d = os.path.join(dst, fn)
        if args.dry_run:
            print("would move:", fn)
            moved += 1
            continue
        if os.path.exists(d):
            try:
                os.remove(s)
            except OSError:
                pass
            continue
        shutil.move(s, d)
        moved += 1
    print("已迁移文件数:", moved)
    print("目标:", dst)
    if not args.dry_run and moved and not os.listdir(src):
        try:
            os.removedirs(src)
        except OSError:
            pass


if __name__ == "__main__":
    main()
