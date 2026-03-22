# FMIYD — 更衣人偶画廊节点

import os
from .nodes import NODE_CLASS_MAPPINGS, NODE_DISPLAY_NAME_MAPPINGS

# 前端脚本目录（ComfyUI 会加载 web/*.js）
WEB_DIRECTORY = "./web"

# 更衣人偶画廊独立页面：浏览器打开后选图可复制 tag，粘贴到节点的 prompt 框
try:
    from server import PromptServer
    from aiohttp import web
    import asyncio as _asyncio
    import json
    import os as _os
    import re as _re
    import time as _time
    import urllib.error as _urllib_error
    import urllib.parse as _urllib_parse
    import urllib.request as _urllib_request
    from urllib.parse import urlparse as _urlparse

    _JUNK_ARTIST_NAME_RE = _re.compile(r"^0\.\d{8,}$")

    def _sanitize_artist_display_name(name_val: str, tag_val: str) -> str:
        """误写入的随机小数（如 0.512016191496403）不作为展示名，退回画师 tag。"""
        t = (tag_val or "").strip() if isinstance(tag_val, str) else ""
        if isinstance(name_val, (int, float)) and not isinstance(name_val, bool):
            try:
                x = float(name_val)
                if 0 < x < 1:
                    return t if t and not _JUNK_ARTIST_NAME_RE.match(t) else ""
            except Exception:
                pass
            return str(name_val)
        if not isinstance(name_val, str):
            return ""
        n = name_val.strip()
        if _JUNK_ARTIST_NAME_RE.match(n):
            return t if t and not _JUNK_ARTIST_NAME_RE.match(t) else ""
        return n

    _web_dir = os.path.join(os.path.dirname(__file__), "web")
    _kisegae_html_path = os.path.join(_web_dir, "kisegae_standalone.html")

    @PromptServer.instance.routes.get("/fmiyd/kisegae")
    async def _serve_kisegae_gallery(request):
        return web.FileResponse(_kisegae_html_path)

    # ------------------------------------------------------------
    # 画师图鉴画廊（本地库：artist_export_catalog）
    # ------------------------------------------------------------
    _pkg_root = os.path.dirname(__file__)
    _artist_html_path = os.path.join(_web_dir, "artist_gallery_standalone.html")

    _artist_export_dir = os.path.join(_pkg_root, "artist_export_catalog")
    # 兼容：如果你还没合并/生成 catalog，则回退到 2000
    _export_2000_dir = os.path.join(_pkg_root, "artist_export_2000")
    if not _os.path.isdir(_artist_export_dir) and _os.path.isdir(_export_2000_dir):
        _artist_export_dir = _export_2000_dir
    _export_1000_dir = os.path.join(_pkg_root, "artist_export_1000")
    if not _os.path.isdir(_artist_export_dir) and _os.path.isdir(_export_1000_dir):
        _artist_export_dir = _export_1000_dir

    _artist_db_path = os.path.join(_artist_export_dir, "artists_with_images.json")
    # 与画师库同目录，供「随机画师串」排除 + 画廊禁止选中
    _artist_blacklist_path = _os.path.join(_os.path.dirname(_artist_db_path), "artist_blacklist.json")
    # 可选：离线灌库时的本地图目录（画廊缩略图已改为 Danbooru 在线；无此目录时不创建、不报错）
    _artist_images_media_dir = os.path.join(_pkg_root, "images", "xl", "drawings", "media")
    _legacy_media_dir = os.path.join(_artist_export_dir, "images", "xl", "drawings", "media")

    def _resolve_artist_media_dir() -> str | None:
        """若存在则优先根目录 images/.../media，否则旧版 catalog 下路径；都不存在则 None。"""
        try:
            if _os.path.isdir(_artist_images_media_dir):
                return _artist_images_media_dir
            if _os.path.isdir(_legacy_media_dir):
                return _legacy_media_dir
        except Exception:
            pass
        return None

    def _safe_join_media_dir(filename: str) -> str | None:
        try:
            if not filename:
                return None
            safe = _os.path.basename(filename)
            if not safe:
                return None
            base_dir = _resolve_artist_media_dir()
            if not base_dir:
                return None
            path = _os.path.join(base_dir, safe)
            # 防止穿越：确保最终路径在 media 目录下
            media_real = _os.path.realpath(base_dir)
            path_real = _os.path.realpath(path)
            if not path_real.startswith(media_real):
                return None
            return path
        except Exception:
            return None

    @PromptServer.instance.routes.get("/fmiyd/artist_gallery")
    async def _serve_artist_gallery(request):
        return web.FileResponse(_artist_html_path)

    @PromptServer.instance.routes.get("/fmiyd/artist_db")
    async def _serve_artist_db(request):
        with open(_artist_db_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        def _normalize_record(rec: dict) -> dict:
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

            name_val = _sanitize_artist_display_name(name_val, tag_val)

            images = rec.get("_images") or []
            if isinstance(images, list):
                images = [str(x) for x in images if isinstance(x, str)]
            else:
                images = []
            return {"画师名/别名": name_val, "画师tag": tag_val, "_images": images}

        if isinstance(data, list):
            data_out = [_normalize_record(r) for r in data if isinstance(r, dict)]
        else:
            data_out = []
        return web.json_response(data_out)

    @PromptServer.instance.routes.get("/fmiyd/artist_images")
    async def _serve_artist_images(request):
        filename = request.query.get("f", "")
        path = _safe_join_media_dir(filename)
        if not path or not _os.path.exists(path):
            raise web.HTTPNotFound()
        return web.FileResponse(path)

    # ------------------------------------------------------------
    # Danbooru 在线缩略图（posts.json + 可选图片代理，避免浏览器直连 CORS/防盗链）
    # ------------------------------------------------------------
    _DANBOORU_POSTS_URL = "https://danbooru.donmai.us/posts.json"
    _DANBOORU_TAGS_URL = "https://danbooru.donmai.us/tags.json"
    _danbooru_preview_cache: dict[tuple[str, int], tuple[list[str], float]] = {}
    _DANBOORU_PREVIEW_TTL = 300.0

    def _normalize_danbooru_tag(tag: str) -> str:
        """与 scripts/fetch_danbooru_artist_images.py 一致。"""
        t = (tag or "").strip() if isinstance(tag, str) else ""
        if not t:
            return ""
        t = _re.sub(r"\s+", "_", t)
        t = _re.sub(r"(?<![_])\(", "_(", t)
        return t

    def _artist_tag_dedupe_key(tag: str) -> str:
        """
        与 scripts/dedupe_artist_tags.py 中 normalize_tag_key 一致：
        用于判断「是否同一画师」（空格↔下划线、连续下划线、大小写忽略）。
        """
        if not isinstance(tag, str):
            return ""
        t = tag.strip().lower()
        t = _re.sub(r"\s+", "_", t)
        t = _re.sub(r"_+", "_", t)
        return t.strip("_")

    def _record_primary_tag(rec: dict) -> str:
        """从库记录中取画师 tag（与去重脚本一致，兼容键名变体）。"""
        v = rec.get("画师tag")
        if isinstance(v, str) and v.strip():
            return v.strip()
        for k, val in rec.items():
            if isinstance(k, str) and "tag" in k.lower() and isinstance(val, str) and val.strip():
                return val.strip()
        return ""

    def _artist_blacklist_read_sync() -> list[str]:
        """返回已规范化的 dedupe key 列表（有序、去重）。"""
        if not _os.path.isfile(_artist_blacklist_path):
            return []
        try:
            with open(_artist_blacklist_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            return []
        if not isinstance(data, list):
            return []
        seen: set[str] = set()
        out: list[str] = []
        for x in data:
            if not isinstance(x, str) or not x.strip():
                continue
            k = _artist_tag_dedupe_key(x)
            if not k or k in seen:
                continue
            seen.add(k)
            out.append(k)
        out.sort()
        return out

    def _artist_blacklist_write_sync(keys: list[str]) -> None:
        uniq: set[str] = set()
        for x in keys:
            if not isinstance(x, str):
                continue
            k = _artist_tag_dedupe_key(x)
            if k:
                uniq.add(k)
        ordered = sorted(uniq)
        parent = _os.path.dirname(_artist_blacklist_path)
        if parent and not _os.path.isdir(parent):
            _os.makedirs(parent, exist_ok=True)
        tmp = _artist_blacklist_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(ordered, f, ensure_ascii=False, indent=2)
            f.flush()
            _os.fsync(f.fileno())
        _os.replace(tmp, _artist_blacklist_path)

    def _artist_blacklist_remove_dedupe_key_sync(dedupe_key: str) -> None:
        k = _artist_tag_dedupe_key(dedupe_key)
        if not k or not _os.path.isfile(_artist_blacklist_path):
            return
        cur = _artist_blacklist_read_sync()
        if k not in cur:
            return
        _artist_blacklist_write_sync([x for x in cur if x != k])

    def _artist_blacklist_set_tag_sync(tag: str, blocked: bool) -> dict:
        raw = (tag or "").strip() if isinstance(tag, str) else ""
        if not raw:
            return {"error": "请提供画师 tag"}
        k = _artist_tag_dedupe_key(raw)
        if not k:
            return {"error": "无效的画师 tag"}
        cur = set(_artist_blacklist_read_sync())
        if blocked:
            cur.add(k)
        else:
            cur.discard(k)
        _artist_blacklist_write_sync(list(cur))
        return {"ok": True, "keys": sorted(cur), "dedupe_key": k, "blocked": blocked}

    def _danbooru_preview_cache_get(key: tuple[str, int]) -> list[str] | None:
        hit = _danbooru_preview_cache.get(key)
        if not hit:
            return None
        urls, ts = hit
        if _time.time() - ts > _DANBOORU_PREVIEW_TTL:
            try:
                del _danbooru_preview_cache[key]
            except Exception:
                pass
            return None
        return urls

    def _danbooru_preview_cache_set(key: tuple[str, int], urls: list[str]) -> None:
        _danbooru_preview_cache[key] = (urls, _time.time())

    def _danbooru_posts_request(url: str, login: str | None, api_key: str | None) -> str:
        """GET posts.json；login/api_key 为空或缺一则不带 Basic，等价于匿名。"""
        req = _urllib_request.Request(url, headers={"User-Agent": "FMIYD-ArtistGallery/1.0"})
        if login and api_key:
            import base64 as _b64

            tok = _b64.b64encode(f"{login}:{api_key}".encode("utf-8")).decode("ascii")
            req.add_header("Authorization", "Basic " + tok)
        with _urllib_request.urlopen(req, timeout=25) as resp:
            return resp.read().decode("utf-8", errors="replace")

    def _parse_danbooru_posts_json(raw: str) -> list[str]:
        data = json.loads(raw)
        if not isinstance(data, list):
            return []
        urls: list[str] = []
        for post in data:
            if not isinstance(post, dict):
                continue
            u = post.get("preview_file_url") or post.get("large_file_url") or post.get("file_url")
            if isinstance(u, str) and u.startswith("http"):
                urls.append(u)
        return urls

    def _fetch_danbooru_previews_sync(tags_q: str, login: str, api_key: str, limit: int) -> tuple[list[str], bool]:
        """
        优先匿名请求，减少带 Basic 鉴权的次数；仅在 401/403/429 且提供了 login+api_key 时再重试。
        返回 (urls, used_auth)。
        """
        params = _urllib_parse.urlencode({"tags": tags_q, "limit": str(limit)})
        url = f"{_DANBOORU_POSTS_URL}?{params}"
        used_auth = False
        raw: str
        try:
            raw = _danbooru_posts_request(url, None, None)
        except _urllib_error.HTTPError as e:
            try:
                detail = e.read().decode("utf-8", errors="replace")[:400]
            except Exception:
                detail = ""
            code = int(e.code)
            if code in (401, 403, 429) and login and api_key:
                try:
                    raw = _danbooru_posts_request(url, login, api_key)
                    used_auth = True
                except _urllib_error.HTTPError as e2:
                    try:
                        d2 = e2.read().decode("utf-8", errors="replace")[:400]
                    except Exception:
                        d2 = ""
                    raise RuntimeError(f"danbooru HTTP {e2.code} (with auth): {d2}") from e2
            else:
                raise RuntimeError(f"danbooru HTTP {code}: {detail}") from e
        urls = _parse_danbooru_posts_json(raw)
        return urls, used_auth

    def _danbooru_tags_fetch_list(url: str, login: str | None, api_key: str | None) -> list[dict]:
        raw = _danbooru_posts_request(url, login, api_key)
        data = json.loads(raw)
        if not isinstance(data, list):
            return []
        return [x for x in data if isinstance(x, dict)]

    def _danbooru_tags_search_name_matches(name_matches: str, login: str, api_key: str, limit: int = 25) -> list[dict]:
        params = _urllib_parse.urlencode({"search[name_matches]": name_matches, "limit": str(limit)})
        url = f"{_DANBOORU_TAGS_URL}?{params}"
        return _danbooru_tags_fetch_list(url, login or None, api_key or None)

    def _danbooru_tag_lookup_exact_name(name: str, login: str, api_key: str) -> dict | None:
        params = _urllib_parse.urlencode({"search[name]": name, "limit": "1"})
        url = f"{_DANBOORU_TAGS_URL}?{params}"
        lst = _danbooru_tags_fetch_list(url, login or None, api_key or None)
        return lst[0] if lst else None

    def _is_danbooru_artist_category(cat) -> bool:
        if cat == 1:
            return True
        if isinstance(cat, str):
            c = cat.strip().lower()
            if c == "artist" or c == "1":
                return True
        return False

    def _merge_tag_hits_by_name(hits: list[dict]) -> list[dict]:
        by_name: dict[str, dict] = {}
        for h in hits:
            n = h.get("name")
            if not isinstance(n, str) or not n:
                continue
            pc = int(h.get("post_count") or 0)
            old = by_name.get(n)
            if old is None or pc > int(old.get("post_count") or 0):
                by_name[n] = h
        return list(by_name.values())

    def _pick_best_artist_tag_name(items: list[dict]) -> str | None:
        artists = [it for it in items if _is_danbooru_artist_category(it.get("category")) and isinstance(it.get("name"), str)]
        if not artists:
            return None
        artists.sort(key=lambda x: int(x.get("post_count") or 0), reverse=True)
        return str(artists[0]["name"])

    def _resolve_artist_canonical_tag(query: str, login: str, api_key: str) -> tuple[str | None, str | None]:
        """(canonical_tag, error_message)"""
        q = (query or "").strip()
        if not q:
            return None, "请输入画师名或画师 tag"
        nq = _normalize_danbooru_tag(q)
        variants: list[str] = []
        for nm in (q, q + "*", nq, nq + "*"):
            if nm and nm not in variants:
                variants.append(nm)
        all_hits: list[dict] = []
        for nm in variants:
            try:
                hits = _danbooru_tags_search_name_matches(nm, login, api_key, 30)
            except Exception as e:
                return None, f"Danbooru 标签搜索失败：{e}"
            all_hits.extend(hits)
        merged = _merge_tag_hits_by_name(all_hits)
        best = _pick_best_artist_tag_name(merged)
        if best:
            return best, None
        if nq:
            try:
                exact = _danbooru_tag_lookup_exact_name(nq, login, api_key)
            except Exception as e:
                return None, f"Danbooru 查询失败：{e}"
            if exact and _is_danbooru_artist_category(exact.get("category")) and isinstance(exact.get("name"), str):
                return str(exact["name"]), None
        return None, "未在 Danbooru「画师」分类中找到匹配标签，请检查拼写或填写站点上的画师 tag"

    def _artist_add_to_local_db_sync(query: str, display_name: str, login: str, api_key: str) -> dict:
        canonical, err = _resolve_artist_canonical_tag(query, login, api_key)
        if err:
            return {"error": err}
        try:
            urls, _ = _fetch_danbooru_previews_sync(f"{canonical} order:score", login, api_key, 1)
        except Exception as e:
            return {"error": f"验证作品列表失败：{e}"}
        if not urls:
            return {"error": "Danbooru 上该画师 tag 暂无可用作品或未返回预览，无法加入图鉴（可稍后重试或填写 D 站账号）"}
        if not _os.path.isfile(_artist_db_path):
            return {"error": "本地画师库文件不存在，无法写入"}
        try:
            with open(_artist_db_path, "r", encoding="utf-8") as f:
                db = json.load(f)
        except Exception as e:
            return {"error": f"读取本地库失败：{e}"}
        if not isinstance(db, list):
            return {"error": "本地画师库格式无效"}
        norm_c = _artist_tag_dedupe_key(canonical)
        if not norm_c:
            return {"error": "无法生成有效的画师 tag 键"}
        for rec in db:
            if not isinstance(rec, dict):
                continue
            t = _record_primary_tag(rec)
            if _artist_tag_dedupe_key(t) == norm_c:
                return {"error": "库中已存在该画师（与已有条目仅空格/下划线/大小写不同，视为同一人）"}
        disp = (display_name or "").strip()
        if not disp:
            disp = canonical.replace("_", " ")
        disp = _sanitize_artist_display_name(disp, canonical)
        if not disp:
            disp = canonical.replace("_", " ")
        new_rec = {"画师tag": canonical, "画师名/别名": disp, "_images": []}
        db.append(new_rec)
        tmp = _artist_db_path + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(db, f, ensure_ascii=False, indent=2)
                f.flush()
                _os.fsync(f.fileno())
            _os.replace(tmp, _artist_db_path)
        except Exception as e:
            try:
                if _os.path.isfile(tmp):
                    _os.remove(tmp)
            except Exception:
                pass
            return {"error": f"写入本地库失败：{e}"}
        return {"ok": True, "record": new_rec}

    def _artist_delete_from_local_db_sync(tag: str) -> dict:
        """按与添加/去重相同的 dedupe key 删除一条画师记录。"""
        raw = (tag or "").strip() if isinstance(tag, str) else ""
        if not raw:
            return {"error": "请提供要删除的画师 tag"}
        if not _os.path.isfile(_artist_db_path):
            return {"error": "本地画师库文件不存在"}
        try:
            with open(_artist_db_path, "r", encoding="utf-8") as f:
                db = json.load(f)
        except Exception as e:
            return {"error": f"读取本地库失败：{e}"}
        if not isinstance(db, list):
            return {"error": "本地画师库格式无效"}
        norm_del = _artist_tag_dedupe_key(raw)
        if not norm_del:
            return {"error": "无效的画师 tag"}
        new_db: list = []
        removed: dict | None = None
        for rec in db:
            if not isinstance(rec, dict):
                new_db.append(rec)
                continue
            t = _record_primary_tag(rec)
            if removed is None and _artist_tag_dedupe_key(t) == norm_del:
                removed = rec
                continue
            new_db.append(rec)
        if removed is None:
            return {"error": "本地库中未找到该画师（可能已删除或与库内写法不一致）"}
        tmp = _artist_db_path + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(new_db, f, ensure_ascii=False, indent=2)
                f.flush()
                _os.fsync(f.fileno())
            _os.replace(tmp, _artist_db_path)
        except Exception as e:
            try:
                if _os.path.isfile(tmp):
                    _os.remove(tmp)
            except Exception:
                pass
            return {"error": f"写入本地库失败：{e}"}
        try:
            _artist_blacklist_remove_dedupe_key_sync(norm_del)
        except Exception:
            pass
        return {"ok": True, "removed_tag": _record_primary_tag(removed)}

    @PromptServer.instance.routes.get("/fmiyd/artist_blacklist")
    async def _fmiyd_artist_blacklist_get(request):
        loop = _asyncio.get_event_loop()
        try:
            keys = await loop.run_in_executor(None, _artist_blacklist_read_sync)
        except Exception as e:
            return web.json_response({"error": str(e)}, status=500)
        return web.json_response({"keys": keys})

    @PromptServer.instance.routes.post("/fmiyd/artist_blacklist_set")
    async def _fmiyd_artist_blacklist_set(request):
        try:
            body = await request.json()
        except Exception:
            return web.json_response({"error": "invalid json"}, status=400)
        if not isinstance(body, dict):
            return web.json_response({"error": "invalid body"}, status=400)
        tag = (body.get("tag") or "").strip()
        blocked = bool(body.get("blocked"))
        loop = _asyncio.get_event_loop()
        try:
            result = await loop.run_in_executor(
                None,
                lambda: _artist_blacklist_set_tag_sync(tag, blocked),
            )
        except Exception as e:
            return web.json_response({"error": str(e)}, status=500)
        if result.get("error"):
            return web.json_response({"error": result["error"]}, status=400)
        return web.json_response(result)

    @PromptServer.instance.routes.post("/fmiyd/artist_delete")
    async def _fmiyd_artist_delete(request):
        try:
            body = await request.json()
        except Exception:
            return web.json_response({"error": "invalid json"}, status=400)
        if not isinstance(body, dict):
            return web.json_response({"error": "invalid body"}, status=400)
        tag = (body.get("tag") or "").strip()
        loop = _asyncio.get_event_loop()
        try:
            result = await loop.run_in_executor(
                None,
                lambda: _artist_delete_from_local_db_sync(tag),
            )
        except Exception as e:
            return web.json_response({"error": str(e)}, status=500)
        if result.get("error"):
            return web.json_response({"error": result["error"]}, status=400)
        return web.json_response(result)

    @PromptServer.instance.routes.post("/fmiyd/artist_add")
    async def _fmiyd_artist_add(request):
        try:
            body = await request.json()
        except Exception:
            return web.json_response({"error": "invalid json"}, status=400)
        if not isinstance(body, dict):
            return web.json_response({"error": "invalid body"}, status=400)
        query = (body.get("query") or "").strip()
        display_name = (body.get("name") or "").strip()
        login = (body.get("login") or "").strip()
        api_key = (body.get("api_key") or "").strip()
        loop = _asyncio.get_event_loop()
        try:
            result = await loop.run_in_executor(
                None,
                lambda: _artist_add_to_local_db_sync(query, display_name, login, api_key),
            )
        except Exception as e:
            return web.json_response({"error": str(e)}, status=500)
        if result.get("error"):
            return web.json_response({"error": result["error"]}, status=400)
        return web.json_response(result)

    def _is_allowed_danbooru_cdn_url(url: str) -> bool:
        try:
            h = (_urlparse(url).hostname or "").lower()
            return h.endswith(".donmai.us") or h == "donmai.us"
        except Exception:
            return False

    def _fetch_danbooru_image_bytes_sync(url: str) -> tuple[bytes, str]:
        req = _urllib_request.Request(url, headers={"User-Agent": "FMIYD-ArtistGallery/1.0"})
        with _urllib_request.urlopen(req, timeout=30) as resp:
            data = resp.read()
            if len(data) > 4 * 1024 * 1024:
                raise ValueError("image too large")
            ct = (resp.headers.get("Content-Type") or "application/octet-stream").split(";")[0].strip()
            if not (ct.startswith("image/") or ct == "application/octet-stream"):
                raise ValueError("not an image response")
            return data, ct

    @PromptServer.instance.routes.post("/fmiyd/danbooru_preview")
    async def _danbooru_preview(request):
        try:
            body = await request.json()
        except Exception:
            return web.json_response({"error": "invalid json"}, status=400)
        raw_tag = (body.get("tag") or "").strip() if isinstance(body, dict) else ""
        try:
            limit = int((body.get("limit") if isinstance(body, dict) else 1) or 1)
        except Exception:
            limit = 1
        limit = max(1, min(limit, 50))
        login = ""
        api_key = ""
        if isinstance(body, dict):
            login = (body.get("login") or "").strip()
            api_key = (body.get("api_key") or "").strip()
        nt = _normalize_danbooru_tag(raw_tag)
        if not nt:
            return web.json_response({"error": "empty tag"}, status=400)
        tags_q = f"{nt} order:score"
        ckey = (nt, limit)
        cached = _danbooru_preview_cache_get(ckey)
        if cached is not None:
            return web.json_response({"urls": cached, "cached": True, "used_auth": None})
        loop = _asyncio.get_event_loop()
        try:
            urls, used_auth = await loop.run_in_executor(None, _fetch_danbooru_previews_sync, tags_q, login, api_key, limit)
        except Exception as e:
            return web.json_response({"error": str(e)}, status=502)
        _danbooru_preview_cache_set(ckey, urls)
        return web.json_response({"urls": urls, "cached": False, "used_auth": used_auth})

    @PromptServer.instance.routes.get("/fmiyd/danbooru_preview_image")
    async def _danbooru_preview_image(request):
        raw = request.query.get("url", "")
        if not isinstance(raw, str) or not raw.startswith("https://") or len(raw) > 2048:
            raise web.HTTPBadRequest()
        if not _is_allowed_danbooru_cdn_url(raw):
            raise web.HTTPForbidden()
        loop = _asyncio.get_event_loop()
        try:
            data, ct = await loop.run_in_executor(None, _fetch_danbooru_image_bytes_sync, raw)
        except Exception as e:
            return web.json_response({"error": str(e)}, status=502)
        return web.Response(
            body=data,
            content_type=ct,
            headers={"Cache-Control": "public, max-age=86400"},
        )
except Exception:
    pass

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS", "WEB_DIRECTORY"]
