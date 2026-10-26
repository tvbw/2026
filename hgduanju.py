# -*- coding: utf-8 -*-
"""
红果短剧 Spider（精简版 v2）
=============================================
依赖：requests（标准库之外唯一的依赖）
原理：解析 hongguoduanju.com 网页 SSR HTML，播放地址从详情页
      JSON-LD 的 TVEpisode.contentUrl 拿 MP4 直链。
没有：x-bogus 签名 / CENC 解密 / protobuf 序列化 / 大常量
"""

import json
import re
import time
from urllib.parse import quote

import requests

try:
    from base.spider import Spider as _BaseSpider
except Exception:
    import sys
    sys.path.append("..")
    from base.spider import Spider as _BaseSpider


# ============================================================
# 配置区
# ============================================================
SITE = "https://hongguoduanju.com"

# 登录态 Cookie（贴你浏览器里那份，有效期到 2026-12-24）
COOKIE = (
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

UA = (
    "Mozilla/5.0 (Linux; Android 6.0; Nexus 5 Build/MRA58N) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/132.0.0.0 Mobile Safari/537.36"
)


def _headers():
    return {
        "User-Agent": UA,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9",
        "Referer": SITE + "/",
        "Cookie": COOKIE,
    }


def _get(url, retries=3):
    """取 HTML，带 3 次重试。"""
    last = None
    for i in range(retries):
        try:
            r = requests.get(url, headers=_headers(), timeout=20)
            r.raise_for_status()
            r.encoding = r.encoding or "utf-8"
            if len(r.text) < 500:
                raise RuntimeError("empty body")
            return r.text
        except Exception as e:
            last = e
            time.sleep(0.6 * (i + 1))
    raise RuntimeError("fetch failed: %s" % last)


# ============================================================
# 解析：卡片 / 详情 / JSON-LD
# ============================================================
_CARD_RE = re.compile(
    r'<a[^>]*href="(/detail\?series_id=(\d+))"[^>]*>(.*?)</a>',
    re.S,
)
_TITLE_RE = re.compile(r'<p[^>]*class="[^"]*pc-title[^"]*"[^>]*>([^<]+)</p>')
_EPISODE_RE = re.compile(r'<p[^>]*class="[^"]*pc-episode[^"]*"[^>]*>([^<]+)</p>')
_IMG_RE = re.compile(r'<img[^>]*class="[^"]*image[^"]*"[^>]*src="([^"]+)"')
_IMG_ALT_RE = re.compile(r'<img[^>]*src="(https?://[^"]+)"')
_TAG_RE = re.compile(r'<span[^>]*class="[^"]*pc-tag-text[^"]*"[^>]*>([^<]+)</span>')
_ALT_RE = re.compile(r'<img[^>]*alt="([^"]+)"')

_LDJSON_RE = re.compile(
    r'<script[^>]+type="application/ld\+json"[^>]*>(.*?)</script>',
    re.S,
)
_MP4_IN_HTML_RE = re.compile(r'https?:[^\s"\'<>\\]+\.mp4[^\s"\'<>\\]*')


def _parse_cards(html):
    """解析卡片列表（首页/分类/搜索通用）。"""
    result, seen = [], set()
    for m in _CARD_RE.finditer(html):
        href, sid, block = m.group(1), m.group(2), m.group(3)
        if sid in seen:
            continue
        seen.add(sid)

        title = ""
        t = _TITLE_RE.search(block)
        if t:
            title = t.group(1).strip()
        if not title:
            a = _ALT_RE.search(block)
            if a:
                title = a.group(1).strip()
        if not title:
            continue

        pic = ""
        i = _IMG_RE.search(block)
        if i:
            pic = i.group(1)
        if not pic:
            i = _IMG_ALT_RE.search(block)
            if i:
                pic = i.group(1)

        ep = ""
        e = _EPISODE_RE.search(block)
        if e:
            ep = e.group(1).strip()

        tags = " / ".join(t.strip() for t in _TAG_RE.findall(block) if t.strip())

        result.append({
            "vod_id": sid,
            "vod_name": title,
            "vod_pic": pic,
            "vod_remarks": ep,
            "vod_content": tags,
        })
    return result


def _parse_episodes_from_ld(html):
    """从 JSON-LD 抽剧集 MP4 地址。"""
    episodes = []
    for m in _LDJSON_RE.finditer(html):
        try:
            data = json.loads(m.group(1))
        except Exception:
            continue
        for item in (data if isinstance(data, list) else [data]):
            if not isinstance(item, dict):
                continue
            if item.get("@type") != "TVEpisode":
                continue
            url = (item.get("contentUrl") or "").strip()
            if not url:
                continue
            episodes.append({
                "url": url,
                "name": (item.get("name") or "").strip(),
            })
    return episodes


def _parse_episodes_from_regex(html):
    """JSON-LD 没命中时的兜底：扫 HTML 里的 .mp4 直链。"""
    urls = list(dict.fromkeys(_MP4_IN_HTML_RE.findall(html)))
    return [{"url": u, "name": ""} for u in urls]


# ============================================================
# Spider 主类
# ============================================================
class Spider(_BaseSpider):

    def getName(self):
        return "红果短剧"

    def init(self, extend=""):
        return

    def isVideoFormat(self, url):
        u = str(url or "").lower()
        return ".mp4" in u or ".m3u8" in u

    def manualVideoCheck(self):
        return False

    def destroy(self):
        pass

    # ---------- 首页 ----------
    def homeContent(self, filter):
        classes = [
            {"type_id": "/category/real-drama", "type_name": "真人剧"},
            {"type_id": "/category/comic-drama", "type_name": "漫剧"},
            {"type_id": "/category/ai-drama", "type_name": "AI剧"},
            {"type_id": "/category/comic", "type_name": "漫画"},
        ]
        try:
            html = _get(SITE + "/")
            return {"class": classes, "list": _parse_cards(html)[:40]}
        except Exception:
            return {"class": classes, "list": []}

    def homeVideoContent(self):
        try:
            return {"list": _parse_cards(_get(SITE + "/"))[:60]}
        except Exception:
            return {"list": []}

    # ---------- 分类 ----------
    def categoryContent(self, tid, pg, filter, extend):
        try:
            page = max(1, int(pg))
        except Exception:
            page = 1

        tid = str(tid or "")
        if tid.startswith("/category/"):
            base = SITE + tid
        elif tid in ("comic", "manju", "漫剧"):
            base = SITE + "/category/comic-drama"
        elif tid in ("ai_comic", "ai_manju", "AI漫剧", "ai漫剧"):
            base = SITE + "/category/ai-drama"
        else:
            base = SITE + "/category/real-drama"

        url = base + (f"?page={page}" if page > 1 else "")
        try:
            html = _get(url)
            items = _parse_cards(html)

            # 从分页链接里扫最大页码
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

    # ---------- 搜索 ----------
    def searchContent(self, key, quick=False, pg="1"):
        try:
            page = max(1, int(pg))
        except Exception:
            page = 1
        key = str(key or "").strip() or "短剧"

        # 依次尝试多种搜索 URL（官网改过几次）
        candidates = [
            f"{SITE}/search?keyword={quote(key)}",
            f"{SITE}/search/{quote(key)}",
            f"{SITE}/search?q={quote(key)}",
        ]
        for url in candidates:
            try:
                html = _get(url)
            except Exception:
                continue
            items = _parse_cards(html)
            if items:
                return {
                    "page": page, "pagecount": 1,
                    "limit": len(items), "total": len(items),
                    "list": items,
                }
        return {"page": page, "pagecount": 1, "limit": 0, "total": 0, "list": []}

    # ---------- 详情 ----------
    def detailContent(self, ids):
        sid = str(ids[0] if isinstance(ids, (list, tuple)) else ids)
        sid = sid.replace("/detail?series_id=", "").replace("hg-series-v1:", "")

        url = f"{SITE}/detail?series_id={quote(sid)}"
        try:
            html = _get(url)
        except Exception:
            return {"list": [{
                "vod_id": sid, "vod_name": "加载失败",
                "vod_play_from": "红果短剧",
                "vod_play_url": f"详情加载失败${url}",
            }]}

        # 基本信息
        title = ""
        m = re.search(r'<title>([^<]+)</title>', html)
        if m:
            title = re.split(r"[_\-|–]", m.group(1))[0].strip()

        cover = ""
        m = re.search(r'<meta[^>]+property="og:image"[^>]+content="([^"]+)"', html)
        if m:
            cover = m.group(1)

        intro = ""
        m = re.search(r'<meta[^>]+name="description"[^>]+content="([^"]+)"', html)
        if m:
            intro = m.group(1)

        # 剧集列表：先 JSON-LD，再 regex 兜底
        episodes = _parse_episodes_from_ld(html)
        if not episodes:
            episodes = _parse_episodes_from_regex(html)

        if episodes:
            play_url = "#".join(
                f"{ep['name'] or ('第%d集' % (i + 1))}${ep['url']}"
                for i, ep in enumerate(episodes)
            )
        else:
            # 什么都没找到：把详情页 URL 丢给壳，让壳自己解析
            play_url = f"整剧播放${url}"

        return {"list": [{
            "vod_id": sid,
            "vod_name": title,
            "vod_pic": cover,
            "vod_content": intro,
            "vod_play_from": "红果短剧",
            "vod_play_url": play_url,
        }]}

    # ---------- 播放 ----------
    def playerContent(self, flag, id, vipFlags=None):
        # MP4 直链 → 直接播
        if str(id).startswith("http") and ".mp4" in str(id).lower():
            return {
                "parse": 0,
                "jx": 0,
                "playUrl": "",
                "url": id,
                "header": {
                    "User-Agent": UA,
                    "Referer": SITE + "/",
                },
            }
        # 详情页 URL（整剧兜底）→ 交给壳解析
        if str(id).startswith("http"):
            return {
                "parse": 1,
                "jx": 0,
                "playUrl": "",
                "url": id,
                "header": _headers(),
            }
        # 兜底
        return {
            "parse": 1,
            "jx": 0,
            "playUrl": "",
            "url": SITE + "/",
            "header": _headers(),
        }
