# -*- coding: utf-8 -*-
"""
MissAV 爬虫 (自愈版 · 1080P 真探测优先)
- 默认节点: https://missav.media （可直连）
- 导航探活: x99dh.cc / x99dh.one
- 列表: /dm539/cn/new 等分类 + __卡片结构解析
- 播放: 管道串 m3u8|...|video → surrit.mrstcdn.store/{uuid}/playlist.m3u8
- 画质: 自动探测 CDN 上真实存在的最高画质 (默认 1080P，无则降级)
"""
import sys
import re
import json
import base64
from urllib.parse import quote, urljoin, urlparse, unquote

sys.path.append('..')
try:
    from base.spider import Spider as BaseSpider
except ImportError:
    class BaseSpider(object):
        def getCache(self, key): return None
        def setCache(self, key, value): return "fail"
        def delCache(self, key): return "fail"
        def fetch(self, url, headers=None, timeout=15, **kw):
            import requests as rq
            r = rq.get(url, headers=headers or {}, timeout=timeout, **kw)
            r.encoding = 'utf-8'
            class R:
                pass
            o = R()
            o.text = r.text
            o.content = r.content
            o.status_code = r.status_code
            o.url = r.url
            return o


HOST_DEFAULT = "https://missav.media"
FALLBACK_HOSTS = [
    "https://missav.ai/dm247/cn",
    "https://missav.mrst.one",
    "https://missav.media",
]
NAV_URLS = ["https://x99dh.vip", "https://x99dh.my"]
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"

# 分类（实测可用 dm 路径）
CLASS_LIST = [
    {"type_id": "/dm539/cn/new", "type_name": "🔥最近更新"},
    {"type_id": "/dm817/cn/uncensored-leak", "type_name": "🔓无码流出"},
    {"type_id": "/dm597/cn/fc2", "type_name": "💎FC2"},
    {"type_id": "/dm2208642/cn/heyzo", "type_name": "👑HEYZO"},
    {"type_id": "/dm42/cn/tokyohot", "type_name": "♨️东京热"},
    {"type_id": "/dm5199603/cn/1pondo", "type_name": "🔞一本道"},
    {"type_id": "/dm301/cn/today-hot", "type_name": "⭐今日热门"},
    {"type_id": "/dm170/cn/weekly-hot", "type_name": "📊本週热门"},
    {"type_id": "/dm273/cn/monthly-hot", "type_name": "🏆本月热门"},
    {"type_id": "/dm278/cn/chinese-subtitle", "type_name": "💬中文字幕"},
    {"type_id": "/dm635/cn/release", "type_name": "✨新作上市"},
]

NAV_CODES = re.compile(
    r'^(new|today-hot|weekly-hot|monthly-hot|chinese-subtitle|release|uncensored-leak|'
    r'fc2|heyzo|tokyohot|1pondo|siro|luxu|gana|ara|scute|madou|vip|actresses|genres|'
    r'makers|search|ranking|maan|caribbeancom|caribbeancompr|10musume|pacopacomama|'
    r'gachinco|xxxav|marriedslash|naughty4610|naughty0930|twav|furuke)$',
    re.I
)

# ========== 画质探测（并发 + 缓存） ==========
_PROBE_CACHE = {}


def _probe_url(url, timeout=1.5, referer=None):
    """
    快速判断 URL 是否真实可访问。
    使用 Range 请求（只取 1 字节），比 HEAD 更兼容部分只允许 GET 的 CDN。
    200 / 206 均视为可用。
    """
    if not url:
        return False
    if url in _PROBE_CACHE:
        return _PROBE_CACHE[url]
    import urllib.request as ur
    result = False
    try:
        req = ur.Request(url, headers={
            "User-Agent": UA,
            "Referer": referer or url.rsplit('/', 3)[0] + '/',
            "Range": "bytes=0-0",
            "Accept": "*/*",
        })
        with ur.urlopen(req, timeout=timeout) as r:
            code = getattr(r, "status", None) or r.getcode()
            result = 200 <= code < 400
    except Exception:
        result = False
    _PROBE_CACHE[url] = result
    return result


def _probe_resolutions(base_url, referer=None, timeout=1.5):
    """
    探测 base_url 下 1080p / 720p / 480p / 360p 哪个真实存在。
    并发探测，返回按优先级排序的 [(name, url), ...]。
    - 有 1080P → 列表首位就是 1080P
    - 没有 1080P → 自动降 720P，其次 480P / 360P
    - 全部探测失败 → 返回空列表（调用方会走自适应兜底）
    """
    if not base_url:
        return []
    ladder = [
        ("1080P", base_url.rstrip("/") + "/1080p/video.m3u8"),
        ("720P",  base_url.rstrip("/") + "/720p/video.m3u8"),
        ("480P",  base_url.rstrip("/") + "/480p/video.m3u8"),
        ("360P",  base_url.rstrip("/") + "/360p/video.m3u8"),
    ]
    from concurrent.futures import ThreadPoolExecutor, as_completed
    order = {n: i for i, (n, _) in enumerate(ladder)}
    alive = []
    try:
        with ThreadPoolExecutor(max_workers=len(ladder)) as pool:
            futs = {pool.submit(_probe_url, u, timeout, referer): (n, u)
                    for n, u in ladder}
            for f in as_completed(futs):
                n, u = futs[f]
                try:
                    if f.result():
                        alive.append((n, u))
                except Exception:
                    pass
    except Exception:
        return []
    alive.sort(key=lambda x: order.get(x[0], 999))
    return alive


def unpack_packer(p, a, c, k):
    chars = "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"

    def int2base(x, base):
        if x < 0:
            return "-" + int2base(-x, base)
        if x == 0:
            return "0"
        res = []
        while x > 0:
            res.append(chars[x % base])
            x //= base
        return "".join(reversed(res))

    d = {}
    while c > 0:
        c -= 1
        key = int2base(c, a)
        d[key] = k[c] if c < len(k) and k[c] else key

    def repl(m):
        w = m.group(0)
        return d.get(w, w)

    return re.sub(r'\b\w+\b', repl, p)


class Spider(BaseSpider):

    def __init__(self):
        try:
            super(Spider, self).__init__()
        except Exception:
            pass
        self.baseHost = HOST_DEFAULT
        self._ua = UA
        self.options = {}

    def init(self, extend=""):
        if isinstance(extend, dict):
            self.options = extend
        elif extend:
            try:
                self.options = json.loads(extend)
            except Exception:
                self.options = {}
        cached = None
        try:
            cached = self.getCache("missav_live_host")
        except Exception:
            pass
        if cached and str(cached).startswith("http"):
            self.baseHost = str(cached).rstrip("/")
        else:
            self._refresh_host()
        return True

    def getName(self):
        return "MissAV"

    def isVideoFormat(self, url):
        low = (url or "").lower()
        return any(k in low for k in (".m3u8", ".mp4", ".flv", ".mkv", ".ts", ".mpd"))

    def manualVideoCheck(self):
        return False

    # ---------- HTTP ----------
    def _headers(self, referer=None):
        return {
            "User-Agent": self._ua,
            "Referer": referer or (self.baseHost + "/"),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Connection": "keep-alive",
        }

    def _is_challenge(self, html):
        if not html or len(html) < 300:
            return True
        if re.search(r'<title[^>]*>\s*Just a moment', html, re.I):
            return True
        if re.search(r'Enable JavaScript and cookies to continue', html, re.I):
            return True
        if re.search(r'cf-browser-verification|checking your browser before accessing', html, re.I):
            return True
        if len(html) < 3000 and re.search(r'Attention Required|Cloudflare Ray ID|cf-error-details', html, re.I):
            if not re.search(r'missav_media-thumbnail|m3u8\||<title[^>]*>.*[Mm]iss', html, re.I):
                return True
        return False

    def _fetch(self, url, referer=None, timeout=15):
        if not url:
            return {"code": 0, "text": "", "url": ""}
        if url.startswith("//"):
            url = "https:" + url
        elif url.startswith("/"):
            url = self.baseHost + url
        try:
            r = self.fetch(url, headers=self._headers(referer), timeout=timeout)
            text = getattr(r, "text", "") or ""
            code = getattr(r, "status_code", 200) or 200
            final = getattr(r, "url", url) or url
            return {"code": code, "text": text, "url": final}
        except Exception as e:
            return {"code": -1, "text": "", "url": url, "err": str(e)}

    def _fetch_heal(self, url, referer=None):
        res = self._fetch(url, referer=referer)
        text = res.get("text") or ""
        if res.get("code") == 200 and text and not self._is_challenge(text) and len(text) > 500:
            return res
        # 换域名重试
        self._refresh_host(force=True)
        if url.startswith("http"):
            url = re.sub(r'https?://[^/]+', self.baseHost, url)
        else:
            url = self.baseHost + (url if url.startswith("/") else "/" + url)
        return self._fetch(url, referer=referer)

    def _refresh_host(self, force=False):
        if not force:
            try:
                cached = self.getCache("missav_live_host")
                if cached and str(cached).startswith("http"):
                    self.baseHost = str(cached).rstrip("/")
                    return self.baseHost
            except Exception:
                pass

        # 导航站
        for nav in NAV_URLS:
            try:
                res = self._fetch(nav)
                text = res.get("text") or ""
                if not text or self._is_challenge(text):
                    continue
                hrefs = re.findall(r'https?://(?:www\.)?missav[a-z0-9.-]+', text, re.I)
                seen = set()
                for h in hrefs:
                    try:
                        p = urlparse(h)
                        base = "%s://%s" % (p.scheme, p.netloc)
                        if base in seen:
                            continue
                        seen.add(base)
                        chk = self._fetch(base + "/dm539/cn/new", referer=base + "/")
                        if chk.get("code") == 200 and not self._is_challenge(chk.get("text") or "") and "thumbnail" in (chk.get("text") or ""):
                            self.baseHost = base
                            try:
                                self.setCache("missav_live_host", base)
                            except Exception:
                                pass
                            return base
                    except Exception:
                        continue
                # base64 块
                for b in re.findall(r'["\']([A-Za-z0-9+/=]{80,})["\']', text):
                    try:
                        decoded = base64.b64decode(b).decode("utf-8", errors="ignore")
                        try:
                            decoded = unquote(decoded)
                        except Exception:
                            pass
                        if "MissAV" not in decoded or "[" not in decoded:
                            continue
                        site_list = json.loads(decoded)
                        for item in site_list:
                            if item.get("name") != "MissAV":
                                continue
                            cands = []
                            if item.get("url"):
                                cands.append(item["url"])
                            for uo in item.get("urls") or []:
                                u = uo.get("url") if isinstance(uo, dict) else uo
                                if u:
                                    cands.append(u)
                            for c_url in cands:
                                p = urlparse(c_url)
                                base = "%s://%s" % (p.scheme, p.netloc)
                                chk = self._fetch(base + "/dm539/cn/new", referer=base + "/")
                                if chk.get("code") == 200 and not self._is_challenge(chk.get("text") or ""):
                                    self.baseHost = base
                                    try:
                                        self.setCache("missav_live_host", base)
                                    except Exception:
                                        pass
                                    return base
                    except Exception:
                        continue
            except Exception:
                continue

        for h in FALLBACK_HOSTS:
            chk = self._fetch(h + "/dm539/cn/new", referer=h + "/")
            if chk.get("code") == 200 and not self._is_challenge(chk.get("text") or "") and "thumbnail" in (chk.get("text") or ""):
                self.baseHost = h
                try:
                    self.setCache("missav_live_host", h)
                except Exception:
                    pass
                return h

        self.baseHost = HOST_DEFAULT
        return self.baseHost

    # ---------- 列表解析 ----------
    def _parse_vod_list(self, html):
        vod_list = []
        seen = set()
        if not html:
            return vod_list

        # 主结构: href + optional video + img[data-src][alt]
        re_main = re.compile(
            r'href=["\']([^"\']*/cn/([a-zA-Z0-9][a-zA-Z0-9_-]*))["\'][^>]*>\s*'
            r'(?:<video[\s\S]*?</video>\s*)?'
            r'<img[\s\S]*?data-src=["\']([^"\']+)["\'][\s\S]*?alt=["\']([^"\']+)["\']',
            re.I
        )
        for m in re_main.finditer(html):
            code = (m.group(2) or "").lower()
            if not code or code in seen or NAV_CODES.match(code):
                continue
            seen.add(code)
            pic = (m.group(3) or "").strip() or ("https://fourhoi.mrstcdn.store/%s/cover-t.jpg" % code)
            title = (m.group(4) or "").strip()
            if not title or title.lower() == code:
                title = code.upper()
            vod_list.append({
                "vod_id": "%s/cn/%s" % (self.baseHost, code),
                "vod_name": title,
                "vod_pic": pic,
                "vod_remarks": code.upper(),
                "style": {"type": "rect", "ratio": 1.78},
            })

        if vod_list:
            return vod_list

        # 兜底: a[href][alt]
        re2 = re.compile(
            r'<a[^>]+href=["\']([^"\']*/cn/([a-zA-Z0-9][a-zA-Z0-9_-]*))["\'][^>]*alt=["\']([^"\']*)["\'][^>]*>([\s\S]*?)</a>',
            re.I
        )
        for m in re2.finditer(html):
            code = (m.group(2) or "").lower()
            if not code or code in seen or NAV_CODES.match(code):
                continue
            if re.search(r'actresses|genres|makers|vip|ranking|search', m.group(1), re.I):
                continue
            seen.add(code)
            title = (m.group(3) or "").strip()
            if not title:
                title = re.sub(r'<[^>]+>', '', m.group(4) or "").strip()
            if not title:
                title = code.upper()
            vod_list.append({
                "vod_id": "%s/cn/%s" % (self.baseHost, code),
                "vod_name": title,
                "vod_pic": "https://fourhoi.mrstcdn.store/%s/cover-t.jpg" % code,
                "vod_remarks": code.upper(),
                "style": {"type": "rect", "ratio": 1.78},
            })
        return vod_list

    # ---------- 播放源提取 ----------
    def _extract_play_sources(self, html):
        sources = []  # [(name, url), ...]

        def push(name, url):
            if not url or not re.match(r'https?://', url, re.I):
                return
            if any(u == url for _, u in sources):
                return
            sources.append((name, url))

        unpacked = ""
        packer = re.search(
            r"}\s*\(\s*(['\"])([\s\S]*?)\1\s*,\s*(\d+)\s*,\s*(\d+)\s*,\s*(['\"])(.*?)\5\.split\(\s*(['\"])\|",
            html, re.I
        )
        if packer:
            try:
                p = packer.group(2).replace("\\'", "'").replace('\\"', '"')
                a = int(packer.group(3))
                c = int(packer.group(4))
                k = packer.group(6).split("|")
                unpacked = unpack_packer(p, a, c, k)
                # 兼容 \xNN / \uNNNN 转义
                unpacked = re.sub(r"\\x([0-9a-fA-F]{2})",
                                  lambda m: chr(int(m.group(1), 16)), unpacked)
                unpacked = re.sub(r"\\u([0-9a-fA-F]{4})",
                                  lambda m: chr(int(m.group(1), 16)), unpacked)
            except Exception:
                pass

        text = (unpacked or "") + "\n" + html

        # === 1) 管道串（最可靠） ===
        # 格式: m3u8|e720..|b723|4248|be28|11fb..|mrstcdn.store|surrit|https|video
        # 可能同时命中广告串，取字段最多的那个
        pipes = re.findall(r'm3u8\|([a-zA-Z0-9|.\-]+?)\|video', text, re.I)
        if pipes:
            best_pipe = max(pipes, key=lambda s: s.count("|"))
            try:
                s = ("m3u8|" + best_pipe + "|video").split("|")
                if len(s) >= 9:
                    uuid = "%s-%s-%s-%s-%s" % (s[5], s[4], s[3], s[2], s[1])
                    tld, domain = s[6], s[7]
                    base = "https://%s.%s/%s" % (domain, tld, uuid)
                    # ★★★ 关键：真实探测哪个画质存在 ★★★
                    # 有 1080P 就只给 1080P；没有就依次降 720P → 480P → 360P
                    for name, url in _probe_resolutions(base, referer=self.baseHost + "/"):
                        push(name, url)
                    # 主播放列表永远兜底（多码率自适应）
                    push("自适应", base + "/playlist.m3u8")
            except Exception:
                pass

        # === 2) source= 变量 ===
        for sm in re.finditer(
            r"\b(source(?:1280|842|720|480|360)?)\s*=\s*['\"]([^'\"]+)['\"]",
            text, re.I
        ):
            key = sm.group(1).lower()
            val = re.sub(r'https?://[^/]+/jmpres/[^/]+/', 'https://', sm.group(2).strip())
            if "m3u8" not in val and "http" not in val:
                continue
            if key == "source1280":
                push("1080P超清", val)
            elif key in ("source842", "source720"):
                push("720P高清", val)
            elif key == "source480":
                push("480P流畅", val)
            elif key == "source360":
                push("360P省流", val)
            elif key == "source":
                push("原线", val)

        # === 3) 通用变量兜底 ===
        for gm in re.finditer(
            r"\b(?:url|file|src|video|playurl|play_url|media|hls|m3u8url)"
            r"\s*[:=]\s*['\"]([^'\"]{8,})['\"]",
            text, re.I
        ):
            val = gm.group(1).strip()
            if not re.search(r"\.m3u8|\.mp4", val, re.I):
                continue
            val = re.sub(r"https?://[^/]+/jmpres/[^/]+/", "https://", val)
            push("线路", val)

        # === 4) 裸 m3u8 兜底 ===
        for um in re.finditer(
            r"https?://[^\s'\"<>\\]+?\.m3u8[^\s'\"<>\\]*", text, re.I
        ):
            push("直链", um.group(0))

        # === 5) UUID 兜底 → surrit.mrstcdn.store ===
        if not sources:
            blacklist = ("snaptrckr", "user_uuid", "popunder", "banner",
                         "cloudflare", "randomuuid")
            for u in re.findall(
                r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}',
                text, re.I
            ):
                idx = text.lower().find(u.lower())
                ctx = text[max(0, idx - 50):idx + 50].lower()
                if any(b in ctx for b in blacklist):
                    continue
                base = "https://surrit.mrstcdn.store/%s" % u
                for name, url in _probe_resolutions(base, referer=self.baseHost + "/"):
                    push(name, url)
                push("自适应", base + "/playlist.m3u8")
                break

        # === 6) 最终排序：1080P → 720P → 480P → 360P → 自适应 → ... ===
        order = {
            "1080P超清": 0, "1080P": 0,
            "720P高清":  1, "720P":  1,
            "480P流畅":  2, "480P":  2,
            "360P省流":  3, "360P":  3,
            "自适应":    4,
            "原线":      5, "线路": 6, "直链": 7,
        }
        best = {}   # url -> (rank, name)
        for name, url in sources:
            r = order.get(name, 99)
            if url not in best or r < best[url][0]:
                best[url] = (r, name)
        sources = sorted(
            ((n, u) for u, (_, n) in best.items()),
            key=lambda x: order.get(x[0], 99)
        )

        return sources

    # ---------- 接口 ----------
    def homeContent(self, filter=False):
        result = {"class": list(CLASS_LIST)}
        if filter:
            result["filters"] = {}
        return result

    def homeVideoContent(self):
        try:
            res = self.categoryContent("/dm539/cn/new", "1", False, {})
            return {"list": (res.get("list") or [])[:20]}
        except Exception:
            return {"list": []}

    def categoryContent(self, tid, pg=1, filter=False, extend=None):
        try:
            page = int(str(pg)) if str(pg).isdigit() else 1
            route = str(tid or "/dm539/cn/new").strip()
            if not route.startswith("/"):
                route = "/" + route
            if re.match(r'^/cn/', route, re.I):
                route = "/dm539" + route

            req_url = self.baseHost + route
            if page > 1:
                req_url += "?page=%d" % page

            res = self._fetch_heal(req_url)
            vod_list = self._parse_vod_list(res.get("text") or "")
            pagecount = page + 1 if len(vod_list) >= 12 else page
            return {
                "page": page,
                "pagecount": pagecount,
                "limit": len(vod_list),
                "total": 9999,
                "list": vod_list,
            }
        except Exception:
            return {"list": [], "page": pg, "pagecount": 0, "limit": 0, "total": 0}

    def detailContent(self, ids):
        try:
            raw = ids[0] if isinstance(ids, (list, tuple)) else str(ids)
            target = str(raw).strip()
            if not target.startswith("http"):
                target = self.baseHost + (target if target.startswith("/") else "/cn/" + target)

            code_m = re.search(r'/cn/([a-zA-Z0-9_-]+)', target, re.I)
            if code_m:
                target = "%s/cn/%s" % (self.baseHost, code_m.group(1).lower())
            else:
                target = re.sub(r'https?://[^/]+', self.baseHost, target)

            res = self._fetch_heal(target)
            html = res.get("text") or ""
            if not html or len(html) < 200:
                return {"list": []}
            if self._is_challenge(html) and not re.search(r'missav_media-thumbnail|og:image|m3u8\|', html, re.I):
                return {"list": []}

            title_m = re.search(r'<title>(.*?)</title>', html, re.I)
            raw_title = title_m.group(1).strip() if title_m else "精彩视频"
            vod_name = raw_title.split(" - ")[0].strip()

            poster_m = re.search(r'<meta\s+property=["\']og:image["\']\s+content=["\']([^"\']+)["\']', html, re.I)
            vod_pic = poster_m.group(1).strip() if poster_m else ""

            sources = self._extract_play_sources(html)
            from_list = []
            url_list = []

            if sources:
                for name, url in sources:
                    from_list.append(name)
                    url_list.append("正片$%s" % url)
            else:
                # 极端兜底：直接根据 UUID 猜，并做一次真实探测
                uuid_m = re.search(
                    r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}',
                    html, re.I
                )
                if uuid_m:
                    u = uuid_m.group(0)
                    base = "https://surrit.mrstcdn.store/%s" % u
                    probed = _probe_resolutions(base, referer=self.baseHost + "/")
                    if probed:
                        for name, url in probed:
                            from_list.append(name)
                            url_list.append("正片$%s" % url)
                    else:
                        # 探测全失败，至少给 1080P 让播放器自己试
                        from_list.append("1080P")
                        url_list.append("正片$%s/1080p/video.m3u8" % base)
                    from_list.append("自适应")
                    url_list.append("正片$%s/playlist.m3u8" % base)
                else:
                    from_list = ["页面嗅探"]
                    url_list = ["正片$%s" % target]

            return {
                "list": [{
                    "vod_id": target,
                    "vod_name": vod_name,
                    "vod_pic": vod_pic,
                    "vod_remarks": "HD高清",
                    "vod_content": "节点: %s\n标题：%s" % (self.baseHost, vod_name),
                    "vod_play_from": "$$$".join(from_list),
                    "vod_play_url": "$$$".join(url_list),
                }]
            }
        except Exception:
            return {"list": []}

    def searchContent(self, key, quick=False, pg="1"):
        try:
            page = int(str(pg)) if str(pg).isdigit() else 1
            search_url = "%s/cn/search/%s" % (self.baseHost, quote(str(key)))
            if page > 1:
                search_url += "?page=%d" % page
            res = self._fetch_heal(search_url)
            vod_list = self._parse_vod_list(res.get("text") or "")
            return {
                "list": vod_list,
                "page": page,
                "pagecount": page + 1 if len(vod_list) >= 12 else page,
                "limit": len(vod_list),
                "total": 9999,
            }
        except Exception:
            return {"list": [], "page": 1, "pagecount": 0}

    def playerContent(self, flag, id, vipFlags=None):
        play_url = str(id or "").strip()
        # 播放 CDN 必须带 Referer/Origin，否则可能 403
        headers = {
            "User-Agent": self._ua,
            "Referer": self.baseHost + "/",
            "Origin": self.baseHost,
            "Accept": "*/*",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Connection": "keep-alive",
        }
        # 直链 m3u8/mp4 不走解析
        is_direct = bool(re.search(r'\.m3u8(\?|$)|\.mp4(\?|$)', play_url, re.I))
        # 统一走 surrit.mrstcdn.store（surrit.com 会 403）
        if "surrit.com/" in play_url and "mrstcdn" not in play_url:
            play_url = play_url.replace("://surrit.com/", "://surrit.mrstcdn.store/")
        return {
            "parse": 0 if is_direct else 1,
            "jx": 0,
            "url": play_url,
            "header": headers,
        }

    def localProxy(self, param):
        pass

    def destroy(self):
        self.options = {}
