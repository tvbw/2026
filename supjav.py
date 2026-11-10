# -*- coding: utf-8 -*-
# [SUPJAV¹⁸  更新于:2026-11-11]
import sys
import json
import re
import time
import threading
from urllib.parse import quote, unquote

try:
    from base.spider import Spider as BaseSpider
except Exception:
    class BaseSpider:
        def homeContent(self, filter):
                return {"class": []}
        def homeVideoContent(self):
                return {"list": []}
        def categoryContent(self, tid, pg, filter, extend):
                return {"list": []}
        def detailContent(self, ids):
                return {"list": []}
        def searchContent(self, key, quick, pg="1"):
                return {"list": []}
        def playerContent(self, flag, id, vipFlags):
                return {}
        def liveContent(self, url):
                return ""
        def proxy(self, params):
                return [404, "text/plain", ""]
        def localProxy(self, params):
                return [404, "text/plain", ""]
        def isVideoFormat(self, url):
                return False
        def manualVideoCheck(self):
                return False
        def action(self, action):
                return {}
        def getDependence(self):
                return []

NAME = "SUPJAV"
HOST = "https://supjav.pics"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
PAGE_SIZE = 30
CACHE_TTL = 120

# ============================================================
# [核心配置] 这一版请保持 DEBUG 和 DIAGNOSTIC 打开，重启后点一个视频，
#           把日志里 [SUPJAV DIAG] 段落的内容贴给我。
# ============================================================
DEBUG = True
DIAGNOSTIC = True              # 打印 m3u8 前 3000 字符 + API 响应
PARSE_MODE = 0                 # 0=返回 m3u8 直链（默认）；1=交给壳内置解析器（parse=1）
RESOLVE_MASTER = False         # 是否把 Master Playlist 解析成媒体列表。默认 False，交给播放器自选
                               # 浏览器默认选 720p，我们改成最低码率是上一版错误，这次关掉

PROXY_ENABLED = False
PROXY_BASE = "http://127.0.0.1:9978/proxy?do=py&url="

STYLE = {"type": "rect", "ratio": 1.33}

_CLS_KEY = "__cls"

class _NetResp(object):
    def __init__(self, resp_dict, url):
        self._d = resp_dict or {}
        self.url = url
        self.status_code = int(self._d.get("code") or 0)
        self._content = self._d.get("content", "")
        self.headers = self._d.get("headers") or {}
        self.encoding = None
        self.apparent_encoding = "utf-8"
        self.text = self._content if isinstance(self._content, str) else ""
        if not self.text and isinstance(self._content, (bytes, bytearray)):
            self.text = bytes(self._content).decode("utf-8", "ignore")
    @property
    def content(self):
        return self._content if isinstance(self._content, (bytes, bytearray)) else self.text.encode("utf-8", "ignore")
    def json(self):
        import json as _json
        return _json.loads(self.text)
    def raise_for_status(self):
        if self.status_code >= 400:
            raise Exception("HTTP %s" % self.status_code)
    def __repr__(self):
        return "<_NetResp %s %d>" % (self.url, self.status_code)

class _NetSession(object):
    def __init__(self, net, headers=None, default_headers=None):
        self.net = net
        self.headers = headers if headers is not None else {}
        if default_headers:
            for k, v in default_headers.items():
                self.headers.setdefault(k, v)
    def _merge(self, headers):
        h = dict(self.headers)
        if headers:
            for k, v in headers.items():
                h[k] = v
        return h
    @staticmethod
    def _build_url(url, params):
        if not params:
            return url
        import urllib.parse as _up
        sep = "&" if "?" in url else "?"
        return url + sep + _up.urlencode(params)
    def _urllib_get(self, full, headers, timeout):
        import urllib.request as _ur, ssl as _ssl
        try:
            ctx = _ssl._create_unverified_context()
        except Exception:
            ctx = None
        req = _ur.Request(full, headers=headers)
        with _ur.urlopen(req, timeout=timeout or 15, context=ctx) as resp:
            raw = resp.read()
            enc = resp.headers.get("Content-Encoding", "")
            if "gzip" in enc:
                import gzip as _g
                raw = _g.decompress(raw)
            return {"code": resp.status, "content": raw, "headers": dict(resp.headers), "error": ""}
    def _urllib_post(self, full, headers, data, timeout):
        import urllib.request as _ur, urllib.parse as _up, ssl as _ssl
        try:
            ctx = _ssl._create_unverified_context()
        except Exception:
            ctx = None
        body = _up.urlencode(data or {}).encode("utf-8")
        req = _ur.Request(full, data=body, headers=headers, method="POST")
        with _ur.urlopen(req, timeout=timeout or 15, context=ctx) as resp:
            raw = resp.read()
            return {"code": resp.status, "content": raw, "headers": dict(resp.headers), "error": ""}
    def get(self, url, params=None, headers=None, timeout=None, **kw):
        h = self._merge(headers)
        full = self._build_url(url, params)
        timeout_s = None
        if timeout:
            timeout_s = int(timeout) / 1000 if timeout > 100 else int(timeout)
        if self.net is not None:
            opts = {"headers": h}
            if timeout_s:
                opts["timeout"] = int(timeout_s * 1000)
            try:
                resp = self.net.req(full, opts)
                return _NetResp(resp, full)
            except Exception:
                pass
        try:
            return _NetResp(self._urllib_get(full, h, timeout_s), full)
        except Exception as e:
            return _NetResp({"code": 0, "content": b"", "headers": {}, "error": str(e)}, full)
    def post(self, url, data=None, params=None, headers=None, timeout=None, **kw):
        h = self._merge(headers)
        full = self._build_url(url, params)
        timeout_s = None
        if timeout:
            timeout_s = int(timeout) / 1000 if timeout > 100 else int(timeout)
        if self.net is not None:
            opts = {"method": "POST", "headers": h, "postType": "form", "data": data or {}}
            if timeout_s:
                opts["timeout"] = int(timeout_s * 1000)
            try:
                resp = self.net.req(full, opts)
                return _NetResp(resp, full)
            except Exception:
                pass
        try:
            return _NetResp(self._urllib_post(full, h, data or {}, timeout_s), full)
        except Exception as e:
            return _NetResp({"code": 0, "content": b"", "headers": {}, "error": str(e)}, full)

class Spider(BaseSpider):

    def __init__(self):
        super().__init__()
        self.host = HOST
        self.name = NAME
        self.session = None
        self._cache = {}
        self._cache_time = {}
        self._lock = threading.Lock()
        self.options = {}

    def init(self, extend=""):
        if isinstance(extend, dict):
            cfg = extend
        elif extend:
            try:
                cfg = json.loads(extend)
            except Exception:
                cfg = {}
        else:
            cfg = {}

        if isinstance(cfg, dict):
            site = (cfg.get("site") or cfg.get("url") or "").strip().rstrip("/")
            if site and site.startswith("http"):
                self.host = site
            self.options = cfg

        base = self.host.rstrip("/")
        self.session = _NetSession(getattr(self, 'net', None))
        self.session.headers.update({
            "User-Agent": UA,
            "Accept": "application/json, text/plain, */*",
            "Referer": base + "/",
            "Origin": base,
        })

    def getDependence(self):
        return []

    def destroy(self):
        with self._lock:
            self._cache.clear()
            self._cache_time.clear()
        self.options = {}

    def isVideoFormat(self, url):
        return bool(re.search(r"\.(m3u8|mp4|flv|mkv|ts)(\?|$)", str(url)))

    def manualVideoCheck(self):
        return False

    def action(self, action):
        return {"msg": "不支持此操作"}

    def homeContent(self, filter):
        classes = self._classes()
        result = {"class": classes}
        if filter:
            result["filters"] = {}
        items, _ = self._posts({}, 1)
        result["list"] = [self._vod(x) for x in items]
        return result

    def homeVideoContent(self):
        return {"list": []}

    def categoryContent(self, tid, pg, filter, extend):
        pg = self._int(pg, 1)
        extend = extend or {}

        if tid.startswith("actor/"):
            actor_id = tid.split("/", 1)[1]
            items, totalpages = self._posts({"actor": actor_id}, pg)
            return self._page_result(items, pg, totalpages)

        items, totalpages = self._posts({"categories": tid}, pg)
        return self._page_result(items, pg, totalpages)

    def detailContent(self, ids):
        if not ids:
            return {"list": []}
        responses = [self._detail(str(video_id)) for video_id in ids]
        merged = {k: v for k, v in (responses[0] or {}).items() if k != "list"} if responses[0] else {}
        merged["list"] = [item for response in responses if response for item in (response.get("list") or [])]
        return merged

    def _detail(self, vid):
        vid = str(vid or "")
        post = self._post_detail(vid)
        if not post:
            return {"list": [], "msg": "未找到此影片"}

        title = self._clean(self._html_text(post.get("title", {}).get("rendered", "")))
        content = self._clean(self._html_text(post.get("content", {}).get("rendered", "")))

        actors = []
        categories = []
        cat_ids = set(post.get("categories") or [])
        for group in (post.get("_embedded", {}).get("wp:term") or []):
            for t in group:
                if t.get("taxonomy") == "actor" and t.get("count", 1) > 0:
                    actors.append(t)
                elif t.get("taxonomy") == "category":
                    categories.append(t)

        actor_text = "、".join(self._clickable("actor", t.get("id"), t.get("name"))
                               for t in actors if t.get("id"))
        type_name = categories[0].get("name", "") if categories else ""

        remarks = "Uncen" if 6 in cat_ids else "Cen"

        vod_pic = self._cover(post, "full")
        vod_year = (post.get("date") or "")[:4]

        vod = {
            "vod_id": str(post.get("id") or vid),
            "vod_name": title or vid,
            "vod_pic": vod_pic,
            "type_name": type_name,
            "vod_year": vod_year,
            "vod_area": "JAV",
            "vod_remarks": remarks,
            "vod_actor": actor_text,
            "vod_content": content,
            "vod_play_from": "SUPJAV",
            "vod_play_url": "正片$" + str(post.get("id") or vid),
        }
        return {"list": [vod]}

    def searchContent(self, key, quick, pg="1"):
        pg = self._int(pg, 1)
        kw = str(key or "").strip()
        items, totalpages = self._posts({"search": kw}, pg)
        return self._page_result(items, pg, totalpages)

    # [关键] playerContent 现在支持 parse 模式切换
    def playerContent(self, flag, id, vipFlags):
        pid = str(id or "").strip()
        if not pid:
            return {"parse": 0, "msg": "无法获取播放地址"}
        m3u8 = self._fetch_play(pid)
        if not m3u8:
            return {"parse": 0, "msg": "无法获取播放地址"}

        base = self.host.rstrip("/")
        header = {
            "User-Agent": UA,
            "Referer": base + "/",
            "Origin": base,
        }

        if PROXY_ENABLED:
            proxy_url = PROXY_BASE + quote(m3u8, safe="")
            if DEBUG:
                print("[SUPJAV PROXY] %s -> %s" % (m3u8, proxy_url))
            return {"parse": 0, "jx": 0, "url": proxy_url, "header": header}

        if DEBUG:
            print("[SUPJAV PLAY] url=%s parse=%d" % (m3u8, PARSE_MODE))

        # [DIAGNOSTIC] 主动探测一次 m3u8 内容，但不修改返回值
        if DIAGNOSTIC:
            self._diagnose_m3u8(m3u8)

        return {"parse": PARSE_MODE, "jx": 0, "url": m3u8, "header": header}

    # [DIAGNOSTIC] 打印 m3u8 的 HTTP 状态和内容前 3000 字符
    def _diagnose_m3u8(self, url):
        try:
            base = self.host.rstrip("/")
            h = {"User-Agent": UA, "Referer": base + "/", "Origin": base}
            r = self.session.get(url, headers=h, timeout=10)
            ct = r.headers.get("Content-Type", "")
            print("[SUPJAV DIAG] m3u8 GET status=%s content-type=%s len=%s"
                  % (r.status_code, ct, len(r.text or "")))
            text = r.text or ""
            if not text:
                print("[SUPJAV DIAG] (empty body)")
                return
            head = text[:3000]
            print("[SUPJAV DIAG] ---------- BEGIN m3u8 ----------")
            print(head)
            if len(text) > 3000:
                print("... (truncated, total %d bytes)" % len(text))
            print("[SUPJAV DIAG] ----------- END m3u8 -----------")
            # 额外统计分片/加密信息
            if "#EXT-X-KEY" in text:
                print("[SUPJAV DIAG] has #EXT-X-KEY (encrypted)")
            if "#EXT-X-STREAM-INF" in text:
                print("[SUPJAV DIAG] is Master Playlist (has #EXT-X-STREAM-INF)")
            else:
                print("[SUPJAV DIAG] is Media Playlist")
            # 提取前 3 个非注释行（分片/子列表 URL），方便一眼看到路径格式
            samples = []
            for line in text.splitlines():
                s = line.strip()
                if s and not s.startswith("#"):
                    samples.append(s)
                    if len(samples) >= 3:
                        break
            if samples:
                print("[SUPJAV DIAG] first URIs: %s" % samples)
        except Exception as e:
            print("[SUPJAV DIAG] probe failed: %s" % e)

    def liveContent(self, url):
        return "[]"

    def localProxy(self, params):
        try:
            url = self._extract_proxy_url(params)
            if not url:
                return [400, "text/plain", "missing url"]
            if DEBUG:
                print("[SUPJAV LOCALPROXY] %s" % url)

            base = self.host.rstrip("/")
            headers = {"User-Agent": UA, "Referer": base + "/", "Origin": base}
            if self.session is None:
                self.session = _NetSession(getattr(self, 'net', None))
                self.session.headers.update(headers)

            r = self.session.get(url, headers=headers, timeout=25)
            if r.status_code >= 400:
                return [r.status_code, "text/plain", b""]

            ct = (r.headers.get("Content-Type") or "").lower()
            path_lower = url.split("?")[0].lower()
            is_m3u8 = ("mpegurl" in ct) or path_lower.endswith(".m3u8") or path_lower.endswith(".m3u")

            if is_m3u8:
                text = r.text
                if text.startswith("\x1f\x8b") or text[:2] == "\x1f\x8b":
                    try:
                        import gzip as _g
                        text = _g.decompress(text.encode("latin-1")).decode("utf-8", "ignore")
                    except Exception:
                        pass
                rewritten = self._rewrite_m3u8(text, url)
                return [200, "application/vnd.apple.mpegurl", rewritten.encode("utf-8")]

            return [r.status_code, ct or "application/octet-stream", r.content]
        except Exception as e:
            return [500, "text/plain", str(e)]

    def proxy(self, params):
        return self.localProxy(params)

    def _extract_proxy_url(self, params):
        raw = ""
        if isinstance(params, dict):
            for k in ("url", "u", "src", "link", "target"):
                v = params.get(k)
                if v:
                    raw = str(v)
                    break
        else:
            s = str(params or "").strip()
            if s.startswith("http") or "%3A%2F%2F" in s.upper():
                raw = s
            elif "=" in s:
                import urllib.parse as _up
                q = _up.parse_qs(s.lstrip("?"))
                for k in ("url", "u", "src", "link"):
                    if q.get(k):
                        raw = q[k][0]
                        break
        if not raw:
            return ""
        if "://" not in raw and "%3A" in raw.upper():
            try:
                raw = unquote(raw)
            except Exception:
                pass
        return raw

    @staticmethod
    def _proxy_prefix():
        p = PROXY_BASE or ""
        if p.endswith("=") or p.endswith("&"):
            return p
        return p + ("&" if "?" in p else "?")

    def _rewrite_m3u8(self, text, base_url):
        from urllib.parse import urljoin, quote as _q
        prefix = self._proxy_prefix()
        out_lines = []

        def _is_special(u):
            return bool(re.match(r"^(data:|skd:|blob:|about:)", u or "", re.I))

        for line in (text or "").splitlines():
            stripped = line.strip()
            if not stripped:
                out_lines.append("")
                continue
            if stripped.startswith("#"):
                def _attr_sub(m):
                    raw = m.group(2) or ""
                    if not raw or _is_special(raw):
                        return m.group(0)
                    abs_url = urljoin(base_url, raw)
                    return '%s="%s%s"' % (m.group(1), prefix, _q(abs_url, safe=""))
                line2 = re.sub(r'(URI)="([^"]*)"', _attr_sub, line)
                out_lines.append(line2)
            else:
                if _is_special(stripped):
                    out_lines.append(stripped)
                else:
                    abs_url = urljoin(base_url, stripped)
                    out_lines.append(prefix + _q(abs_url, safe=""))

        return "\n".join(out_lines)

    def _api(self, path, params=None, use_cache=True):
        path = "/" + str(path).lstrip("/")
        ck = path + json.dumps(params or {}, sort_keys=True)
        if use_cache:
            with self._lock:
                hit = self._cache.get(ck)
                if hit and time.time() - self._cache_time.get(ck, 0) < CACHE_TTL:
                    return hit

        url = self.host.rstrip("/") + path
        try:
            r = self.session.get(url, params=params or {}, timeout=15)
            r.raise_for_status()
            obj = r.json()
            tp = 0
            try:
                tp = int(r.headers.get("X-WP-TotalPages", "0") or 0)
            except Exception:
                tp = 0
            if DEBUG and "/player/" not in path:
                print("[SUPJAV DEBUG] %s -> %d bytes, totalpages=%s" % (r.url, len(r.text), tp))
            result = (obj, tp)
            if use_cache:
                with self._lock:
                    self._cache[ck] = result
                    self._cache_time[ck] = time.time()
            return result
        except Exception:
            if DEBUG:
                print("[SUPJAV DEBUG] FAIL %s?%s" % (url, params))
            return ({}, 0)

    def _classes(self):
        hit = self._cache.get(_CLS_KEY)
        if hit and time.time() - self._cache_time.get(_CLS_KEY, 0) < CACHE_TTL:
            return hit[0]
        cats, _ = self._api("/wp-json/wp/v2/categories", {"per_page": 100})
        arr = []
        if isinstance(cats, list):
            for c in cats:
                try:
                    cnt = int(c.get("count", 0) or 0)
                except Exception:
                    cnt = 0
                if cnt <= 0:
                    continue
                tid = str(c.get("id") or "")
                nm = c.get("name") or tid
                if tid:
                    arr.append({"type_id": tid, "type_name": nm, "style": STYLE, "_cnt": cnt})
            arr.sort(key=lambda x: -x.get("_cnt", 0))
        if not arr:
            arr = [{"type_id": "4", "type_name": "Jav Online", "style": STYLE}]
        for x in arr:
            x.pop("_cnt", None)
        with self._lock:
            self._cache[_CLS_KEY] = (arr, time.time())
        return arr

    def _posts(self, params, pg):
        q = {"per_page": PAGE_SIZE, "page": pg, "_embed": "true"}
        for k, v in (params or {}).items():
            if v not in (None, "", "0"):
                q[k] = v
        obj, tp = self._api("/wp-json/wp/v2/posts", q)
        if not isinstance(obj, list):
            return [], 0
        return obj, tp

    def _post_detail(self, vid):
        vid = vid.strip()
        if not vid:
            return {}
        obj, _ = self._api("/wp-json/wp/v2/posts/" + quote(vid, safe=""), {"_embed": "true"})
        return obj if isinstance(obj, dict) else {}

    # [关键] _fetch_play：多 server 尝试 + 打印 API 完整响应
    def _fetch_play(self, pid):
        servers = [1, 2, 3, None]
        for server in servers:
            params = {"id": pid}
            if server is not None:
                params["server"] = server
            obj, _ = self._api("/wp-json/fb/v1/player/", params, use_cache=False)
            if DIAGNOSTIC:
                try:
                    preview = json.dumps(obj, ensure_ascii=False)
                except Exception:
                    preview = str(obj)
                print("[SUPJAV API] params=%s -> %s" % (params, preview[:2000]))
            if not isinstance(obj, dict) or not obj.get("success"):
                continue
            url = self._parse_player_data(obj.get("data"))
            if url:
                if DEBUG:
                    print("[SUPJAV API] picked server=%s url=%s" % (server, url))
                if RESOLVE_MASTER:
                    return self._resolve_m3u8(url)
                return url
        return ""

    def _parse_player_data(self, data):
        import base64
        texts = []
        if isinstance(data, (dict, list)):
            texts.append(json.dumps(data, ensure_ascii=False))
        elif isinstance(data, str):
            texts.append(data)
            for decoder in (base64.b64decode, base64.urlsafe_b64decode):
                try:
                    padded = data + "=" * (-len(data) % 4)
                    d = decoder(padded)
                    s = d.decode("utf-8", "ignore")
                    if ".m3u8" in s or "http" in s:
                        texts.append(s)
                except Exception:
                    pass
            try:
                u = unquote(data)
                if u != data:
                    texts.append(u)
            except Exception:
                pass

        unescape_pairs = (
            ("\\/", "/"),
            ("\\u0026", "&"), ("\\u003d", "="), ("\\u003f", "?"), ("\\u002F", "/"),
            ("\\u003D", "="), ("\\u003F", "?"),
            ("&amp;", "&"), ("&#038;", "&"), ("&#x26;", "&"),
            ('\\"', '"'),
        )
        patterns = (
            r"""url["']?\s*[:=]\s*["']([^"']+?\.m3u8[^"']*)["']""",
            r"""["'](https?://[^"']+?\.m3u8[^"']*)["']""",
            r"""["']([^"']+?\.m3u8[^"']*)["']""",
            r"""(https?://[^\s"'<>]+?\.m3u8[^\s"'<>]*)""",
        )

        for text in texts:
            if not text:
                continue
            for a, b in unescape_pairs:
                text = text.replace(a, b)
            for pat in patterns:
                m = re.search(pat, text, re.I)
                if m:
                    return self._normalize_media_url(m.group(1))
        return ""

    def _normalize_media_url(self, url):
        url = str(url or "").strip()
        if not url:
            return ""
        url = url.replace("\\/", "/").replace("&amp;", "&")
        if url.startswith("//"):
            url = "https:" + url
        elif url.startswith("/"):
            url = self.host.rstrip("/") + url
        return url

    # [关键] 方案 A 保留，但默认不启用（RESOLVE_MASTER=False）。
    # 若启用，选带宽最低的策略保留（下次再根据诊断结果调整）。
    def _resolve_m3u8(self, url, depth=0):
        if depth > 2:
            return url
        try:
            r = self.session.get(url, timeout=8)
            if r.status_code != 200:
                return url
            text = r.text
        except Exception:
            return url

        if "#EXT-X-STREAM-INF" not in text:
            return url

        from urllib.parse import urljoin, urlparse, urlunparse
        lines = text.splitlines()
        candidates = []
        for i, line in enumerate(lines):
            s = line.strip()
            if s.startswith("#EXT-X-STREAM-INF"):
                bw = 0
                m = re.search(r"BANDWIDTH=(\d+)", s)
                if m:
                    try:
                        bw = int(m.group(1))
                    except Exception:
                        bw = 0
                for j in range(i + 1, len(lines)):
                    nxt = lines[j].strip()
                    if nxt and not nxt.startswith("#"):
                        candidates.append((bw, nxt))
                        break
        if not candidates:
            return url
        candidates.sort(key=lambda x: x[0] if x[0] > 0 else 999999999)
        media_url = candidates[0][1]
        if media_url.startswith("//"):
            media_url = "https:" + media_url
        else:
            media_url = urljoin(url, media_url)
        mu = urlparse(media_url)
        if not mu.query:
            ou = urlparse(url)
            if ou.query:
                media_url = urlunparse((mu.scheme, mu.netloc, mu.path, mu.params, ou.query, mu.fragment))
        if DEBUG:
            print("[SUPJAV RESOLVE] master -> %s" % media_url)
        return self._resolve_m3u8(media_url, depth + 1)

    def _vod(self, post):
        post = post or {}
        pid = str(post.get("id") or "")
        title = self._clean(self._html_text(post.get("title", {}).get("rendered", "")))
        cat_ids = set(post.get("categories") or [])
        remarks = "Uncen" if 6 in cat_ids else "Cen"
        return {
            "vod_id": pid,
            "vod_name": title or pid,
            "vod_pic": self._cover(post, "thumb"),
            "vod_remarks": remarks,
        }

    def _cover(self, post, size="thumb"):
        em = post.get("_embedded", {})
        for fm in em.get("wp:featuredmedia") or []:
            if not isinstance(fm, dict):
                continue
            if size == "thumb":
                sizes = (fm.get("media_details") or {}).get("sizes") or {}
                for sname in ("video-thumb", "video-small", "full"):
                    s = sizes.get(sname) or {}
                    if s.get("source_url"):
                        return s["source_url"]
            u = fm.get("source_url")
            if u:
                return u
        return ""

    def _page_result(self, items, pg, totalpages):
        page = max(1, self._int(pg, 1))
        if not totalpages or totalpages < 1:
            totalpages = page if not items else 9999
        return {
            "list": [self._vod(x) for x in items],
            "page": page,
            "pagecount": totalpages,
            "limit": PAGE_SIZE,
            "total": 999999,
        }

    def _clickable(self, kind, ident, name):
        if not ident:
            return ""
        payload = json.dumps(
            {"id": "%s/%s" % (kind, ident), "name": name, "type_flag": "0"},
            ensure_ascii=False,
            separators=(",", ":"),
        )
        return "[a=cr:%s/]%s[/a]" % (payload, name)

    @staticmethod
    def _html_text(html):
        if not html:
            return ""
        return re.sub(r"<[^>]+>", " ", html)

    @staticmethod
    def _clean(text):
        return re.sub(r"\s+", " ", str(text or "")).strip()

    @staticmethod
    def _int(x, d=0):
        try:
            return int(x)
        except Exception:
            return d
