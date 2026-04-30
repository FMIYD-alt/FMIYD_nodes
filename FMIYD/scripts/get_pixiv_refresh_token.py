#!/usr/bin/env python3
import base64
import hashlib
import http.server
import json
import secrets
import socketserver
import sys
import threading
import urllib.parse
import urllib.request


LOGIN_URL = "https://app-api.pixiv.net/web/v1/login"
TOKEN_URL = "https://oauth.secure.pixiv.net/auth/token"
CALLBACK_PORT = 39001
CALLBACK_URL = f"http://127.0.0.1:{CALLBACK_PORT}/callback"
CLIENT_ID = "MOBrBDS8bl92oOtS2eT1SUSTRJOW2A2"
CLIENT_SECRET = "lsACyCD94FhDUtGgifgqcGwBsWSMgrntSWOzUFvk"
USER_AGENT = "PixivAndroidApp/5.0.234 (Android 11; Pixel 5)"


def _code_verifier() -> str:
    raw = secrets.token_urlsafe(48)
    return raw[:96]


def _code_challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def _build_login_url(challenge: str) -> str:
    q = urllib.parse.urlencode(
        {
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "client": "pixiv-android",
            "redirect_uri": CALLBACK_URL,
        }
    )
    return f"{LOGIN_URL}?{q}"


def _extract_code(callback_url: str) -> str:
    parsed = urllib.parse.urlparse(callback_url.strip())
    qs = urllib.parse.parse_qs(parsed.query)
    code = qs.get("code", [""])[0]
    if not code:
        raise ValueError("回调 URL 中未找到 code 参数。")
    return code


def _exchange_token(code: str, verifier: str) -> dict:
    form = urllib.parse.urlencode(
        {
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
            "grant_type": "authorization_code",
            "code": code,
            "code_verifier": verifier,
            "redirect_uri": CALLBACK_URL,
            "include_policy": "true",
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        TOKEN_URL,
        data=form,
        method="POST",
        headers={
            "User-Agent": USER_AGENT,
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        body = resp.read().decode("utf-8", errors="replace")
    return json.loads(body)


class _CallbackHandler(http.server.BaseHTTPRequestHandler):
    code_value = None
    event = None

    def log_message(self, format, *args):
        return

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path != "/callback":
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b"Not Found")
            return
        qs = urllib.parse.parse_qs(parsed.query)
        code = qs.get("code", [""])[0]
        if code:
            _CallbackHandler.code_value = code
            if _CallbackHandler.event is not None:
                _CallbackHandler.event.set()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write("登录成功，可回到终端。".encode("utf-8"))
        else:
            self.send_response(400)
            self.end_headers()
            self.wfile.write(b"Missing code")


def main() -> int:
    verifier = _code_verifier()
    challenge = _code_challenge(verifier)
    login_url = _build_login_url(challenge)
    evt = threading.Event()
    _CallbackHandler.event = evt

    try:
        httpd = socketserver.TCPServer(("127.0.0.1", CALLBACK_PORT), _CallbackHandler)
    except OSError as e:
        print(f"本地回调端口启动失败: {e}")
        return 10

    th = threading.Thread(target=httpd.serve_forever, daemon=True)
    th.start()

    print("\n=== Pixiv OAuth refresh_token 获取工具 ===")
    print("1) 在浏览器打开下面这个登录链接并登录授权：\n")
    print(login_url)
    print(f"\n2) 脚本已在本地监听 http://127.0.0.1:{CALLBACK_PORT}/callback")
    print("3) 登录成功后会自动抓取 code，无需手工复制 URL")
    print("4) 若 180 秒未完成会自动退出\n")

    ok = evt.wait(180)
    httpd.shutdown()
    httpd.server_close()
    code = _CallbackHandler.code_value if ok else None
    if not code:
        print("\n未自动收到回调。可直接粘贴 pixiv://account/login?... 链接。")
        manual = input("请粘贴 pixiv:// 链接或仅 code: ").strip()
        if not manual:
            print("未输入，已退出。")
            return 2
        if "code=" in manual:
            try:
                p = urllib.parse.urlparse(manual)
                qs = urllib.parse.parse_qs(p.query)
                code = qs.get("code", [""])[0].strip()
            except Exception:
                code = ""
        else:
            code = manual.strip()
        if not code:
            print("无法解析 code。")
            return 2

    try:
        data = _exchange_token(code, verifier)
    except Exception as e:
        print(f"换取 token 失败: {e}")
        return 3

    rt = data.get("refresh_token")
    at = data.get("access_token")
    user = (data.get("user") or {}).get("name")
    if not rt:
        print("响应里没有 refresh_token。原始响应如下：")
        print(json.dumps(data, ensure_ascii=False, indent=2))
        return 4

    print("\n=== 成功 ===")
    if user:
        print(f"用户: {user}")
    if at:
        print(f"access_token: {at}")
    print(f"refresh_token: {rt}")
    print("\n请把 refresh_token 填到 FMIYD 的 Pixiv 节点里。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
