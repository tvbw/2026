# -*- coding: utf-8 -*-
"""
红果短剧 Spider（2026-10 修复版）
=========================================
相对原版改动：
1. 新增 _GLOBAL_COOKIE / _pc_headers()：去游客态，SSR HTML 可正常返回
2. _page() 不再强依赖 _ROUTER_DATA
3. _data() 支持多种 JSON 注入格式
4. 新增 _parse_cards_html()：SSR HTML 兜底解析
5. categoryContent() 走新 URL：/category/{slug}?page=N
6. homeContent / homeVideoContent / detailContent 均加 HTML 兜底
7. init() 支持从 extend 读取 cookie
8. 播放 / CENC / x-bogus 签名逻辑：完整保留

⚠ 前置条件：_BRANCH_ONE_B85、SV2、branch_2_orders 三段常量
   请从原文件复制回来（下方已标 === 从原文件复制 ===）。
"""

from __future__ import annotations
import base64
import binascii
import bisect
import hashlib
import json
import os
import lzma
import random
import re
import struct
import tempfile
import concurrent.futures
import threading
import time
from collections.abc import Mapping
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from html.parser import HTMLParser
from typing import Any
from urllib.parse import parse_qs, quote, urlencode, urlparse
import requests

try:
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
except ImportError:
    hashes = None
    Cipher = algorithms = modes = None
try:
    from Crypto.Cipher import AES as CryptoAES
except ImportError:
    CryptoAES = None
try:
    from base.spider import Spider as _BaseSpider
except Exception:
    try:
        import sys as _sys
        _sys.path.append("..")
        from base.spider import Spider as _BaseSpider
    except Exception:
        class _BaseSpider:
            pass

if Cipher is not None:
    AES_BACKEND = "cryptography"
elif CryptoAES is not None:
    AES_BACKEND = "pycryptodome"
else:
    AES_BACKEND = "none"


# ============================================================
# 【新增】站点常量 + Cookie + UA
# ============================================================
SITE = "https://hongguoduanju.com"

# 用户提供的登录态 Cookie（到期 2026-12-24）
# 如果某天抓不到，去浏览器 F12 → Network → Cookie 头重新复制即可
_GLOBAL_COOKIE = (
    "ttwid=1%7CFUe-ibOEzn12SnhVP5nOngwf5MskiJr-lpk7vofauZU%7C1792971906"
    "%7Cd963d4932d31ef188fabdf562dd0a877a05a764af65ba2628747b2bf00086a7d; "
    "gfkadpd=8662,48688; biz_trace_id=5337fe76; "
    "passport_csrf_token=dbad8c67f041074db23d7d3c256d44ee; "
    "passport_csrf_token_default=dbad8c67f041074db23d7d3c256d44ee; "
    "s_v_web_id=verify_mvohn33s_51c923f8_bf06_e515_8d72_db4b61c56533; "
    "passport_mfa_token=Cjj1KZy5OQ%2FgeVBU6dGaNX3zj9LRYPPIaJw9de3stkdDfpkvxxyRAb%2FsiG5ak7UvMzCh95vXpYfV7hpKCjwAAAAAAAAAAAAAUQ%2BdUPUO1oJjwuRvzYzHUlxDQKpkWfK2CbMCefRjKYJrHTai1pHiqtci14tpjONL0qkQkvKfDhj2sdFsIAIiAQPJvLze; "
    "d_ticket=927f013eb2451ea41f6447f7c923a3d58f9ef; "
    "odin_tt=1b226008f93c9d612cfd5aee59a4d5ce75624bca6c141d1d5580e0a37de7c95dd51764d1dc4aad9425112655d7949248b6d6f38a10bcb58fd7e456db67e3a7c2; "
    "n_mh=Fi8Chlxlfbrkp34GV4R3gHj7qtGbmcKuK4hS_6MHDU0; "
    "passport_auth_status=25d9b84afcda1658710a2ad19a464008%2C; "
    "passport_auth_status_ss=25d9b84afcda1658710a2ad19a464008%2C; "
    "sid_guard=fcb1646b867814ca355be9580dacd9e1%7C1792972707%7C5184000%7CThu%2C+24-Dec-2026+23%3A58%3A27+GMT; "
    "uid_tt=902cadfa8f6ede901d5a4ad9fffaaa5e; "
    "uid_tt_ss=902cadfa8f6ede901d5a4ad9fffaaa5e; "
    "sid_tt=fcb1646b867814ca355be9580dacd9e1; "
    "sessionid=fcb1646b867814ca355be9580dacd9e1; "
    "sessionid_ss=fcb1646b867814ca355be9580dacd9e1; "
    "session_tlb_tag=sttt%7C3%7C_LFka4Z4FMo1W-lYDazZ4f_________6WuJ8pUQnYbohCqDBJqOb8eNG_vt1gpcUe2HrHYIGu8M%3D; "
    "is_staff_user=false; has_biz_token=false; "
    "sid_ucp_v1=1.0.0-KGUxYWNiMzZmYzhhMTY1OGYyNzZlYmFmNzVmNzAyNGE3ZTBmY2ZiNDAKIAig84ChoM3QARCjr_rWBhjbrR8gDDDnhIGlBjgCQPEHGgJsZiIgZmNiMTY0NmI4Njc4MTRjYTM1NWJlOTU4MGRhY2Q5ZTE; "
    "ssid_ucp_v1=1.0.0-KGUxYWNiMzZmYzhhMTY1OGYyNzZlYmFmNzVmNzAyNGE3ZTBmY2ZiNDAKIAig84ChoM3QARCjr_rWBhjbrR8gDDDnhIGlBjgCQPEHGgJsZiIgZmNiMTY0NmI4Njc4MTRjYTM1NWJlOTU4MGRhY2Q5ZTE"
)

# PC 站 UA —— 与用户登录时使用的 UA 一致
_PC_UA = (
    "Mozilla/5.0 (Linux; Android 6.0; Nexus 5 Build/MRA58N) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/132.0.0.0 Mobile Safari/537.36"
)


def _pc_headers():
    h = {
        "User-Agent": _PC_UA,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,"
                  "image/avif,image/webp,image/apng,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9",
        "Cache-Control": "no-cache",
        "Referer": SITE + "/",
    }
    if _GLOBAL_COOKIE:
        h["Cookie"] = _GLOBAL_COOKIE
    return h


EPISODE_PREFIX = "hg-episode-v1:"
_HG_QUALITY_LINES = (
    ("1080", "红果超清"),
    ("720",  "红果高清"),
    ("540",  "红果标准"),
    ("480",  "红果流畅"),
    ("360",  "红果极速"),
)
_QUALITY_LINE_NAME_TO_Q = {
    "超清": "1080", "高清": "720", "标准": "540",
    "流畅": "480", "极速": "360", "1080": "1080", "720": "720",
    "540": "540", "480": "480", "360": "360",
}


def _split_episode_token(token: str) -> tuple[str, str]:
    body = str(token or "")
    if body.startswith(EPISODE_PREFIX):
        body = body[len(EPISODE_PREFIX):]
    if ":" in body:
        head, tail = body.split(":", 1)
        if head.isdigit():
            return head, tail
    return "1080", body


_AI_MANJU_KEYWORDS = [
    "AI漫剧", "AI动画", "AI短剧", "AI动漫", "漫剧AI", "二次元AI", "AI漫画", "动画短剧",
]

_HG_CACHE_DIR = None
_HG_CACHE_MAX_FILES = 8
_HG_CACHE_MAX_BYTES = 400 * 1024 * 1024
_HG_CACHE_MAX_AGE = 6 * 3600


def _hg_cache_dir() -> str:
    global _HG_CACHE_DIR
    if _HG_CACHE_DIR and os.path.isdir(_HG_CACHE_DIR):
        return _HG_CACHE_DIR
    candidates = []
    for root in (
        "/data/user/0/com.fongmi.android.oktv/cache",
        "/data/data/com.fongmi.android.oktv/cache",
        "/data/user/0/com.fongmi.android.tv/cache",
        "/data/data/com.fongmi.android.tv/cache",
        "/sdcard/Android/data/com.fongmi.android.oktv/cache",
        "/sdcard/Android/data/com.fongmi.android.tv/cache",
        "/sdcard/Download",
    ):
        candidates.append(os.path.join(root, "hg_cenc_cache"))
    try:
        candidates.append(os.path.join(tempfile.gettempdir(), "hg_cenc_cache"))
    except Exception:
        pass
    try:
        candidates.append(os.path.join(os.getcwd(), "hg_cenc_cache"))
    except Exception:
        pass
    for path in candidates:
        try:
            os.makedirs(path, exist_ok=True)
            test = os.path.join(path, ".w")
            with open(test, "wb") as fh:
                fh.write(b"1")
            os.remove(test)
            _HG_CACHE_DIR = path
            return path
        except Exception:
            continue
    _HG_CACHE_DIR = tempfile.mkdtemp(prefix="hg_cenc_")
    return _HG_CACHE_DIR


def _hg_cache_path(vid: str, quality: str) -> str:
    safe = re.sub(r"[^0-9A-Za-z_-]", "", str(vid))[:40]
    q = re.sub(r"[^0-9A-Za-z]", "", str(quality or "q"))[:8]
    return os.path.join(_hg_cache_dir(), "%s_%s.mp4" % (safe, q))


def _hg_cache_list() -> list:
    root = _hg_cache_dir()
    files = []
    try:
        now = time.time()
        for name in os.listdir(root):
            if not name.endswith(".mp4"):
                continue
            fp = os.path.join(root, name)
            if not os.path.isfile(fp):
                continue
            try:
                st = os.stat(fp)
            except Exception:
                continue
            files.append({"path": fp, "size": st.st_size,
                          "mtime": st.st_mtime, "age": now - st.st_mtime})
    except Exception:
        return []
    files.sort(key=lambda x: x["mtime"])
    return files


def _hg_cache_cleanup(force: bool = False) -> None:
    try:
        files = _hg_cache_list()
        if not files and not force:
            return
        remain = []
        for item in files:
            if item["age"] > _HG_CACHE_MAX_AGE or item["size"] <= 0:
                try:
                    os.remove(item["path"])
                except Exception:
                    pass
            else:
                remain.append(item)
        total = sum(x["size"] for x in remain)
        while remain and (len(remain) > _HG_CACHE_MAX_FILES or total > _HG_CACHE_MAX_BYTES):
            old = remain.pop(0)
            try:
                os.remove(old["path"])
            except Exception:
                pass
            total -= old["size"]
        root = _hg_cache_dir()
        for name in os.listdir(root):
            if name.endswith(".tmp") or name == ".w":
                try:
                    os.remove(os.path.join(root, name))
                except Exception:
                    pass
    except Exception:
        pass


def _hg_cache_clear_all() -> None:
    try:
        root = _hg_cache_dir()
        for name in os.listdir(root):
            fp = os.path.join(root, name)
            try:
                if os.path.isfile(fp):
                    os.remove(fp)
            except Exception:
                pass
    except Exception:
        pass


def _hg_cache_get(vid: str, quality: str) -> bytes | None:
    _hg_cache_cleanup(False)
    path = _hg_cache_path(vid, quality)
    try:
        if os.path.isfile(path) and os.path.getsize(path) > 64:
            try:
                os.utime(path, None)
            except Exception:
                pass
            with open(path, "rb") as fh:
                return fh.read()
    except Exception:
        return None
    return None


def _hg_cache_put(vid: str, quality: str, data: bytes) -> None:
    if not data or len(data) < 64:
        return
    path = _hg_cache_path(vid, quality)
    try:
        _hg_cache_cleanup(False)
        tmp = path + ".tmp"
        with open(tmp, "wb") as fh:
            fh.write(data)
        os.replace(tmp, path)
        _hg_cache_cleanup(False)
    except Exception:
        try:
            if os.path.exists(path + ".tmp"):
                os.remove(path + ".tmp")
        except Exception:
            pass


def _aes_is_fast() -> bool:
    return AES_BACKEND in ("cryptography", "pycryptodome")


def _http_get_bytes(url: str, headers: dict | None = None, timeout: int = 60) -> bytes:
    h = dict(headers or {})
    r = requests.get(url, headers=h, timeout=timeout)
    r.raise_for_status()
    return r.content


def _probe_content_length(url: str, headers: dict | None = None, timeout: int = 30) -> int:
    h = dict(headers or {})
    try:
        r = requests.head(url, headers=h, timeout=timeout, allow_redirects=True)
        if r.status_code < 400:
            cl = r.headers.get("Content-Length") or r.headers.get("content-length")
            if cl and str(cl).isdigit():
                return int(cl)
    except Exception:
        pass
    try:
        hh = dict(h)
        hh["Range"] = "bytes=0-0"
        r = requests.get(url, headers=hh, timeout=timeout)
        cr = r.headers.get("Content-Range") or r.headers.get("content-range") or ""
        if "/" in cr:
            total = cr.split("/")[-1].strip()
            if total.isdigit():
                return int(total)
        cl = r.headers.get("Content-Length") or "0"
        if str(cl).isdigit() and int(cl) > 1:
            return int(cl)
    except Exception:
        pass
    return 0


def _download_range(url: str, start: int, end: int, headers: dict | None, timeout: int) -> tuple[int, bytes]:
    h = dict(headers or {})
    h["Range"] = "bytes=%d-%d" % (start, end)
    last_err = None
    for attempt in range(3):
        try:
            r = requests.get(url, headers=h, timeout=timeout)
            if r.status_code not in (200, 206):
                raise RuntimeError("range http %s" % r.status_code)
            data = r.content
            if not data:
                raise RuntimeError("empty range body")
            return start, data
        except Exception as err:
            last_err = err
            try:
                time.sleep(0.25 * (attempt + 1))
            except Exception:
                pass
    raise RuntimeError("range %s-%s failed: %s" % (start, end, last_err))


def _multi_download(url: str, headers: dict | None = None, timeout: int = 90, workers: int = 4) -> bytes:
    headers = dict(headers or {})
    total = _probe_content_length(url, headers, timeout=min(30, timeout))
    if total <= 0 or total < 2 * 1024 * 1024:
        return _http_get_bytes(url, headers, timeout=timeout)
    workers = max(2, min(int(workers or 4), 6))
    chunk = max(1 * 1024 * 1024, min(2 * 1024 * 1024, total // workers))
    ranges = []
    start = 0
    while start < total:
        end = min(total - 1, start + chunk - 1)
        ranges.append((start, end))
        start = end + 1
    parts: dict[int, bytes] = {}
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
            futs = [pool.submit(_download_range, url, s, e, headers, timeout)
                    for s, e in ranges]
            for fut in concurrent.futures.as_completed(futs):
                s, data = fut.result()
                parts[s] = data
    except Exception:
        return _http_get_bytes(url, headers, timeout=timeout)
    buf = bytearray()
    for s, e in ranges:
        piece = parts.get(s)
        if piece is None:
            return _http_get_bytes(url, headers, timeout=timeout)
        buf.extend(piece)
    if len(buf) < total * 0.95:
        return _http_get_bytes(url, headers, timeout=timeout)
    return bytes(buf)


_MANJU_KEYWORDS = [
    "漫剧", "动漫短剧", "二次元", "漫画短剧", "国漫短剧", "日漫", "动态漫", "动画剧",
]

VIDEO_URL = "https://api5-normal-sinfonlineb.fqnovel.com/novel/player/multi_video_model/v1/"
UA = _PC_UA
APP_UA = "com.phoenix.read/71332 (Linux; U; Android 16; zh_CN; 25053RT47C; Build/BP2A.250605.031.A3; Cronet/TTNetVersion:04657795 2026-01-23 QuicVersion:c67e9834 2025-09-08)"
MEDIA_UA = "com.phoenix.read/71332"

_HTML_FETCH_ATTEMPTS = 3
_HTML_FETCH_BACKOFF_SECONDS = 1.5
_RANGE_FETCH_ATTEMPTS = 3
_RANGE_FETCH_BACKOFF_SECONDS = 0.8


class HongguoPluginError(RuntimeError):
    pass


def _text(value: Any) -> str:
    return str(value or "").strip()


def _first(*values: Any) -> str:
    for value in values:
        if isinstance(value, (list, tuple)):
            result = _first(*value)
        elif isinstance(value, Mapping):
            result = _first(
                value.get("url"), value.get("uri"), value.get("src"),
                value.get("download_url"), value.get("main_url"),
                value.get("backup_url"), value.get("backup_url_1"),
                value.get("play_addr"), value.get("url_list"),
            )
        else:
            result = _text(value)
        if result:
            return result
    return ""


def _json_response(response: requests.Response) -> Any:
    response.raise_for_status()
    try:
        return response.json()
    except ValueError as exc:
        raise HongguoPluginError("上游响应不是 JSON") from exc


# ============================================================
# 【修改】_page() —— 不再强依赖 _ROUTER_DATA
# ============================================================
def _page(url):
    last_err = None
    for attempt in range(3):
        try:
            r = requests.get(url, headers=_pc_headers(), timeout=30)
            r.raise_for_status()
            r.encoding = r.encoding or "utf-8"
            text = r.text or ""
            if len(text) < 500:
                raise RuntimeError("empty page")
            return text
        except Exception as err:
            last_err = err
            try:
                time.sleep(0.6 * (attempt + 1))
            except Exception:
                pass
    raise RuntimeError("page fetch failed: %s" % last_err)


# ============================================================
# 【修改】_data() —— 支持多路 JSON 注入
# ============================================================
def _data(url):
    html = _page(url)

    m = re.search(r"(?:window\.)?_ROUTER_DATA\s*=\s*", html)
    if m:
        try:
            return json.JSONDecoder().raw_decode(html[m.end():])[0]
        except (ValueError, TypeError):
            pass

    m = re.search(r'<script[^>]+id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.S)
    if m:
        try:
            return json.loads(m.group(1))
        except (ValueError, TypeError):
            pass

    for var in ("__INITIAL_STATE__", "__INITIAL_DATA__", "__DATA__"):
        m = re.search(rf"(?:window\.)?{var}\s*=\s*", html)
        if m:
            try:
                return json.JSONDecoder().raw_decode(html[m.end():])[0]
            except (ValueError, TypeError):
                pass

    for m in re.finditer(r'<script[^>]+type="application/json"[^>]*>(.*?)</script>', html, re.S):
        try:
            obj = json.loads(m.group(1))
            if isinstance(obj, dict) and obj:
                return obj
        except (ValueError, TypeError):
            pass

    return {}


# ============================================================
# 【新增】_parse_cards_html() —— SSR HTML 兜底解析
# ============================================================
def _parse_cards_html(html):
    cards = []
    seen = set()
    for m in re.finditer(r'<a[^>]*href="(/detail\?series_id=(\d+))"[^>]*>(.*?)</a>',
                         html, re.S):
        href, sid, block = m.group(1), m.group(2), m.group(3)
        if sid in seen:
            continue
        seen.add(sid)

        title = ""
        tm = re.search(r'<p[^>]*class="[^"]*pc-title[^"]*"[^>]*>([^<]+)</p>', block)
        if tm:
            title = tm.group(1).strip()
        if not title:
            am = re.search(r'<img[^>]*alt="([^"]+)"', block)
            if am:
                title = am.group(1).strip()

        pic = ""
        pm = re.search(r'<img[^>]*class="[^"]*image[^"]*"[^>]*src="([^"]+)"', block)
        if pm:
            pic = pm.group(1)
        if not pic:
            pm = re.search(r'<img[^>]*src="(https?://[^"]+)"', block)
            if pm:
                pic = pm.group(1)

        ep = ""
        em = re.search(r'<p[^>]*class="[^"]*pc-episode[^"]*"[^>]*>([^<]+)</p>', block)
        if em:
            ep = em.group(1).strip()

        tags = re.findall(r'<span[^>]*class="[^"]*pc-tag-text[^"]*"[^>]*>([^<]+)</span>', block)
        tags = [t.strip() for t in tags if t.strip()]

        if title and sid:
            cards.append({
                "vod_id": sid,
                "vod_name": title,
                "vod_pic": pic,
                "vod_remarks": ep,
                "vod_content": " / ".join(tags),
            })
    return cards


def _item(x):
    x = x or {}
    vd = x.get("video_data") if isinstance(x.get("video_data"), dict) else x
    sid = str(vd.get("series_id") or x.get("series_id")
              or x.get("keyword") or vd.get("keyword") or "")
    name = str(vd.get("series_title") or vd.get("series_name")
               or x.get("series_name") or x.get("name") or "未命名")
    count = vd.get("episode_cnt") or x.get("episode_cnt") or 0
    pic = str(vd.get("series_cover") or x.get("series_cover") or "")
    intro = str(vd.get("series_intro") or x.get("series_intro") or "")
    return {
        "vod_id": sid,
        "vod_name": name,
        "vod_pic": pic,
        "vod_remarks": ("全%s集" % count) if count else "",
        "vod_content": intro,
    }


def _cat_item(x):
    return _item(x)


def _filter_group(key, name, values):
    return {"key": key, "name": name, "value": [{"n": n, "v": v} for n, v in values]}


def _search_loader(key: str) -> dict:
    last = {}
    for attempt in range(3):
        try:
            data = _data(SITE + "/search/" + quote(str(key), safe=""))
            page = (data.get("loaderData") or {}).get("search_(keyword)/page") or {}
            if page.get("searchList"):
                return page
            last = page or last
        except Exception:
            pass
        try:
            time.sleep(0.5 * (attempt + 1))
        except Exception:
            pass
    return last


def _search_by_keywords(keywords, page: int) -> dict:
    page = max(1, int(page or 1))
    kws = [k for k in (keywords or []) if k]
    if not kws:
        kws = ["短剧"]
    key = kws[(page - 1) % len(kws)]
    p = _search_loader(key)
    rows = p.get("searchList") or []
    out = []
    seen = set()
    for x in rows:
        it = _item(x)
        vid = str(it.get("vod_id") or "")
        if not vid or vid in seen:
            continue
        seen.add(vid)
        out.append(it)
    total = int(p.get("totalCount") or 0)
    pagecount = max(len(kws), (total + 9) // 10 if total else len(kws))
    return {
        "page": page,
        "pagecount": max(1, pagecount),
        "limit": len(out),
        "total": total or len(out) * pagecount,
        "list": out,
    }


def _category_loader(page: int, q: dict) -> dict:
    page = max(1, int(page or 1))
    q = dict(q or {})
    if page > 1:
        q["page"] = str(page)
    last = {}
    for attempt in range(3):
        try:
            data = _data(SITE + "/category?" + urlencode(q))
            p = ((data.get("loaderData") or {}).get("category_$")
                 or (data.get("loaderData") or {}).get("category_page") or {})
            rows = p.get("recommendList") or []
            if rows or page > 1:
                return p
            last = p or last
        except Exception:
            pass
        try:
            time.sleep(0.5 * (attempt + 1))
        except Exception:
            pass
    return last


# ============================================================
# ===== SM3 / AES_V3 / x-bogus 等：完整保留原逻辑 =====
# ============================================================
class SM3:
    def __init__(self, data=b""):
        if isinstance(data, str):
            data = data.encode("utf-8")
        self._data = bytearray(data)

    def update(self, data):
        self._data.extend(data)

    def digest(self):
        if hashes is not None and hasattr(hashes, "SM3"):
            digest = hashes.Hash(hashes.SM3())
            digest.update(bytes(self._data))
            return digest.finalize()
        data = bytes(self._data)
        bit_len = len(data) * 8
        data += b"\x80"
        data += b"\x00" * ((56 - len(data) % 64) % 64)
        data += bit_len.to_bytes(8, "big")
        iv = [0x7380166F, 0x4914B2B9, 0x172442D7, 0xDA8A0600,
              0xA96F30BC, 0x163138AA, 0xE38DEE4D, 0xB0FB0E4E]

        def rol32(v, n):
            return ((v << n) | (v >> (32 - n))) & 0xFFFFFFFF

        for off in range(0, len(data), 64):
            block = data[off:off + 64]
            w = [int.from_bytes(block[i:i + 4], "big") for i in range(0, 64, 4)]
            for j in range(16, 68):
                x = w[j - 16] ^ w[j - 9] ^ rol32(w[j - 3], 15)
                w.append((x ^ rol32(x, 15) ^ rol32(x, 23) ^ rol32(w[j - 13], 7) ^ w[j - 6]) & 0xFFFFFFFF)
            w1 = [w[j] ^ w[j + 4] for j in range(64)]
            a, b, c, d, e, f, g, h = iv
            for j in range(64):
                tj = 0x79CC4519 if j < 16 else 0x7A879D8A
                ss1 = rol32((rol32(a, 12) + e + rol32(tj, j % 32)) & 0xFFFFFFFF, 7)
                ss2 = ss1 ^ rol32(a, 12)
                ff = a ^ b ^ c if j < 16 else (a & b) | (a & c) | (b & c)
                gg = e ^ f ^ g if j < 16 else (e & f) | ((~e) & g)
                tt1 = (ff + d + ss2 + w1[j]) & 0xFFFFFFFF
                tt2 = (gg + h + ss1 + w[j]) & 0xFFFFFFFF
                d, c, b, a = c, rol32(b, 9), a, tt1
                h, g, f, e = g, rol32(f, 19), e, (tt2 ^ rol32(tt2, 9) ^ rol32(tt2, 17)) & 0xFFFFFFFF
            iv = [(x ^ y) & 0xFFFFFFFF for x, y in zip(iv, (a, b, c, d, e, f, g, h))]
        return b"".join(x.to_bytes(4, "big") for x in iv)


xtime = lambda a: (((a << 1) ^ 0x1B) & 0xFF) if (a & 0x80) else (a << 1)


def rol(num, shift):
    shift %= 32
    return ((num << shift) | (num >> (32 - shift))) & 0xFFFFFFFF


def rl8(x: int, k: int) -> int:
    n = 8
    s = k & (n - 1)
    return ((x << s) | (x >> (n - s))) & 0xff


def ror32(value, count):
    count %= 32
    low = value << (32 - count)
    value >>= count
    value |= low
    value &= 0xFFFFFFFF
    return value


def ror(value, count):
    count %= 64
    low = value << (64 - count)
    value >>= count
    value |= low
    value &= 0xFFFFFFFFFFFFFFFF
    return value


def get_key_hash(key, rand):
    to_hash = bytearray(68)
    to_hash[:32] = key
    to_hash[32:36] = rand.to_bytes(4, byteorder='little')
    to_hash[36:] = key
    d1 = (rand >> 16) & 0x000000ff
    d2 = (d1 << 11) | (rand >> 24)
    d2 ^= (d1 >> 5) ^ d1
    d2 = ~d2 & 0xffffffff
    return SM3(to_hash).digest(), d2.to_bytes(4, "little")


def split_blocks(message, block_size=16, require_padding=True):
    assert len(message) % block_size == 0 or not require_padding
    return [message[i:i + 16] for i in range(0, len(message), block_size)]


def add_round_key(s, k):
    for i in range(4):
        for j in range(4):
            s[i][j] ^= k[i][j]


def add_round_key_con(s, k, con):
    for i in range(4):
        for j in range(4):
            s[i][j] ^= k[i][con[j]]


def bytes2matrix(text):
    return [list(text[i:i + 4]) for i in range(0, len(text), 4)]


def xor_bytes(a, b):
    return bytearray(i ^ j for i, j in zip(a, b))


def matrix2bytes(matrix):
    return bytearray(sum(matrix, []))


def mix_single_column(a, i):
    t = a[0][i] ^ a[1][i] ^ a[2][i] ^ a[3][i]
    u = a[0][i]
    a[0][i] ^= t ^ xtime(a[0][i] ^ a[1][i])
    a[1][i] ^= t ^ xtime(a[1][i] ^ a[2][i])
    a[2][i] ^= t ^ xtime(a[2][i] ^ a[3][i])
    a[3][i] ^= t ^ xtime(a[3][i] ^ u)


def mix_columns(s):
    for i in range(4):
        mix_single_column(s, i)


def inv_mix_columns(s):
    for i in range(0, 4):
        inv_mix_single_column(s, i)


def inv_mix_single_column(a, i):
    u = xtime(xtime(a[0][i] ^ a[2][i]))
    v = xtime(xtime(a[1][i] ^ a[3][i]))
    a[0][i] ^= u
    a[1][i] ^= v
    a[2][i] ^= u
    a[3][i] ^= v
    mix_single_column(a, i)


# ============================================================
# === 从原文件复制 ===
# 下面这一整段 s_box 常量（1024 字节）请从原 红果短剧1.py 
# 的 "s_box = b''.join([...])" 到 inv_s_box 之间完整复制
# ============================================================
# s_box = b''.join([...])  # <-- 从原文件复制这一整段

inv_s_box = bytearray(1024)


class AES_V3():
    r_con = [[1, 0, 2, 3], [1, 3, 0, 2], [0, 1, 3, 2], [1, 0, 2, 3]]
    r_con2 = [[1, 0, 2, 3], [2, 0, 3, 1], [0, 1, 3, 2], [1, 0, 2, 3]]
    r_orders = [[0, 9, 14, 11, 4, 13, 2, 7, 8, 1, 6, 15, 12, 5, 10, 3],
                [0, 9, 14, 15, 4, 13, 2, 7, 8, 1, 6, 3, 12, 5, 10, 11],
                [0, 9, 14, 7, 4, 13, 2, 11, 8, 1, 6, 3, 12, 5, 10, 15],
                [0, 9, 14, 11, 4, 13, 2, 7, 8, 1, 6, 15, 12, 5, 10, 3]]

    def __init__(self, aes_key, khronos):
        self.word_size = khronos & 3
        self.aes_key = aes_key
        self.s_box = s_box[self.word_size << 8:]
        self.inv_s_box = inv_s_box[self.word_size << 8:]
        self.master_key = self._expand_key()
        self._key_matrices = bytes2matrix(self.master_key)
        self.con = self.r_con[self.word_size]
        self.con2 = self.r_con2[self.word_size]
        self.order = self.r_orders[self.word_size]

    def _expand_key(self):
        init_values = [0xca025ddc, 0x823dc546, 0xc9420583, 0xc298225f]
        init_value = init_values[self.word_size]
        mk = bytearray(init_value.to_bytes(4, "little")) * 4
        mk = xor_bytes(mk, self.aes_key)
        mk += bytearray(32)
        rounds = 8
        for i in range(4, 12):
            idx = 4 * (i - 1)
            k0, k1, k2, k3 = mk[idx], mk[idx + 1], mk[idx + 2], mk[idx + 3]
            if i & 3 == 0:
                k00 = (init_value >> (rounds & 24)) ^ self.s_box[k1]
                k1 = self.s_box[k2]
                k2 = self.s_box[k3]
                k3 = self.s_box[k0]
                k0 = k00 & 0xff
            rounds += 2
            mk[idx + 4] = k0 ^ mk[idx - 12]
            mk[idx + 5] = k1 ^ mk[idx - 11]
            mk[idx + 6] = k2 ^ mk[idx - 10]
            mk[idx + 7] = k3 ^ mk[idx - 9]
        return mk

    @staticmethod
    def sum_data(data):
        key = bytearray(32)
        for i in range(31):
            idx = i * 8
            n0 = (data[idx] >> 4) & 2
            n1 = n0 | data[idx + 1] & 64
            n2 = n1 | (data[idx + 2] >> 2) & 1
            n3 = n2 | (data[idx + 3] << 3) & -128
            n4 = n3 | (data[idx + 4] >> 1) & 4
            n5 = n4 | (data[idx + 5] << 3) & 16
            n6 = n5 | (data[idx + 6] << 5) & 32
            n7 = n6 | (data[idx + 7] >> 4) & 8
            key[i] = (n7 & 0xff)
        key[31] = 1
        return key

    @staticmethod
    def mix_columns(data, key):
        data = bytearray(data)
        for i in range(31):
            kk = key[i]
            idx = i * 8
            data[idx + 0] = (data[idx + 0] & -33) | ((kk << 4) & 0xff & 32)
            data[idx + 1] = (data[idx + 1] & -65) | (kk & 64)
            data[idx + 2] = (data[idx + 2] & -5) | ((kk * 4) & 4)
            data[idx + 3] = (data[idx + 3] & -17) | ((kk >> 3) & 16)
            data[idx + 4] = (data[idx + 4] & -9) | ((kk + kk) & 8)
            data[idx + 5] = (data[idx + 5] & -3) | ((kk >> 3) & 2)
            data[idx + 6] = (data[idx + 6] & -2) | ((kk >> 5) & 1)
            data[idx + 7] = (data[idx + 7] & 127) | ((kk << 4) & 0xff & -128)
        return data

    def encrypt(self, data, iv):
        plaintext = self.sum_data(data)
        blocks = []
        previous = iv
        for plaintext_block in split_blocks(plaintext):
            x = xor_bytes(plaintext_block, previous)
            block = self.encrypt_block(x)
            blocks.append(block)
            previous = block
        key = b''.join(blocks)
        data = self.mix_columns(data, key)
        return key[-1:] + data

    def encrypt_block(self, plaintext):
        plain_state = bytes2matrix(plaintext)
        add_round_key_con(plain_state, self._key_matrices[0:4], self.con2)
        for i in range(1, 3):
            self.sub_bytes(plain_state)
            self.shift_rows(plain_state)
            if i == 1:
                self.shift_rows_con(plain_state, self.con2)
                mix_columns(plain_state)
            add_round_key_con(plain_state, self._key_matrices[i * 4:], self.con2)
        add_round_key(plain_state, self._key_matrices[4:])
        return matrix2bytes(plain_state)

    def decrypt(self, ciphertext, iv, data):
        assert len(iv) == 16
        blocks = []
        previous = iv
        for ciphertext_block in split_blocks(ciphertext):
            dc = xor_bytes(previous, self.decrypt_block(ciphertext_block))
            blocks.append(dc)
            previous = ciphertext_block
        key = b''.join(blocks)
        data = self.mix_columns(data, key)
        return data

    def decrypt_block(self, ciphertext):
        assert len(ciphertext) == 16
        cipher_state = bytes2matrix(ciphertext)
        add_round_key(cipher_state, self._key_matrices[4:])
        for i in range(2, 0, -1):
            add_round_key_con(cipher_state, self._key_matrices[i * 4:], self.con2)
            if i == 1:
                inv_mix_columns(cipher_state)
                self.shift_rows_con(cipher_state, self.con)
            self.inv_shift_rows(cipher_state)
            self.inv_sub_bytes(cipher_state)
        add_round_key_con(cipher_state, self._key_matrices[0:4], self.con2)
        return matrix2bytes(cipher_state)

    def shift_rows_con(self, s, c):
        for i in range(4):
            s[i][0], s[i][1], s[i][2], s[i][3] = s[i][c[0]], s[i][c[1]], s[i][c[2]], s[i][c[3]]

    def shift_rows(self, s):
        bs = matrix2bytes(s)
        for i in range(4):
            for j in range(4):
                s[i][j] = bs[self.order[i * 4 + j]]

    def inv_shift_rows(self, s):
        order = bytearray(16)
        for i in range(16):
            order[self.order[i]] = i
        bs = matrix2bytes(s)
        for i in range(4):
            for j in range(4):
                s[i][j] = bs[order[i * 4 + j]]

    def sub_bytes(self, s):
        for i in range(4):
            for j in range(4):
                s[i][j] = self.s_box[s[i][j]]
        s[0], s[1], s[2], s[3] = s[self.con2[0]], s[self.con2[1]], s[self.con2[2]], s[self.con2[3]]

    def inv_sub_bytes(self, s):
        for i in range(4):
            for j in range(4):
                s[i][j] = self.inv_s_box[s[i][j]]
        s[0], s[1], s[2], s[3] = s[self.con[0]], s[self.con[1]], s[self.con[2]], s[self.con[3]]


def leftCircularShift(k, bits):
    bits = bits % 32
    k = k % (2 ** 32)
    upper = (k << bits) % (2 ** 32)
    result = upper | (k >> (32 - (bits)))
    return (result)


def blockDivide(block, chunks):
    result = []
    size = len(block) // chunks
    for i in range(0, chunks):
        result.append(int.from_bytes(block[i * size:(i + 1) * size], byteorder="little"))
    return (result)


def F(X, Y, Z):
    return ((X & Y) | ((~X) & Z))


def G(X, Y, Z):
    return ((X & Z) | (Y & (~Z)))


def H(X, Y, Z):
    return (X ^ Y ^ Z)


def I(X, Y, Z):
    return (Y ^ (X | (~Z))) & 0xffffffff


def FF(a, b, c, d, M, s, t):
    return b + leftCircularShift((a + F(b, c, d) + M + t), s)


def GG(a, b, c, d, M, s, t):
    return b + leftCircularShift((a + G(b, c, d) + M + t), s)


def HH(a, b, c, d, M, s, t):
    return b + leftCircularShift((a + H(b, c, d) + M + t), s)


def II(a, b, c, d, M, s, t):
    return b + leftCircularShift((a + I(b, c, d) + M + t), s)


def sum_md5(data):
    check_sum = 0x20220420
    for i in range(12):
        if i % 2 == 0:
            temp = (check_sum >> 3) ^ check_sum
            check_sum = data[i] ^ (check_sum << 7)
        else:
            temp = (check_sum >> 5) ^ check_sum
            check_sum = data[i] | (check_sum << 11)
            check_sum ^= 0xffffffff
        check_sum ^= temp
        check_sum &= 0xffffffff
    check_sum |= 4
    check_sum ^= 0x1000000
    return check_sum


# ============================================================
# === 从原文件复制 ===
# SV2 = [...] 那个 64 元素十六进制数组
# ============================================================
# SV2 = [0xa7aefe20, 0x7149f1d6, ...]  # <-- 从原文件复制完整 64 个元素


def md5sum_v3(msg, count_v2, orders, count_v1, n=0):
    count = count_v2 & 0xff
    sv = [ror32(SV2[i], count_v1) for i in range(64)]
    start = [ror32(0x79e0f2fb, count), ror32(0xc8b52570, count),
             ror32(0xebc2f8cd, count), ror32(0x7c104d93, count)]
    count = (count_v2 + 6) & 0xff
    end = [ror32(0x19be4866, count), ror32(0xe85986b4, count),
           ror32(0xe19b326e, count), ror32(0x71d1d7d4, count)]
    A, B, C, D = start
    a, b, c, d = A, B, C, D
    block = msg[:64]
    M = blockDivide(block, 16)
    order1 = orders[:16]
    order2 = orders[16:32]
    order3 = orders[32:48]
    order4 = orders[48:]
    a = FF(a, b, c, d, M[order1[0]], 7, sv[0])
    d = FF(d, a, b, c, M[order1[1]], 12, sv[1])
    c = FF(c, d, a, b, M[order1[2]], 17, sv[2])
    b = FF(b, c, d, a, M[order1[3]], 22, sv[3])
    a = FF(a, b, c, d, M[order1[4]], 7, sv[4])
    d = FF(d, a, b, c, M[order1[5]], 12, sv[5])
    c = FF(c, d, a, b, M[order1[6]], 17, sv[6])
    b = FF(b, c, d, a, M[order1[7]], 22, sv[7])
    a = FF(a, b, c, d, M[order1[8]], 7, sv[8])
    d = FF(d, a, b, c, M[order1[9]], 12, sv[9])
    c = FF(c, d, a, b, M[order1[10]], 17, sv[10])
    b = FF(b, c, d, a, M[order1[11]], 22, sv[11])
    a = FF(a, b, c, d, M[order1[12]], 7, sv[12])
    d = FF(d, a, b, c, M[order1[13]], 12, sv[13])
    c = FF(c, d, a, b, M[order1[14]], 17, sv[14])
    b = FF(b, c, d, a, M[order1[15]], 22, sv[15])
    a = GG(a, b, c, d, M[order2[0]], 5, sv[16])
    d = GG(d, a, b, c, M[order2[1]], 9, sv[17])
    c = GG(c, d, a, b, M[order2[2]], 14, sv[18])
    b = GG(b, c, d, a, M[order2[3]], 20, sv[19])
    a = GG(a, b, c, d, M[order2[4]], 5, sv[20])
    d = GG(d, a, b, c, M[order2[5]], 9, sv[21])
    c = GG(c, d, a, b, M[order2[6]], 14, sv[22])
    b = GG(b, c, d, a, M[order2[7]], 20, sv[23])
    a = GG(a, b, c, d, M[order2[8]], 5, sv[24])
    d = GG(d, a, b, c, M[order2[9]], 9, sv[25])
    c = GG(c, d, a, b, M[order2[10]], 14, sv[26])
    b = GG(b, c, d, a, M[order2[11]], 20, sv[27])
    a = GG(a, b, c, d, M[order2[12]], 5, sv[28])
    d = GG(d, a, b, c, M[order2[13]], 9, sv[29])
    c = GG(c, d, a, b, M[order2[14]], 14, sv[30])
    b = GG(b, c, d, a, M[order2[15]], 20, sv[31])
    a = HH(a, b, c, d, M[order3[0]], 4, sv[32])
    d = HH(d, a, b, c, M[order3[1]], 11, sv[33])
    c = HH(c, d, a, b, M[order3[2]], 16, sv[34])
    b = HH(b, c, d, a, M[order3[3]], 23, sv[35])
    a = HH(a, b, c, d, M[order3[4]], 4, sv[36])
    d = HH(d, a, b, c, M[order3[5]], 11, sv[37])
    c = HH(c, d, a, b, M[order3[6]], 16, sv[38])
    b = HH(b, c, d, a, M[order3[7]], 23, sv[39])
    a = HH(a, b, c, d, M[order3[8]], 4, sv[40])
    d = HH(d, a, b, c, M[order3[9]], 11, sv[41])
    c = HH(c, d, a, b, M[order3[10]], 16, sv[42])
    b = HH(b, c, d, a, M[order3[11]], 23, sv[43])
    a = HH(a, b, c, d, M[order3[12]], 4, sv[44])
    d = HH(d, a, b, c, M[order3[13]], 11, sv[45])
    c = HH(c, d, a, b, M[order3[14]], 16, sv[46])
    b = HH(b, c, d, a, M[order3[15]], 23, sv[47])
    a = II(a, b, c, d, M[order4[0]], 6, sv[48])
    d = II(d, a, b, c, M[order4[1]], 10, sv[49])
    c = II(c, d, a, b, M[order4[2]], 15, sv[50])
    b = II(b, c, d, a, M[order4[3]], 21, sv[51])
    a = II(a, b, c, d, M[order4[4]], 6, sv[52])
    d = II(d, a, b, c, M[order4[5]], 10, sv[53])
    c = II(c, d, a, b, M[order4[6]], 15, sv[54])
    b = II(b, c, d, a, M[order4[7]], 21, sv[55])
    a = II(a, b, c, d, M[order4[8]], 6, sv[56])
    d = II(d, a, b, c, M[order4[9]], 10, sv[57])
    c = II(c, d, a, b, M[order4[10]], 15, sv[58])
    b = II(b, c, d, a, M[order4[11]], 21, sv[59])
    a = II(a, b, c, d, M[order4[12]], 6, sv[60])
    d = II(d, a, b, c, M[order4[13]], 10, sv[61])
    c = II(c, d, a, b, M[order4[14]], 15, sv[62])
    b = II(b, c, d, a, M[order4[15]], 21, sv[63])
    A = (A + a) % (2 ** 32) ^ end[0]
    B = (B + b) % (2 ** 32) ^ end[1]
    C = (C + c) % (2 ** 32) ^ end[2]
    D = (D + d) % (2 ** 32) ^ end[3]
    result = bytearray(A.to_bytes(4, "little") + B.to_bytes(4, "little")
                       + C.to_bytes(4, "little") + D.to_bytes(4, "little"))
    result += sum_md5(result).to_bytes(4, "little")
    return result


def bxor(b1, b2):
    b3 = bytearray(len(b1))
    for i in range(len(b1)):
        b3[i] = b1[i] ^ b2[i]
    return b3


def get_iv(iv, data):
    for i in range(len(data)):
        if i & 1 == 0:
            iv = (iv >> 4) ^ iv ^ (iv << 6) ^ data[i]
        else:
            iv = ~((iv >> 7) ^ iv ^ (data[i] | iv << 12))
        iv = iv & 0xffffffff
    return iv


def hash_f13(query_sm3, body_md5_bytes, ts_bytes, khronos):
    iv = get_iv(0x20230928, query_sm3)
    iv = get_iv(iv, body_md5_bytes)
    iv = get_iv(iv, ts_bytes)
    iv_v0 = ((iv & 15) * 171) >> 9
    branch = (iv & 15) - ((iv_v0 * 3) & 0xff)
    if branch == 0:
        return branch_0(iv_v0, khronos, query_sm3, body_md5_bytes, ts_bytes)
    elif branch == 1:
        return branch_1(iv_v0, khronos, query_sm3, body_md5_bytes, ts_bytes)
    elif branch == 2:
        return branch_2(iv, khronos, query_sm3, body_md5_bytes, ts_bytes)
    else:
        raise Exception("no branch: " + str(branch))


def branch_0(iv_v0, khronos, query_sm3, body_md5_bytes, ts_bytes):
    tt01 = [0xc4a78580, 0xb3c0fd39, 0xc58c5686, 0xc9aa3ba7, 0xf5a7adf2, 0x963c2ed1]
    iv_v1 = tt01[iv_v0]
    count_v1 = (iv_v1 + khronos + 1) & 0xff
    count_v2 = (iv_v1 + khronos) & 0xffffffff
    tt02 = [0xebb64faf, 0x7aadcc2, 0xcf3187bf, 0xe01138ff, 0x6d0bfcff, 0x5a30a3be, 0xb41ad638, 0x34180eb8, 0xf233eb6f,
            0xb1a584cc, 0xccc30dc7, 0x47d1db51, 0xd55653de, 0x70a84fa1, 0x57473c12, 0xf76f0288, 0x2c077f0a, 0xda0dcad0,
            0xfbb86f6c, 0xfdc4cf00, 0x688a020d, 0xe676c6a6, 0x8cd6338b, 0x1a3c8d0e, 0xcce8b06b, 0x6ad0ed0b, 0xa0522717,
            0xdc71ac83, 0x2285db71, 0xd5b4dda6, 0x736f8650, 0x6560306c, 0x617ce2a6, 0xe423417e, 0xa40e143, 0x544e4032,
            0x88dffb2a, 0x716c1ae0, 0x4c467a88, 0x5b23bb3, 0xe1d0b866, 0xbaa3dcb8, 0xae3374d3, 0xc3381a50, 0x1702f75b,
            0xfe6da368, 0xf0b4cf48, 0x4e0ffbb8, 0x72aad10d, 0x26c53a3d, 0xf2bce0f6, 0xb4557581, 0x4a257fdd, 0x8c3182a2,
            0xab0b3b86, 0x3d5dfb14, 0x4f103634, 0xd37b52d7, 0x444eff16, 0xeb0a33d1, 0x6ca86f6e, 0x284ba7, 0x8387cfa,
            0x5fb37586]
    tt03 = [ror32(tt02[i], count_v1) & 0xffffffff for i in range(64)]
    n0 = (count_v2 + 2) & 7
    pad = bytearray(4)
    seed = bytes([0xfa, 0x45, 0x61, 0xd7])
    for i in range(4):
        v = int.from_bytes(bytes([seed[i], seed[i]]), 'little')
        v = v >> n0
        pad[i] = v & 0xff
    count_v2 = count_v2 & 0xff
    init_value = [ror32(0x7aba4fc8, count_v2), ror32(0x67166507, count_v2),
                  ror32(0x6403fa00, count_v2), ror32(0x340f512f, count_v2),
                  ror32(984304912, count_v2), ror32(3005047866, count_v2),
                  ror32(2874125293, count_v2), ror32(2152413264, count_v2)]
    data = query_sm3 + body_md5_bytes + ts_bytes + pad + bytes.fromhex('00 00 00 00 00 00 01 a0')
    di = [0] * (len(data) // 4)
    for i in range(len(data) // 4):
        di[i] = int.from_bytes(data[i * 4:i * 4 + 4], "big")
    di0 = di[0]
    for i in range(112):
        di1, di14 = di[i + 1], di[i + 14]
        r_di1 = rol(di1, 14) ^ rol(di1, 25) ^ (di1 >> 3)
        r_di2 = rol(di14, 13) ^ rol(di14, 15) ^ (di14 >> 10)
        di0 = di0 + di[i + 9] + r_di1 + r_di2
        di.append(di0 & 0xffffffff)
        di0 = di1
    v_j = None
    if iv_v0 == 5:
        v_j = branch0_xor(init_value, iv_v1, di, tt03, 100, 2, 0, 3, 5, 4, 6, 7, 2, 1, 5)
    elif iv_v0 == 4:
        v_j = branch0_xor(init_value, iv_v1, di, tt03, 96, 0, 5, 6, 7, 3, 1, 2, 5, 4, 4)
    elif iv_v0 == 3:
        v_j = branch0_xor(init_value, iv_v1, di, tt03, 99, 3, 6, 2, 4, 5, 1, 0, 0, 7, 6)
    elif iv_v0 == 2:
        v_j = branch0_xor(init_value, iv_v1, di, tt03, 96, 7, 6, 2, 1, 4, 0, 5, 4, 3, 5)
    elif iv_v0 == 1:
        v_j = branch0_xor(init_value, iv_v1, di, tt03, 96, 0, 6, 7, 5, 3, 2, 1, 5, 4, 4)
    elif iv_v0 == 0:
        v_j = branch0_xor(init_value, iv_v1, di, tt03, 101, 5, 7, 6, 3, 2, 1, 0, 5, 4, 3)
    ret = bytearray(32)
    for i in range(8):
        ret[i * 4:i * 4 + 4] = ((v_j[i] + init_value[i]) & 0xffffffff).to_bytes(4, 'big')
    ret = bxor(ret[:16], ret[16:])
    ret += sum_md5(ret).to_bytes(4, "little")
    return ret


def swap_v0(src, src_xor, tt2, table_f, order1, typ=None):
    da0 = [0] * 8
    ha0 = src_xor[:]
    for i in range(8):
        da0[i] = src[order1[i]] ^ src_xor[i]
    for round in range(10):
        rr_0 = r00(ha0[0], ha0[1], ha0[2], ha0[3], ha0[4], ha0[5], ha0[6], ha0[7], 0, table_f)
        rr_1 = r00(ha0[1], ha0[2], ha0[3], ha0[4], ha0[5], ha0[6], ha0[7], ha0[0], 0, table_f)
        rr_2 = r00(ha0[2], ha0[3], ha0[4], ha0[5], ha0[6], ha0[7], ha0[0], ha0[1], 0, table_f)
        rr_3 = r00(ha0[3], ha0[4], ha0[5], ha0[6], ha0[7], ha0[0], ha0[1], ha0[2], 0, table_f)
        rr_4 = r00(ha0[4], ha0[5], ha0[6], ha0[7], ha0[0], ha0[1], ha0[2], ha0[3], 0, table_f)
        rr_5 = r00(ha0[5], ha0[6], ha0[7], ha0[0], ha0[1], ha0[2], ha0[3], ha0[4], 0, table_f)
        rr_6 = r00(ha0[6], ha0[7], ha0[0], ha0[1], ha0[2], ha0[3], ha0[4], ha0[5], 0, table_f)
        rr_7 = r00(ha0[7], ha0[0], ha0[1], ha0[2], ha0[3], ha0[4], ha0[5], ha0[6], 0, table_f)
        rr_7 = rr_7 ^ tt2[round + 1]
        d0, d1, d2, d3, d4, d5, d6, d7 = da0
        da0[0] = r00(d0, d1, d2, d3, d4, d5, d6, d7, rr_0, table_f)
        da0[1] = r00(d1, d2, d3, d4, d5, d6, d7, d0, rr_1, table_f)
        da0[2] = r00(d2, d3, d4, d5, d6, d7, d0, d1, rr_2, table_f)
        da0[3] = r00(d3, d4, d5, d6, d7, d0, d1, d2, rr_3, table_f)
        da0[4] = r00(d4, d5, d6, d7, d0, d1, d2, d3, rr_4, table_f)
        da0[5] = r00(d5, d6, d7, d0, d1, d2, d3, d4, rr_5, table_f)
        da0[6] = r00(d6, d7, d0, d1, d2, d3, d4, d5, rr_6, table_f)
        da0[7] = r00(d7, d0, d1, d2, d3, d4, d5, d6, rr_7, table_f)
        ha0[0], ha0[1], ha0[2], ha0[3], ha0[4], ha0[5], ha0[6], ha0[7] = rr_0, rr_1, rr_2, rr_3, rr_4, rr_5, rr_6, rr_7
    if typ is None:
        src[0] = da0[0] ^ src_xor[0] ^ src[0]
        src[1] = da0[7] ^ src_xor[1] ^ src[1]
        src[2] = da0[6] ^ src_xor[2] ^ src[2]
        src[3] = da0[5] ^ src_xor[3] ^ src[3]
        src[4] = da0[4] ^ src_xor[4] ^ src[4]
        src[5] = da0[3] ^ src_xor[5] ^ src[5]
        src[6] = da0[2] ^ src_xor[6] ^ src[6]
        src[7] = da0[1] ^ src_xor[7] ^ src[7]
    else:
        src[0] = da0[7] ^ typ[1]
        src[1] = da0[6] ^ typ[2]
        src[2] = da0[5] ^ typ[3]
        src[3] = da0[4] ^ typ[4]
        src[4] = da0[3] ^ typ[5]
        src[5] = da0[2] ^ typ[6]
        src[6] = da0[1] ^ typ[7] ^ src[7]
        src[7] = da0[0] ^ typ[0]
    return src


def branch_1(iv_v0, khronos, query_sm3, body_md5_bytes, ts_bytes):
    tt1 = [0x808a9c79, 0xf079807e, 0xbadf79c5, 0xa785d3ff, 0x82d8438c]
    iv_v1 = tt1[iv_v0]
    c_v1 = (iv_v1 + khronos) & 0xff
    c_v1 = ror(khronos, c_v1)
    orders = bytes.fromhex(
        '05 07 01 02 04 00 06 03 00 05 02 04 01 03 07 06'
        '05 07 02 04 01 06 03 00 03 00 02 04 06 07 01 05'
        '04 05 00 03 06 02 01 07 00 00 00 00 00 00 00 00')
    order1 = orders[iv_v0 * 8:iv_v0 * 8 + 8]
    iv_v1 = (iv_v1 + khronos + 1) & 63
    tt1 = [0x87aeea5dab37cd6b, 0x7ff48becb4f54087, 0xb0724c06706bbd5d, 0x1fe5dfb1143e328d,
           0x1a2331d00af4f1f2, 0xcaff7131bb1e71ba, 0x33385e1042752218, 0xff01ed65d4a441fb,
           0xadb1ec8828c80e8, 0x62475d12f4e06fe7, 0xbd0b238da4fe72]
    tt2 = [ror(tt1[i], iv_v1) for i in range(11)]
    to_sign = bytearray(query_sm3 + body_md5_bytes + ts_bytes + bytes([0x80, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0]))
    src = [int.from_bytes(to_sign[i * 8:i * 8 + 8], 'big') for i in range(len(to_sign) // 8)]
    src_xor = [c_v1] * 8
    table_f = get_branch_1_table_f(iv_v0)
    swap = swap_v0(src, src_xor, tt2, table_f, order1)
    data = [0] * 8
    data[7] = 416
    src_xor = [swap[4], swap[3], swap[2], swap[1], swap[0], swap[7], swap[6], swap[5]]
    swap = swap_v0(data, src_xor, tt2, table_f, order1, swap)
    ret = bytearray(32)
    n = 0
    for i in range(7, -1, -1):
        pp = swap[i].to_bytes(8, "little")
        ret[n + 0], ret[n + 1], ret[n + 2], ret[n + 3] = pp[1], pp[3], pp[5], pp[6]
        n += 4
    for i in range(16):
        ret[i] ^= ret[i + 16]
    ret = ret[:16]
    ret += sum_md5(ret).to_bytes(4, "little")
    return ret


def r00(r0, r1, r2, r3, r4, r5, r6, r7, tt, table_f, v=0):
    x = table_f(8 * (r0 >> 56))
    r1 = (r1 >> 45) & 2040
    if tt > 0:
        x = x ^ tt
    x = x ^ table_f(r1 + 2048)
    r2 = (r2 >> 37) & 2040
    x = x ^ table_f(r2 + 4096)
    r3 = (r3 >> 29) & 2040
    x = x ^ table_f(r3 + 6144)
    r4 = (r4 >> 21) & 2040
    x = x ^ table_f(r4 + 8192)
    r5 = (r5 >> 13) & 2040
    x = x ^ table_f(r5 + 10240)
    r6 = (r6 >> 8) & 255
    x = x ^ table_f(8 * r6 + 12288)
    r7 = r7 & 255
    x = x ^ table_f(8 * r7 + 14336)
    return x


# ============================================================
# === 从原文件复制 ===
# branch_2_orders = bytes.fromhex(...) 那个十六进制串
# ============================================================
# branch_2_orders = bytes.fromhex('...')  # <-- 从原文件复制完整十六进制串


def branch_2(iv, khronos, query_sm3, body_md5_bytes, ts_bytes):
    n0 = (iv & 15 - 2) * 86
    iv_v0 = (n0 >> 15 & 0xff) + (n0 >> 8 & 0xff)
    t001 = [0x8980f29b, 0xeb549c7f, 0xb08726db, 0xd40cb5e6, 0xe8f559e4]
    n1 = t001[iv_v0]
    count_v1 = (n1 + khronos + 1) & 0xff
    count_v2 = (n1 + khronos) & 0xffffffff
    n0 = (count_v2 + 5) & 7
    pad = bytearray(8)
    seed = bytes([0x84, 0x96, 0x77, 0x9d, 0xd4, 0x15, 0x0b, 0xf8])
    for i in range(8):
        v = int.from_bytes(bytes([seed[i], seed[i]]), 'little')
        v = v >> n0
        pad[i] = v & 0xff
    data = query_sm3 + body_md5_bytes + ts_bytes + pad + bytes.fromhex('a0 01 00 00')
    idx = iv_v0 << 6
    return md5sum_v3(data, count_v2, branch_2_orders[idx:idx + 64], count_v1)


def branch0_xor(data, base, di, tt03, round, x1, x2, x3, x4, x5, x6, x7, x8, x9, x10):
    d = data[:]
    for i in range(round):
        offset = base + i
        n0 = di[offset & 127]
        n1 = ((d[x3] ^ d[x4]) & d[x1]) ^ d[x3]
        n2 = rol(d[x1], 26) ^ rol(d[x1], 21) ^ rol(d[x1], 7)
        offset = offset & 63
        n3 = tt03[offset]
        n4 = (n0 + n1 + n2 + n3 + d[x5]) & 0xffffffff
        n5 = rol(d[x2], 30) ^ rol(d[x2], 19) ^ rol(d[x2], 10)
        n6 = (d[x2] & d[x6]) | ((d[x2] | d[x6]) & d[x7])
        n7 = n5 + n6
        o = d[x9]
        d[0], d[1], d[2], d[3], d[4], d[5], d[6], d[7] = d[7], d[0], d[1], d[2], d[3], d[4], d[5], d[6]
        d[x10] = (n7 + n4) & 0xffffffff
        d[x8] = (o + n4) & 0xffffffff
    return d


# ============================================================
# === 从原文件复制 ===
# _BRANCH_ONE_B85 = ('...' '...' ...) 那个约 5000 行的 base85 编码
# ============================================================
# _BRANCH_ONE_B85 = (...)


def _branch_one_bytes() -> bytes:
    if not hasattr(_branch_one_bytes, "value"):
        _branch_one_bytes.value = lzma.decompress(base64.b85decode(_BRANCH_ONE_B85))
    return _branch_one_bytes.value


branch_1_table = None


def get_branch_1_table_f(iv_v0):
    global branch_1_table
    if branch_1_table is None:
        branch_1_table = _branch_one_bytes()
    table = branch_1_table[iv_v0 << 14:]

    def table_f(x):
        return int.from_bytes(table[x:x + 8], 'little')
    return table_f


# ============================================================
# protobuf 编码（保持原样）
# ============================================================
def _varint(value: int) -> bytes:
    value = int(value)
    if value < 0:
        value &= (1 << 64) - 1
    result = bytearray()
    while value > 0x7F:
        result.append((value & 0x7F) | 0x80)
        value >>= 7
    result.append(value)
    return bytes(result)


def _sint(value: int, bits: int) -> int:
    value = int(value)
    return (value << 1) if value >= 0 else (value << 1) ^ (~0)


def _proto_field(field: int, value: Any, kind: str) -> bytes:
    if value in (None, "", b"", 0, 0.0, False):
        return b""
    if kind == "sint32":
        return _varint((field << 3) | 0) + _varint(_sint(int(value), 32))
    if kind == "sint64":
        return _varint((field << 3) | 0) + _varint(_sint(int(value), 64))
    if kind == "float":
        return _varint((field << 3) | 5) + struct.pack("<f", float(value))
    if kind == "bytes":
        raw = bytes(value)
    elif kind == "string":
        raw = str(value).encode("utf-8")
    elif kind == "message":
        raw = bytes(value)
    else:
        raise ValueError(f"unknown protobuf field kind: {kind}")
    return _varint((field << 3) | 2) + _varint(len(raw)) + raw


def _proto(fields: list) -> bytes:
    return b"".join(_proto_field(field, value, kind) for field, value, kind in fields)


def _encode_request() -> bytes:
    return _proto([(1, 111, "sint32"), (2, 10, "sint32"),
                   (3, 694367, "sint32"), (5, 586952199, "sint32")])


def _encode_device(device: Mapping[str, Any]) -> bytes:
    fields = [
        (1, device.get("d1"), "sint32"), (2, device.get("collect_stat"), "sint32"),
        (3, device.get("aid"), "string"), (4, device.get("device_id"), "string"),
        (5, device.get("sec_device_token"), "string"), (6, device.get("app_version"), "string"),
        (7, device.get("battery"), "sint32"), (8, device.get("battery2"), "sint32"),
        (9, device.get("battery_health"), "sint32"), (10, device.get("battery_changed"), "sint32"),
        (11, device.get("network"), "string"), (12, device.get("tz"), "string"),
        (13, device.get("lan"), "string"), (14, device.get("cpu"), "sint32"),
        (15, device.get("resolution"), "string"), (16, device.get("sdcard"), "float"),
        (17, device.get("sdcard_used"), "float"), (18, device.get("memory"), "float"),
        (19, device.get("memory2"), "float"), (20, device.get("data"), "float"),
        (21, device.get("data_used"), "float"), (22, device.get("os_version"), "string"),
        (23, device.get("brightness"), "sint32"), (24, device.get("volume"), "sint32"),
        (25, device.get("ts"), "sint64"), (26, device.get("ts2"), "sint64"),
        (27, device.get("ts3"), "sint64"), (28, device.get("ts4"), "sint64"),
        (29, device.get("usb"), "sint32"), (30, device.get("hw_version"), "string"),
        (31, device.get("brand"), "string"), (32, device.get("board"), "string"),
        (33, device.get("product_name"), "string"), (34, device.get("product_device"), "string"),
        (35, device.get("product_manufacturer"), "string"), (36, device.get("hardware"), "string"),
        (38, device.get("unknown38"), "sint32"), (40, device.get("unknown40"), "sint32"),
    ]
    return _proto(fields)


def _encode_env(env: Mapping[str, Any]) -> bytes:
    fields = [
        (1, env.get("launch_time"), "sint32"), (2, env.get("unknown2"), "sint32"),
        (3, env.get("unknown3"), "sint32"), (5, env.get("unknown5"), "sint32"),
        (6, env.get("version"), "string"), (7, env.get("pid"), "sint32"),
        (12, _encode_device(env.get("device") or {}), "message"),
        (13, _proto([
            (1, (env.get("report") or {}).get("time"), "sint64"),
            (2, (env.get("report") or {}).get("state"), "sint32"),
            (4, (env.get("report") or {}).get("code"), "sint32"),
            (5, (env.get("report") or {}).get("times"), "sint32"),
            (6, (env.get("report") or {}).get("unknown6"), "sint32"),
        ]), "message"),
        (14, env.get("app_version"), "string"),
        (15, env.get("unknown15"), "sint32"), (16, env.get("unknown16"), "sint32"),
        (18, env.get("unknown18"), "sint32"), (19, env.get("unknown19"), "sint32"),
        (20, env.get("unknown20"), "sint32"), (21, env.get("unknown21"), "sint32"),
    ]
    return _proto(fields)


def _encode_medusa(values: Mapping[str, Any]) -> bytes:
    return _proto([
        (1, values.get("magic"), "bytes"), (2, values.get("version"), "sint32"),
        (3, values.get("rand"), "sint32"), (4, values.get("ms_app_id"), "string"),
        (5, values.get("device_id"), "string"), (6, values.get("license_id"), "string"),
        (7, values.get("app_version"), "string"), (8, values.get("sdk_version_str"), "string"),
        (9, values.get("sdk_version"), "sint32"), (10, values.get("xg_seed_bytes"), "bytes"),
        (12, values.get("time"), "sint32"), (13, values.get("query_body_ts_hash"), "bytes"),
        (14, values.get("query_sm3"), "bytes"), (15, _encode_request(), "message"),
        (16, values.get("sec_device_token"), "string"), (17, values.get("time2"), "sint32"),
        (18, values.get("lanusk_hash"), "bytes"), (19, values.get("query_body_hash_sm3"), "bytes"),
        (20, values.get("psk_version"), "string"), (21, values.get("call_type"), "sint32"),
        (23, _encode_env(values.get("env") or {}), "message"),
        (24, values.get("unknown24"), "string"), (26, values.get("original"), "string"),
    ])


def _json_body_md5(data: Any, data_type: str | None = None) -> str:
    if not data:
        return ""
    if isinstance(data, str):
        raw = data.encode("utf-8")
    elif isinstance(data, bytes):
        raw = data
    elif data_type == "application/json; charset=UTF-8":
        raw = json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    else:
        raw = urlencode(data).encode("utf-8")
    return hashlib.md5(raw).hexdigest().upper()


def _url_encode(value: Mapping[str, Any]) -> str:
    return urlencode(value).replace("+", "%20").replace("%2A", "*")


def _get_params_encrypturl(url: str, params: Mapping[str, Any], devices: Mapping[str, Any]):
    result = dict(params)
    for key, value in devices.items():
        if key in result:
            result[key] = value
        elif key == "device_id" and "did" in result:
            result["did"] = value
    result["ts"] = int(time.time())
    result["_rticket"] = int(time.time() * 1000)
    return url.split("?", 1)[0] + "?" + _url_encode(result), result


def _xg_rc4(data: bytes, key: bytes) -> bytearray:
    table = list(range(256))
    j = 0
    for i in range(256):
        j = (j + table[i] + key[i % len(key)]) % 256
        table[i] = table[j]
    i = j = 0
    result = bytearray(len(data))
    for index, value in enumerate(data):
        i = (i + 1) & 0xFF
        x = table[i]
        j = (j + x) & 0xFF
        y = table[j]
        table[i] = y
        result[index] = value ^ table[(y + y) & 0xFF]
    return result


def _reverse_bits(value: int) -> int:
    return int(f"{value:08b}"[::-1], 2)


def _encrypt_gorgon(body, query, khronos, xg_rand, data_type) -> str:
    body_md5 = _json_body_md5(body, data_type).lower() if body else ""
    data = bytearray(hashlib.md5(query.encode()).digest()[:4])
    data += bytes.fromhex(body_md5)[:4] if body_md5 else b"\0\0\0\0"
    data += b"\0\0\0\0" + (67503104).to_bytes(4, "little") + khronos.to_bytes(4, "big")
    key = bytes((0x4A, 320 & 0xFF, 0x16, (xg_rand >> 8) & 0xFF, 0x47, 0x6C, 1, xg_rand & 0xFF))
    result = _xg_rc4(data, key)
    for index, value in enumerate(result):
        value = ((value >> 4) | (value << 4)) & 0xFF
        following = result[index + 1] if index + 1 < len(result) else result[0]
        result[index] = (~(_reverse_bits(following ^ value) ^ 20)) & 0xFF
    return (b"\x84\x04" + xg_rand.to_bytes(2, "little")
            + (320).to_bytes(2, "little") + result).hex()


def _ror64(value: int, count: int) -> int:
    count %= 64
    return ((value >> count) | (value << (64 - count))) & 0xFFFFFFFFFFFFFFFF


def _encrypt_helios(khronos: int, rand_value: int = 0) -> str:
    value = rand_value or random.randint(0, 0xFFFFFFFF)
    seed = value.to_bytes(4, "little") + b"8662"
    digest = hashlib.md5(seed).digest()
    keys = b"".join(f"{item:02x}".encode() for item in digest)
    table = [int.from_bytes(keys[:8], "little")]
    words = [int.from_bytes(keys[i:i + 8], "little") for i in range(0, 32, 8)]
    first, second = words[0], words[1]
    words = words[2:]
    for index in range(0x22):
        value2 = _ror64(second, 8)
        value2 = (value2 + first) & 0xFFFFFFFFFFFFFFFF
        value2 = (value2 ^ index) & 0xFFFFFFFFFFFFFFFF
        words.append(value2)
        value2 ^= _ror64(first, 61)
        value2 &= 0xFFFFFFFFFFFFFFFF
        table.append(value2)
        first, second = value2, words.pop(0)
    raw = (f"{khronos}-1588093228-8662").encode()
    pad = 16 - len(raw) % 16
    raw += bytes([pad]) * pad
    output = bytearray()
    for offset in range(0, len(raw), 16):
        left = int.from_bytes(raw[offset:offset + 8], "little")
        right = int.from_bytes(raw[offset + 8:offset + 16], "little")
        for index in range(0x22):
            right = (table[index] ^ (left + _ror64(right, 8))) & 0xFFFFFFFFFFFFFFFF
            left = (right ^ _ror64(left, 61)) & 0xFFFFFFFFFFFFFFFF
        output += left.to_bytes(8, "little") + right.to_bytes(8, "little")
    return base64.b64encode(value.to_bytes(4, "little") + output).decode()


def _gen_medusa_proto(url, url_params, devices, data, khronos, data_type):
    body_md5 = _json_body_md5(data, data_type).lower() if data else ""
    body_md5_bytes = bytes.fromhex(body_md5) if body_md5 else bytes(16)
    ts_bytes = khronos.to_bytes(4, "little")
    query = url.split("?", 1)[1] if "?" in url else ""
    query_sm3 = SM3(query).digest()
    query_body_hash = SM3(query.encode() + body_md5_bytes + b"none").digest()
    device_id = str(devices.get("device_id", url_params.get("device_id", url_params.get("did", ""))))
    version_name = str(devices.get("version_name", url_params.get("version_name", "7.1.3.32")))
    device_model = str(devices.get("device_model", url_params.get("device_type", "")))
    brand = str(devices.get("device_brand", url_params.get("device_brand", "")))
    sec_device_token = str(devices.get("sec_device_token") or "")
    device_sec_device_token = str(devices.get("device_sec_device_token") or "")
    proto_rand = random.randint(0, 0xFFFFFFFF)
    launch_time = random.randint(100, 120)
    process_id = random.randint(10001, 12000)
    report_ts = 1728388016635
    report_time = int(time.time())
    device = {
        "d1": 1, "collect_stat": 2, "aid": "8662", "device_id": device_id,
        "sec_device_token": device_sec_device_token,
        "app_version": "!noperm!", "battery": -888888, "battery2": -888888,
        "battery_health": 3, "battery_changed": -888888, "network": "!notset!",
        "tz": "Asia/Shanghai,8", "lan": "zh_CN", "cpu": 4,
        "sdcard": 255.24993896484375, "sdcard_used": 35.58599090576172,
        "memory": 3.467449188232422, "memory2": 3.467449188232422,
        "data": 255.1754913330078, "data_used": 42.17544174194336,
        "os_version": str(devices.get("os_version", url_params.get("os_version", ""))),
        "brightness": 41, "volume": 36, "ts": report_ts, "ts2": report_ts,
        "ts3": report_ts, "ts4": report_ts + 2, "usb": -1, "hw_version": device_model,
        "brand": brand, "board": device_model, "product_name": device_model,
        "product_device": str(devices.get("device_manufacturer", brand)),
        "product_manufacturer": brand, "hardware": brand, "unknown38": 31,
    }
    env = {
        "launch_time": launch_time, "unknown2": 146331399,
        "unknown3": 146331396, "unknown5": 7, "version": "v04.06.04.03-bugfix",
        "pid": process_id, "device": device,
        "report": {"time": report_time, "state": -2, "code": 200, "times": 0, "unknown6": 0},
        "app_version": version_name,
    }
    values = {
        "magic": b"\xf7\xe8_\xfa\xd7\xd7\xdc;\xd6*\xc8pW\xcfa\x18",
        "version": 3, "rand": proto_rand, "ms_app_id": "8662",
        "device_id": device_id, "license_id": "1588093228", "app_version": version_name,
        "sdk_version_str": "v04.06.04-ml-android", "sdk_version": 67503104,
        "xg_seed_bytes": (320).to_bytes(8, "little"), "time": khronos,
        "query_body_ts_hash": hash_f13(query_sm3, body_md5_bytes, ts_bytes, khronos),
        "query_sm3": query_sm3[:6], "sec_device_token": sec_device_token, "time2": khronos,
        "lanusk_hash": b"", "query_body_hash_sm3": query_body_hash, "psk_version": "none",
        "call_type": 312, "env": env,
        "unknown24": '{"cmr":16777216,"cmr2":16777216,"un_h":1879194040,"vpn":0,"kd":0,"fkd":3672518972,"pd":-1872573247,"dyn":"","do":0,"tk":true}',
    }
    return _encode_medusa(values), query_sm3, hash_f13(query_sm3, body_md5_bytes, ts_bytes, khronos)


def _xmxor_two(data: bytes, key: bytes) -> bytearray:
    encoded = bytearray(len(data))
    for index, value in enumerate(data):
        position = (index * 4) & 28
        d0, d1 = key[position], key[position + 1]
        d2 = (rl8(value, 4) + d0) ^ d1
        d2 = rl8((~d2) & 0xFF, 3)
        d2 = ((d2 + d1) & 0xFF) ^ d0
        encoded[-index - 1] = (~d2) & 0xFF
    return encoded


def _xmxor(data: bytes, key: bytes) -> bytearray:
    value = _xmxor_two(data, key)
    last_flag = value[-1] ^ value[-2]
    data0 = value[0]
    value[0] = (~last_flag + value[0]) & 0xFF
    value[1] = ((value[0] ^ value[-1] ^ 254) + value[1]) & 0xFF
    value[2] = (value[2] + ((last_flag - data0) ^ rl8(value[1], 3) ^ 2)) & 0xFF
    for index in range(len(value) - 4):
        temp = rl8(value[index + 2], 3) ^ value[index + 1] ^ (index + 3)
        value[index + 3] = (~temp + value[index + 3]) & 0xFF
    value[-1] ^= value[-2]
    value[0] = ((value[0] ^ value[1]) + sum(value[1:])) & 0xFF
    return value


def _gen_medusa(url, url_params, devices, data, khronos, data_type) -> str:
    config_key = b"\xf1Y3vvn\xa9\x8d4\xf3\x1b\x05z\x9d[\xe4"
    config_iv = b"\x1f\xe1\t\xa4\x12R\x83\xf4\x18\xde\x9e\x05\x1a\x96\x9e\x12"
    sign_key = b"\x8e\xbd\xfa8\x06\xec\xc5\xce\xe7\x94#\xe6\x02\x9e\xd8%@\xbc\"\x18\xbb~\xae\xf7\x1c\xb6\x91\xf7\xaa\x8a\xa2\xf5"
    proto, query_sm3, body_sm3 = _gen_medusa_proto(url, url_params, devices, data, khronos, data_type)
    hash_rand = random.randint(0, 0xFFFFFFFF)
    xm_rand = random.randint(0, 0xFFFFFFFF)
    key, seed = get_key_hash(sign_key, hash_rand)
    mixed = _xmxor(proto, key)
    mixed = (320).to_bytes(8, "little") + mixed
    mixed = bytearray(mixed[::-1])
    for index in range(len(mixed)):
        mixed[index] ^= seed[~index & 3]
    hash_bytes = hash_rand.to_bytes(4, "little")
    check_bit = ((query_sm3[0] & 63) << 14) | 0x18000001 | ((body_sm3[0] & 63) << 8)
    mixed = b"\x35" + xm_rand.to_bytes(4, "little") + check_bit.to_bytes(4, "little") + mixed + hash_bytes[2:]
    mixed = AES_V3(config_key, khronos).encrypt(mixed, config_iv)
    version = bytes.fromhex("03 00 00 00 f7 e8 5f fa d7 d7 dc 3b d6 2a c8 70 57 cf 61 18")
    version_or = b"".join((int.from_bytes(version[i:i + 4], "little") ^ khronos).to_bytes(4, "little")
                          for i in range(0, 20, 4))
    return base64.b64encode(version_or + hash_bytes[:2] + (256).to_bytes(2, "little") + mixed).decode()


def _core_sixgod(url, params, devices, data, header):
    data_type = str(header.get("content-type", header.get("Content-Type", "")))
    xg_rand = random.randint(0, 0xFFFF)
    encrypted_url, url_params = _get_params_encrypturl(url, params, devices)
    khronos = int(time.time())
    encoded_query = _url_encode(url_params)
    values = {
        "khronos": str(khronos),
        "ladon": base64.b64encode(khronos.to_bytes(4, "big")).decode(),
        "argus": base64.b64encode(khronos.to_bytes(4, "little")).decode(),
        "gorgon": _encrypt_gorgon(data, encoded_query, khronos, xg_rand, data_type),
        "helios": _encrypt_helios(khronos, 0),
        "medusa": _gen_medusa(encrypted_url, url_params, devices, data, khronos, data_type),
    }
    signs = {
        "x-ladon": values["ladon"], "x-khronos": values["khronos"],
        "x-argus": values["argus"], "x-gorgon": values["gorgon"],
        "x-helios": values["helios"], "x-medusa": values["medusa"],
    }
    if data:
        signs["x-ss-stub"] = _json_body_md5(data, data_type)
    result_headers = {str(key).lower(): str(value) for key, value in header.items()}
    result_headers.update(signs)
    if devices.get("ua"):
        result_headers["user-agent"] = str(devices["ua"])
    result_headers["x-tt-dt"] = str(devices.get("x_tt_dt", ""))
    return result_headers, encrypted_url


def _device_config(config: Mapping[str, Any]) -> dict:
    device_id = _text(config.get("device_id"))
    install_id = _text(config.get("install_id"))
    if not device_id or not install_id:
        raise HongguoPluginError("缺少红果 device_id/install_id 配置")
    return {
        "device_id": device_id, "iid": install_id, "install_id": install_id,
        "device_brand": "Redmi", "device_model": "25053RT47C", "device_type": "25053RT47C",
        "device_manufacturer": "Xiaomi", "os_version": "16", "version_name": "7.1.3.32",
        "x_tt_dt": _text(config.get("x_tt_dt")),
        "sec_device_token": _text(config.get("sec_device_token")),
        "device_sec_device_token": _text(config.get("device_sec_device_token")),
        "ua": APP_UA,
    }


def _video_model(video_id: str, config: Mapping[str, Any]) -> dict:
    devices = _device_config(config)
    params = {
        "iid": devices["install_id"],
        "device_id": devices["device_id"],
        "ac": "wifi", "channel": "update_64", "aid": "8662",
        "app_name": "novelread", "version_code": "71332",
        "version_name": "7.1.3.32", "device_platform": "android",
        "os": "android", "ssmix": "a", "device_type": "25053RT47C",
        "device_brand": "Redmi", "language": "zh", "os_api": "36",
        "os_version": "16", "manifest_version_code": "71332",
        "resolution": "1280*2772", "dpi": "520",
        "update_version_code": "71332", "host_abi": "arm64-v8a",
        "dragon_device_type": "phone", "pv_player": "71332",
        "compliance_status": "0", "need_personal_recommend": "1",
        "player_so_load": "1", "is_android_pad_screen": "0",
    }
    payload = {
        "biz_param": {
            "detail_page_version": 0, "device_level": 3,
            "disable_digg_stat": False, "need_all_video_definition": True,
            "need_mp4_align": False, "use_os_player": False,
            "use_server_dns": False, "video_platform": 1024,
        },
        "mixed_video_id_map": {"1004": [video_id]},
    }
    request_headers = {
        "User-Agent": APP_UA,
        "Accept": "application/json; charset=utf-8,application/x-protobuf",
        "Content-Type": "application/json; charset=UTF-8",
        "x-xs-from-web": "0", "x-ss-req-ticket": str(int(time.time() * 1000)),
        "x-tt-request-tag": "t=0;n=0", "sdk-version": "2",
        "passport-sdk-version": "50561", "x-vc-bdturing-sdk-version": "3.7.2.cn",
    }
    signed_headers, signed_url = _core_sixgod(VIDEO_URL, params, devices, payload, request_headers)
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    response = requests.post(signed_url, headers=signed_headers, data=body, timeout=30)
    response_data = _json_response(response)
    data = response_data.get("data") or {}
    if not isinstance(data, Mapping):
        raise HongguoPluginError("video_model 数据为空")
    entry = data.get(video_id)
    if entry is None:
        for value in data.values():
            if isinstance(value, Mapping):
                entry = value
                break
            if isinstance(value, list) and value and isinstance(value[0], Mapping):
                entry = value[0]
                break
    if not isinstance(entry, Mapping):
        entry = data
    raw_model = entry.get("video_model") if isinstance(entry, Mapping) else None
    if raw_model is None:
        raw_model = data.get("video_model")
    if isinstance(raw_model, str):
        try:
            raw_model = json.loads(raw_model)
        except ValueError as exc:
            raise HongguoPluginError("video_model JSON 无效") from exc
    if not isinstance(raw_model, Mapping):
        raise HongguoPluginError("video_model 为空")
    return dict(raw_model)


def _video_list_from_model(model: Mapping[str, Any]) -> Any:
    for key in ("video_list", "dynamic_video_list"):
        if model.get(key) is not None:
            return model[key]
    dynamic = model.get("dynamic_video")
    if isinstance(dynamic, Mapping):
        for key in ("dynamic_video_list", "video_list", "list"):
            if dynamic.get(key) is not None:
                return dynamic[key]
    video_info = model.get("video_info")
    if isinstance(video_info, Mapping):
        data = video_info.get("data")
        if isinstance(data, Mapping):
            return _video_list_from_model(data)
    data = model.get("data")
    if isinstance(data, Mapping):
        return _video_list_from_model(data)
    return None


_QUALITY_ORDER = ("2160", "1440", "1080", "720", "576", "540", "480", "360")


def _int(value: Any) -> int:
    match = re.search(r"\d+", _text(value))
    return int(match.group()) if match else 0


def _quality(value: Any) -> str:
    text = _text(value).lower()
    match = re.search(r"(2160|1440|1080|720|576|540|480|360)", text)
    return match.group(1) if match else "1080"


def _select_quality(video_list: Any, wanted: str = "1080") -> tuple:
    def rows_from(value, hinted_quality=""):
        if isinstance(value, list):
            result = []
            for item in value:
                result.extend(rows_from(item, hinted_quality))
            return result
        if not isinstance(value, Mapping):
            return []
        if any(key in value for key in ("main_url", "backup_url", "backup_url_1",
                                        "play_addr", "spade_a", "encrypt_info")):
            return [(hinted_quality, dict(value))]
        result = []
        for key, item in value.items():
            if key in {"dynamic_video", "video_info", "data"} and isinstance(item, Mapping):
                result.extend(rows_from(item, hinted_quality))
                continue
            if key in {"video_list", "dynamic_video_list", "list"}:
                result.extend(rows_from(item, _quality(key)))
                continue
            if isinstance(item, (Mapping, list)):
                result.extend(rows_from(item, _quality(key)))
        return result

    candidates = rows_from(video_list)
    rows = {}
    for hinted_quality, item in candidates:
        definition = _quality(item.get("definition") or item.get("vheight")
                              or (item.get("video_meta") or {}).get("definition")
                              or hinted_quality)
        rows[definition] = item
    if not rows:
        raise HongguoPluginError("播放模型没有清晰度")
    requested = _quality(wanted)
    order = [requested] + [item for item in _QUALITY_ORDER if item != requested]
    for definition in order:
        if definition in rows:
            return definition, rows[definition]
    definition = max(rows, key=lambda item: _int(item))
    return definition, rows[definition]


def _fallback_api_value(value: Any) -> str:
    if isinstance(value, Mapping):
        return _first(value.get("fallback_api"), value.get("url"),
                      value.get("api"), value.get("data"))
    if isinstance(value, (list, tuple)):
        for item in value:
            result = _fallback_api_value(item)
            if result:
                return result
        return ""
    text = _text(value)
    if text.startswith("{"):
        try:
            decoded = json.loads(text)
        except ValueError:
            decoded = {}
        if decoded:
            return _fallback_api_value(decoded)
    return text if len(text) > 10 else ""


def _decrypt_spade_url(value: str, key_seed: bytes) -> str:
    raw = _b64(value)
    if len(raw) < 20 or raw[0] != 0xA8 or raw[2:4] != b"\x01\x00":
        raise HongguoPluginError("spade URL 头无效")
    cipher_data = raw[4: len(raw) - (len(raw) - 4) % 16]
    if not cipher_data:
        raise HongguoPluginError("spade URL 密文为空")
    constants = bytes.fromhex(
        "4dd4c2e6b83162090e52b3c7a6733ba4"
        "1cb2462b829ab58a196b39db57177524"
        "f49baf7f08e8d68d26a72e37c1a95a2f"
        "1f05a51892aef2949732b62a38aadd58")
    first = hashlib.sha512(key_seed).digest()
    second = hashlib.sha512(first + constants).digest()
    plaintext = _aes_cbc_decrypt(second[:16], second[16:32], cipher_data)
    if plaintext:
        padding = plaintext[-1]
        if 1 <= padding <= 16 and padding <= len(plaintext):
            plaintext = plaintext[:-padding]
    return plaintext.rstrip(b"\0").decode("utf-8", errors="replace")


def _parse_ref(value: str, prefix: str) -> str:
    if not value.startswith(prefix):
        raise HongguoPluginError("播放引用无效")
    raw = value[len(prefix):]
    if not raw or not _VIDEO_ID.fullmatch(raw):
        raise HongguoPluginError("播放引用格式无效")
    return raw


def _key_seed_from_model(model: Mapping[str, Any]) -> bytes:
    value = _text(model.get("key_seed"))
    if value:
        return _b64(value)
    for key in ("dynamic_video", "video_info", "data"):
        nested = model.get(key)
        if isinstance(nested, Mapping):
            result = _key_seed_from_model(nested)
            if result:
                return result
    return b""


_VIDEO_ID = re.compile(r"^\d+$")


# ============================================================
# CENC 解密（保持原样）
# ============================================================
def _find_box(data, fourcc, start):
    for index in range(max(4, start), len(data) - 4):
        if data[index: index + 4] != fourcc:
            continue
        size = struct.unpack(">I", data[index - 4: index])[0]
        if size == 1 and index + 12 <= len(data):
            size = struct.unpack(">Q", data[index + 4: index + 12])[0]
        if 8 <= size <= 5_000_000 and index - 4 + size <= len(data):
            return index - 4, size
    return -1, 0


def _box_body(data, fourcc, start):
    offset, size = _find_box(data, fourcc, start)
    return data[offset + 8: offset + size] if offset >= 0 else None


def _parse_track(moov, track_offset):
    if track_offset < 0:
        return None
    stbl_offset, _ = _find_box(moov, b"stbl", track_offset + 8)
    if stbl_offset < 0:
        return None
    stsz = _box_body(moov, b"stsz", stbl_offset)
    stco = _box_body(moov, b"stco", stbl_offset)
    co64 = _box_body(moov, b"co64", stbl_offset)
    stsc = _box_body(moov, b"stsc", stbl_offset)
    saiz = _box_body(moov, b"saiz", stbl_offset)
    saio = _box_body(moov, b"saio", stbl_offset)
    if any(v is None for v in (stsz, stsc, saiz, saio)) or (stco is None and co64 is None):
        return None
    default_size = struct.unpack(">I", stsz[4:8])[0]
    sample_count = struct.unpack(">I", stsz[8:12])[0]
    sizes = [default_size] * sample_count if default_size else [
        struct.unpack(">I", stsz[12 + i * 4: 16 + i * 4])[0] for i in range(sample_count)
    ]
    chunk_table = stco if stco is not None else co64
    chunk_count = struct.unpack(">I", chunk_table[4:8])[0]
    chunk_width = 4 if stco is not None else 8
    offsets = [int.from_bytes(chunk_table[8 + i * chunk_width: 8 + (i + 1) * chunk_width], "big")
               for i in range(chunk_count)]
    entry_count = struct.unpack(">I", stsc[4:8])[0]
    entries = [(struct.unpack(">I", stsc[8 + i * 12: 12 + i * 12])[0],
                struct.unpack(">I", stsc[12 + i * 12: 16 + i * 12])[0])
               for i in range(entry_count)]
    chunk_samples = [0] * chunk_count
    for index, (first_chunk, samples_per_chunk) in enumerate(entries):
        end = entries[index + 1][0] - 1 if index + 1 < len(entries) else chunk_count
        for chunk in range(first_chunk - 1, min(end, chunk_count)):
            chunk_samples[chunk] = samples_per_chunk
    saiz_flags = int.from_bytes(saiz[1:4], "big")
    saiz_cursor = 12 if saiz_flags & 1 else 4
    if len(saiz) < saiz_cursor + 5:
        return None
    default_aux_size = saiz[saiz_cursor]
    aux_count = struct.unpack(">I", saiz[saiz_cursor + 1: saiz_cursor + 5])[0]
    aux_sizes = [default_aux_size] * aux_count if default_aux_size else [
        int(saiz[saiz_cursor + 5 + i]) for i in range(aux_count)
        if saiz_cursor + 5 + i < len(saiz)
    ]
    if len(aux_sizes) != aux_count:
        return None
    saio_flags = int.from_bytes(saio[1:4], "big")
    saio_cursor = 12 if saio_flags & 1 else 4
    offset_width = 8 if saio[0] == 1 else 4
    if len(saio) < saio_cursor + 4 + offset_width:
        return None
    entry_count = int.from_bytes(saio[saio_cursor: saio_cursor + 4], "big")
    if entry_count < 1:
        return None
    aux_offset = int.from_bytes(saio[saio_cursor + 4: saio_cursor + 4 + offset_width], "big")
    return sizes, offsets, chunk_samples, aux_sizes, aux_offset, sample_count


def _replace_fourcc(data, old, new):
    position = 0
    while True:
        position = data.find(old, position)
        if position < 0:
            return
        data[position: position + len(old)] = new
        position += len(new)


def _replace_sinf(data):
    position = 0
    while True:
        position = data.find(b"sinf", position)
        if position < 0:
            return
        if position >= 4:
            size = struct.unpack(">I", data[position - 4: position])[0]
            end = position - 4 + size
            if 8 <= size < 50_000 and end <= len(data):
                data[position: position + 4] = b"free"
                data[position + 4: end] = b"\x00" * max(0, end - position - 4)
                position = end
                continue
        position += 4


def decrypt_mp4_cenc(data, content_key):
    if len(content_key) != 16:
        raise HongguoPluginError("CENC 密钥长度错误")
    result = bytearray(data)
    if len(result) < 16:
        raise HongguoPluginError("MP4 数据过短")
    moov_start, moov_size = _find_box(memoryview(result), b"moov", 0)
    if moov_start < 0 or moov_size < 8:
        raise HongguoPluginError("MP4 moov 越界")
    moov = memoryview(result)[moov_start: moov_start + moov_size]
    tracks = []
    track_search = 0
    while True:
        track, track_size = _find_box(moov, b"trak", track_search)
        if track < 0:
            break
        tracks.append(track)
        track_search = track + max(track_size, 8)
    decrypted_samples = 0
    for track in tracks:
        parsed = _parse_track(moov, track)
        if parsed is None:
            continue
        sizes, offsets, chunk_counts, aux_sizes, aux_offset, sample_count = parsed
        aux_size = sum(max(s, 8) for s in aux_sizes)
        if not sample_count or aux_offset < 0 or aux_offset + aux_size > len(result):
            continue
        aux = result[aux_offset: aux_offset + aux_size]
        sample_index = 0
        aux_index = 0
        for chunk_index, chunk_offset in enumerate(offsets):
            current = chunk_offset
            for _ in range(chunk_counts[chunk_index]):
                if sample_index >= sample_count or sample_index >= len(sizes):
                    break
                size = sizes[sample_index]
                if current + size > len(result):
                    raise HongguoPluginError("MP4 样本越界")
                if sample_index >= len(aux_sizes):
                    raise HongguoPluginError("MP4 辅助信息数量不足")
                entry_size = max(aux_sizes[sample_index], 8)
                iv = bytes(aux[aux_index: aux_index + min(entry_size, 8)]).ljust(8, b"\0") + b"\0" * 8
                result[current: current + size] = _aes_ctr_decrypt(
                    content_key, iv, bytes(result[current: current + size]))
                current += size
                sample_index += 1
                aux_index += entry_size
                decrypted_samples += 1
    if not decrypted_samples:
        raise HongguoPluginError("MP4 没有可解密的 CENC 样本")
    moov_buffer = bytearray(result[moov_start: moov_start + moov_size])
    _restore_cenc_codecs(moov_buffer)
    _replace_sinf(moov_buffer)
    result[moov_start: moov_start + moov_size] = moov_buffer
    return bytes(result)


MEDIA_HEADERS = {"User-Agent": MEDIA_UA, "Referer": "https://novel.snssdk.com/"}

_STREAM_PORT_RANGE = (9990, 10000)
_STREAM_CHUNK = 1 << 20
_STREAM_HEAD_PROBE = 1 << 16
_STREAM_TTL_SECONDS = 900
_STREAM_MAX_SESSIONS = 4
_STREAM_STATE = {"port": 0, "server": None, "sessions": {}}
_STREAM_LOCK = threading.RLock()


def _toplevel_boxes(buf):
    boxes = []
    cursor = 0
    while cursor + 8 <= len(buf):
        size = struct.unpack(">I", buf[cursor: cursor + 4])[0]
        fourcc = bytes(buf[cursor + 4: cursor + 8])
        if size == 1:
            if cursor + 16 > len(buf):
                break
            size = struct.unpack(">Q", buf[cursor + 8: cursor + 16])[0]
        if size < 8:
            break
        boxes.append((cursor, size, fourcc))
        cursor += size
    return boxes


def _range_get(url, start, end):
    headers = dict(MEDIA_HEADERS)
    headers["Range"] = "bytes=%d-%d" % (start, end)
    expected = end - start + 1
    last_error = None
    for attempt in range(_RANGE_FETCH_ATTEMPTS):
        if attempt:
            time.sleep(_RANGE_FETCH_BACKOFF_SECONDS * attempt)
        try:
            response = requests.get(url, headers=headers, timeout=60)
        except requests.RequestException as error:
            last_error = error
            continue
        if response.status_code not in (200, 206):
            last_error = HongguoPluginError("媒体分片请求失败 %s" % response.status_code)
            continue
        body = response.content
        if not body or (response.status_code == 206 and len(body) < expected):
            last_error = HongguoPluginError("媒体分片长度不足 %d/%d" % (len(body), expected))
            continue
        total = 0
        cr = response.headers.get("Content-Range") or ""
        if "/" in cr:
            tail = cr.rsplit("/", 1)[1].strip()
            if tail.isdigit():
                total = int(tail)
        if not total:
            length = response.headers.get("Content-Length") or ""
            total = int(length) if length.isdigit() else 0
        return body, total
    raise last_error or HongguoPluginError("媒体分片请求失败")


def _fetch_moov(url):
    probe, total = _range_get(url, 0, _STREAM_HEAD_PROBE - 1)
    if not total:
        raise HongguoPluginError("媒体总长度未知")
    moov_start = 0
    moov_size = 0
    for offset, size, fourcc in _toplevel_boxes(probe):
        if fourcc == b"moov":
            moov_start = offset
            moov_size = size
            break
    if not moov_size:
        raise HongguoPluginError("未找到 moov 顶层盒")
    if moov_start + moov_size > total:
        raise HongguoPluginError("moov 越界")
    if moov_start + moov_size <= len(probe):
        return total, moov_start, bytes(probe[moov_start: moov_start + moov_size])
    moov, _ = _range_get(url, moov_start, moov_start + moov_size - 1)
    if len(moov) != moov_size:
        raise HongguoPluginError("moov 分片长度不符")
    return total, moov_start, moov


def _original_format_near(data, entry_pos, default):
    blob = bytes(data[entry_pos: min(len(data), entry_pos + 800)])
    idx = 0
    while True:
        pos = blob.find(b"frma", idx)
        if pos < 0:
            return default
        if pos + 8 <= len(blob):
            fmt = bytes(blob[pos + 4: pos + 8])
            if fmt not in (b"", b"\x00\x00\x00\x00", b"encv", b"enca") and all(32 <= c < 127 for c in fmt):
                return fmt
        idx = pos + 4


def _restore_cenc_codecs(data):
    pos = 0
    while True:
        pos = data.find(b"encv", pos)
        if pos < 0:
            break
        data[pos: pos + 4] = _original_format_near(data, pos, b"avc1")
        pos += 4
    pos = 0
    while True:
        pos = data.find(b"enca", pos)
        if pos < 0:
            break
        data[pos: pos + 4] = _original_format_near(data, pos, b"mp4a")
        pos += 4


def _rewrite_moov(moov):
    result = bytearray(moov)
    _restore_cenc_codecs(result)
    _replace_sinf(result)
    return bytes(result)


def _sample_table(moov, moov_start):
    view = memoryview(moov)
    samples = []
    track_search = 0
    while True:
        track, track_size = _find_box(view, b"trak", track_search)
        if track < 0:
            break
        track_search = track + max(track_size, 8)
        parsed = _parse_track(view, track)
        if parsed is None:
            continue
        sizes, offsets, chunk_counts, aux_sizes, aux_offset, sample_count = parsed
        aux_length = sum(max(s, 8) for s in aux_sizes)
        aux_local = aux_offset - moov_start
        if aux_local < 0 or aux_local + aux_length > len(moov):
            raise HongguoPluginError("CENC 辅助信息不在 moov 内，无法流式解密")
        aux = moov[aux_local: aux_local + aux_length]
        sample_index = 0
        aux_index = 0
        for chunk_index, chunk_offset in enumerate(offsets):
            current = chunk_offset
            for _ in range(chunk_counts[chunk_index]):
                if sample_index >= sample_count or sample_index >= len(sizes):
                    break
                if sample_index >= len(aux_sizes):
                    raise HongguoPluginError("CENC 辅助信息数量不足")
                entry_size = max(aux_sizes[sample_index], 8)
                iv = bytes(aux[aux_index: aux_index + min(entry_size, 8)]).ljust(8, b"\0") + b"\0" * 8
                samples.append((current, sizes[sample_index], iv))
                current += sizes[sample_index]
                aux_index += entry_size
                sample_index += 1
    if not samples:
        raise HongguoPluginError("moov 中没有可解密的 CENC 样本")
    samples.sort()
    return samples


class _StreamSession:
    def __init__(self, url, content_key, total, moov_start, moov):
        if len(content_key) != 16:
            raise


# ============================================================
# ========== 红果短剧 2026-10 修复补丁（追加在文件末尾即可）==========
# 覆盖内容：
#   - _page / _data          （不再强依赖 _ROUTER_DATA + 加 Cookie）
#   - 新增 _parse_cards_html / _extract_json_ld_episodes
#   - homeContent / homeVideoContent / categoryContent
#   - searchContent / detailContent / playerContent
# 原有常量、CENC 解密、x-bogus 签名：全部不动
# ============================================================

_GLOBAL_COOKIE = (
    "ttwid=1%7CFUe-ibOEzn12SnhVP5nOngwf5MskiJr-lpk7vofauZU%7C1792971906"
    "%7Cd963d4932d31ef188fabdf562dd0a877a05a764af65ba2628747b2bf00086a7d; "
    "gfkadpd=8662,48688; biz_trace_id=5337fe76; "
    "passport_csrf_token=dbad8c67f041074db23d7d3c256d44ee; "
    "passport_csrf_token_default=dbad8c67f041074db23d7d3c256d44ee; "
    "s_v_web_id=verify_mvohn33s_51c923f8_bf06_e515_8d72_db4b61c56533; "
    "passport_mfa_token=Cjj1KZy5OQ%2FgeVBU6dGaNX3zj9LRYPPIaJw9de3stkdDfpkvxxyRAb%2FsiG5ak7UvMzCh95vXpYfV7hpKCjwAAAAAAAAAAAAAUQ%2BdUPUO1oJjwuRvzYzHUlxDQKpkWfK2CbMCefRjKYJrHTai1pHiqtci14tpjONL0qkQkvKfDhj2sdFsIAIiAQPJvLze; "
    "d_ticket=927f013eb2451ea41f6447f7c923a3d58f9ef; "
    "odin_tt=1b226008f93c9d612cfd5aee59a4d5ce75624bca6c141d1d5580e0a37de7c95dd51764d1dc4aad9425112655d7949248b6d6f38a10bcb58fd7e456db67e3a7c2; "
    "n_mh=Fi8Chlxlfbrkp34GV4R3gHj7qtGbmcKuK4hS_6MHDU0; "
    "passport_auth_status=25d9b84afcda1658710a2ad19a464008%2C; "
    "passport_auth_status_ss=25d9b84afcda1658710a2ad19a464008%2C; "
    "sid_guard=fcb1646b867814ca355be9580dacd9e1%7C1792972707%7C5184000%7CThu%2C+24-Dec-2026+23%3A58%3A27+GMT; "
    "uid_tt=902cadfa8f6ede901d5a4ad9fffaaa5e; "
    "uid_tt_ss=902cadfa8f6ede901d5a4ad9fffaaa5e; "
    "sid_tt=fcb1646b867814ca355be9580dacd9e1; "
    "sessionid=fcb1646b867814ca355be9580dacd9e1; "
    "sessionid_ss=fcb1646b867814ca355be9580dacd9e1; "
    "session_tlb_tag=sttt%7C3%7C_LFka4Z4FMo1W-lYDazZ4f_________6WuJ8pUQnYbohCqDBJqOb8eNG_vt1gpcUe2HrHYIGu8M%3D; "
    "is_staff_user=false; has_biz_token=false; "
    "sid_ucp_v1=1.0.0-KGUxYWNiMzZmYzhhMTY1OGYyNzZlYmFmNzVmNzAyNGE3ZTBmY2ZiNDAKIAig84ChoM3QARCjr_rWBhjbrR8gDDDnhIGlBjgCQPEHGgJsZiIgZmNiMTY0NmI4Njc4MTRjYTM1NWJlOTU4MGRhY2Q5ZTE; "
    "ssid_ucp_v1=1.0.0-KGUxYWNiMzZmYzhhMTY1OGYyNzZlYmFmNzVmNzAyNGE3ZTBmY2ZiNDAKIAig84ChoM3QARCjr_rWBhjbrR8gDDDnhIGlBjgCQPEHGgJsZiIgZmNiMTY0NmI4Njc4MTRjYTM1NWJlOTU4MGRhY2Q5ZTE"
)

_PC_UA = (
    "Mozilla/5.0 (Linux; Android 6.0; Nexus 5 Build/MRA58N) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/132.0.0.0 Mobile Safari/537.36"
)


def _pc_headers():
    h = {
        "User-Agent": _PC_UA,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,"
                  "image/avif,image/webp,image/apng,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9",
        "Cache-Control": "no-cache",
        "Referer": SITE + "/",
    }
    if _GLOBAL_COOKIE:
        h["Cookie"] = _GLOBAL_COOKIE
    return h


def _page(url):
    last_err = None
    for attempt in range(3):
        try:
            r = requests.get(url, headers=_pc_headers(), timeout=30)
            r.raise_for_status()
            r.encoding = r.encoding or "utf-8"
            text = r.text or ""
            if len(text) < 500:
                raise RuntimeError("empty page")
            return text
        except Exception as err:
            last_err = err
            try:
                time.sleep(0.6 * (attempt + 1))
            except Exception:
                pass
    raise RuntimeError("page fetch failed: %s" % last_err)


def _data(url):
    html = _page(url)

    m = re.search(r"(?:window\.)?_ROUTER_DATA\s*=\s*", html)
    if m:
        try:
            return json.JSONDecoder().raw_decode(html[m.end():])[0]
        except (ValueError, TypeError):
            pass

    m = re.search(r'<script[^>]+id="__NEXT_DATA__"[^>]*>(.*?)</script>',
                  html, re.S)
    if m:
        try:
            return json.loads(m.group(1))
        except (ValueError, TypeError):
            pass

    for var in ("__INITIAL_STATE__", "__INITIAL_DATA__", "__DATA__"):
        m = re.search(rf"(?:window\.)?{var}\s*=\s*", html)
        if m:
            try:
                return json.JSONDecoder().raw_decode(html[m.end():])[0]
            except (ValueError, TypeError):
                pass

    for m in re.finditer(
        r'<script[^>]+type="application/json"[^>]*>(.*?)</script>',
        html, re.S,
    ):
        try:
            obj = json.loads(m.group(1))
            if isinstance(obj, dict) and obj:
                return obj
        except (ValueError, TypeError):
            pass

    return {}


def _parse_cards_html(html):
    cards = []
    seen = set()
    for m in re.finditer(
        r'<a[^>]*href="(/detail\?series_id=(\d+))"[^>]*>(.*?)</a>',
        html, re.S,
    ):
        href, sid, block = m.group(1), m.group(2), m.group(3)
        if sid in seen:
            continue
        seen.add(sid)

        title = ""
        tm = re.search(r'<p[^>]*class="[^"]*pc-title[^"]*"[^>]*>([^<]+)</p>', block)
        if tm:
            title = tm.group(1).strip()
        if not title:
            am = re.search(r'<img[^>]*alt="([^"]+)"', block)
            if am:
                title = am.group(1).strip()

        pic = ""
        pm = re.search(r'<img[^>]*class="[^"]*image[^"]*"[^>]*src="([^"]+)"', block)
        if pm:
            pic = pm.group(1)
        if not pic:
            pm = re.search(r'<img[^>]*src="(https?://[^"]+)"', block)
            if pm:
                pic = pm.group(1)

        ep = ""
        em = re.search(r'<p[^>]*class="[^"]*pc-episode[^"]*"[^>]*>([^<]+)</p>', block)
        if em:
            ep = em.group(1).strip()

        tags = re.findall(
            r'<span[^>]*class="[^"]*pc-tag-text[^"]*"[^>]*>([^<]+)</span>',
            block,
        )
        tags = [t.strip() for t in tags if t.strip()]

        if title and sid:
            cards.append({
                "vod_id": sid,
                "vod_name": title,
                "vod_pic": pic,
                "vod_remarks": ep,
                "vod_content": " / ".join(tags),
            })
    return cards


def _extract_json_ld_episodes(html, series_id=""):
    episodes = []
    for m in re.finditer(
        r'<script[^>]+type="application/ld\+json"[^>]*>(.*?)</script>',
        html, re.S,
    ):
        try:
            data = json.loads(m.group(1))
        except Exception:
            continue
        items = data if isinstance(data, list) else [data]
        for item in items:
            if not isinstance(item, dict):
                continue
            if item.get("@type") != "TVEpisode":
                continue
            content_url = item.get("contentUrl") or ""
            if not content_url:
                continue
            episodes.append({
                "url": content_url,
                "name": item.get("name") or "",
            })
    return episodes


def _patched_homeContent(self, filter):
    class_list = [
        {"type_id": "/category/real-drama", "type_name": "真人剧"},
        {"type_id": "/category/comic-drama", "type_name": "漫剧"},
        {"type_id": "/category/ai-drama", "type_name": "AI剧"},
        {"type_id": "/category/comic", "type_name": "漫画"},
    ]
    home_list = []
    try:
        html = _page(SITE + "/")
        home_list = _parse_cards_html(html)[:40]
    except Exception:
        home_list = []
    return {"class": class_list, "list": home_list}


def _patched_homeVideoContent(self):
    try:
        html = _page(SITE + "/")
        return {"list": _parse_cards_html(html)[:60]}
    except Exception:
        return {"list": []}


def _patched_categoryContent(self, tid, pg, filter, extend):
    try:
        page = max(1, int(pg))
    except (TypeError, ValueError):
        page = 1

    tid_str = str(tid)
    if tid_str.startswith("/category/"):
        base = SITE + tid_str
    elif tid_str in ("comic", "manju", "漫剧"):
        base = SITE + "/category/comic-drama"
    elif tid_str in ("ai_comic", "ai_manju", "AI漫剧", "ai漫剧"):
        base = SITE + "/category/ai-drama"
    elif tid_str == "/":
        base = SITE + "/"
    else:
        base = SITE + "/category/real-drama"

    url = base + (f"?page={page}" if page > 1 else "")
    try:
        html = _page(url)
        items = _parse_cards_html(html)
        max_page = page
        for m in re.finditer(r'href="[^"]*[?&]page=(\d+)"', html):
            try:
                n = int(m.group(1))
                if n > max_page:
                    max_page = n
            except Exception:
                pass
        return {
            "page": page,
            "pagecount": max_page,
            "limit": len(items),
            "total": max_page * len(items) if items else 0,
            "list": items,
        }
    except Exception:
        return {"page": page, "pagecount": 1, "limit": 0, "total": 0, "list": []}


def _patched_searchContent(self, key, quick=False, pg="1"):
    try:
        page = max(1, int(pg))
    except (TypeError, ValueError):
        page = 1
    key = str(key or "").strip() or "短剧"

    try:
        api_url = f"{SITE}/search?q={quote(key)}&page={page}"
        r = requests.get(api_url, headers=_pc_headers(), timeout=15)
        if r.status_code == 200:
            try:
                data = r.json()
                rows = data.get("data") or data.get("list") or []
                if isinstance(rows, list) and rows:
                    items = []
                    for row in rows:
                        sid = str(row.get("series_id") or row.get("id") or "")
                        name = row.get("series_name") or row.get("title") or ""
                        if sid and name:
                            items.append({
                                "vod_id": sid,
                                "vod_name": name,
                                "vod_pic": row.get("cover") or row.get("pic") or "",
                                "vod_remarks": row.get("episode_cnt") or "",
                            })
                    if items:
                        return {"page": page, "pagecount": 1,
                                "limit": len(items), "total": len(items),
                                "list": items}
            except Exception:
                pass
    except Exception:
        pass

    for url in (
        f"{SITE}/search/{quote(key)}",
        f"{SITE}/search?keyword={quote(key)}",
        f"{SITE}/search?q={quote(key)}",
    ):
        try:
            html = _page(url)
            items = _parse_cards_html(html)
            if items:
                return {"page": page, "pagecount": 1,
                        "limit": len(items), "total": len(items),
                        "list": items}
        except Exception:
            continue

    return {"page": page, "pagecount": 1, "limit": 0, "total": 0, "list": []}


def _patched_detailContent(self, ids):
    sid = str(ids[0] if isinstance(ids, (list, tuple)) else ids)
    sid = sid.replace("hg-series-v1:", "")

    series_name = ""
    series_cover = ""
    series_intro = ""
    episode_right_text = ""
    actors = []
    vids = []

    try:
        data = _data(SITE + "/detail?series_id=" + quote(sid, safe=""))
        p = (data.get("loaderData") or {}).get("detail_page") or {}
        s = p.get("seriesDetail") or {}
        series_name = str(s.get("series_name") or "")
        series_cover = str(s.get("series_cover") or "")
        series_intro = str(s.get("series_intro") or "")
        episode_right_text = str(s.get("episode_right_text") or "")
        vids = list(s.get("vid_list") or [])
        actors = [str(x.get("nickname"))
                  for x in (s.get("celebrities") or [])
                  if isinstance(x, dict) and x.get("nickname")]
    except Exception:
        pass

    html = ""
    try:
        html = _page(SITE + "/detail?series_id=" + quote(sid, safe=""))
    except Exception:
        pass

    episodes = []
    if html:
        episodes = _extract_json_ld_episodes(html, sid)
        if not series_name:
            m = re.search(r'<title>([^<]+)</title>', html)
            if m:
                series_name = re.split(r"[_\-|–]", m.group(1))[0].strip()
        if not series_cover:
            m = re.search(r'<meta[^>]+property="og:image"[^>]+content="([^"]+)"', html)
            if m:
                series_cover = m.group(1)

    play_from = []
    play_url = []
    if episodes:
        play_from.append("红果短剧")
        play_url.append("#".join(
            f"{ep.get('name') or ('第%d集' % (i + 1))}${ep['url']}"
            for i, ep in enumerate(episodes)
        ))
    elif vids:
        for q, line_name in _HG_QUALITY_LINES:
            eps = "#".join(
                "第%d集%s%s%s%s" % (i + 1, "$", EPISODE_PREFIX, q + ":", str(v))
                for i, v in enumerate(vids)
            )
            play_from.append(line_name)
            play_url.append(eps)
    else:
        play_from.append("红果短剧")
        play_url.append(f"未找到播放源${SITE}/detail?series_id={sid}")

    return {"list": [{
        "vod_id": sid,
        "vod_name": series_name,
        "vod_pic": series_cover,
        "vod_year": "", "vod_area": "", "vod_director": "",
        "vod_actor": ",".join(actors),
        "vod_content": series_intro,
        "vod_remarks": episode_right_text,
        "vod_play_from": "$$$".join(play_from),
        "vod_play_url": "$$$".join(play_url),
    }]}


def _patched_playerContent(self, flag, id, vipFlags=None):
    if str(id).startswith("http") and ".mp4" in str(id).lower():
        return {
            "parse": 0,
            "jx": 0,
            "playUrl": "",
            "url": id,
            "header": _pc_headers(),
        }

    token_q, vid = _split_episode_token(id)
    line_q = "1080"
    for name_key, candidate_q in _QUALITY_LINE_NAME_TO_Q.items():
        if name_key in str(flag or ""):
            line_q = candidate_q
            break
    q = line_q if token_q == "1080" and str(flag) else token_q
    q = q if q in _QUALITY_LINE_NAME_TO_Q else "1080"

    if not str(vid).isdigit():
        return {
            "parse": 1, "jx": 0, "playUrl": "",
            "url": SITE + "/",
            "header": {"User-Agent": _PC_UA},
        }

    proxy = ""
    try:
        if hasattr(self, "getProxyUrl"):
            proxy = (self.getProxyUrl() or "").strip()
    except Exception:
        proxy = ""

    if proxy:
        sep = "&" if "?" in proxy else "?"
        url = proxy + sep + urlencode({
            "vid": vid,
            "q": q,
            "hg": "cenc",
            "did": self.device_id or "",
            "iid": self.install_id or "",
        })
        return {
            "parse": 0, "jx": 0, "playUrl": "",
            "url": url,
            "header": {
                "User-Agent": MEDIA_UA,
                "Referer": "https://novel.snssdk.com/",
            },
        }

    try:
        port = _start_stream_server()
    except Exception:
        port = 0
    if port:
        query = urlencode({
            "vid": vid, "q": q,
            "did": self.device_id or "",
            "iid": self.install_id or "",
        })
        return {
            "parse": 0, "jx": 0, "playUrl": "",
            "url": "http://127.0.0.1:%d/hg.mp4?%s" % (port, query),
            "header": {"User-Agent": _PC_UA},
        }

    return {
        "parse": 1, "jx": 0, "playUrl": "",
        "url": SITE + "/",
        "header": {"User-Agent": _PC_UA},
    }


# ---- 应用补丁 ----
Spider.homeContent       = _patched_homeContent
Spider.homeVideoContent  = _patched_homeVideoContent
Spider.categoryContent   = _patched_categoryContent
Spider.searchContent     = _patched_searchContent
Spider.detailContent     = _patched_detailContent
Spider.playerContent     = _patched_playerContent

print("[红果短剧] 补丁已应用：homeContent / homeVideoContent / "
      "categoryContent / searchContent / detailContent / playerContent")
