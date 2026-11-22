# -*- coding: utf-8 -*-
"""
51系列标准模板 · 发布页自愈版
------------------------------------------------------------------
特点：
1. 仅依赖【一级导航发布页】+【二级导航发布页】即可自动探测三级域名主页，
   不需要手动维护动态域名，长期免维护。
2. 一级发布页常被 JS/meta 混淆跳转，requests 静态正则抓不到目标，
   本模板会跟随跳转链 + 兜底走二级导航发布页提取候选域名。
3. 三级域名探测采用「并发 + 首个命中即返回」，并缓存站点 host 与
   最后成功跳转的发布页 URL，二次启动秒级复用。
4. 业务层（分类/列表/详情/搜索/播放/图片 AES 解密/m3u8 代理）
   完整保留 51 系列原有逻辑，方便作为标准模板长期使用。
"""
import json
import re
import sys
import hashlib
from base64 import b64decode, b64encode
from urllib.parse import urlparse, urljoin, unquote
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
    SITE_NAME     = "51系列"
    SITE_KEYWORDS = ["51吃瓜", "51爆料", "51cg"]
    PLAY_FROM     = "51爆料"

    # ---- 缓存键 ----
    HOST_CACHE_KEY = "sp51_host_v1"     # 最终三级域名主页
    PUB_CACHE_KEY  = "sp51_pub_v1"      # 最后成功跳转的发布页 URL

    # ---- 跳转跟随 ----
    JUMP_MAX_HOPS  = 2

    # ---- 一级导航发布页（主入口）----
    PUBLISH_URLS = [
        "https://51cgf24.com/",
    ]
    # ---- 二级导航发布页（一级被 JS 混淆抓不到时的兜底）----
    PUBLISH_FALLBACK_AFTER_JUMP = [
        "https://www.sunkdjlla.cc/",
        "https://www.nqvudlbn.cc/",
    ]

    # ---- 超时 ----
    PUBLISH_TIMEOUT = 15
    PROBE_TIMEOUT   = 15
    FAST_TIMEOUT    = 10

    # ---- 站点特征 ----
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
# ② 发布页解析器（自愈核心）
# ==================================================================
class PublishResolver:
    """
    以「发布页」为唯一锚点：
      发布页 → 跟随 JS/meta 跳转 → 提取候选三级域名 → 并发探测 → 命中缓存
    一级发布页若因 JS 混淆拿不到跳转目标，自动走二级导航发布页兜底。
    """

    JUMP_PATTERNS = (
        r'<meta[^>]+http-equiv=["\']?refresh["\']?[^>]*?url\s*=\s*([^"\'>\s]+)',
        r'url\s*=\s*([^"\'>\s;]+)["\'][^>]*http-equiv=["\']?refresh',
        r'(?:window\s*\.\s*)?location(?:\.href)?\s*=\s*["\'](https?://[^"\']+)["\']',
        r'(?:window\s*\.\s*)?location\s*\.\s*(?:replace|assign)\s*\(\s*["\'](https?://[^"\']+)["\']',
        r'(?:var\s+)?(?:url|href|targetUrl|jumpUrl)\s*=\s*["\'](https?://[^"\']+)["\']',
    )

    def __init__(self, cfg, fetcher, cache_get=None, cache_set=None):
        self.cfg = cfg
        self.fetch = fetcher
        self.cache_get = cache_get
        self.cache_set = cache_set
        # 发布页自身 origin（避免把发布页当作候选站点去探测）
        self._publish_set = {
            self._final_host(u)
            for u in (list(cfg.PUBLISH_URLS) + list(cfg.PUBLISH_FALLBACK_AFTER_JUMP))
            if u
        }

    # ---------- 抓取 / URL 工具 ----------
    def _fetch_safe(self, url, timeout=None):
        try:
            return self.fetch(url, timeout=timeout or self.cfg.PROBE_TIMEOUT)
        except Exception:
            return None

    @staticmethod
    def _final_host(url):
        if not url:
            return ""
        try:
            p = urlparse(url)
            if p.scheme in ("http", "https") and p.netloc:
                return "%s://%s" % (p.scheme, p.netloc.lower())
        except Exception:
            pass
        return ""

    # ---------- 缓存 ----------
    def _read_kv(self, key, field):
        if not self.cache_get:
            return ""
        try:
            raw = self.cache_get(key)
        except Exception:
            return ""
        if raw is None:
            return ""
        if isinstance(raw, bytes):
            try:
                raw = raw.decode("utf-8", "ignore")
            except Exception:
                return ""
        s = str(raw).strip()
        if not s:
            return ""
        if s.startswith("{"):
            try:
                return str(json.loads(s).get(field) or "").strip()
            except Exception:
                return ""
        return s  # 兼容旧版直接字符串缓存

    def _write_kv(self, key, data):
        if not self.cache_set or not data:
            return
        try:
            self.cache_set(key, json.dumps(data))
        except Exception:
            pass

    # ---------- JS/meta 跳转目标提取 ----------
    def _extract_jump_targets(self, html, base_url):
        if not html:
            return []
        out, seen = [], set()

        def _norm(u):
            try:
                u = unquote(str(u)).strip().strip('"\' ')
            except Exception:
                return ""
            if not u or u.startswith(("javascript:", "data:", "mailto:", "#")):
                return ""
            if u.startswith("//"):
                u = "https:" + u
            if not u.startswith("http"):
                u = urljoin(base_url or "", u)
            low = u.lower()
            if any(b in low for b in self.cfg.DOMAIN_BLACKLIST):
                return ""
            try:
                tld = urlparse(u).netloc.lower().split(".")[-1]
                if tld not in self.cfg.VALID_TLDS:
                    return ""
            except Exception:
                return ""
            if u.rstrip("/") == (base_url or "").rstrip("/"):
                return ""
            return u

        texts = [html]
        # base64 混淆脚本
        for m in re.finditer(r'["\']([A-Za-z0-9+/=]{40,})["\']', html):
            try:
                d = b64decode(m.group(1)).decode("utf-8", "ignore")
                if any(k in d for k in ("location", "url", "http")):
                    texts.append(d)
            except Exception:
                continue

        last_idx = len(self.JUMP_PATTERNS) - 1
        for t in texts:
            for i, pat in enumerate(self.JUMP_PATTERNS):
                for m in re.finditer(pat, t, re.I):
                    # 最后一条“变量赋值”容易误伤 HTML 属性，跳过标签内
                    if i == last_idx:
                        lt = t.rfind("<", 0, m.start())
                        gt = t.rfind(">", 0, m.start())
                        if lt > gt:
                            continue
                    u = _norm(m.group(1))
                    if u and u not in seen:
                        seen.add(u)
                        out.append(u)
            if len(t) < 3000 and ("location" in t or "refresh" in t):
                for m in re.finditer(r'["\'](https?://[^"\']{8,})["\']', t):
                    u = _norm(m.group(1))
                    if u and u not in seen:
                        seen.add(u)
                        out.append(u)
        return out[:5]

    # ---------- 跟随单条发布页跳转链 ----------
    def _crawl_one_publish(self, start_url):
        pages, visited = [], set()
        cur = start_url.rstrip("/") + "/"
        for _ in range(self.cfg.JUMP_MAX_HOPS + 1):
            if not cur or cur in visited:
                break
            visited.add(cur)
            r = self._fetch_safe(cur, self.cfg.PUBLISH_TIMEOUT)
            if r is None or r.status_code != 200:
                break
            html = r.text or ""
            final = self._final_host(r.url) or cur.rstrip("/")
            pages.append((final, html))
            targets = self._extract_jump_targets(html, final)
            if not targets:
                break
            cur = targets[0].rstrip("/") + "/"
        return pages

    # ---------- 从发布页提取候选域名 ----------
    def _extract_hosts(self, html):
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
            if h in self._publish_set:
                return
            if h in seen:
                return
            seen.add(h)
            hosts.append(h)

        # 策略1：HTML/JS 中的 http(s) 链接（<a>、script 字符串等）
        for m in re.finditer(r'https?://[^\s"\'<>()\[\]{},;]+', html):
            _add(m.group(0))
        # 策略2：base64 混淆脚本
        for m in re.finditer(r'["\']([A-Za-z0-9+/=]{80,})["\']', html):
            try:
                dec = b64decode(m.group(1)).decode("utf-8", "ignore")
                for u in re.finditer(r'https?://[^\s"\'<>()\[\]{},;]+', dec):
                    _add(u.group(0))
            except Exception:
                continue
        # 策略3：中文提示附近的裸域名
        for m in re.finditer(
            r'(?:新地址|新网址|永久地址|最新地址|最新域名|官方入口|请访问|访问地址|'
            r'线路[一二三四五六七八九十\d]+)'
            r'[：:\s]*((?:https?://)?[a-zA-Z0-9][a-zA-Z0-9.\-]{3,}\.[a-zA-Z]{2,10})',
            html
        ):
            u = m.group(1)
            if not u.startswith("http"):
                u = "https://" + u
            _add(u)
        # 策略4：裸域名扫描（限制前 6000 字符，避免噪音过多）
        for m in re.finditer(
            r'(?<![\w.\-])((?:[a-zA-Z0-9](?:[a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?\.)+[a-zA-Z]{2,10})'
            r'(?![\w.\-])',
            html[:6000]
        ):
            d = m.group(1).lower().strip('.')
            if d.split('.')[-1] not in self.cfg.VALID_TLDS:
                continue
            _add("https://" + d)
        return hosts[:20]

    # ---------- 站点有效性校验 ----------
    def _site_ok(self, html):
        if not html or len(html) < self.cfg.PROBE_MIN_HTML:
            return False
        low = html.lower()
        for m in ('just a moment', 'cf-browser-verification', 'checking your browser',
                  '__cf_chl_', 'ddos-guard', 'enable javascript and cookies',
                  '请开启 javascript', '请启用 javascript'):
            if m in low:
                return False
        has_article = (
            low.count("<article") >= 1
            or low.count("realtime-card") >= 1
            or low.count("video-card") >= 1
            or low.count("post-title") >= 1
            or low.count("entry-title") >= 1
        )
        return has_article or self.cfg.match_keyword(html)

    # ---------- 探测单个候选 ----------
    def _probe_one(self, url, timeout=None):
        r = self._fetch_safe(url, timeout or self.cfg.PROBE_TIMEOUT)
        if r is None or r.status_code != 200:
            return ""
        if not self._site_ok(r.text):
            return ""
        return self._final_host(r.url) or url.rstrip("/")

    # ---------- 并发探测（首个命中立即返回，未启动任务取消）----------
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

    # ---------- 并发抓发布页（含跟随跳转）----------
    def _crawl_publishes(self, urls):
        if not urls:
            return []
        hosts = []
        ex = ThreadPoolExecutor(max_workers=min(8, len(urls)))
        try:
            futs = {ex.submit(self._crawl_one_publish, u): u for u in urls}
            try:
                for f in as_completed(futs, timeout=self.cfg.PUBLISH_TIMEOUT * (self.cfg.JUMP_MAX_HOPS + 1) + 10):
                    try:
                        pages = f.result() or []
                    except Exception:
                        continue
                    if not pages:
                        continue
                    # 记录最后成功跳转的发布页（下次优先尝试）
                    self._write_kv(self.cfg.PUB_CACHE_KEY, {"pub": pages[-1][0]})
                    for _u, html in pages:
                        hosts.extend(self._extract_hosts(html))
            except Exception:
                pass
        finally:
            ex.shutdown(wait=False, cancel_futures=True)
        return hosts

    # ---------- 统一入口 ----------
    def resolve(self):
        # 1) HOST 缓存快速校验
        cached = self._read_kv(self.cfg.HOST_CACHE_KEY, "host")
        if cached and self._probe_one(cached.rstrip("/") + "/", self.cfg.FAST_TIMEOUT):
            return cached

        # 2) 最近一次成功跳转的发布页（加速路径）
        candidates = []
        pub_cached = self._read_kv(self.cfg.PUB_CACHE_KEY, "pub")
        if pub_cached:
            r = self._fetch_safe(pub_cached.rstrip("/") + "/", self.cfg.FAST_TIMEOUT)
            if r is not None and r.status_code == 200:
                candidates.extend(self._extract_hosts(r.text or ""))

        # 3) 一级导航发布页
        if not candidates:
            candidates = self._crawl_publishes(self.cfg.PUBLISH_URLS)

        # 4) 二级导航发布页兜底（针对 JS 混淆拿不到跳转目标的情况）
        if not candidates:
            candidates = self._crawl_publishes(self.cfg.PUBLISH_FALLBACK_AFTER_JUMP)

        # 5) 去重后并发探测
        uniq, seen = [], set()
        for h in candidates:
            h = h.rstrip("/")
            if h and h not in seen:
                seen.add(h)
                uniq.append(h)
        host = self._probe_hosts(uniq)
        if host:
            self._write_kv(self.cfg.HOST_CACHE_KEY, {"host": host})
            return host

        # 6) 全部失败时回退过期缓存
        return cached or ""


# ==================================================================
# ③ Spider 主体（业务层保留 51 系列原有逻辑）
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

    # ---------- 生命周期 ----------
    def init(self, extend=""):
        global img_cache
        img_cache.clear()
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
        return "🍉%s|发布页自愈版" % self.CONFIG.SITE_NAME

    def isVideoFormat(self, url):
        return any(e in (url or "") for e in (".m3u8", ".mp4", ".ts"))

    def manualVideoCheck(self):
        return False

    def destroy(self):
        global img_cache
        img_cache.clear()

    # ---------- 发布页自愈 ----------
    def get_working_host(self):
        resolver = PublishResolver(
            self.CONFIG, self._request,
            cache_get=getattr(self, "getCache", None),
            cache_set=getattr(self, "setCache", None),
        )
        return resolver.resolve()

    def _request(self, url, timeout=None, **kw):
        try:
            return requests.get(
                url, headers=self.headers, proxies=self.proxies,
                timeout=timeout or self.CONFIG.PROBE_TIMEOUT,
                verify=False, allow_redirects=True, **kw)
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
        for sel in ('.category-list ul li', '.nav-menu li', '.menu li', 'nav ul li'):
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
        return {"class": classes, "list": self.getlist(data("#index article, article"))}

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
            return {'list': [], 'page': 1, 'pagecount': 1, 'limit': 90, 'total': 0}
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
            url = ids[0] if ids[0].startswith('http') else f"{self.host}{ids[0]}"
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
                        video_url = json.loads(cfg_attr).get('video', {}).get('url', '')
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
        return [200, 'video/mp2t', res.content] if res is not None else [404, 'text/plain', b'']

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
            p_html = p_img.outer_html() if hasattr(p_img, 'outer_html') else str(p_img)
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
