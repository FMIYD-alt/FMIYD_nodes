# -*- coding: utf-8 -*-
"""
一键拉取 Drawing Spells 数据并生成「本地数据库」页面。
运行后会在 web/drawing_spells_data/ 生成 db.json，并生成带内嵌数据的 HTML。

可选：--download-imgs N  顺带把前 N 张图下到 drawing_spells_cache/imgs/，
这样不依赖实时访问外网，图片也能显示（例如：--download-imgs 500 可先下前 500 张）。
若本机需代理访问 GitHub，请先设置环境变量：set HTTPS_PROXY=http://127.0.0.1:7890 再运行。
"""
from __future__ import print_function
import os
import re
import json
import sys

try:
    from urllib.request import urlopen, Request
except ImportError:
    from urllib2 import urlopen, Request

BASE = "https://raw.githubusercontent.com/hbl917070/DrawingSpells/main/data/"
IMGS_RAW_BASE = "https://raw.githubusercontent.com/hbl917070/DrawingSpells/main/imgs/"
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(SCRIPT_DIR)
WEB = os.path.join(ROOT, "web")
DATA_DIR = os.path.join(WEB, "drawing_spells_data")
CACHE_IMGS_DIR = os.path.join(ROOT, "drawing_spells_cache", "imgs")
DB_JSON = os.path.join(DATA_DIR, "db.json")
HTML_TEMPLATE = os.path.join(WEB, "drawing_spells_standalone.html")
HTML_OUT = os.path.join(WEB, "drawing_spells_standalone_inlined.html")


def fetch(url, binary=False):
    req = Request(url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"})
    data = urlopen(req, timeout=30).read()
    return data if binary else data.decode("utf-8", errors="replace")


def download_images(char_list, limit):
    """把前 limit 张图片下载到 drawing_spells_cache/imgs/，与 ComfyUI 后端缓存目录一致。"""
    os.makedirs(CACHE_IMGS_DIR, exist_ok=True)
    done = 0
    for i, item in enumerate(char_list):
        if done >= limit:
            break
        f = (item or {}).get("file") or ""
        if not f or ".." in f or "/" in f or "\\" in f:
            continue
        safe = f.replace("\\", "_").replace("/", "_").strip()
        if safe != f:
            continue
        path = os.path.join(CACHE_IMGS_DIR, safe)
        if os.path.isfile(path):
            done += 1
            continue
        url = IMGS_RAW_BASE + f
        try:
            raw = fetch(url, binary=True)
            if len(raw) < 100:
                continue
            with open(path, "wb") as out:
                out.write(raw)
            done += 1
            if done % 50 == 0:
                print("  已下载 %d 张..." % done)
        except Exception:
            pass
    return done


def extract_js_array(text, var_name):
    """从 var _characterList = [...]; 或 var _imageCountList = {...}; 中提取 JSON。"""
    pattern = re.compile(r"var\s+" + re.escape(var_name) + r"\s*=\s*", re.I)
    m = pattern.search(text)
    if not m:
        return None
    start = m.end()
    if text[start] == "[":
        end_char = "]"
    elif text[start] == "{":
        end_char = "}"
    else:
        return None
    depth = 0
    i = start
    in_string = None
    escape = False
    while i < len(text):
        c = text[i]
        if escape:
            escape = False
            i += 1
            continue
        if c == "\\" and in_string:
            escape = True
            i += 1
            continue
        if in_string:
            if c == in_string:
                in_string = None
            i += 1
            continue
        if c in ("'", '"'):
            in_string = c
            i += 1
            continue
        if c == "[" or c == "{":
            depth += 1
        elif c == "]" or c == "}":
            depth -= 1
            if depth == 0 and c == end_char:
                return text[start : i + 1]
        i += 1
    return None


def main():
    download_imgs = 0
    if "--download-imgs" in sys.argv:
        idx = sys.argv.index("--download-imgs")
        if idx + 1 < len(sys.argv):
            try:
                download_imgs = int(sys.argv[idx + 1])
            except ValueError:
                pass
    if download_imgs < 0:
        download_imgs = 0

    print("正在拉取 characterList.js ...")
    char_js = fetch(BASE + "characterList.js")
    print("正在拉取 imageCountList.js ...")
    count_js = fetch(BASE + "imageCountList.js")

    print("解析 characterList ...")
    raw_char = extract_js_array(char_js, "_characterList")
    raw_count = extract_js_array(count_js, "_imageCountList")
    if not raw_char:
        print("解析 _characterList 失败", file=sys.stderr)
        sys.exit(1)
    # 兼容 JS 中的 \u0027 等
    try:
        char_list = json.loads(raw_char)
    except Exception as e:
        print("characterList JSON 解析失败:", e, file=sys.stderr)
        sys.exit(1)
    try:
        count_dict = json.loads(raw_count) if raw_count else {}
    except Exception:
        count_dict = {}

    os.makedirs(DATA_DIR, exist_ok=True)
    db = {"characterList": char_list, "imageCountList": count_dict}
    with open(DB_JSON, "w", encoding="utf-8") as f:
        json.dump(db, f, ensure_ascii=False, separators=(",", ":"))
    print("已写入", DB_JSON)

    if download_imgs > 0:
        print("正在下载前 %d 张图片到 %s ..." % (download_imgs, CACHE_IMGS_DIR))
        n = download_images(char_list, download_imgs)
        print("图片已缓存 %d 张，ComfyUI 将优先从本地读取。" % n)

    if not os.path.isfile(HTML_TEMPLATE):
        print("未找到模板", HTML_TEMPLATE, file=sys.stderr)
        return
    with open(HTML_TEMPLATE, "r", encoding="utf-8") as f:
        html = f.read()
    # 注入内嵌数据
    db_escaped = json.dumps(db, ensure_ascii=False).replace("\\", "\\\\").replace("</", "<\\/").replace("'", "\\'")
    inject = "window.__FMIYD_DS_DB__=JSON.parse('" + db_escaped + "');\n"
    html = html.replace("<script>\n(function() {", "<script>\n" + inject + "(function() {")
    # 在末尾改为：若有内嵌数据则直接用，否则 loadData
    old_tail = "    loadData(function() {\n        document.getElementById(\"status\").textContent = \"就绪，共 \" + processedList.length + \" 条\";\n        currentPage = 1;\n        render();\n    });\n})();"
    new_tail = "    if (window.__FMIYD_DS_DB__) {\n        _characterList = __FMIYD_DS_DB__.characterList || [];\n        _imageCountList = __FMIYD_DS_DB__.imageCountList || {};\n        processList();\n        document.getElementById(\"status\").textContent = \"就绪，共 \" + processedList.length + \" 条（本地数据）\";\n        currentPage = 1;\n        render();\n    } else {\n        loadData(function() {\n            document.getElementById(\"status\").textContent = \"就绪，共 \" + processedList.length + \" 条\";\n            currentPage = 1;\n            render();\n        });\n    }\n})();"
    if old_tail not in html:
        print("模板末尾未匹配，请检查 loadData 调用", file=sys.stderr)
    else:
        html = html.replace(old_tail, new_tail)
    with open(HTML_OUT, "w", encoding="utf-8") as f:
        f.write(html)
    print("已生成", HTML_OUT)
    print("完成。请重启 ComfyUI，二次元角色提示词查找将使用本地数据。")


if __name__ == "__main__":
    main()
