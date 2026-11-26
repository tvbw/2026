# -*- coding: utf-8 -*-
"""
91吃瓜 · 快速直达 + 单导航兜底 + 多结构列表适配
=========================================================================
本版相对 v10 的优化：
- 【性能】移植"91网址跳转"的快速直达逻辑：
    * 缓存(6h)命中直接校验返回（秒级）
    * SEED_HOSTS(三级域名)并发探测，命中即返回（≤8s）
    * 仅当三级域名全灭时，抓一次 NAV_URL(导航页)提取新域名
    * 删除 v10 的多轮回溯 / 多入口并发解析 / 入口缓存 / base64域名解码
      / 兄弟域扫描 等慢路径逻辑，从 ~1分钟 降到 秒级
- 【域名分类（务必分清）】
    * SEED_HOSTS：三级域名（如 but.ybejhul.com / build.ovtrphyw.cc），
      是**内容站**，能直接打开主页
    * NAV_URL：导航/发布页域名（如 91cgb24.com），是**导航页**，
      仅用来查找新内容站域名，绝不做内容站使用
- 【保留】v10 的多结构列表选择器（.realtime-card / .video-card / ...）
- 【保留】懒加载图片属性识别 / AES 图片解密 / m3u8 代理 / 相关推荐聚合
=========================================================================
"""
import json
import re
import sys
import time
import base64
import hashlib
import logging
from urllib.parse import unquote, urlparse
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
        def delCache(self, k):    pass
        def getProxyUrl(self):    return ""

try:
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
except Exception:
    pass
LOG = logging.getLogger(__name__)


class Config:
    # ================== 站点身份 ==================
    SITE_NAME            = "91吃瓜"
    SITE_KEYWORDS        = ["91吃瓜", "91cg"]
    PLAY_FROM            = "91吃瓜"
    PLAY_FALLBACK_TITLE  = "91吃瓜"
    HOST_CACHE_KEY       = "cg91_host_v1"
    HOST_CACHE_TTL       = 6 * 3600

    # ================== 三级域名（内容站种子，并发探测命中即用）==================
    # 【这些是"三级域名"】能直接打开站点内容主页，是真正的业务站点
    # 与下面的 NAV_URL 严格区分：NAV_URL 是导航页，不是内容站
    SEED_HOSTS = [
        "https://d2w4b8lvgqly57.cloudfront.net/",
        "https://brain.crkhazah.cc/",
        "https://billion.crkhazah.cc/",
    ]
   
    # ================== 网址导航页（唯一一个，仅作兜底）==================
    # 【这是"导航/发布页域名"】不是内容站，只在三级域名全部失效时抓一次，
    # 用于提取新内容站域名；绝不做内容站使用，也不做多轮回溯
    NAV_URL = "https://www.ozkbkdqs.cc/"

    FALLBACK_HOST  = None

    # ================== 探测参数（精简，避免长延迟）==================
    FAST_TIMEOUT       = 6      # 缓存校验超时
    PROBE_TIMEOUT      = 8      # 新域名探测超时
    PROBE_MIN_HTML     = 2000   # 内容站 HTML 最小长度
    PROBE_MIN_ARTICLE  = 1      # 内容站最少内容卡片数

    # ================== 站点结构特征 ==================
    SITE_MARKERS = [
        "post-title", "entry-title", "<article", 'class="post',
        "realtime-card", "candid-video", "video-card",
    ]

    NAV_PAGE_KEYWORDS = (
        "线路一", "线路二", "线路三", "线路四", "线路五",
        "线路1", "线路2", "线路3",
        "推荐访问", "线路正常", "官方导航", "发布页", "备用线路",
        "地址发布页", "永久地址", "最新地址",
    )

    VALID_TLDS = {
        'com', 'net', 'org', 'cc', 'xyz', 'lol', 'vip', 'app', 'top', 'cn', 'co', 'io', 'me',
        'tv', 'club', 'site', 'online', 'info', 'biz', 'pro', 'link', 'live', 'shop', 'fun',
        'work', 'icu', 'life', 'world', 'store', 'tech', 'space', 'website', 'host',
        'pw', 'tk', 'ml', 'ga', 'cf', 'gq', 'su', 'ws', 'ly', 'to', 'st', 'in', 'tw',
        'hk', 'jp', 'kr', 'ru', 'us', 'uk', 'de', 'fr', 'nl', 'eu', 'au', 'ca', 'sg', 'my',
        'sbs', 'bet', 'cam', 'one', 'plus', 'now', 'today', 'pub', 'dev', 'cool', 'cloud',
    }

    DOMAIN_BLACKLIST = (
        'google', 'gstatic', 'googleusercontent', 'bing.com', 'baidu.com',
        'so.com', 'sogou.com', 'yandex', 'facebook', 'fbcdn', 'instagram',
        'twitter', 'twimg', 'youtube', 'ytimg', 't.me', 'telegram', 'whatsapp',
        'discord', 'reddit', 'tiktok', 'pinterest', 'apple.com', 'icloud',
        'microsoft', 'windows', 'amazonaws', 'cloudflare', 'cloudfront',
        'azureedge', 'github', 'gitlab', 'gitee', 'bitbucket', 'w3.org',
        'wikipedia', 'mozilla.org', 'stackoverflow', 'jsdelivr', 'unpkg',
        'bootstrapcdn', 'jquery', 'fontawesome', 'gmail', 'outlook', 'hotmail',
        'yahoo', 'protonmail', 'qq.com', '163.com', '126.com', 'sina.com',
        'weibo.com', 'statcounter', 'google-analytics', 'umeng', 'cnzz',
        'beian.miit.gov.cn', 'wordpress.org', 'wix.com', 'weebly', 'shopify',
        '51.la', 'cnzz.com', '51yes', 'addthis', 'sharethis',
    )

    EXTRA_BLACKLIST = ('beian.miit.gov.cn', 'w3.org', 'example.com')

    # ================== 列表选择器（v10 多结构适配）==================
    SEL_ARTICLE      = (
        "#index article, #archive article, article, "
        ".realtime-card, .video-card, .video-item, .post-item, .card-item"
    )
    SEL_ARTICLE_HOME = (
        "#index article, article, "
        ".realtime-card, .video-card, .video-item, .post-item, .card-item"
    )
    SEL_PLAYER       = ".dplayer"
    SEL_CONTENT      = ".post-content, article, .realtime-content"
    SEL_TAGS         = ".post-tags a, .tags a, .keywords a"
    SEL_SUMMARY      = ".post-content"
    SEL_TITLE        = ".post-title, h1"

    SEL_NAV = [
        "ul.navbar-nav.mr-auto > li.nav-item > a.nav-link",
        "ul.navbar-nav > li.nav-item > a.nav-link",
        "ul.navbar-nav li a.nav-link",
        "#navbarCollapse a.nav-link",
        ".navbar-nav a.nav-link",
        ".realtime-tabs a",
        ".category-tabs a",
        ".category-list ul li",
        ".nav-menu li",
        ".menu li",
        ".tabs a",
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
        "点击观看", "点击播放", "点击进入", "进入观看", "前往观看",
        "观看", "播放", "视频", "立即观看", "在线观看", "在线播放",
        "完整版", "高清",
        "第一弹", "第二弹", "第三弹", "第四弹", "第五弹",
        "第六弹", "第七弹", "第八弹", "第九弹", "第十弹",
        "第1集", "第2集", "第3集", "第4集", "第5集",
        "第6集", "第7集", "第8集", "第9集", "第10集",
        "第1话", "第2话", "第3话", "第4话", "第5话",
        "episode", "watch", "play", "full",
    )

    LINK_URL_PATTERNS = (
        r"/vodplay/", r"/vodplay\b", r"/v/\d+", r"/play/",
        r"/video/", r"/watch/", r"/player/", r"\.m3u8",
    )

    IMG_AES_KEYS = [
        (b"f5d965df75336270", b"97b60394abc2fbe1"),
        (b"75336270f5d965df", b"abc2fbe197b60394"),
    ]

    HEADERS = {
        "User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                       "AppleWebKit/537.36 (KHTML, like Gecko) "
                       "Chrome/120.0.0.0 Safari/537.36"),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
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
# ② 快速直达域名解析器（参考"91网址跳转"版 resolve()）
# ==================================================================
class DomainResolver:
    """快速直达域名解析：
    1) 缓存有效 → 校验后直接返回（秒级）
    2) 并发探测 SEED_HOSTS（三级域名），命中即返回（≤ PROBE_TIMEOUT）
    3) 全部失败 → 抓一次 NAV_URL（导航页）提取新域名 → 并发探测一次
    4) 都失败 → 回退 SEED_HOSTS[0]
    不做多轮回溯、不做复杂入口页解析，避免 1 分钟级延迟。
    """

    SKIP_HREF = (
        '.js', '.css', '.jpg', '.jpeg', '.png', '.gif', '.webp', '.svg', '.ico',
        '.woff', '.woff2', '.ttf', '.eot', '.map', 'mailto:', 'javascript:', 'tel:',
        '/sese.html', '/ybml.html', '/qun.html', '/github.html', '/telegram.html',
        '/about.html', '/contact.html', 'mrds1.app',
    )

    def __init__(self, cfg, fetcher, cache_get=None, cache_set=None):
        self.cfg = cfg
        self.fetch = fetcher
        self.cache_get = cache_get
        self.cache_set = cache_set

    # -------------------- 基础 --------------------
    def _safe_fetch(self, url, timeout):
        try:
            return self.fetch(url, timeout=timeout)
        except Exception as e:
            LOG.debug("fetch 异常 %s: %s", url, e)
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

    # -------------------- 页面判定 --------------------
    def _is_blocked_page(self, html):
        if not html:
            return False
        low = html.lower()
        markers = (
            'just a moment', 'cf-browser-verification', 'cf-challenge',
            'checking your browser', '__cf_chl_', 'ddos-guard',
            'cf-ray', 'cloudflare-nginx', 'enable javascript and cookies',
            '请开启 javascript', '请启用 javascript', '请稍候',
        )
        if any(m in low for m in markers):
            return True
        if len(html) < 1500 and '<script' in low and 'body' in low:
            return True
        return False

    def _is_nav_page(self, html):
        if not html:
            return False
        if 'data-base=' in html and 'id="list-wrap"' in html:
            return True
        low = html.lower()
        if (low.count("<article") >= 1
                or low.count('class="post') >= 3
                or low.count('realtime-card') >= 2
                or low.count('video-card') >= 2):
            return False
        hits = sum(1 for kw in self.cfg.NAV_PAGE_KEYWORDS if kw in html)
        return hits >= 3

    def _site_ok(self, html):
        if not html or len(html) < self.cfg.PROBE_MIN_HTML:
            return False
        if self._is_blocked_page(html):
            return False
        if self._is_nav_page(html):
            return False
        low = html.lower()
        has_article = (low.count("<article") >= self.cfg.PROBE_MIN_ARTICLE
                       or low.count("realtime-card") >= self.cfg.PROBE_MIN_ARTICLE
                       or low.count("video-card") >= self.cfg.PROBE_MIN_ARTICLE)
        has_marker = any(m in low for m in self.cfg.SITE_MARKERS)
        has_keyword = self.cfg.match_keyword(html)
        return has_article or has_marker or has_keyword

    # -------------------- 并发探测 --------------------
    def _probe_hosts(self, urls, tag="探测"):
        """并发探测一批 URL，返回第一个命中的最终 host（跟随 302）"""
        if not urls:
            return ""
        urls = [u.rstrip("/") + "/" for u in urls if u]
        if not urls:
            return ""
        try:
            with ThreadPoolExecutor(max_workers=min(8, len(urls))) as ex:
                futs = {ex.submit(self._safe_fetch, u, self.cfg.PROBE_TIMEOUT): u
                        for u in urls}
                for f in as_completed(futs, timeout=self.cfg.PROBE_TIMEOUT + 6):
                    u = futs[f]
                    try:
                        r = f.result()
                    except Exception as e:
                        print(f"  [{tag}] {u} 异常: {e}")
                        continue
                    if r is None:
                        print(f"  [{tag}] {u} 无响应")
                        continue
                    if r.status_code != 200:
                        print(f"  [{tag}] {u} HTTP={r.status_code}")
                        continue
                    if not self._site_ok(r.text):
                        print(f"  [{tag}] {u} 内容不匹配 (len={len(r.text or '')})")
                        continue
                    final = self._final_host(r.url) or u.rstrip("/")
                    print(f"  [{tag}] {u} → {final} 命中")
                    return final
        except Exception as e:
            LOG.debug("%s 并发异常: %s", tag, e)
        return ""

    # -------------------- 导航页提取（轻量版）--------------------
    def _extract_new_hosts(self, html):
        """从导航页 HTML 中提取内容站域名候选（简化版，无多轮回溯）"""
        if not html:
            return []
        nav_host = self._final_host(self.cfg.NAV_URL).rstrip("/")
        hosts, seen = [], set()

        def _add(h):
            h = self._final_host(h).rstrip("/")
            if not h or h == nav_host:
                return
            hl = h.lower()
            if any(bl in hl for bl in self.cfg.DOMAIN_BLACKLIST):
                return
            if any(bl in hl for bl in getattr(self.cfg, "EXTRA_BLACKLIST", ())):
                return
            if h in seen:
                return
            seen.add(h)
            hosts.append(h)

        # 1) 显式 <a href="https://..."> 链接
        for m in re.finditer(r'<a\b[^>]+href="(https?://[^"]+)"[^>]*>', html):
            href = m.group(1)
            if any(skip in href for skip in self.SKIP_HREF):
                continue
            _add(href)

        # 2) JS 跳转
        for pat in (
            r'''location(?:\.href)?\s*=\s*["'](https?://[^"']+)["']''',
            r'''location\.(?:replace|assign)\(\s*["'](https?://[^"']+)["']''',
            r'''window\.open\(\s*["'](https?://[^"']+)["']''',
        ):
            for m in re.finditer(pat, html):
                _add(m.group(1))

        # 3) 中文提示附近的域名
        for m in re.finditer(
            r'(?:新地址|新网址|永久地址|最新地址|最新域名|官方入口|请访问|访问地址|线路[一二三四五六七八九十\d]+)'
            r'[：:\s]*((?:https?://)?[a-zA-Z0-9][a-zA-Z0-9.\-]{3,}\.[a-zA-Z]{2,10})',
            html
        ):
            u = m.group(1)
            if not u.startswith("http"):
                u = "https://" + u
            _add(u)

        # 4) 裸域名扫描（严格 TLD + 黑名单过滤）
        for m in re.finditer(
            r'(?<![\w.\-])((?:[a-zA-Z0-9](?:[a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?\.)+[a-zA-Z]{2,10})(?![\w.\-])',
            html
        ):
            d = m.group(1).lower().strip('.')
            parts = d.split(".")
            if len(parts) < 2 or parts[-1] not in self.cfg.VALID_TLDS:
                continue
            _add("https://" + d)

        return hosts[:15]

    # -------------------- 缓存 --------------------
    def _read_cache(self):
        if not self.cache_get:
            return ""
        try:
            raw = self.cache_get(self.cfg.HOST_CACHE_KEY)
        except Exception:
            return ""
        if not raw:
            return ""
        if isinstance(raw, str):
            s = raw.strip()
            if s.startswith("http"):
                return s.rstrip("/")
            try:
                d = json.loads(s)
                if isinstance(d, dict):
                    return str(d.get("host") or "").rstrip("/")
            except Exception:
                return ""
        return ""

    def _write_cache(self, host):
        if not self.cache_set or not host:
            return
        try:
            self.cache_set(self.cfg.HOST_CACHE_KEY,
                           json.dumps({"host": host, "ts": int(time.time())}))
        except Exception:
            pass

    # -------------------- 主入口 --------------------
    def resolve(self):
        # 1) 缓存命中 → 校验返回
        cached = self._read_cache()
        if cached:
            r = self._safe_fetch(cached + "/", self.cfg.FAST_TIMEOUT)
            if r is not None and r.status_code == 200 and self._site_ok(r.text):
                final = self._final_host(r.url) or cached
                print(f"缓存有效: {cached}" + (f" → {final}" if final != cached else ""))
                if final != cached:
                    self._write_cache(final)
                return final
            print(f"缓存失效: {cached}")

        # 2) 并发探测三级域名（SEED_HOSTS = 内容站）
        print(f"[快速直达] 并发探测三级域名 x{len(self.cfg.SEED_HOSTS)} ...")
        final = self._probe_hosts(self.cfg.SEED_HOSTS, tag="三级域名")
        if final:
            self._write_cache(final)
            return final

        # 3) 导航页兜底（NAV_URL = 导航/发布页，只抓一次）
        nav = (self.cfg.NAV_URL or "").rstrip("/")
        if nav:
            print(f"[导航兜底] 三级域名全部失效，抓取导航页: {nav}")
            r = self._safe_fetch(nav + "/", self.cfg.PROBE_TIMEOUT)
            if r is not None and r.status_code == 200:
                new_hosts = self._extract_new_hosts(r.text or "")
                print(f"[导航兜底] 提取到 {len(new_hosts)} 个候选: {new_hosts[:5]}")
                if new_hosts:
                    final = self._probe_hosts(new_hosts, tag="导航候选")
                    if final:
                        self._write_cache(final)
                        return final
            else:
                print(f"[导航兜底] 抓取失败: {nav}")

        # 4) 回退
        fb = (self.cfg.FALLBACK_HOST or
              (self.cfg.SEED_HOSTS[0] if self.cfg.SEED_HOSTS else "")).rstrip("/")
        if fb:
            print(f"【警告】全部失败，回退: {fb}")
        return fb


# ==================================================================
# ③ 主爬虫
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
        self._img_cache = {}
        self._page_cache = {}
        self._page_index = {}
        self._page_keys = []
        self._detail_cache = {}

    def init(self, extend=""):
        self._img_cache = {}
        self._page_cache = {}
        self._page_index = {}
        self._page_keys = []
        self._detail_cache = {}
        self.proxies = {}

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

        self.headers = dict(self.CONFIG.HEADERS)

        manual = ""
        if isinstance(raw_extend, dict):
            manual = raw_extend.get("host", "") or ""
        if not manual and isinstance(extend, str) and extend.strip().startswith("http"):
            manual = extend.strip()

        if manual:
            manual = manual.strip().rstrip("/")
            if not manual.startswith("http"):
                manual = "https://" + manual
            print(f"【extend 指定】使用域名: {manual}")
            self.host = manual
        else:
            self.host = self.get_working_host()

        if self.host:
            self.headers.update({"Origin": self.host, "Referer": self.host + "/"})
        print(f"使用站点: {self.host}")

    def getName(self):
        return "🍉%s|快速直达版" % self.CONFIG.SITE_NAME

    def isVideoFormat(self, url):
        return any(ext in (url or "") for ext in (".m3u8", ".mp4", ".ts"))

    def manualVideoCheck(self):
        return False

    def destroy(self):
        self._img_cache.clear()
        self._page_cache.clear()
        self._page_index.clear()
        self._page_keys.clear()
        self._detail_cache.clear()

    # -------------------- 基础请求 --------------------
    def _request(self, url, timeout=None, **kw):
        try:
            return requests.get(
                url, headers=self.headers, proxies=self.proxies,
                timeout=timeout or self.CONFIG.PROBE_TIMEOUT,
                verify=False, allow_redirects=True, **kw)
        except Exception as e:
            LOG.debug("GET 异常 %s: %s", url, e)
            return None

    def _soup(self, url, timeout=None):
        r = self._request(url, timeout=timeout)
        if r is None or r.status_code != 200:
            return None
        try:
            return self.getpq(r.text)
        except Exception:
            return None

    @staticmethod
    def getpq(data):
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

    # -------------------- host 解析（极简：委托给 DomainResolver）--------------------
    def get_working_host(self):
        resolver = DomainResolver(
            self.CONFIG, self._request,
            cache_get=getattr(self, "getCache", None),
            cache_set=getattr(self, "setCache", None),
        )
        return resolver.resolve()

    # -------------------- 页面级缓存 --------------------
    def _cache_items(self, key, items):
        out = [x for x in (items or []) if isinstance(x, dict) and x.get("vod_id")]
        if not out:
            return
        self._page_cache[key] = out
        if key in self._page_keys:
            self._page_keys.remove(key)
        self._page_keys.append(key)
        for it in out:
            self._page_index[str(it["vod_id"])] = key
        while len(self._page_keys) > 30:
            self._page_cache.pop(self._page_keys.pop(0), None)

    def _items_of(self, vid):
        key = self._page_index.get(str(vid))
        if key is None or key not in self._page_cache:
            return []
        return list(self._page_cache.get(key, []))

    @staticmethod
    def _encode_nid(vid):
        try:
            return base64.b64encode(str(vid).encode("utf-8")).decode("ascii").rstrip("=")
        except Exception:
            return ""

    @staticmethod
    def _decode_nid(s):
        s = str(s or "")
        if s.startswith("nid:"):
            s = s[4:]
        if not s:
            return ""
        pad = "=" * (-len(s) % 4)
        try:
            return base64.b64decode(s + pad).decode("utf-8", "ignore")
        except Exception:
            return ""

    # -------------------- 首页 / 分类 --------------------
    def homeContent(self, filter=False):
        if not self.host:
            return {"class": [], "list": []}
        data = self._soup(self.host + "/")
        if data is None:
            print(f"[homeContent] 抓取 {self.host} 失败")
            return {"class": [], "list": []}
        lst = self._getlist(data(self.CONFIG.SEL_ARTICLE_HOME))
        if lst:
            self._cache_items(("home",), lst)
        if not lst:
            print(f"[homeContent] 列表解析为空，检查 SEL_ARTICLE_HOME")
        return {"class": self._parse_classes(data), "list": lst}

    def homeVideoContent(self):
        if not self.host:
            return {"list": []}
        data = self._soup(self.host + "/")
        if data is None:
            return {"list": []}
        lst = self._getlist(data(self.CONFIG.SEL_ARTICLE_HOME))
        if lst:
            self._cache_items(("homev",), lst)
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
            hit = False
            try:
                for k in data(sel).items():
                    a = k if k.is_("a") else k("a").eq(0)
                    _add(a.attr("href"), a.text())
                    hit = True
            except Exception:
                continue
            if hit and classes:
                break

        if not classes:
            for sel in self.CONFIG.SEL_SUB_NAV:
                hit = False
                try:
                    for a in data(sel).items():
                        _add(a.attr("href"), a.attr("title") or a.text())
                        hit = True
                except Exception:
                    continue
                if hit:
                    break

        if not classes:
            classes = [dict(self.CONFIG.DEFAULT_CATEGORY)]
        return classes

    def _build_page_url(self, tid, pg):
        tid = str(tid or "/")
        if tid.startswith("http"):
            base = tid.rstrip("/")
        else:
            base = self._abs(tid).rstrip("/")

        if pg <= 1:
            return base + "/"

        host_ns = self.host.rstrip("/")
        if base == host_ns:
            return "%s/page/%d/" % (host_ns, pg)

        if "/category/" in base or "/tag/" in base:
            if "/page/" in base:
                base = base.split("/page/")[0]
            return "%s/%d/" % (base, pg)

        if "/page/" in base:
            base = base.split("/page/")[0]
            return "%s/page/%d/" % (base, pg)

        return "%s/page/%d/" % (base, pg)

    def categoryContent(self, tid, pg=1, filter=False, extend=None):
        try:
            pg = int(pg or 1)
        except Exception:
            pg = 1

        if not self.host:
            return {"list": [], "page": pg, "pagecount": 1, "limit": 90, "total": 0}

        tid = str(tid or "/")
        if "@folder" in tid:
            v = self._getfod(tid.replace("@folder", ""))
            return {"list": v, "page": 1, "pagecount": 1, "limit": 90, "total": len(v)}

        url = self._build_page_url(tid, pg)
        data = self._soup(url)
        if data is None:
            print(f"[categoryContent] 抓取失败: {url}")
            return {"list": [], "page": pg, "pagecount": 9999, "limit": 90, "total": 0}

        lst = self._getlist(data(self.CONFIG.SEL_ARTICLE), tid)
        if lst:
            self._cache_items(("cate", tid, str(pg)), lst)
        else:
            print(f"[categoryContent] 列表为空: {url} 检查 SEL_ARTICLE 或页面结构")
        return {"list": lst, "page": pg, "pagecount": 9999, "limit": 90, "total": 999999}

    # -------------------- 列表 --------------------
    def _getlist(self, data, tid=""):
        videos, seen = [], set()
        is_folder = "/mrdg" in (tid or "")

        for k in data.items():
            a = k if k.is_("a") else k("a").eq(0)
            href = ((a.attr("href") if a else "") or k.attr("href") or "").strip()
            if not href or href in ("#", "javascript:;", "javascript:void(0)"):
                continue

            title = ""
            for src_elem in (a, k):
                if not src_elem:
                    continue
                for attr in ("aria-label", "title", "data-title"):
                    v = (src_elem.attr(attr) or "").strip()
                    if v:
                        title = v
                        break
                if title:
                    break
                img_alt = (src_elem("img").attr("alt") or "").strip()
                if img_alt:
                    title = img_alt
                    break
            if not title:
                title = (k("h2").text() or k(".entry-title").text()
                         or k(".post-title").text() or "").strip()
            if not title and k.is_("a"):
                title = (k.text() or "").strip()
            if not title and a and a.is_("a"):
                title = (a.text() or "").strip()

            if not title:
                continue

            vid = "%s%s" % (href, "@folder" if is_folder else "")
            if vid in seen:
                continue
            seen.add(vid)

            remark = ""
            try:
                remark = (k("time").text() or "").strip()
            except Exception:
                remark = ""
            if not remark:
                remark = self._parse_date(k)

            videos.append({
                "vod_id": vid,
                "vod_name": title,
                "vod_pic": self._extract_img(k),
                "vod_remarks": remark,
                "vod_tag": "folder" if is_folder else "",
                "style": {"type": "rect", "ratio": 1.33},
            })
        return videos

    def _getfod(self, id):
        data = self._soup(self._abs(id))
        if data is None:
            return []
        out = []
        try:
            for i, h2 in enumerate(data(".post-content h2").items()):
                p_txt = data(".post-content p").eq(i * 2)
                p_img = data(".post-content p").eq(i * 2 + 1)
                href = p_txt("a").attr("href")
                if not href:
                    continue
                out.append({
                    "vod_id": href,
                    "vod_name": (p_txt.text() or "").strip(),
                    "vod_pic": self._extract_img(p_img),
                    "vod_remarks": (h2.text() or "").strip(),
                })
        except Exception as e:
            LOG.debug("目录解析异常: %s", e)
        return out

    # -------------------- 详情 --------------------
    def _raw_detail(self, vid):
        vid = str(vid or "")
        if vid.endswith("@folder"):
            vid = vid[:-7]
        url = self._abs(vid)
        data = self._soup(url)
        if data is None:
            print(f"[detail] 抓取失败: {url}")
            return [], "", url
        playlist = self._extract_playlist(data)
        content = self._extract_content(data) or self.CONFIG.PLAY_FALLBACK_TITLE
        return playlist, content, url

    def _raw_detail_cached(self, vid):
        key = str(vid or "")
        if key in self._detail_cache:
            return self._detail_cache[key]
        result = self._raw_detail(key)
        self._detail_cache[key] = result
        while len(self._detail_cache) > 60:
            first = next(iter(self._detail_cache))
            self._detail_cache.pop(first, None)
        return result

    def detailContent(self, ids):
        orig_vid = str(ids[0] if isinstance(ids, (list, tuple)) else ids)
        if not self.host:
            return {"list": [{"vod_play_from": self.CONFIG.PLAY_FROM,
                              "vod_play_url": "获取失败"}]}

        vid = orig_vid
        if vid.startswith("nid:"):
            decoded = self._decode_nid(vid)
            if decoded:
                vid = decoded
                orig_vid = decoded

        playlist, content, url = self._raw_detail_cached(vid)

        related = self._items_of(orig_vid)
        if related:
            play_url = self._build_playlist_with_related(orig_vid, playlist, related)
        else:
            play_url = "#".join(playlist) or ("未找到视频源，请访问网页$" + url)

        return {"list": [{
            "vod_play_from": self.CONFIG.PLAY_FROM,
            "vod_play_url":  play_url,
            "vod_content":   content,
        }]}

    def _build_playlist_with_related(self, vid, own_playlist, related):
        parts, used = [], set()
        for p in (own_playlist or []):
            name = (p.split("$", 1)[0] if "$" in p else p).strip()
            if not name or name in used:
                continue
            used.add(name)
            parts.append(p)

        if not parts:
            cur_name = ""
            for it in related:
                if str(it.get("vod_id")) == str(vid):
                    cur_name = self._clean(it.get("vod_name") or "")
                    break
            cur_name = cur_name or "正片"
            parts.append("%s$nid:%s" % (cur_name, self._encode_nid(vid)))
            used.add(cur_name)

        for it in related:
            iid = str(it.get("vod_id") or "")
            if not iid or iid == str(vid):
                continue
            name = self._clean(it.get("vod_name") or iid) or iid
            if not name or name in used:
                continue
            used.add(name)
            parts.append("%s$nid:%s" % (name, self._encode_nid(iid)))
        return "#".join(parts)

    # -------------------- 播放源 --------------------
    def _extract_playlist(self, data):
        try:
            if data(self.CONFIG.SEL_PLAYER):
                pl = self._from_dplayer(data)
                if pl:
                    return pl
        except Exception:
            pass
        return self._from_links(data)

    def _from_dplayer(self, data):
        out, used = [], set()
        try:
            items = list(data(self.CONFIG.SEL_PLAYER).items())
        except Exception:
            return out
        for i, k in enumerate(items, 1):
            try:
                cfg = json.loads(k.attr("data-config") or "{}")
                url = (cfg.get("video") or {}).get("url", "")
                if not url:
                    continue
                base = self._near_heading(k) or ("视频%d" % i)
                out.append("%s$%s" % (self._unique(self._clean(base), used), url))
            except Exception:
                continue
        return out

    def _from_links(self, data):
        out, used = [], set()
        try:
            links = list(data(self.CONFIG.SEL_CONTENT)("a").items())
        except Exception:
            return out
        for i, link in enumerate(links, 1):
            txt = (link.text() or "").strip()
            href = link.attr("href")
            if not href:
                continue
            hit_text = any(kw in txt for kw in self.CONFIG.LINK_KEYWORDS)
            hit_url = any(re.search(p, href, re.I)
                          for p in self.CONFIG.LINK_URL_PATTERNS)
            if not (hit_text or hit_url):
                continue
            name = txt.replace("点击观看：", "").replace("点击观看", "").strip()
            name = self._clean(name) or ("视频%d" % i)
            out.append("%s$%s" % (self._unique(name, used), self._abs(href)))
        return out

    @staticmethod
    def _clean(s):
        return str(s or "").replace("$", " ").replace("#", " ").strip()

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
    def _near_heading(k, levels=4):
        try:
            p = k.parents().eq(0)
        except Exception:
            return ""
        for _ in range(levels):
            if not p:
                break
            h = (p.find("h2, h3, h4").eq(0).text() or "").strip()
            if h:
                return h
            p = p.parents().eq(0)
        return ""

    def _extract_content(self, data):
        tags, seen = [], set()
        try:
            for k in data(self.CONFIG.SEL_TAGS).items():
                t = (k.text() or "").strip()
                h = k.attr("href")
                if not t or not h or t in seen:
                    continue
                seen.add(t)
                target = json.dumps({"id": h, "name": t})
                tags.append("[a=cr:%s/]%s[/a]" % (target, t))
        except Exception:
            pass

        if tags:
            try:
                summary = (data(self.CONFIG.SEL_SUMMARY).text() or "")[:150].strip()
            except Exception:
                summary = ""
            return " ".join(tags) + (("\n\n" + summary) if summary else "")

        try:
            return (data(self.CONFIG.SEL_TITLE).text() or "").strip()
        except Exception:
            return ""

    # -------------------- 图片 / 日期 --------------------
    def _parse_date(self, k):
        try:
            t = k("time").text()
        except Exception:
            t = ""
        if t:
            return t.strip()
        try:
            full = k.text() or ""
        except Exception:
            full = ""
        m = re.search(r"(\d{4}\s*年\s*\d{1,2}\s*月\s*\d{1,2}\s*日)", full)
        if not m:
            m = re.search(r"(\d{4}-\d{1,2}-\d{1,2})", full)
        return m.group(1) if m else ""

    def _extract_img(self, elem):
        if elem is None:
            return ""

        try:
            text = elem("script").text() or ""
        except Exception:
            text = ""
        if m := re.search(r"loadBannerDirect\('([^']+)'", text):
            return self._proc_url(m.group(1))

        img = elem if elem.is_("img") else elem("img").eq(0)
        if img:
            for attr in ("data-xkrkllgl", "data-src", "data-original",
                         "data-lazy-src", "data-echo", "data-url"):
                v = img.attr(attr)
                if v and not str(v).startswith("data:"):
                    return self._proc_url(v)

            v = img.attr("src")
            if v and str(v).startswith("data:"):
                return self._proc_url(v)
            if v and not str(v).startswith("data:"):
                return self._proc_url(v)

        try:
            html = elem.outer_html() if hasattr(elem, "outer_html") else str(elem)
        except Exception:
            html = str(elem or "")
        html = (html.replace("&quot;", '"')
                    .replace("&apos;", "'")
                    .replace("&amp;", "&"))

        m = re.search(r'(https?://[^"\'\s)]+\.(?:jpg|png|jpeg|webp|gif))', html, re.I)
        if m:
            return self._proc_url(m.group(1))

        m = re.search(r"(data:image/[a-zA-Z0-9+/=;,]+)", html)
        if m:
            return self._proc_url(m.group(1))

        m = re.search(r'url\s*\(\s*[\'"]?([^"\'\)]+)[\'"]?\s*\)', html, re.I)
        if m:
            return self._proc_url(m.group(1))
        return ""

    def _proc_url(self, url):
        if not url:
            return ""
        url = str(url).strip("'\" ")
        if url.startswith("data:"):
            try:
                _, b64s = url.split(",", 1)
                raw = base64.b64decode(b64s)
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
        return (b.startswith(b"\xff\xd8")
                or b.startswith(b"\x89PNG")
                or b.startswith(b"GIF8"))

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

    # -------------------- 搜索 --------------------
    def searchContent(self, key, quick=False, pg=1):
        try:
            pg = int(pg or 1)
        except Exception:
            pg = 1
        if not self.host:
            return {"list": [], "page": pg, "pagecount": 9999}

        url = ("%s/search/%s/" % (self.host, key) if pg <= 1
               else "%s/search/%s/%d/" % (self.host, key, pg))
        data = self._soup(url)
        if data is None:
            print(f"[searchContent] 抓取失败: {url}")
            return {"list": [], "page": pg, "pagecount": 9999}
        lst = self._getlist(data("article, .realtime-card, .video-card, .video-item"))
        if lst:
            self._cache_items(("search", str(key), str(pg)), lst)
        return {"list": lst, "page": pg, "pagecount": 9999}

    # -------------------- 播放 / 代理 --------------------
    def playerContent(self, flag, id, vipFlags=None):
        s = str(id or "")

        if s.startswith("nid:"):
            vid = self._decode_nid(s)
            if not vid:
                return {"parse": 0, "url": "", "header": self.headers}
            playlist, _content, url = self._raw_detail_cached(vid)
            real = ""
            if playlist:
                p0 = playlist[0]
                real = p0.split("$", 1)[1] if "$" in p0 else p0
            if not real:
                real = url
            s = real

        parse = 0 if self.isVideoFormat(s) else 1
        final = self.proxy(s) if ".m3u8" in s else s
        return {"parse": parse, "url": final, "header": self.headers}

    def proxy(self, data, kind="m3u8"):
        if data and self.proxies:
            return "%s&url=%s&type=%s" % (self.getProxyUrl(), self.e64(data), kind)
        return data

    def localProxy(self, param):
        try:
            param = param or {}
            t = param.get("type")

            if t == "cache":
                d = self._img_cache.get(param.get("key"))
                return [200, "image/jpeg", d] if d else [404, "text/plain", b"Expired"]

            if t == "img":
                raw = param.get("url") or ""
                real = raw if raw.startswith("http") else self.d64(raw)
                res = self._request(real, timeout=10)
                if res is None:
                    return [404, "text/plain", b""]
                return [200, "image/jpeg", self.aesimg(res.content)]

            if t == "m3u8":
                return self.m3Proxy(param.get("url"))

            if t == "mkey":
                raw = param.get("url") or ""
                real = raw if raw.startswith("http") else self.d64(raw)
                res = self._request(real, timeout=10)
                return ([200, "application/octet-stream", res.content]
                        if res is not None else [404, "text/plain", b""])

            return self.tsProxy(param.get("url"))
        except Exception:
            return [404, "text/plain", b""]

    def m3Proxy(self, url):
        real = url if str(url).startswith("http") else self.d64(url)
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
                                      'URI="%s"' % self.proxy(m.group(1), "mkey"),
                                      line))
                    iskey = False
                    continue
            if "#EXT" not in line and line.strip():
                if not line.startswith("http"):
                    line = "%s/%s" % (base, line)
                out.append(self.proxy(line, "ts"))
            else:
                out.append(line)
        return [200, "application/vnd.apple.mpegurl", "\n".join(out)]

    def tsProxy(self, url):
        real = url if str(url).startswith("http") else self.d64(url)
        res = self._request(real)
        return [200, "video/mp2t", res.content] if res is not None else [404, "text/plain", b""]

    @staticmethod
    def e64(s):
        return base64.b64encode(str(s).encode()).decode()

    @staticmethod
    def d64(s):
        return base64.b64decode(str(s).encode()).decode()
