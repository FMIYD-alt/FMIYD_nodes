import datetime
import hashlib
import urllib.error
import urllib.parse
import urllib.request

code = "u4q6aw5PtScVTUMKl3k9AZXC0IciTT-uK-GvlO-KXac"
verifier = "BL94ocknl0d547evGCDlqctX6LzaMxHbOR5-8C9_zB2wtHCzZmRs2607Ae_qVHzo"

combos = [
    (
        "MOBrBDS8bl92oOtS2eT1SUSTRJOW2A2",
        "lsACyCD94FhDUtGgifgqcGwBsWSMgrntSWOzUFvk",
        "PixivAndroidApp/5.0.234 (Android 11; Pixel 5)",
    ),
    (
        "MOBrBDS8blbauoSck0ZfDbtuzpyT",
        "lsACyCD94FhDUtGTXi3QzcFE2uU1hqtDaKeqrdwj",
        "PixivIOSApp/7.13.3 (iOS 14.6; iPhone13,2)",
    ),
]

for cid, csec, ua in combos:
    t = datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S+00:00")
    h = hashlib.md5((t + "28c1fdd170a5204386cb1313c7077b34f83e4aaf4aa829ce78c231e05b0bae2c").encode()).hexdigest()
    data = urllib.parse.urlencode(
        {
            "client_id": cid,
            "client_secret": csec,
            "grant_type": "authorization_code",
            "code": code,
            "code_verifier": verifier,
            "redirect_uri": "https://app-api.pixiv.net/web/v1/users/auth/pixiv/callback",
            "include_policy": "true",
            "get_secure_url": "1",
        }
    ).encode()
    req = urllib.request.Request(
        "https://oauth.secure.pixiv.net/auth/token",
        data=data,
        method="POST",
        headers={
            "User-Agent": ua,
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
            "x-client-time": t,
            "x-client-hash": h,
            "app-os": "ios",
            "app-os-version": "14.6",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = resp.read().decode("utf-8", errors="replace")
        print("SUCCESS", cid)
        print(body)
        break
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        print("FAIL", cid, e.code, body[:300])
