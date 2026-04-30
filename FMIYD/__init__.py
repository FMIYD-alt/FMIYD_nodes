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
    import threading as _threading

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

    # 更衣人偶：浏览器直连 api.github.com 易失败（限流、网络、CORS 环境），由本机 Comfy 进程代拉
    _KISEGAE_TREE_API = (
        "https://api.github.com/repos/hayde0096/Kisegaeningyou/git/trees/main?recursive=1"
    )
    _KISEGAE_CONTENTS_API_ROOT = "https://api.github.com/repos/hayde0096/Kisegaeningyou/contents"

    def _kisegae_github_fetch_sync(url: str) -> tuple[int, bytes]:
        req = _urllib_request.Request(
            url,
            headers={
                "User-Agent": "FMIYD-Kisegae-Gallery/1.0 (ComfyUI custom node)",
                "Accept": "application/vnd.github+json",
            },
        )
        try:
            with _urllib_request.urlopen(req, timeout=60) as resp:
                return int(getattr(resp, "status", 200) or 200), resp.read()
        except _urllib_error.HTTPError as e:
            try:
                body = e.read()
            except Exception:
                body = b'{"message":"HTTP error"}'
            return int(e.code), body
        except Exception:
            return 0, b'{"message":"network or timeout"}'

    @PromptServer.instance.routes.get("/fmiyd/kisegae_api/tree")
    async def _fmiyd_kisegae_api_tree(request):
        loop = _asyncio.get_event_loop()

        def run() -> tuple[int, bytes]:
            return _kisegae_github_fetch_sync(_KISEGAE_TREE_API)

        status, body = await loop.run_in_executor(None, run)
        if status != 200 or not body:
            st = 502 if status == 0 else (status if 400 <= status < 600 else 502)
            return web.Response(
                body=body if body else b'{"message":"upstream error"}',
                status=st,
                content_type="application/json",
            )
        return web.Response(
            body=body,
            status=200,
            content_type="application/json",
            headers={"Cache-Control": "public, max-age=180"},
        )

    @PromptServer.instance.routes.get("/fmiyd/kisegae_api/contents")
    async def _fmiyd_kisegae_api_contents(request):
        p = (request.query.get("p") or "").strip()
        if ".." in p or p.startswith("/") or p.startswith("\\"):
            return web.json_response({"message": "invalid path"}, status=400)
        parts = [seg for seg in p.replace("\\", "/").split("/") if seg and seg != ".."]
        safe = "/".join(parts)
        url = (
            _KISEGAE_CONTENTS_API_ROOT
            + ("/" + _urllib_parse.quote(safe, safe="") if safe else "")
        )
        loop = _asyncio.get_event_loop()

        def run() -> tuple[int, bytes]:
            return _kisegae_github_fetch_sync(url)

        status, body = await loop.run_in_executor(None, run)
        if status != 200 or not body:
            st = 502 if status == 0 else (status if 400 <= status < 600 else 502)
            return web.Response(
                body=body if body else b'{"message":"upstream error"}',
                status=st,
                content_type="application/json",
            )
        return web.Response(body=body, status=200, content_type="application/json")

    # ------------------------------------------------------------
    # 画师图鉴画廊（本地库：artist_export_catalog）
    # ------------------------------------------------------------
    _pkg_root = os.path.dirname(__file__)
    _artist_html_path = os.path.join(_web_dir, "artist_gallery_standalone.html")
    _danbooru_gallery_html_path = os.path.join(_web_dir, "danbooru_gallery_standalone.html")

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
        return web.FileResponse(
            _artist_html_path,
            headers={"Cache-Control": "no-store, max-age=0"},
        )

    @PromptServer.instance.routes.get("/fmiyd/danbooru_gallery")
    async def _serve_danbooru_gallery(request):
        return web.FileResponse(
            _danbooru_gallery_html_path,
            headers={"Cache-Control": "no-store, max-age=0"},
        )

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
    # Pixiv 画廊（官方 App API；需用户自行配置 OAuth refresh_token）
    # ------------------------------------------------------------
    _pixiv_html_path = _os.path.join(_web_dir, "pixiv_gallery_standalone.html")
    _pixiv_token_lock = _threading.Lock()
    _pixiv_access_cache: dict[str, tuple[str, float]] = {}
    _PIXIV_CLIENT_ID = "MOBrBDS8bl92oOtS2eT1SUSTRJOW2A2"
    _PIXIV_CLIENT_SECRET = "lsACyCD94FhDUtGgifgqcGwBsWSMgrntSWOzUFvk"
    _PIXIV_UA = "PixivAndroidApp/5.0.234 (Android 11; Pixel 5)"
    _PIXIV_WEB_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    # 与 web/pixiv_gallery_standalone.html 中 PAGE_SIZE 对齐；网页端每页条数与 App 不同，用于 offset→页码+切片
    _PIXIV_GALLERY_PAGE = 18
    _PIXIV_WEB_RANK_CHUNK = 50
    _PIXIV_WEB_SEARCH_CHUNK = 60

    def _pixiv_access_token_sync(refresh_token: str) -> str | None:
        """用 refresh_token 换 access_token（带简单内存缓存）。"""
        rt = (refresh_token or "").strip()
        if not rt:
            return None
        now = _time.time()
        with _pixiv_token_lock:
            hit = _pixiv_access_cache.get(rt)
            if hit and hit[1] > now + 90:
                return hit[0]
        form = _urllib_parse.urlencode(
            {
                "client_id": _PIXIV_CLIENT_ID,
                "client_secret": _PIXIV_CLIENT_SECRET,
                "grant_type": "refresh_token",
                "refresh_token": rt,
                "get_secure_url": "1",
            }
        ).encode("utf-8")
        req = _urllib_request.Request(
            "https://oauth.secure.pixiv.net/auth/token",
            data=form,
            method="POST",
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "User-Agent": _PIXIV_UA,
                "Accept": "application/json",
            },
        )
        try:
            with _urllib_request.urlopen(req, timeout=25) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
            data = json.loads(raw)
            at = data.get("access_token")
            if not isinstance(at, str) or not at:
                return None
            ex = int(data.get("expires_in") or 3600)
            with _pixiv_token_lock:
                _pixiv_access_cache[rt] = (at, now + max(30, ex - 120))
            return at
        except Exception:
            return None

    def _pixiv_app_get_bytes_sync(refresh_token: str, path_query: str) -> tuple[int, bytes]:
        """GET https://app-api.pixiv.net + path_query（须以 / 开头）。"""
        at = _pixiv_access_token_sync(refresh_token)
        if not at:
            return 401, b'{"error":"auth_failed","detail":"invalid or missing refresh_token"}'
        url = "https://app-api.pixiv.net" + path_query
        req = _urllib_request.Request(
            url,
            method="GET",
            headers={
                "User-Agent": _PIXIV_UA,
                "Authorization": "Bearer " + at,
                "Accept": "application/json",
            },
        )
        try:
            with _urllib_request.urlopen(req, timeout=30) as resp:
                return int(getattr(resp, "status", 200) or 200), resp.read()
        except _urllib_error.HTTPError as e:
            try:
                err_body = e.read()
            except Exception:
                err_body = b"{}"
            return int(e.code), err_body
        except Exception:
            return 0, b'{"error":"network"}'

    def _pixiv_me_user_sync(refresh_token: str) -> dict | None:
        """当前登录用户（需有效 refresh_token）。"""
        st, body = _pixiv_app_get_bytes_sync(refresh_token, "/v1/user/me")
        if st != 200:
            return None
        try:
            data = json.loads(body.decode("utf-8", errors="replace"))
        except Exception:
            return None
        u = data.get("user")
        return u if isinstance(u, dict) else None

    def _pixiv_proxy_src_allowed(url: str) -> bool:
        try:
            p = _urlparse(url)
            if (p.scheme or "").lower() != "https":
                return False
            h = (p.hostname or "").lower()
            return h.endswith("pximg.net") or h == "embed.pixiv.net"
        except Exception:
            return False

    def _pixiv_proxy_image_sync(url: str) -> tuple[str, bytes]:
        if not _pixiv_proxy_src_allowed(url):
            return "text/plain", b"forbidden"
        req = _urllib_request.Request(
            url,
            headers={
                "User-Agent": _PIXIV_UA,
                "Referer": "https://www.pixiv.net/",
                "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
            },
        )
        try:
            with _urllib_request.urlopen(req, timeout=45) as resp:
                data = resp.read()
                ct = resp.headers.get("Content-Type") or "image/jpeg"
                return ct.split(";")[0].strip(), data
        except Exception:
            return "text/plain", b""

    @PromptServer.instance.routes.get("/fmiyd/pixiv_gallery")
    async def _serve_pixiv_gallery(request):
        if not _os.path.isfile(_pixiv_html_path):
            raise web.HTTPNotFound()
        return web.FileResponse(
            _pixiv_html_path,
            headers={"Cache-Control": "no-store, max-age=0"},
        )

    def _pixiv_cookie_header_value(raw_cookie: str) -> str:
        c = (raw_cookie or "").strip()
        if not c:
            return ""
        if "..." in c:
            return ""
        if "=" in c:
            if c.lower().strip() in ("phpsessid=", "phpsessid=..."):
                return ""
            return c
        return f"PHPSESSID={c}"

    def _pixiv_uid_from_cookie(raw_cookie: str) -> int:
        """
        尝试从 Cookie 中提取 uid。
        常见 PHPSESSID 形如: 12345678_xxxxxxxxx
        """
        c = _pixiv_cookie_header_value(raw_cookie)
        if not c:
            return 0
        parts = [p.strip() for p in c.split(";") if p.strip()]
        sess = ""
        for p in parts:
            if p.lower().startswith("phpsessid="):
                sess = p.split("=", 1)[1].strip()
                break
        if not sess:
            return 0
        m = _re.match(r"^(\d+)_", sess)
        if not m:
            return 0
        try:
            return int(m.group(1))
        except Exception:
            return 0

    def _pixiv_uid_from_web_extra_sync(raw_cookie: str) -> int:
        """
        通过网页端登录态接口尝试解析当前 uid（Cookie 模式兜底）。
        """
        st, data = _pixiv_web_get_json_sync("/ajax/user/extra?lang=zh", raw_cookie)
        if st != 200 or not isinstance(data, dict) or data.get("error"):
            return 0
        body = data.get("body") if isinstance(data.get("body"), dict) else {}
        cand = body.get("userId") or body.get("id")
        try:
            uid = int(str(cand).strip())
            return uid if uid > 0 else 0
        except Exception:
            return 0

    def _pixiv_resolve_uid_cookie_sync(raw_cookie: str, uid_hint: str = "") -> int:
        if isinstance(uid_hint, str) and uid_hint.strip().isdigit():
            return int(uid_hint.strip())
        uid = _pixiv_uid_from_cookie(raw_cookie)
        if uid > 0:
            return uid
        return _pixiv_uid_from_web_extra_sync(raw_cookie)

    def _pixiv_web_get_json_sync(path_query: str, raw_cookie: str = "") -> tuple[int, dict]:
        url = "https://www.pixiv.net" + path_query
        headers = {
            "User-Agent": _PIXIV_WEB_UA,
            "Accept": "application/json",
            "Referer": "https://www.pixiv.net/",
            "X-Requested-With": "XMLHttpRequest",
        }
        c = _pixiv_cookie_header_value(raw_cookie)
        if c:
            headers["Cookie"] = c
        req = _urllib_request.Request(url, method="GET", headers=headers)
        try:
            with _urllib_request.urlopen(req, timeout=30) as resp:
                st = int(getattr(resp, "status", 200) or 200)
                body = resp.read().decode("utf-8", errors="replace")
        except _urllib_error.HTTPError as e:
            try:
                body = e.read().decode("utf-8", errors="replace")
            except Exception:
                body = "{}"
            st = int(e.code)
        except Exception:
            return 0, {"error": "network"}
        try:
            return st, json.loads(body)
        except Exception:
            return 502, {"error": "bad_json", "_raw": body[:300]}

    def _pixiv_norm_illust(item: dict) -> dict | None:
        if not isinstance(item, dict):
            return None
        iid = item.get("id") or item.get("illust_id")
        if iid is None:
            return None
        title = item.get("title") or ""
        urls = item.get("image_urls") if isinstance(item.get("image_urls"), dict) else {}
        urls_ajax = item.get("urls") if isinstance(item.get("urls"), dict) else {}
        thumb = item.get("url")
        reg = urls_ajax.get("regular") or urls_ajax.get("small") or urls_ajax.get("thumb_mini")
        orig = urls_ajax.get("original") or urls.get("original")
        sq = urls.get("square_medium") or urls_ajax.get("square") or thumb
        medium = urls.get("medium") or reg or urls_ajax.get("regular") or thumb
        large = urls.get("large") or urls_ajax.get("original") or orig or reg or medium
        img = large or medium or sq
        if not isinstance(img, str) or not img:
            return None
        dl = orig or large or medium
        xr = item.get("x_restrict")
        if xr is None:
            xr = item.get("xRestrict")
        if xr is None:
            xr = item.get("restrict")
        try:
            x_restrict = int(xr) if xr is not None else 0
        except Exception:
            x_restrict = 0
        sl = item.get("sanity_level")
        if sl is None:
            sl = item.get("sanityLevel")
        if sl is None:
            sl = item.get("sl")
        try:
            sanity_level = int(sl) if sl is not None else 0
        except Exception:
            sanity_level = 0
        return {
            "id": int(iid),
            "title": str(title),
            "image_urls": {
                "square_medium": sq or img,
                "medium": medium or img,
                "large": large or img,
            },
            "meta_single_page": {"original_image_url": dl or img},
            "_x_restrict": x_restrict,
            "_sanity_level": sanity_level,
        }

    def _pixiv_parse_bool_query(v: str | None, default: bool) -> bool:
        if v is None:
            return default
        s = str(v).strip().lower()
        if s in ("1", "true", "yes", "on"):
            return True
        if s in ("0", "false", "no", "off"):
            return False
        return default

    def _pixiv_rating_flags_from_request(request) -> tuple[bool, bool, bool]:
        show_r18 = _pixiv_parse_bool_query(request.query.get("show_r18"), False)
        show_r18g = _pixiv_parse_bool_query(request.query.get("show_r18g"), False)
        show_sensitive = _pixiv_parse_bool_query(request.query.get("show_sensitive"), True)
        return show_r18, show_r18g, show_sensitive

    def _pixiv_filter_illusts_by_rating(rows: list[dict], show_r18: bool, show_r18g: bool, show_sensitive: bool) -> list[dict]:
        out: list[dict] = []
        for it in rows:
            if not isinstance(it, dict):
                continue
            try:
                xr = int(it.get("_x_restrict") or 0)
            except Exception:
                xr = 0
            try:
                sl = int(it.get("_sanity_level") or 0)
            except Exception:
                sl = 0
            if xr >= 2 and not show_r18g:
                continue
            if xr == 1 and not show_r18:
                continue
            # Pixiv 常见 sanity_level: 2 普通, 4 轻微敏感, 6+ 更高敏感
            if sl >= 6 and not show_sensitive:
                continue
            out.append(it)
        return out

    def _pixiv_norm_follow_row(raw: dict) -> dict | None:
        """统一关注列表项为 { user: { id, name, account, profile_image_url } }（兼容 App / 网页多种字段）。"""
        if not isinstance(raw, dict):
            return None
        u = raw.get("user") if isinstance(raw.get("user"), dict) else raw
        if not isinstance(u, dict):
            return None
        uid = u.get("id") or u.get("userId") or u.get("user_id")
        if uid is None:
            return None
        try:
            uid_i = int(str(uid).strip())
        except Exception:
            return None
        name = str(u.get("name") or u.get("userName") or u.get("user_name") or "")
        account = str(u.get("account") or u.get("userAccount") or u.get("pixivId") or "")
        p = u.get("profileImageUrl") or u.get("profile_image_url")
        avatar = ""
        if isinstance(p, dict):
            avatar = str(p.get("medium") or p.get("large") or p.get("url") or "")
        elif isinstance(p, str):
            avatar = p
        if not avatar:
            for k in ("imageBig", "userIcon", "thumbnailUrl", "image", "url"):
                v = u.get(k)
                if isinstance(v, str) and v.startswith("http"):
                    avatar = v
                    break
        return {"user": {"id": uid_i, "name": name, "account": account, "profile_image_url": avatar, "profileImageUrl": avatar}}

    def _pixiv_web_user_illusts_cookie_sync(uid: int, offset: int, cookie: str) -> tuple[int, list[dict]]:
        """网页端：某用户插画列表（与 /pixiv/api/user_illusts Cookie 分支一致）。"""
        st0, all_data = _pixiv_web_get_json_sync(f"/ajax/user/{uid}/profile/all", cookie)
        ids = list((((all_data or {}).get("body") or {}).get("illusts") or {}).keys())
        sub = ids[offset : offset + 30]
        if not sub:
            return (200 if st0 == 200 else st0, [])
        qs = "&".join([f"ids%5B%5D={_urllib_parse.quote(str(i))}" for i in sub])
        st1, d1 = _pixiv_web_get_json_sync(
            f"/ajax/user/{uid}/profile/illusts?{qs}&work_category=illustManga&is_first_page=0",
            cookie,
        )
        works = (((d1 or {}).get("body") or {}).get("works") or {})
        rows = [works.get(str(i)) for i in sub if works.get(str(i))]
        out = [_pixiv_norm_illust(x) for x in rows]
        return (max(st0, st1) if st0 != 200 or st1 != 200 else 200, [x for x in out if x])

    def _pixiv_norm_illust_page_item(illust_id: int, idx: int, title: str, src: dict) -> dict | None:
        """标准化单张页面数据，供前端逐页选择。"""
        if not isinstance(src, dict):
            return None
        urls = src.get("image_urls") if isinstance(src.get("image_urls"), dict) else src.get("urls")
        if not isinstance(urls, dict):
            urls = src if isinstance(src, dict) else {}
        orig = urls.get("original") or urls.get("large") or urls.get("regular")
        med = urls.get("medium") or urls.get("regular") or urls.get("large") or orig
        sq = urls.get("square_medium") or urls.get("small") or med or orig
        img = orig or med or sq
        if not isinstance(img, str) or not img:
            return None
        try:
            iid = int(illust_id) * 1000 + int(idx)
        except Exception:
            iid = int(idx)
        return {
            "id": iid,
            "title": f"{title or illust_id} · P{idx + 1}",
            "image_urls": {"square_medium": sq or img, "medium": med or img, "large": orig or med or img},
            "meta_single_page": {"original_image_url": orig or med or img},
            "illust_id": int(illust_id),
            "page_index": int(idx),
        }

    @PromptServer.instance.routes.get("/fmiyd/pixiv/api/ranking")
    async def _pixiv_api_ranking(request):
        rt = request.headers.get("X-Pixiv-Refresh-Token", "").strip()
        cookie = request.headers.get("X-Pixiv-Cookie", "").strip()
        show_r18, show_r18g, show_sensitive = _pixiv_rating_flags_from_request(request)
        mode = (request.query.get("mode") or "day").strip() or "day"
        try:
            offset = max(0, int(request.query.get("offset", "0")))
        except ValueError:
            offset = 0
        loop = _asyncio.get_event_loop()
        if rt:
            q = _urllib_parse.urlencode({"mode": mode, "offset": offset, "filter": "for_ios"})
            status, body = await loop.run_in_executor(None, lambda: _pixiv_app_get_bytes_sync(rt, "/v1/illust/ranking?" + q))
            if status != 200:
                return web.Response(body=body, status=status if 200 <= status < 600 else 502, content_type="application/json")
            try:
                data = json.loads(body.decode("utf-8", errors="replace"))
            except Exception:
                return web.Response(body=body, status=200, content_type="application/json")
            rows = (data.get("illusts") if isinstance(data, dict) else None) or []
            out = [_pixiv_norm_illust(x if isinstance(x, dict) else {}) for x in rows]
            filtered = _pixiv_filter_illusts_by_rating([x for x in out if x], show_r18, show_r18g, show_sensitive)
            return web.json_response({"illusts": filtered}, status=200)
        # 排行榜是公开数据，Cookie 模式下改为匿名网页请求，避免坏 cookie 导致 502
        chunk = _PIXIV_WEB_RANK_CHUNK
        p = offset // chunk + 1
        start_in = offset % chunk
        mode_map = {"day": "daily", "week": "weekly", "month": "monthly", "day_male": "daily_r18", "day_female": "daily_r18g"}
        q = _urllib_parse.urlencode({"mode": mode_map.get(mode, "daily"), "content": "illust", "format": "json", "p": p})
        st, data = await loop.run_in_executor(None, lambda: _pixiv_web_get_json_sync("/ranking.php?" + q, ""))
        contents = data.get("contents") if isinstance(data, dict) else []
        flat = list(contents or [])
        page_slice = flat[start_in : start_in + _PIXIV_GALLERY_PAGE]
        out = [_pixiv_norm_illust(x) for x in page_slice]
        filtered = _pixiv_filter_illusts_by_rating([x for x in out if x], show_r18, show_r18g, show_sensitive)
        return web.json_response({"illusts": filtered}, status=200 if st == 200 else st)

    @PromptServer.instance.routes.get("/fmiyd/pixiv/api/search_illust")
    async def _pixiv_api_search_illust(request):
        rt = request.headers.get("X-Pixiv-Refresh-Token", "").strip()
        cookie = request.headers.get("X-Pixiv-Cookie", "").strip()
        show_r18, show_r18g, show_sensitive = _pixiv_rating_flags_from_request(request)
        word = (request.query.get("word") or "").strip()
        if not word:
            return web.json_response({"error": "empty_word"}, status=400)
        try:
            offset = max(0, int(request.query.get("offset", "0")))
        except ValueError:
            offset = 0
        sort = (request.query.get("sort") or "date_desc").strip()
        ratio = (request.query.get("ratio") or "").strip()
        loop = _asyncio.get_event_loop()
        if rt:
            q = _urllib_parse.urlencode(
                {
                    "word": word,
                    "search_target": "title_and_caption",
                    "sort": sort,
                    "filter": "for_ios",
                    "offset": offset,
                }
            )
            status, body = await loop.run_in_executor(None, lambda: _pixiv_app_get_bytes_sync(rt, "/v1/search/illust?" + q))
            if status != 200:
                return web.Response(body=body, status=status if 200 <= status < 600 else 502, content_type="application/json")
            try:
                data = json.loads(body.decode("utf-8", errors="replace"))
            except Exception:
                return web.Response(body=body, status=200, content_type="application/json")
            rows = (data.get("illusts") if isinstance(data, dict) else None) or []
            out = [_pixiv_norm_illust(x if isinstance(x, dict) else {}) for x in rows]
            filtered = _pixiv_filter_illusts_by_rating([x for x in out if x], show_r18, show_r18g, show_sensitive)
            return web.json_response({"illusts": filtered}, status=200)
        chunk = _PIXIV_WEB_SEARCH_CHUNK
        p = offset // chunk + 1
        start_in = offset % chunk
        order_map = {"date_desc": "date_d", "date_asc": "date_a", "popular_desc": "popular_d"}
        web_order = order_map.get(sort, "date_d")
        web_params = {"word": word, "order": web_order, "mode": "all", "p": p, "s_mode": "s_tag"}
        if ratio:
            web_params["ratio"] = ratio
        q_art = _urllib_parse.urlencode(web_params)
        path_seg = _urllib_parse.quote(word, safe="")

        def _search_artworks() -> tuple[int, dict]:
            return _pixiv_web_get_json_sync(f"/ajax/search/artworks/{path_seg}?{q_art}", cookie)

        st, data = await loop.run_in_executor(None, _search_artworks)
        rows_full = list((((data or {}).get("body") or {}).get("illustManga") or {}).get("data") or [])
        bad_html = isinstance(data, dict) and data.get("error") == "bad_json"
        try_user = st in (404, 403) or (st == 502 and bad_html)
        if try_user:

            def _search_users() -> tuple[int, dict]:
                q_u = _urllib_parse.urlencode({"word": word, "order": "date_d", "s_mode": "s_usr"})
                return _pixiv_web_get_json_sync(f"/ajax/search/users/{path_seg}?{q_u}", cookie)

            st2, data2 = await loop.run_in_executor(None, _search_users)
            users = (((data2 or {}).get("body") or {}).get("users") or [])
            if st2 == 200 and users:
                u0 = users[0] if isinstance(users[0], dict) else {}
                uid = u0.get("userId") or u0.get("id")
                if uid is not None:
                    try:
                        uid_i = int(str(uid).strip())
                    except Exception:
                        uid_i = 0
                    if uid_i > 0:

                        def _user_ill() -> tuple[int, list[dict]]:
                            return _pixiv_web_user_illusts_cookie_sync(uid_i, offset, cookie)

                        st3, ill = await loop.run_in_executor(None, _user_ill)
                        filtered_ill = _pixiv_filter_illusts_by_rating([x for x in ill if x], show_r18, show_r18g, show_sensitive)
                        return web.json_response(
                            {
                                "illusts": filtered_ill,
                                "search_via": "user_name",
                                "resolved_user_id": uid_i,
                            },
                            status=200 if st3 == 200 else st3,
                        )
            if try_user:
                return web.json_response(
                    {"illusts": [], "error": "search_failed", "detail": st, "user_search_http": st2},
                    status=200,
                )
        rows = rows_full[start_in : start_in + _PIXIV_GALLERY_PAGE]
        out = [_pixiv_norm_illust(x) for x in rows]
        filtered = _pixiv_filter_illusts_by_rating([x for x in out if x], show_r18, show_r18g, show_sensitive)
        return web.json_response({"illusts": filtered}, status=200 if st == 200 else st)

    @PromptServer.instance.routes.get("/fmiyd/pixiv/api/user_illusts")
    async def _pixiv_api_user_illusts(request):
        rt = request.headers.get("X-Pixiv-Refresh-Token", "").strip()
        cookie = request.headers.get("X-Pixiv-Cookie", "").strip()
        show_r18, show_r18g, show_sensitive = _pixiv_rating_flags_from_request(request)
        try:
            uid = int(request.query.get("user_id", "0"))
        except ValueError:
            uid = 0
        if uid <= 0:
            return web.json_response({"error": "bad_user_id"}, status=400)
        try:
            offset = max(0, int(request.query.get("offset", "0")))
        except ValueError:
            offset = 0
        loop = _asyncio.get_event_loop()
        if rt:
            q = _urllib_parse.urlencode({"user_id": uid, "type": "illust", "filter": "for_ios", "offset": offset})
            status, body = await loop.run_in_executor(None, lambda: _pixiv_app_get_bytes_sync(rt, "/v1/user/illusts?" + q))
            if status != 200:
                return web.Response(body=body, status=status if 200 <= status < 600 else 502, content_type="application/json")
            try:
                data = json.loads(body.decode("utf-8", errors="replace"))
            except Exception:
                return web.Response(body=body, status=200, content_type="application/json")
            rows = (data.get("illusts") if isinstance(data, dict) else None) or []
            out = [_pixiv_norm_illust(x if isinstance(x, dict) else {}) for x in rows]
            filtered = _pixiv_filter_illusts_by_rating([x for x in out if x], show_r18, show_r18g, show_sensitive)
            return web.json_response({"illusts": filtered}, status=200)
        st_w, ill = await loop.run_in_executor(None, lambda: _pixiv_web_user_illusts_cookie_sync(uid, offset, cookie))
        filtered = _pixiv_filter_illusts_by_rating([x for x in ill if x], show_r18, show_r18g, show_sensitive)
        return web.json_response({"illusts": filtered}, status=200 if st_w == 200 else st_w)

    @PromptServer.instance.routes.get("/fmiyd/pixiv/api/illust_pages")
    async def _pixiv_api_illust_pages(request):
        rt = request.headers.get("X-Pixiv-Refresh-Token", "").strip()
        cookie = request.headers.get("X-Pixiv-Cookie", "").strip()
        try:
            illust_id = int(request.query.get("illust_id", "0"))
        except ValueError:
            illust_id = 0
        title = (request.query.get("title") or "").strip()
        if illust_id <= 0:
            return web.json_response({"error": "bad_illust_id"}, status=400)
        loop = _asyncio.get_event_loop()
        if rt:
            q = _urllib_parse.urlencode({"illust_id": illust_id, "filter": "for_ios"})
            st, body = await loop.run_in_executor(None, lambda: _pixiv_app_get_bytes_sync(rt, "/v1/illust/detail?" + q))
            try:
                data = json.loads(body.decode("utf-8", errors="replace"))
            except Exception:
                data = {}
            ill = ((data or {}).get("illust") or {}) if isinstance(data, dict) else {}
            t = str(ill.get("title") or title or str(illust_id))
            u = ill.get("user") if isinstance(ill.get("user"), dict) else {}
            author = {
                "id": int(u.get("id") or 0) if str(u.get("id") or "0").isdigit() else 0,
                "name": str(u.get("name") or ""),
                "account": str(u.get("account") or ""),
                "avatar": str((u.get("profile_image_urls") or {}).get("medium") if isinstance(u.get("profile_image_urls"), dict) else (u.get("profile_image_url") or "")),
                "is_followed": bool(u.get("is_followed")),
            }
            pages = []
            raw_pages = ill.get("meta_pages")
            if isinstance(raw_pages, list) and raw_pages:
                for i, p in enumerate(raw_pages):
                    row = _pixiv_norm_illust_page_item(illust_id, i, t, p if isinstance(p, dict) else {})
                    if row:
                        pages.append(row)
            else:
                ms = ill.get("meta_single_page") if isinstance(ill.get("meta_single_page"), dict) else {}
                iu = ill.get("image_urls") if isinstance(ill.get("image_urls"), dict) else {}
                src = {"image_urls": {"original": ms.get("original_image_url") or iu.get("large") or iu.get("medium") or iu.get("square_medium"), "large": iu.get("large"), "medium": iu.get("medium"), "square_medium": iu.get("square_medium")}}
                row = _pixiv_norm_illust_page_item(illust_id, 0, t, src)
                if row:
                    pages.append(row)
            return web.json_response({"pages": pages, "illust_id": illust_id, "title": t, "author": author}, status=200 if st == 200 else st)

        st, data = await loop.run_in_executor(None, lambda: _pixiv_web_get_json_sync(f"/ajax/illust/{illust_id}/pages", cookie))
        st_meta, d_meta = await loop.run_in_executor(None, lambda: _pixiv_web_get_json_sync(f"/ajax/illust/{illust_id}", cookie))
        meta_body = ((d_meta or {}).get("body") or {}) if isinstance(d_meta, dict) else {}
        author = {
            "id": int(meta_body.get("userId") or 0) if str(meta_body.get("userId") or "0").isdigit() else 0,
            "name": str(meta_body.get("userName") or ""),
            "account": str(meta_body.get("userAccount") or ""),
            "avatar": str(meta_body.get("userIllusts") and "" or ""),
            "is_followed": bool(meta_body.get("isFollowed") or False),
        }
        rows = ((data or {}).get("body") or []) if isinstance(data, dict) else []
        pages = []
        if isinstance(rows, list) and rows:
            for i, p in enumerate(rows):
                row = _pixiv_norm_illust_page_item(illust_id, i, title or str(illust_id), p if isinstance(p, dict) else {})
                if row:
                    pages.append(row)
        if not pages:
            st2, d2 = (st_meta, d_meta)
            body = ((d2 or {}).get("body") or {}) if isinstance(d2, dict) else {}
            t = str(body.get("title") or title or str(illust_id))
            row = _pixiv_norm_illust_page_item(illust_id, 0, t, {"urls": body.get("urls") if isinstance(body.get("urls"), dict) else {}})
            if row:
                pages = [row]
            st = st2 if st != 200 else st
        return web.json_response({"pages": pages, "illust_id": illust_id, "title": title or str(illust_id), "author": author}, status=200 if st == 200 else st)

    @PromptServer.instance.routes.get("/fmiyd/pixiv/api/search_user")
    async def _pixiv_api_search_user(request):
        rt = request.headers.get("X-Pixiv-Refresh-Token", "").strip()
        cookie = request.headers.get("X-Pixiv-Cookie", "").strip()
        word = (request.query.get("word") or "").strip()
        if not word:
            return web.json_response({"error": "empty_word"}, status=400)
        try:
            offset = max(0, int(request.query.get("offset", "0")))
        except ValueError:
            offset = 0
        loop = _asyncio.get_event_loop()
        if word.isdigit():
            uid = int(word)
            if rt:
                q = _urllib_parse.urlencode({"user_id": uid, "filter": "for_ios"})
                st, body = await loop.run_in_executor(None, lambda: _pixiv_app_get_bytes_sync(rt, "/v1/user/detail?" + q))
                try:
                    data = json.loads(body.decode("utf-8", errors="replace"))
                except Exception:
                    data = {}
                one = _pixiv_norm_follow_row(((data or {}).get("user") or {}))
                out = [one] if one else []
                return web.json_response({"users": out, "user_previews": out}, status=200 if st == 200 else st)
            st, data = await loop.run_in_executor(None, lambda: _pixiv_web_get_json_sync(f"/ajax/user/{uid}", cookie))
            one = _pixiv_norm_follow_row(((data or {}).get("body") or {}))
            out = [one] if one else []
            return web.json_response({"users": out, "user_previews": out}, status=200 if st == 200 else st)
        if rt:
            q = _urllib_parse.urlencode({"word": word, "filter": "for_ios", "offset": offset})
            status, body = await loop.run_in_executor(None, lambda: _pixiv_app_get_bytes_sync(rt, "/v1/search/user?" + q))
            try:
                data = json.loads(body.decode("utf-8", errors="replace"))
            except Exception:
                data = {}
            raw_previews = (data.get("user_previews") if isinstance(data, dict) else None) or []
            out_users = []
            for p in raw_previews:
                row = _pixiv_norm_follow_row(p if isinstance(p, dict) else {})
                if row:
                    out_users.append(row)
            return web.json_response(
                {
                    "users": out_users,
                    "user_previews": out_users,
                },
                status=200 if status == 200 else status,
            )
        page = max(1, offset // _PIXIV_GALLERY_PAGE + 1)
        q = _urllib_parse.urlencode({"word": word, "order": "date_d", "s_mode": "s_usr", "p": page})
        st, data = await loop.run_in_executor(None, lambda: _pixiv_web_get_json_sync(f"/ajax/search/users/{_urllib_parse.quote(word)}?{q}", cookie))
        raw_users = (((data or {}).get("body") or {}).get("users") or [])
        users_out = []
        for u in raw_users:
            row = _pixiv_norm_follow_row(u if isinstance(u, dict) else {})
            if row:
                users_out.append(row)
        return web.json_response({"users": users_out, "user_previews": users_out}, status=200 if st == 200 else st)

    @PromptServer.instance.routes.get("/fmiyd/pixiv/api/me")
    async def _pixiv_api_me(request):
        rt = request.headers.get("X-Pixiv-Refresh-Token", "").strip()
        cookie = request.headers.get("X-Pixiv-Cookie", "").strip()
        uid = (request.headers.get("X-Pixiv-User-Id", "") or request.query.get("user_id", "") or "").strip()
        loop = _asyncio.get_event_loop()
        if rt:
            body = await loop.run_in_executor(None, lambda: _pixiv_app_get_bytes_sync(rt, "/v1/user/me")[1])
            try:
                return web.json_response(json.loads(body.decode("utf-8", errors="replace")))
            except Exception:
                return web.Response(body=body, content_type="application/json")
        if cookie:
            resolved_uid = _pixiv_resolve_uid_cookie_sync(cookie, uid)
            if resolved_uid <= 0:
                return web.json_response({"error": "cookie_user_id_unresolved"}, status=401)
            st, data = await loop.run_in_executor(None, lambda: _pixiv_web_get_json_sync(f"/ajax/user/{resolved_uid}", cookie))
            body = data.get("body") if isinstance(data, dict) else None
            if st == 200 and isinstance(body, dict):
                return web.json_response({"user": {"id": body.get("userId") or int(resolved_uid), "name": body.get("name") or body.get("userName") or "", "account": body.get("account") or ""}}, status=200)
            return web.json_response({"error": "cookie_invalid_or_expired"}, status=401)
        return web.json_response({"error": "missing_auth"}, status=401)

    @PromptServer.instance.routes.get("/fmiyd/pixiv/api/following")
    async def _pixiv_api_following(request):
        rt = request.headers.get("X-Pixiv-Refresh-Token", "").strip()
        cookie = request.headers.get("X-Pixiv-Cookie", "").strip()
        uid_hdr = (request.headers.get("X-Pixiv-User-Id", "") or request.query.get("user_id", "") or "").strip()
        try:
            offset = max(0, int(request.query.get("offset", "0")))
        except ValueError:
            offset = 0
        restrict = (request.query.get("restrict") or "public").strip() or "public"
        if restrict not in ("public", "private"):
            restrict = "public"
        loop = _asyncio.get_event_loop()
        if rt:
            def run_app_follow() -> tuple[int, bytes]:
                me = _pixiv_me_user_sync(rt)
                if not me or me.get("id") is None:
                    return 401, b'{"error":"me_failed"}'
                return _pixiv_app_get_bytes_sync(
                    rt,
                    "/v1/user/following?"
                    + _urllib_parse.urlencode(
                        {"user_id": int(me["id"]), "restrict": restrict, "offset": offset}
                    ),
                )
            status, body = await loop.run_in_executor(None, run_app_follow)
            return web.Response(body=body, status=status if 200 <= status < 600 else 502, content_type="application/json")
        uid_resolved = _pixiv_resolve_uid_cookie_sync(cookie, uid_hdr)
        if uid_resolved <= 0:
            return web.json_response({"error": "missing_user_id_for_cookie"}, status=400)
        rest = "show" if restrict == "public" else "hide"
        q = _urllib_parse.urlencode({"offset": offset, "limit": 24, "rest": rest})
        st, data = await loop.run_in_executor(None, lambda: _pixiv_web_get_json_sync(f"/ajax/user/{uid_resolved}/following?{q}", cookie))
        raw_users = (((data or {}).get("body") or {}).get("users") or [])
        users_out = []
        for item in raw_users:
            row = _pixiv_norm_follow_row(item if isinstance(item, dict) else {})
            if row:
                users_out.append(row)
        return web.json_response({"users": users_out}, status=200 if st == 200 else st)

    @PromptServer.instance.routes.get("/fmiyd/pixiv/api/bookmarks")
    async def _pixiv_api_bookmarks(request):
        rt = request.headers.get("X-Pixiv-Refresh-Token", "").strip()
        cookie = request.headers.get("X-Pixiv-Cookie", "").strip()
        show_r18, show_r18g, show_sensitive = _pixiv_rating_flags_from_request(request)
        uid_hdr = (request.headers.get("X-Pixiv-User-Id", "") or request.query.get("user_id", "") or "").strip()
        restrict = (request.query.get("restrict") or "public").strip() or "public"
        if restrict not in ("public", "private"):
            restrict = "public"
        max_bm = (request.query.get("max_bookmark_id") or "").strip()
        loop = _asyncio.get_event_loop()
        if rt:
            def run_app() -> tuple[int, bytes]:
                me = _pixiv_me_user_sync(rt)
                if not me or me.get("id") is None:
                    return 401, b'{"error":"me_failed"}'
                params: dict[str, str] = {"user_id": str(int(me["id"])), "restrict": restrict, "filter": "for_ios"}
                if max_bm.isdigit():
                    params["max_bookmark_id"] = max_bm
                return _pixiv_app_get_bytes_sync(rt, "/v1/user/bookmarks/illust?" + _urllib_parse.urlencode(params))
            status, body = await loop.run_in_executor(None, run_app)
            if status != 200:
                return web.Response(body=body, status=status if 200 <= status < 600 else 502, content_type="application/json")
            try:
                data = json.loads(body.decode("utf-8", errors="replace"))
            except Exception:
                return web.Response(body=body, status=200, content_type="application/json")
            rows = (data.get("illusts") if isinstance(data, dict) else None) or []
            out = [_pixiv_norm_illust(x if isinstance(x, dict) else {}) for x in rows]
            filtered = _pixiv_filter_illusts_by_rating([x for x in out if x], show_r18, show_r18g, show_sensitive)
            next_mid = ""
            next_url = str((data or {}).get("next_url") or "")
            if next_url:
                try:
                    parsed = _urllib_parse.urlparse(next_url)
                    qd = _urllib_parse.parse_qs(parsed.query)
                    n = qd.get("max_bookmark_id", [""])[0]
                    next_mid = str(n or "")
                except Exception:
                    next_mid = ""
            return web.json_response({"illusts": filtered, "next_max_bookmark_id": next_mid}, status=200)
        uid_resolved = _pixiv_resolve_uid_cookie_sync(cookie, uid_hdr)
        if uid_resolved <= 0:
            return web.json_response({"error": "missing_user_id_for_cookie"}, status=400)
        rest = "show" if restrict == "public" else "hide"
        q = {"tag": "", "offset": "0", "limit": "30", "rest": rest}
        if max_bm.isdigit():
            q["max_bookmark_id"] = max_bm
        st, data = await loop.run_in_executor(None, lambda: _pixiv_web_get_json_sync(f"/ajax/user/{uid_resolved}/illusts/bookmarks?{_urllib_parse.urlencode(q)}", cookie))
        rows = (((data or {}).get("body") or {}).get("works") or [])
        out = [_pixiv_norm_illust(x) for x in rows]
        filtered = _pixiv_filter_illusts_by_rating([x for x in out if x], show_r18, show_r18g, show_sensitive)
        next_mid = (((data or {}).get("body") or {}).get("bookmarkRanges") or {}).get("public", [None])[0]
        return web.json_response({"illusts": filtered, "next_max_bookmark_id": next_mid}, status=200 if st == 200 else st)

    @PromptServer.instance.routes.get("/fmiyd/pixiv/proxy_image")
    async def _pixiv_proxy_image(request):
        raw = request.query.get("url", "")
        try:
            url = _urllib_parse.unquote(raw)
        except Exception:
            url = raw
        loop = _asyncio.get_event_loop()

        def run() -> tuple[str, bytes]:
            return _pixiv_proxy_image_sync(url)

        ct, data = await loop.run_in_executor(None, run)
        if not data:
            raise web.HTTPNotFound()
        return web.Response(body=data, content_type=ct)

    # ------------------------------------------------------------
    # Danbooru 在线缩略图（posts.json + 可选图片代理，避免浏览器直连 CORS/防盗链）
    # ------------------------------------------------------------
    _DANBOORU_BASE_URL = "https://danbooru.donmai.us"
    _DANBOORU_POSTS_URL = f"{_DANBOORU_BASE_URL}/posts.json"
    _DANBOORU_TAGS_URL = f"{_DANBOORU_BASE_URL}/tags.json"
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

    def _danbooru_request_with_auth(
        url: str,
        method: str = "GET",
        login: str | None = None,
        api_key: str | None = None,
        body: bytes | None = None,
    ) -> tuple[int, str]:
        req = _urllib_request.Request(
            url,
            data=body,
            method=method.upper(),
            headers={
                "User-Agent": "FMIYD-DanbooruGallery/1.0",
                "Accept": "application/json",
            },
        )
        if login and api_key:
            import base64 as _b64

            tok = _b64.b64encode(f"{login}:{api_key}".encode("utf-8")).decode("ascii")
            req.add_header("Authorization", "Basic " + tok)
        if body is not None:
            req.add_header("Content-Type", "application/json")
        try:
            with _urllib_request.urlopen(req, timeout=25) as resp:
                return int(getattr(resp, "status", 200) or 200), resp.read().decode("utf-8", errors="replace")
        except _urllib_error.HTTPError as e:
            try:
                txt = e.read().decode("utf-8", errors="replace")
            except Exception:
                txt = ""
            return int(getattr(e, "code", 500) or 500), txt

    def _danbooru_check_network_sync() -> bool:
        st, _ = _danbooru_request_with_auth(f"{_DANBOORU_BASE_URL}/tags.json?limit=1")
        return st in (200, 204)

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

    def _danbooru_gallery_norm_posts(data: list) -> list[dict]:
        out: list[dict] = []
        if not isinstance(data, list):
            return out
        image_exts = {"jpg", "jpeg", "png", "webp", "gif", "avif"}
        for post in data:
            if not isinstance(post, dict):
                continue
            # favorites API 在部分情况下会返回 {"post": {...}} 结构
            if isinstance(post.get("post"), dict):
                post = post.get("post")
            pid = int(post.get("id") or 0)
            if pid <= 0:
                continue
            ext = str(post.get("file_ext") or "").strip().lower()
            if ext and ext not in image_exts:
                continue
            if bool(post.get("is_video")):
                continue
            p = post.get("preview_file_url") or ""
            l = post.get("large_file_url") or ""
            o = post.get("file_url") or l or p
            if not isinstance(o, str) or not o.startswith("http"):
                continue
            lo = o.lower()
            if any(lo.endswith("." + x) for x in ("mp4", "webm", "mkv", "mov", "avi", "swf", "zip")):
                continue
            out.append(
                {
                    "id": pid,
                    "title": f"ID {pid}",
                    "rating": str(post.get("rating") or ""),
                    "score": int(post.get("score") or 0),
                    "tags": str(post.get("tag_string") or ""),
                    "tag_string_artist": str(post.get("tag_string_artist") or ""),
                    "tag_string_copyright": str(post.get("tag_string_copyright") or ""),
                    "tag_string_character": str(post.get("tag_string_character") or ""),
                    "tag_string_general": str(post.get("tag_string_general") or ""),
                    "tag_string_meta": str(post.get("tag_string_meta") or ""),
                    "image_urls": {
                        "thumb": p if isinstance(p, str) else "",
                        "large": l if isinstance(l, str) else "",
                        "original": o if isinstance(o, str) else "",
                    },
                }
            )
        return out

    def _danbooru_gallery_fetch_posts_sync(
        mode: str,
        tags: str,
        page: int,
        limit: int,
        rating: str,
        login: str,
        api_key: str,
    ) -> tuple[list[dict], bool, bool, int, str]:
        def _convert_tags_to_api_format(tags_string: str) -> str:
            if not tags_string:
                return ""
            segs = [x for x in str(tags_string).replace("，", ",").split(",") if str(x).strip()]
            has_multi = len(segs) > 1
            known_metatag_prefixes = {
                "order",
                "rating",
                "id",
                "score",
                "fav",
                "date",
                "status",
                "source",
                "filetype",
                "width",
                "height",
                "mpixels",
                "parent",
                "child",
                "pool",
                "user",
            }
            out: list[str] = []
            for seg in segs:
                t = str(seg).strip()
                # 与 ComfyUI-Danbooru-Gallery 前端逻辑对齐：反转义括号。
                t = t.replace("\\(", "(").replace("\\)", ")")
                if ":" not in t:
                    t = "_".join(x for x in t.split() if x)
                else:
                    pfx = t.split(":", 1)[0].strip().lower()
                    # 只在多 tag 联查时处理未知前缀冒号，单 tag 保持原样。
                    if has_multi and pfx not in known_metatag_prefixes:
                        t = t.replace("\\", "\\\\").replace(":", "\\:")
                if t:
                    out.append(t)
            return " ".join(out)
        mode_n = (mode or "ranking").strip().lower()
        lim = max(1, min(int(limit), 50))
        fetch_lim = lim + 1
        pg = max(1, int(page))
        used_auth = False

        rt = (rating or "all").strip().lower()
        allowed_ratings = ("g", "s", "q", "e")
        if rt in ("", "all"):
            selected_ratings = set(allowed_ratings)
        else:
            toks = [x.strip().lower() for x in rt.replace("，", ",").split(",") if x.strip()]
            selected_ratings = {x for x in toks if x in allowed_ratings}
            if not selected_ratings:
                selected_ratings = set(allowed_ratings)
        single_rating = next(iter(selected_ratings)) if len(selected_ratings) == 1 else ""

        def _apply_selected_ratings(posts: list[dict]) -> list[dict]:
            if len(selected_ratings) == len(allowed_ratings):
                return posts
            return [p for p in posts if str(p.get("rating") or "").lower() in selected_ratings]

        # 收藏页：直接走 favorites.json（需要登录）
        if mode_n == "favorites":
            if not (login and api_key):
                raise RuntimeError("favorites_requires_login")
            # 优先用 posts.json + fav:login，返回结构更稳定，和普通列表一致
            fb_tags = f"fav:{login} order:score"
            fb_params = _urllib_parse.urlencode({"tags": fb_tags, "limit": str(fetch_lim), "page": str(pg)})
            fb_url = f"{_DANBOORU_POSTS_URL}?{fb_params}"
            try:
                raw = _danbooru_posts_request(fb_url, login, api_key)
                data = json.loads(raw)
                if not isinstance(data, list):
                    raise RuntimeError(f"favorites_posts_non_list_response: {str(data)[:240]}")
                posts = _apply_selected_ratings(_danbooru_gallery_norm_posts(data))
                has_more = len(data) > lim
                return posts[:lim], True, has_more, len(posts[:lim]), f"fav:{login} order:score"
            except Exception:
                # fallback: 兼容 favorites.json（某些实例对 fav:login 行为有差异）
                pass
            params = _urllib_parse.urlencode({"page": str(pg), "limit": str(fetch_lim)})
            url = f"{_DANBOORU_BASE_URL}/favorites.json?{params}"
            raw2 = _danbooru_posts_request(url, login, api_key)
            data2 = json.loads(raw2)
            if not isinstance(data2, list):
                raise RuntimeError(f"favorites_fallback_non_list_response: {str(data2)[:240]}")
            posts2 = _apply_selected_ratings(_danbooru_gallery_norm_posts(data2))
            has_more2 = len(data2) > lim
            return posts2[:lim], True, has_more2, len(posts2[:lim]), f"fav:{login} order:score"

        # 排行榜/搜索：与 ComfyUI-Danbooru-Gallery 搜索逻辑对齐
        # （逗号切分后转 API 格式，再按空格拼接标签）。
        # 与 ComfyUI-Danbooru-Gallery 对齐：前端已把输入转成 API tags。
        # 仅在明确是逗号输入时才做一次转换，避免后端重复转换破坏多 tag。
        tags_in = str(tags or "").strip()
        converted_tags = _convert_tags_to_api_format(tags_in) if ("," in tags_in or "，" in tags_in) else tags_in
        parts = [x for x in converted_tags.strip().split() if x]
        parts = [x for x in parts if not x.startswith("order:") and not x.startswith("rating:")]
        user_tag_count = len(parts)
        if mode_n == "search" and user_tag_count <= 0:
            return [], used_auth, False, 0, ""
        if mode_n == "search":
            parts.append("order:score")
        else:
            parts.append("order:rank")

        req_tags = " ".join(parts).strip()
        if single_rating:
            req_tags = f"{req_tags} rating:{single_rating}".strip()
        req_params: dict[str, str] = {
            "tags": req_tags,
            "limit": str(fetch_lim),
            "page": str(pg),
        }
        params = _urllib_parse.urlencode(req_params)
        url = f"{_DANBOORU_POSTS_URL}?{params}"
        try:
            raw = _danbooru_posts_request(url, None, None)
        except _urllib_error.HTTPError as e:
            code = int(getattr(e, "code", 0) or 0)
            if code in (401, 403, 429) and login and api_key:
                raw = _danbooru_posts_request(url, login, api_key)
                used_auth = True
            elif code == 422 and mode_n == "search":
                # 422 兜底：退化为“仅用户 tags”（不附加 order/rating）再试一次。
                fallback_tags = _convert_tags_to_api_format(tags or "").strip()
                if not fallback_tags:
                    return [], used_auth, False, 0, ""
                params2 = _urllib_parse.urlencode({"tags": fallback_tags, "limit": str(fetch_lim), "page": str(pg)})
                url2 = f"{_DANBOORU_POSTS_URL}?{params2}"
                try:
                    raw = _danbooru_posts_request(url2, login if login and api_key else None, api_key if login and api_key else None)
                    used_auth = bool(login and api_key)
                    req_tags = fallback_tags
                except _urllib_error.HTTPError as e2:
                    code2 = int(getattr(e2, "code", 0) or 0)
                    if code2 == 422:
                        # 不再把 422 当硬错误打断界面，返回空结果并保留查询串。
                        return [], bool(login and api_key), False, 0, fallback_tags
                    raise
            else:
                raise
        data = json.loads(raw)
        posts = _apply_selected_ratings(_danbooru_gallery_norm_posts(data))
        data_len = len(data) if isinstance(data, list) else 0
        has_more = data_len > lim
        out_posts = posts[:lim]
        return out_posts, used_auth, has_more, len(out_posts), req_tags

    @PromptServer.instance.routes.get("/fmiyd/danbooru_gallery/posts")
    async def _fmiyd_danbooru_gallery_posts(request):
        mode = (request.query.get("mode") or "ranking").strip()
        tags = (request.query.get("tags") or "").strip()
        rating = (request.query.get("rating") or "all").strip()
        try:
            page = int(request.query.get("page") or 1)
        except Exception:
            page = 1
        try:
            limit = int(request.query.get("limit") or 18)
        except Exception:
            limit = 18
        login = (request.headers.get("X-Danbooru-Login") or "").strip()
        api_key = (request.headers.get("X-Danbooru-Api-Key") or "").strip()
        loop = _asyncio.get_event_loop()
        try:
            posts, used_auth, has_more, matched_count, effective_tags = await loop.run_in_executor(
                None,
                lambda: _danbooru_gallery_fetch_posts_sync(mode, tags, page, limit, rating, login, api_key),
            )
        except Exception as e:
            return web.json_response({"error": str(e)}, status=502)
        return web.json_response(
            {
                "posts": posts,
                "page": max(1, page),
                "used_auth": used_auth,
                "mode": mode,
                "rating": rating,
                "has_more": has_more,
                "matched_count": matched_count,
                "effective_tags": effective_tags,
            },
            headers={"Cache-Control": "no-store, max-age=0"},
        )

    @PromptServer.instance.routes.get("/fmiyd/danbooru_gallery/tags")
    async def _fmiyd_danbooru_gallery_tags(request):
        q = (request.query.get("q") or "").strip()
        if not q:
            return web.json_response({"tags": []})
        login = (request.headers.get("X-Danbooru-Login") or "").strip()
        api_key = (request.headers.get("X-Danbooru-Api-Key") or "").strip()
        params = _urllib_parse.urlencode(
            {
                "search[name_or_alias_matches]": f"{q}*",
                "search[order]": "count",
                "limit": "20",
            }
        )
        url = f"{_DANBOORU_TAGS_URL}?{params}"
        used_auth = False
        try:
            raw = _danbooru_posts_request(url, None, None)
        except _urllib_error.HTTPError as e:
            code = int(getattr(e, "code", 0) or 0)
            if code in (401, 403, 429) and login and api_key:
                raw = _danbooru_posts_request(url, login, api_key)
                used_auth = True
            else:
                raise
        try:
            data = json.loads(raw)
        except Exception:
            data = []
        def _to_int_count(v) -> int:
            try:
                if isinstance(v, bool):
                    return 0
                if isinstance(v, (int, float)):
                    return max(0, int(v))
                s = str(v or "").strip()
                if not s:
                    return 0
                return max(0, int(float(s)))
            except Exception:
                return 0
        out: list[dict] = []
        if isinstance(data, list):
            for it in data:
                if not isinstance(it, dict):
                    continue
                name = str(it.get("name") or "").strip()
                if not name:
                    continue
                pc = _to_int_count(it.get("post_count"))
                if pc <= 0:
                    # 兼容不同返回字段，尽量贴近站内显示计数。
                    pc = max(pc, _to_int_count(it.get("posts_count")))
                    pc = max(pc, _to_int_count(it.get("count")))
                out.append(
                    {
                        "name": name,
                        "post_count": pc,
                        "category": int(it.get("category") or 0),
                    }
                )
        out.sort(key=lambda x: int(x.get("post_count") or 0), reverse=True)
        return web.json_response({"tags": out, "used_auth": used_auth}, headers={"Cache-Control": "no-store, max-age=0"})

    @PromptServer.instance.routes.get("/fmiyd/danbooru_gallery/check_network")
    async def _fmiyd_danbooru_gallery_check_network(request):
        loop = _asyncio.get_event_loop()
        ok = await loop.run_in_executor(None, _danbooru_check_network_sync)
        return web.json_response({"success": True, "connected": bool(ok)})

    @PromptServer.instance.routes.get("/fmiyd/danbooru_gallery/verify_auth")
    async def _fmiyd_danbooru_gallery_verify_auth(request):
        login = (request.headers.get("X-Danbooru-Login") or "").strip()
        api_key = (request.headers.get("X-Danbooru-Api-Key") or "").strip()
        if not (login and api_key):
            return web.json_response({"success": False, "valid": False, "error": "missing_credentials"}, status=400)
        loop = _asyncio.get_event_loop()

        def run():
            return _danbooru_request_with_auth(f"{_DANBOORU_BASE_URL}/profile.json", "GET", login, api_key)

        st, raw = await loop.run_in_executor(None, run)
        ok = st in (200, 204)
        return web.json_response({"success": ok, "valid": ok, "status": st, "raw": raw[:400] if not ok else ""}, status=(200 if ok else 401))

    @PromptServer.instance.routes.get("/fmiyd/danbooru_gallery/tags_by_category")
    async def _fmiyd_danbooru_gallery_tags_by_category(request):
        category = (request.query.get("category") or "general").strip().lower()
        try:
            page = max(1, int(request.query.get("page") or 1))
        except Exception:
            page = 1
        try:
            limit = max(1, min(int(request.query.get("limit") or 40), 100))
        except Exception:
            limit = 40
        cat_map = {"general": 0, "artist": 1, "copyright": 3, "character": 4, "meta": 5}
        if category not in cat_map:
            category = "general"
        login = (request.headers.get("X-Danbooru-Login") or "").strip()
        api_key = (request.headers.get("X-Danbooru-Api-Key") or "").strip()
        q = _urllib_parse.urlencode(
            {
                "search[category]": str(cat_map[category]),
                "search[order]": "count",
                "page": str(page),
                "limit": str(limit),
            }
        )
        url = f"{_DANBOORU_TAGS_URL}?{q}"
        loop = _asyncio.get_event_loop()

        def run():
            st, raw = _danbooru_request_with_auth(url, "GET", None, None)
            if st in (401, 403, 429) and login and api_key:
                st, raw = _danbooru_request_with_auth(url, "GET", login, api_key)
            return st, raw

        st, raw = await loop.run_in_executor(None, run)
        if st != 200:
            return web.json_response({"error": f"http_{st}"}, status=502)
        try:
            data = json.loads(raw)
        except Exception:
            data = []
        rows = []
        if isinstance(data, list):
            for it in data:
                if not isinstance(it, dict):
                    continue
                nm = str(it.get("name") or "").strip()
                if not nm:
                    continue
                rows.append(
                    {
                        "name": nm,
                        "post_count": int(it.get("post_count") or 0),
                        "category": int(it.get("category") or 0),
                    }
                )
        return web.json_response({"tags": rows, "category": category, "page": page, "limit": limit}, headers={"Cache-Control": "no-store, max-age=0"})

    @PromptServer.instance.routes.post("/fmiyd/danbooru_gallery/favorites/add")
    async def _fmiyd_danbooru_gallery_favorites_add(request):
        login = (request.headers.get("X-Danbooru-Login") or "").strip()
        api_key = (request.headers.get("X-Danbooru-Api-Key") or "").strip()
        if not (login and api_key):
            return web.json_response({"success": False, "error": "favorites_requires_login"}, status=401)
        try:
            body = await request.json()
        except Exception:
            body = {}
        pid = int((body or {}).get("post_id") or 0)
        if pid <= 0:
            return web.json_response({"success": False, "error": "invalid_post_id"}, status=400)
        url = f"{_DANBOORU_BASE_URL}/favorites.json"
        payload = json.dumps({"post_id": pid}).encode("utf-8")
        loop = _asyncio.get_event_loop()
        st, raw = await loop.run_in_executor(None, lambda: _danbooru_request_with_auth(url, "POST", login, api_key, payload))
        ok = st in (200, 201, 204, 422)
        return web.json_response({"success": ok, "status": st, "raw": raw[:300] if not ok else ""}, status=(200 if ok else 502))

    @PromptServer.instance.routes.post("/fmiyd/danbooru_gallery/favorites/remove")
    async def _fmiyd_danbooru_gallery_favorites_remove(request):
        login = (request.headers.get("X-Danbooru-Login") or "").strip()
        api_key = (request.headers.get("X-Danbooru-Api-Key") or "").strip()
        if not (login and api_key):
            return web.json_response({"success": False, "error": "favorites_requires_login"}, status=401)
        try:
            body = await request.json()
        except Exception:
            body = {}
        pid = int((body or {}).get("post_id") or 0)
        if pid <= 0:
            return web.json_response({"success": False, "error": "invalid_post_id"}, status=400)
        url = f"{_DANBOORU_BASE_URL}/favorites/{pid}.json"
        loop = _asyncio.get_event_loop()
        st, raw = await loop.run_in_executor(None, lambda: _danbooru_request_with_auth(url, "DELETE", login, api_key))
        ok = st in (200, 204)
        return web.json_response({"success": ok, "status": st, "raw": raw[:300] if not ok else ""}, status=(200 if ok else 502))
except Exception:
    pass

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS", "WEB_DIRECTORY"]
