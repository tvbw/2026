# -*- coding: utf-8 -*-
"""
51系列标准模板 · 发布页秒跳自愈版
------------------------------------------------------------------
核心思路：
  1. 一级跳板页（如 https://51cgf24.com/）进入后通常会被
     HTTP 3xx 或 HTML/JS 立即跳转到二级发布页；
  2. 只要快速拿到【二级发布页 URL】并抓取其 HTML，即可从中
     提取三级内容站候选域名；
  3. 对候选域名做并发探测，首个命中即为可用站点，写入缓存；
  4. 一级页解析失败时，直接用 PUBLISH_FALLBACK_AFTER_JUMP
     里硬编码的二级发布页做保底。

发布页缓存（PUB_CACHE_KEY）记录“上次成功跳转到的二级页”，
下次启动先试它，可秒进；失效后自动回退到一级跳板页重新解析。
一级页与二级页同时失效属于故障级事件，才需要手动更新
PUBLISH_FALLBACK_AFTER_JUMP。
"""
import json
import re
import sys
import hashlib
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
        def getCache(self, k):    return None
        def setCache(self, k, v): pass
        def getProxyUrl(self):    return ""

try:
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
except Exception:
    pass

img_cache = {}


# ==================================================================
# ① 站点配置
# ==================================================================
class Config:
    SITE_NAME     = "51吃瓜8"
    SITE_KEYWORDS = ["51吃瓜", "51爆料", "51吃瓜8"]
    PLAY_FROM     = "51吃瓜8"

    # ---- 缓存键 ----
    HOST_CACHE_KEY = "sp51cg_host_v1"      # 最终三级内容站
    PUB_CACHE_KEY  = "sp51cg_pub_v1"       # 上次成功跳转到的二级发布页

      # ---- 二级发布页（硬编码保底，域名变了再改这里）----
    PUBLISH_FALLBACK_AFTER_JUMP = [
        "https://www.sunkdjlla.cc/",
        "https://www.gvhafcbw.cc/",
    ]
    # ---- 一级跳板页（只填这一个）----
    PUBLISH_URLS = [
        "https://51cgf24.com/",
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
# ② 发布页解析器（核心）
# ==================================================================
class PublishResolver:
    """
    职责：快速完成 一级跳板页 → 二级发布页 → 三级内容站域名 的解析。
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
        # 一级跳板页 origin（用于判断 requests 是否已跳出跳板页）
        self._jump_origins = {
            self._origin(u) for u in cfg.PUBLISH_URLS if u
        }
        # 所有发布页 origin（用于从候选域名中排除发布页自身）
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
        u = unquote(str(u or "")).strip().strip('"\' ')
        if not u:
            return ""
        if u.startswith("//"):
            u = "https:" + u
        if not u.startswith("http"):
            u = urljoin(base_url or "", u)
        return u

    # ---------- 一级页 → 二级页 ----------
    def _resolve_jump_page(self, start_url):
        """
        返回：(二级发布页 URL, 该页 HTML)
        失败返回 ("", "")。
        """
        start_url = start_url.rstrip("/") + "/"
        r = self.fetch(start_url, timeout=self.cfg.PUBLISH_TIMEOUT,
                       allow_redirects=True)
        if r is None:
            return "", ""

        final_url = r.url.rstrip("/") + "/"
        html = r.text or ""

        # 情况 A：requests 已通过 3xx 跳出跳板页（落到二级页或三级站）
        if self._origin(final_url) not in self._jump_origins:
            return final_url, html

        # 情况 B：落地仍是跳板页本身，说明跳转写在 HTML/JS 里
        target = self._extract_html_jump(html, final_url)
        if not target:
            return "", ""

        target = target.rstrip("/") + "/"
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
            if h in self._publish_origins:   # 排除发布页自身
                return
            if h in seen:
                return
            seen.add(h)
            hosts.append(h)

        # 策略1：所有 http(s) 链接
        for m in re.finditer(r'https?://[^\s"\'<>()\[\]{},;]+', html):
            _add(m.group(0))

        # 策略2：裸域名（限制扫描长度）
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
            ex.shutdown(wait=False, cancel_futures=True)
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
# ③ Spider 主体
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

    # ---------- 缓存兜底（BaseSpider 无 getCache/setCache 时用内存）----------
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
        global img_cache
        img_cache.clear()
        self._mem_cache = {}
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
        global img_cache
        img_cache.clear()
        self._mem_cache = {}

    # ---------- 发布页自愈 ----------
    def get_working_host(self):
        resolver = PublishResolver(
            self.CONFIG, self._request,
            cache_get=self._cache_get,
            cache_set=self._cache_set,
        )
        return resolver.resolve()

    def _request(self, url, timeout=None, **kw):
        kw.setdefault("allow_redirects", True)
        try:
            return requests.get(
                url, headers=self.headers, proxies=self.proxies,
                timeout=timeout or self.CONFIG.PROBE_TIMEOUT,
                verify=False, **kw)
        except Exception:
            return None

    def getpq(self, data):
        try:
            return pq(data)
        except Exception:
            return pq(data.encode("utf-8"))

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

    # ---------- 首页 / 分类 ----------
    def homeContent(self, filter=False):
        if not self.host:
            return {"class": [], "list": []}
        r = self._request(self.host)
        if r is None or r.status_code != 200:
            return {"class": [], "list": []}
        data = self.getpq(r.text)

        classes = []
        for sel in ('.category-list ul li', '.nav-menu li',
                    '.menu li', 'nav ul li'):
            for k in data(sel).items():
                a = k('a')
                href = (a.attr('href') or '').strip()
                name = (a.text() or '').strip()
                if href and href != '#' and name:
                    classes.append({'type_name': name, 'type_id': href})
            if classes:
                break
        if not classes:
            classes = [{'type_name': '最新', 'type_id': '/latest/'},
                       {'type_name': '热门', 'type_id': '/hot/'}]
        return {"class": classes,
                "list": self.getlist(data("#index article, article"))}

    def homeVideoContent(self):
        if not self.host:
            return {"list": []}
        r = self._request(self.host)
        if r is None or r.status_code != 200:
            return {"list": []}
        data = self.getpq(r.text)
        return {"list": self.getlist(data("#index article, article"))}

    def categoryContent(self, tid, pg=1, filter=False, extend=None):
        if not self.host:
            return {'list': [], 'page': 1, 'pagecount': 1,
                    'limit': 90, 'total': 0}
        try:
            if '@folder' in tid:
                v = self.getfod(tid.replace('@folder', ''))
                return {'list': v, 'page': 1, 'pagecount': 1,
                        'limit': 90, 'total': len(v)}

            pg = int(pg) if pg else 1
            if tid.startswith('http'):
                base_url = tid.rstrip('/')
            else:
                path = tid if tid.startswith('/') else f"/{tid}"
                base_url = f"{self.host}{path}".rstrip('/')
            url = f"{base_url}/" if pg == 1 else f"{base_url}/{pg}/"

            r = self._request(url)
            if r is None or r.status_code != 200:
                return {'list': [], 'page': pg, 'pagecount': 9999,
                        'limit': 90, 'total': 0}
            data = self.getpq(r.text)
            videos = self.getlist(
                data('#archive article, #index article, article'), tid)
            return {'list': videos, 'page': pg, 'pagecount': 9999,
                    'limit': 90, 'total': 999999}
        except Exception:
            return {'list': [], 'page': 1, 'pagecount': 9999,
                    'limit': 90, 'total': 0}

    # ---------- 详情 ----------
    def detailContent(self, ids):
        try:
            if not self.host:
                return {'list': [{'vod_play_from': self.CONFIG.PLAY_FROM,
                                  'vod_play_url': '获取失败'}]}
            url = ids[0] if ids[0].startswith('http') else self._abs(ids[0])
            r = self._request(url)
            if r is None or r.status_code != 200:
                return {'list': [{'vod_play_from': self.CONFIG.PLAY_FROM,
                                  'vod_play_url': '获取失败'}]}
            data = self.getpq(r.text)

            plist, used_names = [], set()
            if data('.dplayer'):
                for c, k in enumerate(data('.dplayer').items(), start=1):
                    try:
                        cfg_attr = k.attr('data-config')
                        if not cfg_attr:
                            continue
                        video_url = (json.loads(cfg_attr)
                                     .get('video', {}).get('url', ''))
                        if not video_url:
                            continue
                        ep_name = ''
                        parent = k.parents().eq(0)
                        for _ in range(4):
                            if not parent:
                                break
                            heading = parent.find('h2, h3, h4').eq(0).text().strip()
                            if heading:
                                ep_name = heading
                                break
                            parent = parent.parents().eq(0)
                        base_name = ep_name or f"视频{c}"
                        name, n = base_name, 2
                        while name in used_names:
                            name = f"{base_name} {n}"
                            n += 1
                        used_names.add(name)
                        plist.append(f"{name}${video_url}")
                    except Exception:
                        continue

            if not plist:
                content_area = data('.post-content, article')
                kws = ('点击观看', '观看', '播放', '视频', '第一弹', '第二弹',
                       '第三弹', '第四弹', '第五弹', '第六弹', '第七弹',
                       '第八弹', '第九弹', '第十弹')
                for i, link in enumerate(content_area('a').items(), start=1):
                    link_text = link.text().strip()
                    link_href = link.attr('href')
                    if not link_href or not any(kw in link_text for kw in kws):
                        continue
                    ep_name = (link_text.replace('点击观看：', '')
                                        .replace('点击观看', '').strip()) or f"视频{i}"
                    if not link_href.startswith('http'):
                        link_href = (f"{self.host}{link_href}"
                                     if link_href.startswith('/')
                                     else f"{self.host}/{link_href}")
                    plist.append(f"{ep_name}${link_href}")

            play_url = '#'.join(plist) if plist else f"未找到视频源${url}"

            # 标签
            vod_content = ''
            try:
                tags, seen_names, seen_ids = [], set(), set()
                candidates = []
                for k in data('.tags a, .keywords a, .post-tags a').items():
                    t, h = k.text().strip(), k.attr('href')
                    if t and h:
                        candidates.append({'name': t, 'id': h})
                candidates.sort(key=lambda x: len(x['name']), reverse=True)
                for item in candidates:
                    name, id_ = item['name'], item['id']
                    if id_ in seen_ids:
                        continue
                    if any(name in s for s in seen_names):
                        continue
                    target = json.dumps({'id': id_, 'name': name})
                    tags.append(f'[a=cr:{target}/]{name}[/a]')
                    seen_names.add(name)
                    seen_ids.add(id_)
                vod_content = (' '.join(tags) if tags
                               else (data('.post-title').text() or ''))
            except Exception:
                vod_content = '获取标签失败'
            if not vod_content:
                vod_content = data('h1').text() or self.CONFIG.PLAY_FROM

            return {'list': [{
                'vod_play_from': self.CONFIG.PLAY_FROM,
                'vod_play_url':  play_url,
                'vod_content':   vod_content,
            }]}
        except Exception:
            return {'list': [{'vod_play_from': self.CONFIG.PLAY_FROM,
                              'vod_play_url': '获取失败'}]}

    # ---------- 搜索 ----------
    def searchContent(self, key, quick=False, pg=1):
        if not self.host:
            return {'list': [], 'page': 1, 'pagecount': 9999}
        try:
            pg = int(pg) if pg else 1
            url = (f"{self.host}/search/{key}/" if pg == 1
                   else f"{self.host}/search/{key}/{pg}/")
            r = self._request(url)
            if r is None or r.status_code != 200:
                return {'list': [], 'page': pg, 'pagecount': 9999}
            return {'list': self.getlist(self.getpq(r.text)('article')),
                    'page': pg, 'pagecount': 9999}
        except Exception:
            return {'list': [], 'page': 1, 'pagecount': 9999}

    # ---------- 播放 ----------
    def playerContent(self, flag, id, vipFlags=None):
        parse = 0 if self.isVideoFormat(id) else 1
        url = self.proxy(id) if '.m3u8' in id else id
        return {'parse': parse, 'url': url, 'header': self.headers}

    def proxy(self, data, kind='m3u8'):
        if data and self.proxies:
            return f"{self.getProxyUrl()}&url={self.e64(data)}&type={kind}"
        return data

    def localProxy(self, param):
        try:
            t = param.get('type')
            url = param.get('url')
            if t == 'cache':
                key = param.get('key')
                if content := img_cache.get(key):
                    return [200, 'image/jpeg', content]
                return [404, 'text/plain', b'Expired']
            if t == 'img':
                real = url if str(url).startswith('http') else self.d64(url)
                res = self._request(real, timeout=10)
                if res is None:
                    return [404, 'text/plain', b'']
                return [200, 'image/jpeg', self.aesimg(res.content)]
            if t == 'm3u8':
                return self.m3Proxy(url)
            return self.tsProxy(url)
        except Exception:
            return [404, 'text/plain', b'']

    def m3Proxy(self, url):
        real = url if str(url).startswith('http') else self.d64(url)
        res = self._request(real)
        if res is None:
            return [404, 'text/plain', b'']
        base = res.url.rsplit('/', 1)[0]
        lines = []
        for line in res.text.split('\n'):
            if '#EXT' not in line and line.strip():
                if not line.startswith('http'):
                    line = f"{base}/{line}"
                lines.append(self.proxy(line, 'ts'))
            else:
                lines.append(line)
        return [200, 'application/vnd.apple.mpegurl', '\n'.join(lines)]

    def tsProxy(self, url):
        real = url if str(url).startswith('http') else self.d64(url)
        res = self._request(real)
        return ([200, 'video/mp2t', res.content]
                if res is not None else [404, 'text/plain', b''])

    # ---------- 编解码 / 图片 ----------
    def e64(self, text):
        return b64encode(str(text).encode()).decode()

    def d64(self, text):
        return b64decode(str(text).encode()).decode()

    def aesimg(self, data):
        if len(data) < 16:
            return data
        keys = [(b'f5d965df75336270', b'97b60394abc2fbe1'),
                (b'75336270f5d965df', b'abc2fbe197b60394')]
        for k, v in keys:
            try:
                dec = unpad(AES.new(k, AES.MODE_CBC, v).decrypt(data), 16)
                if dec.startswith(b'\xff\xd8') or dec.startswith(b'\x89PNG'):
                    return dec
            except Exception:
                pass
            try:
                dec = unpad(AES.new(k, AES.MODE_ECB).decrypt(data), 16)
                if dec.startswith(b'\xff\xd8'):
                    return dec
            except Exception:
                pass
        return data

    # ---------- 列表解析 ----------
    def getlist(self, data, tid=''):
        videos = []
        is_folder = '/mrdg' in (tid or '')
        for k in data.items():
            card_html = k.outer_html() if hasattr(k, 'outer_html') else str(k)
            a = k if k.is_('a') else k('a').eq(0)
            href = a.attr('href')
            title = (k('h2').text() or k('.entry-title').text()
                     or k('.post-title').text())
            if not title and k.is_('a'):
                title = k.text()
            if not (href and title):
                continue
            videos.append({
                'vod_id': f"{href}{'@folder' if is_folder else ''}",
                'vod_name': title.strip(),
                'vod_pic': self.getimg(k('script').text(), k, card_html),
                'vod_remarks': k('time').text() or '',
                'vod_tag': 'folder' if is_folder else '',
                'style': {"type": "rect", "ratio": 1.33},
            })
        return videos

    def getfod(self, id):
        url = self._abs(id)
        r = self._request(url)
        if r is None:
            return []
        data = self.getpq(r.text)
        videos = []
        for i, h2 in enumerate(data('.post-content h2').items()):
            p_txt = data('.post-content p').eq(i * 2)
            p_img = data('.post-content p').eq(i * 2 + 1)
            p_html = (p_img.outer_html()
                      if hasattr(p_img, 'outer_html') else str(p_img))
            videos.append({
                'vod_id': p_txt('a').attr('href'),
                'vod_name': p_txt.text().strip(),
                'vod_pic': self.getimg('', p_img, p_html),
                'vod_remarks': h2.text().strip(),
            })
        return videos

    def getimg(self, text, elem=None, html_content=None):
        if m := re.search(r"loadBannerDirect\('([^']+)'", text or ''):
            return self._proc_url(m.group(1))

        if html_content is None and elem is not None:
            html_content = (elem.outer_html()
                            if hasattr(elem, 'outer_html') else str(elem))
        if not html_content:
            return ''

        html_content = (html_content.replace('&quot;', '"')
                                    .replace('&apos;', "'")
                                    .replace('&amp;', '&'))

        if 'data:image' in html_content:
            if m := re.search(r'(data:image/[a-zA-Z0-9+/=;,]+)', html_content):
                return self._proc_url(m.group(1))

        if m := re.search(r'(https?://[^"\'\s)]+\.(?:jpg|png|jpeg|webp))',
                          html_content, re.I):
            return self._proc_url(m.group(1))

        if 'url(' in html_content:
            if m := re.search(r'url\s*\(\s*[\'"]?([^"\'\)]+)[\'"]?\s*\)',
                              html_content, re.I):
                return self._proc_url(m.group(1))
        return ''

    def _proc_url(self, url):
        if not url:
            return ''
        url = url.strip('\'" ')
        if url.startswith('data:'):
            try:
                _, b64_str = url.split(',', 1)
                raw = b64decode(b64_str)
                if not (raw.startswith(b'\xff\xd8')
                        or raw.startswith(b'\x89PNG')
                        or raw.startswith(b'GIF8')):
                    raw = self.aesimg(raw)
                key = hashlib.md5(raw).hexdigest()
                img_cache[key] = raw
                return f"{self.getProxyUrl()}&type=cache&key={key}"
            except Exception:
                return ""
        if not url.startswith('http'):
            url = (f"{self.host}{url}" if url.startswith('/')
                   else f"{self.host}/{url}")
        return f"{self.getProxyUrl()}&url={self.e64(url)}&type=img"


# ==================================================================
# ④ 播放源聚合扩展：播放页面显示关键推荐条目
# ==================================================================
def _install_playlist_extension(_C):
    if getattr(_C, "_pl_patched", False):
        return _C
    _C._pl_patched = True
    _orig_init   = getattr(_C, "init", None)
    _orig_home   = getattr(_C, "homeContent", None)
    _orig_homev  = getattr(_C, "homeVideoContent", None)
    _orig_cate   = getattr(_C, "categoryContent", None)
    _orig_detail = getattr(_C, "detailContent", None)
    _orig_search = getattr(_C, "searchContent", None)
    _orig_searchp= getattr(_C, "searchContentPage", None)
    _orig_player = getattr(_C, "playerContent", None)

    def _ensure(self):
        if not hasattr(self, "page_cache"):
            self.page_cache, self.page_index, self.page_keys, self._src_cache = {}, {}, [], {}

    def _clean(s): return str(s or "").replace("$", " ").replace("#", " ").strip()

    def _enc(s):
        try: return quote(str(s or ""), safe="")
        except Exception: return str(s or "")

    def _dec(s):
        try: return unquote(str(s or ""))
        except Exception: return str(s or "")

    def _cache_page(self, key, items):
        _ensure(self)
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
        _ensure(self)
        key = self.page_index.get(str(vid))
        return list(self.page_cache.get(key, [])) if key in self.page_cache else []

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
                parts.append((_clean(n), u))
            src.append((_clean(name) or "线路%d" % (i + 1), parts))
        return [x for x in src if x[1]]

    def _call_detail(self, vid):
        if not _orig_detail:
            return {}
        try:
            return _as_result(_orig_detail(self, [vid]))
        except TypeError:
            try:
                return _as_result(_orig_detail(self, vid))
            except Exception:
                return {}
        except Exception:
            return {}

    def _load_src(self, vid):
        _ensure(self)
        vid = str(vid)
        if vid in self._src_cache:
            return self._src_cache[vid]
        r = self._pl_call_detail(vid)
        vod = ((r.get("list") or [None])[0]) or {}
        src = _split_sources(vod)
        self._src_cache[vid] = src
        return src

    def _item_parts(self, it, src_idx, current_sources, current_vid):
        iid = str(it.get("vod_id") or "")
        if not iid:
            return []
        name = _clean(it.get("vod_name") or iid) or iid
        if iid == str(current_vid):
            eps = []
            if current_sources:
                eps = (current_sources[src_idx][1]
                       if src_idx < len(current_sources) and current_sources[src_idx][1]
                       else current_sources[0][1])
            if len(eps) > 1:
                out = []
                for i, (en, u) in enumerate(eps):
                    out.append("%s$%s" % (_clean("%s %s" % (name, en or "%02d" % (i + 1))), u))
                return out
            if eps:
                return ["%s$%s" % (name, eps[0][1])]
            return ["%s$nid:%s" % (name, _enc(iid))]
        return ["%s$nid:%s" % (name, _enc(iid))]

    def _apply_playlist(self, vid, vod, items):
        sources = _split_sources(vod)
        _ensure(self)
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
            sources = [("线路1", [("播放", "nid:%s" % _enc(vid))])]
        pf, pu = [], []
        for i, (sname, _e) in enumerate(sources):
            parts = []
            for it in plist:
                parts.extend(self._pl_item_parts(it, i, sources, vid))
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

    def init(self, *a, **kw):
        _ensure(self)
        if _orig_init:
            return _orig_init(self, *a, **kw)

    def homeContent(self, *a, **kw):
        _ensure(self)
        r = _orig_home(self, *a, **kw) if _orig_home else {}
        try: _cache_page(self, ("home",), _as_result(r).get("list"))
        except Exception: pass
        return r

    def homeVideoContent(self, *a, **kw):
        _ensure(self)
        r = _orig_homev(self, *a, **kw) if _orig_homev else {"list": []}
        try: _cache_page(self, ("homev",), _as_result(r).get("list"))
        except Exception: pass
        return r

    def categoryContent(self, *a, **kw):
        _ensure(self)
        r = _orig_cate(self, *a, **kw) if _orig_cate else {"list": []}
        try:
            tid = a[0] if a else kw.get("tid", "")
            pg  = a[1] if len(a) > 1 else kw.get("pg", "1")
            ext = a[3] if len(a) > 3 else kw.get("extend", "")
            _cache_page(self, ("cate", str(tid), str(pg), str(ext)),
                        _as_result(r).get("list"))
        except Exception: pass
        return r

    def searchContent(self, *a, **kw):
        _ensure(self)
        if not _orig_search:
            return {"list": []}
        r = _orig_search(self, *a, **kw)
        try:
            key = a[0] if a else kw.get("key", "")
            pg  = a[2] if len(a) > 2 else kw.get("pg", "1")
            _cache_page(self, ("search", str(key), str(pg)), _as_result(r).get("list"))
        except Exception: pass
        return r

    def searchContentPage(self, *a, **kw):
        _ensure(self)
        if not _orig_searchp:
            return {"list": []}
        r = _orig_searchp(self, *a, **kw)
        try:
            key = a[0] if a else kw.get("key", "")
            pg  = a[2] if len(a) > 2 else kw.get("page", kw.get("pg", "1"))
            _cache_page(self, ("searchp", str(key), str(pg)), _as_result(r).get("list"))
        except Exception: pass
        return r

    def detailContent(self, ids, *a, **kw):
        _ensure(self)
        if isinstance(ids, (list, tuple)):
            vid = str(ids[0]) if ids else ""
            call_ids = list(ids)
        else:
            vid = str(ids)
            call_ids = [vid]
        if vid.startswith("nid:"):
            vid = _dec(vid[4:])
            call_ids[0] = vid
        cached = _page_of(self, vid)
        if _orig_detail:
            try:
                r = _orig_detail(self, call_ids, *a, **kw)
            except TypeError:
                r = _orig_detail(self, call_ids)
        else:
            r = {"list": []}
        try:
            rr = _as_result(r)
            lst = rr.get("list") or []
            if not lst or not isinstance(lst[0], dict):
                return r
            vod = dict(lst[0])
            vod["vod_id"] = str(vod.get("vod_id") or vid)
            if not vod.get("vod_name") and cached:
                hit = next((x for x in cached if str(x.get("vod_id")) == vid), None)
                if hit:
                    vod["vod_name"] = hit.get("vod_name") or vid
            if cached:
                vod = self._pl_apply_playlist(vid, vod, cached)
            rr = dict(rr)
            rr["list"] = [vod]
            if isinstance(r, dict) or r is None:
                return rr
            try:
                return json.dumps(rr, ensure_ascii=False)
            except Exception:
                return rr
        except Exception:
            return r

    def playerContent(self, flag, id, vipFlags=None, *a, **kw):
        _ensure(self)
        s = str(id)
        if s.startswith("nid:"):
            vid = _dec(s[4:])
            sources = self._pl_load_src(vid)
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
        if not _orig_player:
            return {"parse": 0, "url": id}
        try:
            return _orig_player(self, flag, id, vipFlags, *a, **kw)
        except TypeError:
            try:
                return _orig_player(self, flag, id, vipFlags)
            except TypeError:
                return _orig_player(self, flag, id)

    _C._pl_call_detail    = _call_detail
    _C._pl_load_src       = _load_src
    _C._pl_item_parts     = _item_parts
    _C._pl_apply_playlist = _apply_playlist
    if _orig_init:    _C.init              = init
    if _orig_home:    _C.homeContent       = homeContent
    if _orig_homev:   _C.homeVideoContent  = homeVideoContent
    if _orig_cate:    _C.categoryContent   = categoryContent
    if _orig_search:  _C.searchContent     = searchContent
    if _orig_searchp: _C.searchContentPage = searchContentPage
    if _orig_detail:  _C.detailContent     = detailContent
    if _orig_player:  _C.playerContent     = playerContent
    return _C


try:
    _install_playlist_extension(Spider)
except Exception:
    pass
