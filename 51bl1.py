# -*- coding: utf-8 -*-
"""
51系列标准模板 · 发布页秒跳自愈版（修正版）
------------------------------------------------------------------
相对原拼接版的修正：
  1. 【致命】删除重复的 Spider 基类实现，原文件后段引用了不存在的
     SiteConfig / DomainResolver，模块在类定义阶段直接 NameError，
     永远无法导入；现统一为单一 Spider。
  2. 【严重】HOST_CACHE_KEY 与 PUB_CACHE_KEY 原来都叫 "51bl"，
     互相覆盖导致缓存永远失效；现已拆分为两个键。
  3. 【严重】SITE_KEYWORDS 原为字符串，match_keyword 按字符迭代；
     现为元组。
  4. 【修复】LOG 未定义（NameError）；改用 logging。
  5. 【修复】_get() 中 allow_redirects 显式传参与 **kw 冲突风险。
  6. 【修复】"mkey" 类型的 AES key 请求按 ts 流返回错误 Content-Type。
  7. 【优化】播放源聚合扩展由猴子补丁改为原生方法，去掉一层间接。
  8. 【优化】vod_play_from / 站点名统一走 CONFIG，不再硬编码。
"""
import json
import re
import sys
import hashlib
import logging
from base64 import b64decode, b64encode
from urllib.parse import urlparse, urljoin, unquote, quote
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
from Crypto.Cipher import AES
from Crypto.Util.Padding import unpad
from pyquery import PyQuery as pq

sys.path.append('..')
try:
    from base.spider import Spider as BaseSpider
except ImportError:
    class BaseSpider:
        """脱离主程序运行时的兜底基类"""
        def getCache(self, k):    return None
        def setCache(self, k, v): pass
        def getProxyUrl(self):    return ""

try:
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
except Exception:
    pass

LOG = logging.getLogger(__name__)


# ==================================================================
# ① 站点配置
# ==================================================================
class Config:
    SITE_NAME     = "51爆料"
    SITE_KEYWORDS = ("51爆料",)          # 修正：原为字符串，会被按字符迭代
    PLAY_FROM     = "51爆料"

    # ---- 缓存键（修正：原两个键同名 "51bl" 会互相覆盖）----
    HOST_CACHE_KEY = "51bl_host"
    PUB_CACHE_KEY  = "51bl_pub"

    # ---- 一级跳板页（只填这一个）----
    PUBLISH_URLS = [
        "https://51blk5.com/",
    ]
    # ---- 二级发布页（硬编码保底，域名变了再改这里）----
    PUBLISH_FALLBACK_AFTER_JUMP = [
        "https://www.yobbmdnp.cc/",
    ]

    # ---- 超时 ----
    PUBLISH_TIMEOUT = 12
    PROBE_TIMEOUT   = 12
    FAST_TIMEOUT    = 8

    # ---- 站点有效性特征 ----
    PROBE_MIN_HTML = 1500
    SITE_MARKERS = (
        "post-title", "entry-title", "<article", 'class="post',
        "realtime-card", "candid-video", "video-card",
    )

    VALID_TLDS = {
        'com', 'net', 'org', 'cc', 'xyz', 'lol', 'vip', 'app', 'top', 'cn',
        'co', 'io', 'me', 'tv', 'club', 'site', 'online', 'info', 'biz',
        'pro', 'link', 'live', 'shop', 'fun', 'work', 'icu', 'life',
        'world', 'store', 'tech', 'space', 'website', 'host', 'pw', 'tk',
        'ml', 'ga', 'cf', 'gq', 'su', 'ws', 'ly', 'to', 'st', 'in', 'tw',
        'hk', 'jp', 'kr', 'ru', 'us', 'uk', 'de', 'fr', 'nl', 'eu', 'au',
        'ca', 'sg', 'my', 'sbs', 'bet', 'cam', 'one', 'plus', 'now',
        'today', 'pub', 'dev', 'cool', 'cloud',
    }
    DOMAIN_BLACKLIST = (
        'google', 'gstatic', 'bing.com', 'baidu.com', 'so.com', 'sogou.com',
        'yandex', 'facebook', 'fbcdn', 'instagram', 'twitter', 'twimg',
        'youtube', 'ytimg', 't.me', 'telegram', 'whatsapp', 'discord',
        'reddit', 'tiktok', 'pinterest', 'apple.com', 'icloud', 'microsoft',
        'windows', 'amazonaws', 'cloudflare', 'cloudfront', 'azureedge',
        'github', 'gitlab', 'gitee', 'bitbucket', 'w3.org', 'wikipedia',
        'mozilla.org', 'stackoverflow', 'jsdelivr', 'unpkg', 'bootstrapcdn',
        'jquery', 'fontawesome', 'gmail', 'outlook', 'hotmail', 'yahoo',
        'protonmail', 'qq.com', '163.com', '126.com', 'sina.com',
        'weibo.com', 'statcounter', 'google-analytics', 'umeng', 'cnzz',
        'beian.miit.gov.cn', 'wordpress.org', 'wix.com', 'weebly',
        'shopify', '51.la', 'cnzz.com', '51yes', 'navone.cloud',
    )

    HEADERS = {
        "User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                       "AppleWebKit/537.36 (KHTML, like Gecko) "
                       "Chrome/120.0.0.0 Safari/537.36"),
        "Accept": ("text/html,application/xhtml+xml,application/xml;q=0.9,"
                   "image/avif,image/webp,image/apng,*/*;q=0.8"),
        "Accept-Language": "zh-CN,zh;q=0.9",
        "Connection": "keep-alive",
        "Cache-Control": "no-cache",
    }

    # ===== 选择器/常量 =====
    SEL_ARTICLE      = "#index article, #archive article, article"
    SEL_ARTICLE_HOME = "#index article, article"
    SEL_PLAYER       = ".dplayer"
    SEL_CONTENT      = ".post-content, article"
    SEL_TAGS         = ".post-tags a, .tags a, .keywords a"
    SEL_SUMMARY      = ".post-content"
    SEL_TITLE        = ".post-title, h1"
    SEL_NAV = [
        "ul.navbar-nav.mr-auto > li.nav-item > a.nav-link",
        "ul.navbar-nav > li.nav-item > a.nav-link",
        "ul.navbar-nav li a.nav-link",
        "#navbarCollapse a.nav-link",
        ".navbar-nav a.nav-link",
        ".category-list ul li",
        ".nav-menu li",
        ".menu li",
        "nav ul li",
        "header nav a",
        "nav a",
    ]
    SEL_SUB_NAV = [
        "ul.navbar-nav.mr-auto li.nav-item.dropdown > ul.dropdown-menu > li.dropdown-item > a",
        "ul.dropdown-menu > li.dropdown-item > a",
        ".dropdown-menu a",
    ]
    DEFAULT_CATEGORY = {"type_name": "首页", "type_id": "/"}
    LINK_KEYWORDS = (
        "点击观看","点击播放","观看","播放","视频",
        "第一弹","第二弹","第三弹","第四弹","第五弹",
        "第六弹","第七弹","第八弹","第九弹","第十弹",
        "第1集","第2集","第3集","第4集","第5集",
    )
    LINK_URL_PATTERNS = (r"/vodplay/", r"/v/\d+", r"/play/", r"/video/", r"\.m3u8")
    IMG_AES_KEYS = [
        (b"f5d965df75336270", b"97b60394abc2fbe1"),
        (b"75336270f5d965df", b"abc2fbe197b60394"),
    ]

    @classmethod
    def match_keyword(cls, text):
        if not text:
            return False
        for kw in cls.SITE_KEYWORDS:
            try:
                if hasattr(kw, "search"):
                    if kw.search(text):
                        return True
                elif kw in text:
                    return True
            except Exception:
                continue
        return False


# ==================================================================
# ② 发布页解析器（一级跳板 → 二级发布页 → 三级内容站）
# ==================================================================
class PublishResolver:
    """
    快速完成 一级跳板页 → 二级发布页 → 三级内容站域名 的解析。
    只识别两种跳转方式：
      - HTTP 3xx（requests 自动跟随）
      - HTML/JS：<meta refresh> / location.href / location.replace
    """

    META_REFRESH_RE = re.compile(
        r'<meta[^>]+http-equiv=["\']?refresh["\']?[^>]*?'
        r'content=["\']?\s*\d+\s*;\s*url=([^"\'>\s]+)',
        re.I,
    )
    JS_LOCATION_RE = re.compile(
        r'(?:window\.|document\.)?location(?:\.href)?\s*=\s*["\'](https?://[^"\']+)["\']'
        r'|'
        r'(?:window\.|document\.)?location\.(?:replace|assign)\s*\(\s*["\'](https?://[^"\']+)["\']',
        re.I,
    )

    def __init__(self, cfg, fetcher, cache_get=None, cache_set=None):
        self.cfg = cfg
        self.fetch = fetcher
        self.cache_get = cache_get
        self.cache_set = cache_set
        self._jump_origins = {
            self._origin(u) for u in cfg.PUBLISH_URLS if u
        }
        self._publish_origins = {
            self._origin(u) for u in
            (list(cfg.PUBLISH_URLS) + list(cfg.PUBLISH_FALLBACK_AFTER_JUMP))
            if u
        }

    @staticmethod
    def _origin(url):
        try:
            p = urlparse(url)
            if p.scheme in ("http", "https") and p.netloc:
                return f"{p.scheme}://{p.netloc}".lower()
        except Exception:
            pass
        return ""

    @staticmethod
    def _final_host(url):
        try:
            p = urlparse(url)
            if p.scheme in ("http", "https") and p.netloc:
                return f"{p.scheme}://{p.netloc.lower()}"
        except Exception:
            pass
        return ""

    @staticmethod
    def _normalize_url(u, base_url):
        u = unquote(str(u or "")).strip().strip('"\' ').replace("&amp;", "&")
        if not u:
            return ""
        if u.startswith("//"):
            u = "https:" + u
        if not u.startswith("http"):
            u = urljoin(base_url or "", u)
        return u

    # ---------- 一级页 → 二级页 ----------
    def _resolve_jump_page(self, start_url):
        start_url = start_url.rstrip("/") + "/"
        r = self.fetch(start_url, timeout=self.cfg.PUBLISH_TIMEOUT,
                       allow_redirects=True)
        if r is None:
            return "", ""

        final_url = r.url.rstrip("/") + "/"
        html = r.text or ""

        # 情况 A：requests 已通过 3xx 跳出跳板页
        if self._origin(final_url) not in self._jump_origins:
            return final_url, html

        # 情况 B：落地仍是跳板页本身，跳转写在 HTML/JS 里
        target = self._extract_html_jump(html, final_url)
        if not target:
            return "", ""

        r2 = self.fetch(target, timeout=self.cfg.PUBLISH_TIMEOUT,
                        allow_redirects=True)
        if r2 is None:
            return "", ""
        return r2.url.rstrip("/") + "/", (r2.text or "")

    def _extract_html_jump(self, html, base_url):
        if not html:
            return ""
        m = self.META_REFRESH_RE.search(html)
        if m:
            return self._normalize_url(m.group(1), base_url)
        m = self.JS_LOCATION_RE.search(html)
        if m:
            return self._normalize_url(m.group(1) or m.group(2), base_url)
        return ""

    # ---------- 二级页 → 候选三级域名 ----------
    def _extract_candidate_hosts(self, html):
        if not html:
            return []
        hosts, seen = [], set()

        def _add(raw):
            h = self._final_host(raw)
            if not h:
                return
            hl = h.lower()
            if any(b in hl for b in self.cfg.DOMAIN_BLACKLIST):
                return
            if h in self._publish_origins:
                return
            if h in seen:
                return
            seen.add(h)
            hosts.append(h)

        for m in re.finditer(r'https?://[^\s"\'<>()\[\]{},;]+', html):
            _add(m.group(0))

        for m in re.finditer(
            r'(?<![\w.\-])((?:[a-zA-Z0-9](?:[a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?\.)+[a-zA-Z]{2,10})(?![\w.\-])',
            html[:8000],
        ):
            d = m.group(1).lower().strip('.')
            if d.split('.')[-1] not in self.cfg.VALID_TLDS:
                continue
            _add("https://" + d)

        return hosts[:20]

    # ---------- 站点有效性 ----------
    def _site_ok(self, html):
        if not html or len(html) < self.cfg.PROBE_MIN_HTML:
            return False
        low = html.lower()
        blocked = ('just a moment', 'cf-browser-verification',
                   'checking your browser', '__cf_chl_', 'ddos-guard',
                   'enable javascript and cookies')
        if any(b in low for b in blocked):
            return False
        has_article = (
            '<article' in low
            or 'realtime-card' in low
            or 'video-card' in low
            or 'post-title' in low
            or 'entry-title' in low
        )
        return has_article or self.cfg.match_keyword(html)

    # ---------- 并发探测 ----------
    def _probe_one(self, url, timeout=None):
        r = self.fetch(url, timeout=timeout or self.cfg.PROBE_TIMEOUT,
                       allow_redirects=True)
        if r is None or r.status_code != 200:
            return ""
        if not self._site_ok(r.text):
            return ""
        return self._final_host(r.url) or url.rstrip("/")

    def _probe_hosts(self, hosts):
        if not hosts:
            return ""
        urls = [h.rstrip("/") + "/" for h in hosts]
        ex = ThreadPoolExecutor(max_workers=min(8, len(urls)))
        try:
            futs = {ex.submit(self._probe_one, u): u for u in urls}
            try:
                for f in as_completed(futs, timeout=self.cfg.PROBE_TIMEOUT + 5):
                    try:
                        h = f.result()
                    except Exception:
                        continue
                    if h:
                        for x in futs:
                            x.cancel()
                        return h
            except Exception:
                pass
        finally:
            try:
                ex.shutdown(wait=False, cancel_futures=True)  # cancel_futures 需 py3.9+
            except TypeError:
                ex.shutdown(wait=False)
        return ""

    # ---------- 缓存 ----------
    def _read_cache(self, key, field):
        if not self.cache_get:
            return ""
        try:
            raw = self.cache_get(key)
        except Exception:
            return ""
        if not raw:
            return ""
        if isinstance(raw, bytes):
            try:
                raw = raw.decode("utf-8", "ignore")
            except Exception:
                return ""
        if isinstance(raw, dict):
            return str(raw.get(field) or "").strip()
        s = str(raw).strip()
        if not s:
            return ""
        if s.startswith("{"):
            try:
                return str(json.loads(s).get(field) or "").strip()
            except Exception:
                return ""
        return s

    def _write_cache(self, key, data):
        if not self.cache_set or not data:
            return
        try:
            self.cache_set(key, json.dumps(data))
        except Exception:
            pass

    # ---------- 统一入口 ----------
    def resolve(self):
        # 1) HOST 缓存快速校验
        cached_host = self._read_cache(self.cfg.HOST_CACHE_KEY, "host")
        if cached_host:
            hit = self._probe_one(cached_host.rstrip("/") + "/",
                                  self.cfg.FAST_TIMEOUT)
            if hit:
                print(f"[HOST缓存] 有效: {hit}")
                if hit != cached_host:
                    self._write_cache(self.cfg.HOST_CACHE_KEY, {"host": hit})
                return hit
            print(f"[HOST缓存] 失效: {cached_host}")

        # 2) 上次成功的二级发布页（加速路径）
        pub_cached = self._read_cache(self.cfg.PUB_CACHE_KEY, "pub")
        if pub_cached:
            r = self.fetch(pub_cached.rstrip("/") + "/",
                           timeout=self.cfg.FAST_TIMEOUT,
                           allow_redirects=True)
            if r is not None and r.status_code == 200:
                cands = self._extract_candidate_hosts(r.text or "")
                host = self._probe_hosts(cands)
                if host:
                    print(f"[PUB缓存] {pub_cached} → 命中 {host}")
                    self._write_cache(self.cfg.HOST_CACHE_KEY, {"host": host})
                    return host
            print(f"[PUB缓存] 失效: {pub_cached}")

        # 3) 一级跳板页 → 秒跳转 → 二级发布页
        for pub_url in self.cfg.PUBLISH_URLS:
            print(f"[一级页] 解析: {pub_url}")
            jump_url, html = self._resolve_jump_page(pub_url)
            if not jump_url:
                print(f"[一级页] {pub_url} 未能拿到跳转目标")
                continue
            print(f"[一级页] {pub_url} → {jump_url}")
            self._write_cache(self.cfg.PUB_CACHE_KEY, {"pub": jump_url})
            cands = self._extract_candidate_hosts(html)
            host = self._probe_hosts(cands)
            if host:
                print(f"[一级页] 命中: {host}")
                self._write_cache(self.cfg.HOST_CACHE_KEY, {"host": host})
                return host

        # 4) 二级发布页硬编码兜底
        for fb_url in self.cfg.PUBLISH_FALLBACK_AFTER_JUMP:
            fb_url = fb_url.rstrip("/") + "/"
            print(f"[二级保底] 解析: {fb_url}")
            r = self.fetch(fb_url, timeout=self.cfg.PUBLISH_TIMEOUT,
                           allow_redirects=True)
            if r is None or r.status_code != 200:
                print(f"[二级保底] {fb_url} 访问失败")
                continue
            final_url = r.url.rstrip("/") + "/"
            self._write_cache(self.cfg.PUB_CACHE_KEY, {"pub": final_url})
            cands = self._extract_candidate_hosts(r.text or "")
            host = self._probe_hosts(cands)
            if host:
                print(f"[二级保底] 命中: {host}")
                self._write_cache(self.cfg.HOST_CACHE_KEY, {"host": host})
                return host

        # 5) 全部失败回退旧缓存
        print("[发布页] 全部策略失败，回退旧缓存")
        return cached_host or ""


# ==================================================================
# ③ Spider 主体（播放源聚合逻辑已整合为原生方法）
# ==================================================================
class Spider(BaseSpider):
    CONFIG = Config

    def __init__(self, *a, **kw):
        try:
            super().__init__(*a, **kw)
        except Exception:
            pass
        self.proxies = {}
        self.host = ""
        self.headers = dict(self.CONFIG.HEADERS)
        self._mem_cache = {}
        self._img_cache = {}
        # 播放源聚合所需的页面缓存（原猴子补丁改为原生实现）
        self.page_cache, self.page_index, self.page_keys, self._src_cache = {}, {}, [], {}

    # ---------- 缓存兜底 ----------
    def _cache_get(self, key):
        fn = getattr(self, "getCache", None)
        if callable(fn):
            try:
                v = fn(key)
                if v:
                    return v
            except Exception:
                pass
        return self._mem_cache.get(key)

    def _cache_set(self, key, value):
        self._mem_cache[key] = value
        fn = getattr(self, "setCache", None)
        if callable(fn):
            try:
                fn(key, value)
            except Exception:
                pass

    # ---------- 生命周期 ----------
    def init(self, extend=""):
        self._mem_cache = {}
        self._img_cache = {}
        self.page_cache, self.page_index, self.page_keys, self._src_cache = {}, {}, [], {}
        self.proxies = {}
        self.headers = dict(self.CONFIG.HEADERS)

        raw_extend = {}
        if isinstance(extend, dict):
            raw_extend = dict(extend)
        elif isinstance(extend, str) and extend.strip().startswith("{"):
            try:
                raw_extend = json.loads(extend)
            except Exception:
                raw_extend = {}
        if raw_extend:
            self.proxies = {k: v for k, v in raw_extend.items()
                            if k in ("http", "https", "all")}

        manual = raw_extend.get("host", "") if isinstance(raw_extend, dict) else ""
        if not manual and isinstance(extend, str) and extend.strip().startswith("http"):
            manual = extend.strip()
        if manual:
            manual = manual.strip().rstrip("/")
            if not manual.startswith("http"):
                manual = "https://" + manual
            self.host = manual
            print(f"【extend 指定】使用域名: {self.host}")
        else:
            self.host = self.get_working_host()

        if self.host:
            self.headers.update({"Origin": self.host, "Referer": self.host + "/"})
        print(f"使用站点: {self.host}")

    def getName(self):
        return "🍉%s|发布页秒跳自愈版" % self.CONFIG.SITE_NAME

    def isVideoFormat(self, url):
        return any(e in (url or "") for e in (".m3u8", ".mp4", ".ts"))

    def manualVideoCheck(self):
        return False

    def destroy(self):
        self._img_cache = {}
        self._mem_cache = {}
        self.page_cache, self.page_index, self.page_keys, self._src_cache = {}, {}, [], {}

    # ---------- 发布页自愈 ----------
    def get_working_host(self):
        resolver = PublishResolver(
            self.CONFIG, self._request,
            cache_get=self._cache_get,
            cache_set=self._cache_set,
        )
        return resolver.resolve()

    def _request(self, url, timeout=None, **kw):
        kw.setdefault("allow_redirects", True)   # 修正：原为显式传参，与 **kw 冲突风险
        try:
            return requests.get(
                url, headers=self.headers, proxies=self.proxies,
                timeout=timeout or self.CONFIG.PROBE_TIMEOUT,
                verify=False, **kw)
        except Exception as e:
            LOG.debug("GET 异常 %s: %s", url, e)
            return None

    def _get_soup(self, url, timeout=15):
        r = self._request(url, timeout=timeout)
        if r is None or r.status_code != 200:
            return None, None
        return r, self.getpq(r.text)

    @staticmethod
    def getpq(data):
        try:
            return pq(data)
        except Exception:
            return pq(data.encode("utf-8"))

    @staticmethod
    def e64(s): return b64encode(str(s).encode()).decode()
    @staticmethod
    def d64(s): return b64decode(str(s).encode()).decode()

    def _abs(self, href):
        href = (href or "").strip()
        if not href:
            return ""
        if href.startswith("http"):
            return href
        if href.startswith("//"):
            return "https:" + href
        if not self.host:
            return href
        return self.host + (href if href.startswith("/") else "/" + href)

    @staticmethod
    def _unique(name, seen):
        if name not in seen:
            seen.add(name)
            return name
        c = 2
        while "%s %d" % (name, c) in seen:
            c += 1
        new = "%s %d" % (name, c)
        seen.add(new)
        return new

    @staticmethod
    def _clean(s):
        return str(s or "").replace("$", " ").replace("#", " ").strip()

    @staticmethod
    def _enc(s):
        try: return quote(str(s or ""), safe="")
        except Exception: return str(s or "")

    @staticmethod
    def _dec(s):
        try: return unquote(str(s or ""))
        except Exception: return str(s or "")

    @staticmethod
    def _as_result(r):
        if r is None:
            return {}
        if isinstance(r, dict):
            return r
        if isinstance(r, (bytes, bytearray)):
            r = r.decode("utf-8", "ignore")
        if isinstance(r, str):
            s = r.strip()
            if s[:1] in "{[":
                try:
                    return json.loads(s)
                except Exception:
                    return {}
        return {}

    @staticmethod
    def _split_sources(vod):
        fr = str((vod or {}).get("vod_play_from") or "").split("$$$")
        ur = str((vod or {}).get("vod_play_url") or "").split("$$$")
        while len(ur) < len(fr):
            ur.append("")
        src = []
        for i, name in enumerate(fr):
            parts = []
            for p in (ur[i] or "").split("#"):
                if not p:
                    continue
                n, u = p.split("$", 1) if "$" in p else (str(i + 1), p)
                parts.append((Spider._clean(n), u))
            src.append((Spider._clean(name) or "线路%d" % (i + 1), parts))
        return [x for x in src if x[1]]

    # ---------- 页面缓存（供播放源聚合使用）----------
    def _cache_page(self, key, items):
        out = [x for x in (items or []) if isinstance(x, dict) and x.get("vod_id")]
        if not out:
            return
        self.page_cache[key] = out
        if key in self.page_keys:
            self.page_keys.remove(key)
        self.page_keys.append(key)
        for it in out:
            self.page_index[str(it["vod_id"])] = key
        while len(self.page_keys) > 30:
            self.page_cache.pop(self.page_keys.pop(0), None)

    def _page_of(self, vid):
        key = self.page_index.get(str(vid))
        return list(self.page_cache.get(key, [])) if key in self.page_cache else []

    # ---------- 首页 ----------
    def homeContent(self, filter=False):
        if not self.host:
            print("[homeContent] self.host 为空，直接返回空列表")
            return {"class": [], "list": []}
        r, data = self._get_soup(self.host)
        if data is None:
            print(f"[homeContent] 抓取 {self.host} 失败")
            return {"class": [], "list": []}
        lst = self._parse_list(data(self.CONFIG.SEL_ARTICLE_HOME))
        self._cache_page(("home",), lst)
        if not lst:
            print(f"[homeContent] 列表解析为空，HTML长度={len(r.text or '')}，检查 SEL_ARTICLE_HOME")
        return {
            "class": self._parse_classes(data),
            "list":  lst,
        }

    def homeVideoContent(self):
        if not self.host:
            return {"list": []}
        r, data = self._get_soup(self.host)
        if data is None:
            return {"list": []}
        lst = self._parse_list(data(self.CONFIG.SEL_ARTICLE_HOME))
        self._cache_page(("homev",), lst)
        return {"list": lst}

    def _parse_classes(self, data):
        classes, seen = [], set()
        def _add(href, name):
            href = (href or "").strip()
            name = (name or "").strip()
            if not href or not name or href == "#":
                return
            if href.startswith(("javascript:", "mailto:", "tel:")):
                return
            if not href.startswith("http"):
                href = "/" + href.lstrip("/")
            if href in seen:
                return
            seen.add(href)
            classes.append({"type_name": name, "type_id": href})
        for sel in self.CONFIG.SEL_NAV:
            for k in data(sel).items():
                a = k if k.is_("a") else k("a").eq(0)
                _add(a.attr("href"), a.text())
            if classes:
                break
        for sel in self.CONFIG.SEL_SUB_NAV:
            for a in data(sel).items():
                _add(a.attr("href"), a.attr("title") or a.text())
            if classes:
                break
        if not classes:
            classes = [dict(self.CONFIG.DEFAULT_CATEGORY)]
        return classes

    # ---------- 分类 ----------
    def categoryContent(self, tid, pg=1, filter=False, extend=None):
        if not self.host:
            return {"list": [], "page": 1, "pagecount": 1, "limit": 90, "total": 0}
        pg = int(pg or 1)
        if "@folder" in tid:
            v = self._parse_folder(tid.replace("@folder", ""))
            return {"list": v, "page": 1, "pagecount": 1, "limit": 90, "total": len(v)}
        url = self._build_page_url(tid, pg)
        r, data = self._get_soup(url)
        if data is None:
            return {"list": [], "page": pg, "pagecount": 9999, "limit": 90, "total": 0}
        lst = self._parse_list(data(self.CONFIG.SEL_ARTICLE), tid)
        self._cache_page(("cate", str(tid), str(pg), str(extend or "")), lst)
        return {
            "list": lst,
            "page": pg, "pagecount": 9999, "limit": 90, "total": 999999,
        }

    def _build_page_url(self, tid, pg):
        if tid.startswith("http"):
            base = tid.rstrip("/")
        else:
            base = (self.host + "/" + tid.lstrip("/")).rstrip("/")
        if pg == 1:
            return base + "/"
        host_ns = self.host.rstrip("/")
        if base == host_ns:
            return "%s/page/%d/" % (host_ns, pg)
        if "/category/" in base or "/tag/" in base:
            return "%s/%d/" % (base, pg)
        if "/page/" in base:
            return "%s/%d/" % (base, pg)
        return "%s/page/%d/" % (base, pg)

    def _parse_list(self, data, tid=""):
        is_folder = "/mrdg" in (tid or "")
        videos = []
        for k in data.items():
            href = k.attr("href") or k("a").eq(0).attr("href")
            title = (k("h2").text() or k(".entry-title").text()
                     or k(".post-title").text() or "").strip()
            if not title and k.is_("a"):
                title = (k.text() or "").strip()
            if not href or not title:
                continue
            videos.append({
                "vod_id":      "%s%s" % (href, "@folder" if is_folder else ""),
                "vod_name":    title,
                "vod_pic":     self._parse_pic(k),
                "vod_remarks": self._parse_date(k),
                "vod_tag":     "folder" if is_folder else "",
                "style":       {"type": "rect", "ratio": 1.33},
            })
        return videos

    def _parse_folder(self, id):
        r, data = self._get_soup(self._abs(id))
        if data is None:
            return []
        out = []
        for i, h2 in enumerate(data(".post-content h2").items()):
            p_txt = data(".post-content p").eq(i * 2)
            p_img = data(".post-content p").eq(i * 2 + 1)
            out.append({
                "vod_id":      p_txt("a").attr("href"),
                "vod_name":    p_txt.text().strip(),
                "vod_pic":     self._parse_pic(p_img),
                "vod_remarks": h2.text().strip(),
            })
        return out

    # ---------- 搜索 ----------
    def searchContent(self, key, quick=False, pg=1):
        if not self.host:
            return {"list": [], "page": 1, "pagecount": 1}
        pg = int(pg or 1)
        url = "%s/search/%s/%s" % (self.host, key, ("%d/" % pg) if pg > 1 else "")
        r, data = self._get_soup(url)
        if data is None:
            return {"list": [], "page": pg, "pagecount": 9999}
        lst = self._parse_list(data("article"))
        self._cache_page(("search", str(key), str(pg)), lst)
        return {"list": lst, "page": pg, "pagecount": 9999}

    # ---------- 详情（含播放源聚合，原生实现）----------
    def _load_src(self, vid):
        vid = str(vid)
        if vid in self._src_cache:
            return self._src_cache[vid]
        vod = ((self._raw_detail(vid).get("list") or [None])[0]) or {}
        src = self._split_sources(vod)
        self._src_cache[vid] = src
        return src

    def _raw_detail(self, vid):
        url = vid if vid.startswith("http") else self.host + vid
        r, data = self._get_soup(url)
        if data is None:
            return {"list": [{"vod_play_from": self.CONFIG.PLAY_FROM,
                              "vod_play_url":  "获取失败"}]}
        playlist = self._extract_playlist(data)
        play_url = "#".join(playlist) or "未找到视频源，请访问网页$%s" % url
        return {"list": [{
            "vod_play_from": self.CONFIG.PLAY_FROM,
            "vod_play_url":  play_url,
            "vod_content":   self._extract_content(data),
        }]}

    def _item_parts(self, it, src_idx, current_sources, current_vid):
        iid = str(it.get("vod_id") or "")
        if not iid:
            return []
        name = self._clean(it.get("vod_name") or iid) or iid
        if iid == str(current_vid):
            eps = []
            if current_sources:
                eps = (current_sources[src_idx][1]
                       if src_idx < len(current_sources) and current_sources[src_idx][1]
                       else current_sources[0][1])
            if len(eps) > 1:
                out = []
                for i, (en, u) in enumerate(eps):
                    out.append("%s$%s" % (self._clean("%s %s" % (name, en or "%02d" % (i + 1))), u))
                return out
            if eps:
                return ["%s$%s" % (name, eps[0][1])]
            return ["%s$nid:%s" % (name, self._enc(iid))]
        return ["%s$nid:%s" % (name, self._enc(iid))]

    def _apply_playlist(self, vid, vod, items):
        sources = self._split_sources(vod)
        self._src_cache[str(vid)] = sources
        if not items:
            return vod
        ordered = [x for x in items if str(x.get("vod_id")) == str(vid)]
        ordered += [x for x in items if str(x.get("vod_id")) != str(vid)]
        plist, seen = [], set()
        for it in ordered:
            iid = str(it.get("vod_id") or "")
            if not iid or iid in seen:
                continue
            seen.add(iid)
            plist.append(it)
        if not plist:
            return vod
        if not sources:
            sources = [("线路1", [("播放", "nid:%s" % self._enc(vid))])]
        pf, pu = [], []
        for i, (sname, _e) in enumerate(sources):
            parts = []
            for it in plist:
                parts.extend(self._item_parts(it, i, sources, vid))
            if not parts:
                continue
            pf.append(sname or "线路%d" % (i + 1))
            pu.append("#".join(parts))
        if not pf:
            return vod
        vod = dict(vod)
        vod["vod_play_from"] = "$$$".join(pf)
        vod["vod_play_url"]  = "$$$".join(pu)
        return vod

    def detailContent(self, ids):
        vid = str(ids[0] if isinstance(ids, (list, tuple)) else ids)
        if vid.startswith("nid:"):
            vid = self._dec(vid[4:])
        if not self.host:
            return {"list": [{"vod_play_from": self.CONFIG.PLAY_FROM,
                              "vod_play_url":  "获取失败"}]}
        cached = self._page_of(vid)
        rr = self._as_result(self._raw_detail(vid))
        lst = rr.get("list") or []
        if not lst or not isinstance(lst[0], dict):
            return rr
        vod = dict(lst[0])
        vod["vod_id"] = str(vod.get("vod_id") or vid)
        if not vod.get("vod_name") and cached:
            hit = next((x for x in cached if str(x.get("vod_id")) == vid), None)
            if hit:
                vod["vod_name"] = hit.get("vod_name") or vid
        if cached:
            vod = self._apply_playlist(vid, vod, cached)
        rr["list"] = [vod]
        return rr

    def _extract_playlist(self, data):
        if data(self.CONFIG.SEL_PLAYER):
            pl = self._from_dplayer(data)
            if pl:
                return pl
        return self._from_links(data)

    def _from_dplayer(self, data):
        out, used = [], set()
        for i, k in enumerate(data(self.CONFIG.SEL_PLAYER).items(), 1):
            try:
                cfg = json.loads(k.attr("data-config") or "{}")
                url = cfg.get("video", {}).get("url", "")
                if not url:
                    continue
                base = self._near_heading(k) or "视频%d" % i
                out.append("%s$%s" % (self._unique(base, used), url))
            except Exception:
                continue
        return out

    def _from_links(self, data):
        out, used = [], set()
        for i, link in enumerate(data(self.CONFIG.SEL_CONTENT)("a").items(), 1):
            txt = (link.text() or "").strip()
            href = link.attr("href")
            if not href:
                continue
            if not (any(kw in txt for kw in self.CONFIG.LINK_KEYWORDS) or
                    any(re.search(p, href, re.I) for p in self.CONFIG.LINK_URL_PATTERNS)):
                continue
            name = (txt.replace("点击观看：", "").replace("点击观看", "").strip() or "视频%d" % i)
            out.append("%s$%s" % (self._unique(name, used), self._abs(href)))
        return out

    @staticmethod
    def _near_heading(k, levels=4):
        p = k.parents().eq(0)
        for _ in range(levels):
            if not p:
                break
            h = p.find("h2, h3, h4").eq(0).text().strip()
            if h:
                return h
            p = p.parents().eq(0)
        return ""

    def _extract_content(self, data):
        tags = []
        for k in data(self.CONFIG.SEL_TAGS).items():
            t, h = (k.text() or "").strip(), k.attr("href")
            if t and h:
                tags.append("[a=cr:%s/]%s[/a]" % (json.dumps({"id": self._abs(h), "name": t}), t))
        if tags:
            return " ".join(tags) + "\n\n" + (data(self.CONFIG.SEL_SUMMARY).text() or "")[:150]
        return data(self.CONFIG.SEL_TITLE).text() or "未命名"

    def _parse_pic(self, k):
        return self._extract_img(k("script").text(), k)

    def _parse_date(self, k):
        t = k("time").text()
        if t:
            return t.strip()
        full = k.text()
        m = re.search(r"(\d{4}\s*年\s*\d{1,2}\s*月\s*\d{1,2}\s*日)", full)
        if not m:
            m = re.search(r"(\d{4}-\d{1,2}-\d{1,2})", full)
        return m.group(1) if m else ""

    def _extract_img(self, text, elem=None):
        if m := re.search(r"loadBannerDirect\('([^']+)'", text or ""):
            return self._proc_url(m.group(1))
        html = elem.outer_html() if hasattr(elem, "outer_html") else str(elem or "")
        html = html.replace("&quot;", '"').replace("&apos;", "'").replace("&amp;", "&")
        for pat in (
            r"(data:image/[a-zA-Z0-9+/=;,]+)",
            r'(https?://[^"\'\s)]+\.(?:jpg|png|jpeg|webp))',
            r'url\s*\(\s*[\'"]?([^"\'\)]+)[\'"]?\s*\)',
        ):
            m = re.search(pat, html, re.I)
            if m:
                return self._proc_url(m.group(1))
        return ""

    def _proc_url(self, url):
        if not url:
            return ""
        url = url.strip("'\" ")
        if url.startswith("data:"):
            try:
                _, b64s = url.split(",", 1)
                raw = b64decode(b64s)
                if not self._is_image(raw):
                    raw = self.aesimg(raw)
                key = hashlib.md5(raw).hexdigest()
                self._img_cache[key] = raw
                return "%s&type=cache&key=%s" % (self.getProxyUrl(), key)
            except Exception:
                return ""
        return "%s&url=%s&type=img" % (self.getProxyUrl(), self.e64(self._abs(url)))

    @staticmethod
    def _is_image(b):
        return (b.startswith(b"\xff\xd8") or b.startswith(b"\x89PNG") or b.startswith(b"GIF8"))

    def aesimg(self, data):
        if len(data) < 16:
            return data
        for key, iv in self.CONFIG.IMG_AES_KEYS:
            if iv:
                try:
                    dec = unpad(AES.new(key, AES.MODE_CBC, iv).decrypt(data), 16)
                    if self._is_image(dec):
                        return dec
                except Exception:
                    pass
            try:
                dec = unpad(AES.new(key, AES.MODE_ECB).decrypt(data), 16)
                if self._is_image(dec):
                    return dec
            except Exception:
                pass
        return data

    # ---------- 播放 ----------
    def playerContent(self, flag, id, vipFlags=None):
        s = str(id)
        if s.startswith("nid:"):
            vid = self._dec(s[4:])
            sources = self._load_src(vid)
            real = ""
            if sources:
                picked = None
                for name, eps in sources:
                    if str(name) == str(flag) and eps:
                        picked = eps
                        break
                if not picked:
                    picked = sources[0][1]
                if picked:
                    real = picked[0][1]
            id = real if real and not str(real).startswith("nid:") else vid
        parse = 0 if self.isVideoFormat(id) else 1
        url = self.proxy(id) if ".m3u8" in id else id
        return {"parse": parse, "url": url, "header": self.headers}

    def proxy(self, data, kind="m3u8"):
        if data and self.proxies:
            return "%s&url=%s&type=%s" % (self.getProxyUrl(), self.e64(data), kind)
        return data

    def localProxy(self, param):
        try:
            t = param.get("type")
            if t == "cache":
                d = self._img_cache.get(param.get("key"))
                return [200, "image/jpeg", d] if d else [404, "text/plain", b"Expired"]
            if t == "img":
                raw = param.get("url") or ""
                real = raw if raw.startswith("http") else self.d64(raw)
                res = self._request(real, timeout=10)
                return [200, "image/jpeg", self.aesimg(res.content)] if res else [404, "text/plain", b""]
            if t == "m3u8":
                return self._m3_proxy(param.get("url"))
            if t == "mkey":   # 修正：AES key 不能按 ts 流返回
                return self._key_proxy(param.get("url"))
            return self._ts_proxy(param.get("url"))
        except Exception:
            return [404, "text/plain", b""]

    def _key_proxy(self, url):
        real = url if url.startswith("http") else self.d64(url)
        res = self._request(real)
        return [200, "binary/octet-stream", res.content] if res else [404, "text/plain", b""]

    def _m3_proxy(self, url):
        real = url if url.startswith("http") else self.d64(url)
        res = self._request(real)
        if res is None:
            return [404, "text/plain", b""]
        base = res.url.rsplit("/", 1)[0]
        out, iskey = [], True
        for line in res.text.split("\n"):
            if iskey and 'URI="' in line:
                m = re.search(r'URI="([^"]*)"', line)
                if m:
                    out.append(re.sub(r'URI="[^"]*"',
                                      'URI="%s"' % self.proxy(m.group(1), "mkey"), line))
                    iskey = False
                    continue
            if "#EXT" not in line and line.strip():
                if not line.startswith("http"):
                    line = "%s/%s" % (base, line)
                out.append(self.proxy(line, "ts"))
            else:
                out.append(line)
        return [200, "application/vnd.apple.mpegurl", "\n".join(out)]

    def _ts_proxy(self, url):
        real = url if url.startswith("http") else self.d64(url)
        res = self._request(real)
        return [200, "video/mp2t", res.content] if res else [404, "text/plain", b""]
