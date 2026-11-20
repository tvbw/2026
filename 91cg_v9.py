# -*- coding: utf-8 -*-
"""
91吃瓜 · 快速跳转 + 自愈抓取 + 分类全量发现 + 实时监控多结构适配
=========================================================================
本版针对"一级目录 + 二级平铺目录漏抓"的修复：
- 【核心】_parse_classes 遍历所有 SEL_NAV 全部合并（不再命中即 break）
        此前"命中即 break"会漏掉非 .nav-link 类的二级嵌套分类
- 【新增】_scan_category_links 兜底扫描首页所有 /category/* /tag/* 链接
- 【新增】_parse_category_overview 访问 /category/ 总览页补充完整分类
- 【增强】_augment_with_filters 处理全部一级分类（不再限制前 8 个）
- 【保留】实时监控页 .realtime-card 多结构解析 / data-xkrkllgl 懒加载图
- 【保留】播放相关推荐聚合 / 快慢路径域名自愈
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


# ==================================================================
# ① 配置
# ==================================================================
class Config:
    SITE_NAME            = "91吃瓜1"
    SITE_KEYWORDS        = ["91吃瓜1"]
    PLAY_FROM            = "91吃瓜1"
    PLAY_FALLBACK_TITLE  = "91吃瓜1"
    HOST_CACHE_KEY       = "cg91_host_v10"
    CLASS_CACHE_KEY      = "cg91_classes_v10"
    CLASS_CACHE_TTL      = 3600

    FAST_HOSTS = [
        "https://but.ybejhul.com/",
        "https://adopt.ybejhul.com/",
        "https://d2w4b8lvgqly57.cloudfront.net/",
        "https://build.ovtrphyw.cc/",
        "https://boss.ovtrphyw.cc/",
    ]
    PUBLISH_URLS = [
        "https://www.mgrhlgof.cc/",
        "https://91cgb24.com/",
        "https://91cgb20.com/",
        "https://91cgb23.com/",
        "https://91cgb21.com/",
        "https://91cgb22.com/",
    ]

    SEED_HOSTS = [
        "https://but.ybejhul.com/",
        "https://adopt.ybejhul.com/",
        "https://d2w4b8lvgqly57.cloudfront.net/",
        "https://build.ovtrphyw.cc/",
        "https://boss.ovtrphyw.cc/",
        "https://91cgb24.com/",
        "https://91cgb20.com/",
    ]

    FALLBACK_HOST  = None
    HOST_CACHE_TTL = 6 * 3600

    FAST_TIMEOUT         = 15
    PROBE_TIMEOUT        = 20
    PROBE_MIN_HTML       = 2000
    PROBE_MIN_ARTICLE    = 1
    PROBE_MAX_ROUNDS     = 2
    PROBE_MAX_CANDIDATES = 30
    ENTRY_CACHE_TTL      = 1800

    FILTER_PROBE_TIMEOUT = 10   # 单个分类页抓筛选栏的超时
    FILTER_TOTAL_TIMEOUT = 30     # 全部一级分类的总超时（并发）

    SITE_MARKERS = [
        "post-title", "entry-title", "<article", 'class="post',
        "realtime-card", "candid-video", "video-card", "post-card",
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

    SEL_ARTICLE = (
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

    # 首页导航 - 遍历所有选择器合并（不再命中即 break）
    SEL_NAV = [
        # 抓全类：优先放前面，li 能覆盖嵌套子分类
        ".nav-menu li",
        ".nav-menu a",
        ".menu li",
        ".menu a",
        ".category-list ul li",
        ".category-list a",
        "nav ul li",
        "nav a",
        "header nav a",
        ".navbar-nav a.nav-link",
        "#navbarCollapse a.nav-link",
        "ul.navbar-nav li a.nav-link",
        "ul.navbar-nav > li.nav-item > a.nav-link",
        "ul.navbar-nav.mr-auto > li.nav-item > a.nav-link",
        # 二级子导航
        "ul.navbar-nav.mr-auto li.nav-item.dropdown > ul.dropdown-menu > li.dropdown-item > a",
        "ul.dropdown-menu > li.dropdown-item > a",
        ".dropdown-menu a",
        # 分类页 / 实时监控页的 tabs
        ".realtime-tabs a",
        ".category-tabs a",
        ".tabs a",
    ]

    # 筛选栏选择器（分类页内的子分类切换）
    SEL_FILTER = [
        ".realtime-tabs a",
        ".filter-tabs a",
        ".filter-nav a",
        ".filter-list a",
        ".filter-links a",
        ".sub-cats a",
        ".subcategories a",
        ".sub-categories a",
        ".sub-nav a",
        ".sub-nav-list a",
        ".sub-cate a",
        ".category-children a",
        ".child-cats a",
        ".children-cat a",
        ".tag-filter a",
        ".tag-list a",
        ".tag-links a",
        ".category-filter a",
        ".screening a",
        ".screening-tabs a",
        ".category-tabs a",
        ".archive-tabs a",
        ".type-tabs a",
        ".content-tabs a",
        ".post-categories a",
        ".video-tabs a",
        # 通用 ul/li 兜底
        ".tabs li a",
        ".tab-list a",
    ]

    # 分类总览页选择器
    SEL_OVERVIEW = [
        ".category-list a",
        ".categories a",
        ".category-item a",
        ".cat-list a",
        ".cat-item a",
        ".category-name a",
        ".archive-list a",
        ".type-list a",
        ".taxonomy-list a",
        ".terms-list a",
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
# ② DomainResolver（与上一版完全一致，此处从略）
#    直接把上一版代码里的 class DomainResolver 原封不动放进来即可
# ==================================================================
# class DomainResolver:
#     ...   <- 上一版内容，无需改动
# ...   <-
# 如果你没有上一版的 DomainResolver，把下面这段最小版本放进来也能跑
# （完整版请从上一轮回复拷贝，功能更全，这里放最精简版本保底）：

class DomainResolver:
    def __init__(self, cfg, fetcher):
        self.cfg, self.fetch = cfg, fetcher

    def resolve(self):
        # 简化版：只并发探测 SEED_HOSTS
        try:
            with ThreadPoolExecutor(max_workers=min(6, len(self.cfg.SEED_HOSTS))) as ex:
                futs = {ex.submit(self._check, u.rstrip("/") + "/"): u
                        for u in self.cfg.SEED_HOSTS if u}
                for f in as_completed(futs, timeout=self.cfg.PROBE_TIMEOUT + 5):
                    try:
                        h = f.result()
                        if h:
                            return h
                    except Exception:
                        continue
        except Exception:
            pass
        return (self.cfg.FAST_HOSTS[0] if self.cfg.FAST_HOSTS else "").rstrip("/")

    def _check(self, url):
        try:
            r = self.fetch(url, timeout=self.cfg.PROBE_TIMEOUT)
            if r is None or r.status_code != 200:
                return ""
            text = r.text or ""
            if len(text) < self.cfg.PROBE_MIN_HTML:
                return ""
            low = text.lower()
            if (low.count("<article") >= 1
                    or low.count("realtime-card") >= 1
                    or low.count("post-card") >= 1
                    or any(m in low for m in self.cfg.SITE_MARKERS)
                    or self.cfg.match_keyword(text)):
                try:
                    p = urlparse(r.url or url)
                    if p.scheme and p.netloc:
                        return "%s://%s" % (p.scheme, p.netloc.lower())
                except Exception:
                    pass
                return url.rstrip("/")
        except Exception:
            return ""
        return ""


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

    # -------------------- 生命周期 --------------------
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
        return "🍉%s|终极完美版" % self.CONFIG.SITE_NAME

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

    # -------------------- 页面特征判断 --------------------
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
                or low.count('video-card') >= 2
                or low.count('post-card') >= 2):
            return False
        hits = sum(1 for kw in self.CONFIG.NAV_PAGE_KEYWORDS if kw in html)
        return hits >= 3

    def _is_site(self, html, min_len=None):
        if not html:
            return False, "空响应"
        if self._is_blocked_page(html):
            return False, "CF/验证页"
        if self._is_nav_page(html):
            return False, "导航页"
        if len(html) < (min_len or self.CONFIG.PROBE_MIN_HTML):
            return False, "HTML过短(%d)" % len(html)
        low = html.lower()
        has_article = (low.count("<article") >= 1
                       or low.count("realtime-card") >= 1
                       or low.count("video-card") >= 1
                       or low.count("post-card") >= 1)
        has_marker = any(m in low for m in self.CONFIG.SITE_MARKERS)
        has_keyword = self.CONFIG.match_keyword(html)
        if not (has_article or has_marker or has_keyword):
            return False, "无内容结构"
        return True, "OK"

    # -------------------- host 探测 --------------------
    def _read_host_cache(self):
        fn = getattr(self, "getCache", None)
        if not fn:
            return ""
        try:
            raw = fn(self.CONFIG.HOST_CACHE_KEY)
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

    def _write_host_cache(self, host):
        fn = getattr(self, "setCache", None)
        if not fn or not host:
            return
        try:
            fn(self.CONFIG.HOST_CACHE_KEY,
               json.dumps({"host": host, "ts": int(time.time())}))
        except Exception:
            pass

    def _verify_host(self, host, timeout=None):
        if not host:
            return ""
        host = host.rstrip("/")
        r = self._request(host + "/", timeout=timeout or self.CONFIG.FAST_TIMEOUT)
        if r is None or r.status_code != 200:
            return ""
        ok, _reason = self._is_site(r.text)
        if not ok:
            return ""
        return self._final_host(r.url) or host

    def _fast_probe(self):
        urls = [u.rstrip("/") for u in self.CONFIG.FAST_HOSTS if u]
        if not urls:
            return ""
        results = {}
        try:
            with ThreadPoolExecutor(max_workers=min(8, len(urls))) as ex:
                futs = {ex.submit(self._request, u + "/", self.CONFIG.FAST_TIMEOUT): u
                        for u in urls}
                for f in as_completed(futs, timeout=self.CONFIG.FAST_TIMEOUT + 6):
                    u = futs[f]
                    try:
                        results[u] = f.result()
                    except Exception:
                        results[u] = None
        except Exception as e:
            LOG.debug("快路径并发异常: %s", e)

        for u in urls:
            r = results.get(u)
            if r is None or r.status_code != 200:
                continue
            ok, reason = self._is_site(r.text)
            if not ok:
                print(f"  [快路径] {u} 不通过: {reason}")
                continue
            final = self._final_host(r.url) or u
            print(f"  [快路径] {u} → {final} 命中")
            return final
        return ""

    def _slow_probe(self):
        print("[慢路径] 启动探测 ...")
        resolver = DomainResolver(self.CONFIG, self._request)
        return resolver.resolve()

    def get_working_host(self):
        cached = self._read_host_cache()
        if cached:
            final = self._verify_host(cached)
            if final:
                print(f"缓存有效: {cached}")
                if final != cached:
                    self._write_host_cache(final)
                return final
            print(f"缓存失效: {cached}")

        host = self._fast_probe()
        if host:
            self._write_host_cache(host)
            return host

        host = self._slow_probe()
        if host:
            host = host.rstrip("/")
            self._write_host_cache(host)
            return host

        host = (self.CONFIG.FAST_HOSTS[0] if self.CONFIG.FAST_HOSTS else "").rstrip("/")
        if host:
            print(f"【警告】全部探测失败，回退 {host}")
        return host

    # -------------------- 分类结构缓存 --------------------
    def _read_classes_cache(self):
        fn = getattr(self, "getCache", None)
        if not fn:
            return None
        try:
            raw = fn(self.CONFIG.CLASS_CACHE_KEY)
        except Exception:
            return None
        if not raw:
            return None
        try:
            d = json.loads(raw) if isinstance(raw, str) else raw
            if not isinstance(d, dict):
                return None
            ts = int(d.get("ts") or 0)
            if time.time() - ts >= self.CONFIG.CLASS_CACHE_TTL:
                return None
            classes = d.get("classes") or []
            return classes if isinstance(classes, list) and classes else None
        except Exception:
            return None

    def _write_classes_cache(self, classes):
        fn = getattr(self, "setCache", None)
        if not fn or not classes:
            return
        try:
            fn(self.CONFIG.CLASS_CACHE_KEY, json.dumps({
                "ts": int(time.time()),
                "classes": classes,
            }, ensure_ascii=False))
        except Exception:
            pass

    # -------------------- 页面级 items 缓存 --------------------
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

    # -------------------- 首页 / 分类（核心改动）--------------------
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
        # 1) 缓存
        cached = self._read_classes_cache()
        if cached:
            print(f"[classes] 命中缓存 → {len(cached)} 个")
            return cached

        # 2) 首页导航 - 遍历所有 SEL_NAV 合并
        classes = self._parse_home_nav(data)
        print(f"[classes] 首页导航 → {len(classes)} 个")

        # 3) 兜底扫描 - 首页所有 /category/* /tag/* 链接
        extra = self._scan_category_links(data)
        if extra:
            classes = self._merge_classes(classes, extra)
            print(f"[classes] 首页链接补充 → {len(classes)} 个")

        # 4) 分类总览页补充
        for path in ("/category/", "/categories/", "/category/index/"):
            ov = self._soup(self._abs(path), timeout=self.CONFIG.FILTER_PROBE_TIMEOUT)
            if ov is None:
                continue
            ov_classes = self._parse_category_overview(ov)
            if ov_classes:
                classes = self._merge_classes(classes, ov_classes)
                print(f"[classes] 总览页 {path} 补充 → {len(classes)} 个")
                break

        # 5) 兜底
        if not classes:
            classes = [dict(self.CONFIG.DEFAULT_CATEGORY)]

        # 6) 每个一级分类抓筛选栏子分类（核心改动：全部处理）
        try:
            merged = self._augment_with_filters(classes)
            if merged and len(merged) > len(classes):
                print(f"[classes] 筛选栏合并 {len(classes)} → {len(merged)} 个")
                classes = merged
        except Exception as e:
            LOG.debug("筛选子分类异常: %s", e)

        # 7) 写缓存
        self._write_classes_cache(classes)
        return classes

    def _parse_home_nav(self, data):
        """遍历所有 SEL_NAV 选择器，全部合并去重（不再命中即 break）"""
        out, seen = [], set()
        for sel in self.CONFIG.SEL_NAV:
            try:
                items = list(data(sel).items())
            except Exception:
                continue
            for k in items:
                a = k if k.is_("a") else k("a").eq(0)
                href = (a.attr("href") or "").strip()
                name = (a.text() or "").strip()
                if not href or not name or href == "#":
                    continue
                if href.startswith(("javascript:", "mailto:", "tel:")):
                    continue
                if not (href.startswith("/") or href.startswith("http")):
                    continue
                if href in seen:
                    continue
                # 绝对链接只保留同域
                if href.startswith("http"):
                    if self._final_host(href) != self.host:
                        continue
                    try:
                        p = urlparse(href)
                        href = p.path or "/"
                    except Exception:
                        continue
                seen.add(href)
                out.append({"type_name": name, "type_id": href})
        return out

    def _scan_category_links(self, data):
        """扫描首页所有 href 匹配 /category/* 或 /tag/* 的链接"""
        out, seen = [], set()
        try:
            for a in data("a").items():
                href = (a.attr("href") or "").strip()
                name = (a.text() or "").strip()
                if not href or not name:
                    continue
                if not re.match(r"^/(?:category|tag|tags|type)/[\w\-]+(?:/[\w\-]+)?/?$", href):
                    continue
                if href in seen:
                    continue
                seen.add(href)
                out.append({"type_name": name, "type_id": href})
        except Exception:
            pass
        return out

    def _parse_category_overview(self, data):
        """分类总览页 - 从常见容器抓所有分类"""
        out, seen = [], set()
        for sel in self.CONFIG.SEL_OVERVIEW:
            try:
                items = list(data(sel).items())
            except Exception:
                continue
            for a in items:
                href = (a.attr("href") or "").strip()
                name = (a.text() or "").strip()
                if not href or not name:
                    continue
                if href.startswith(("javascript:", "mailto:", "tel:")):
                    continue
                if href.startswith("http"):
                    if self._final_host(href) != self.host:
                        continue
                    try:
                        p = urlparse(href)
                        href = p.path or "/"
                    except Exception:
                        continue
                if not href.startswith("/"):
                    continue
                if href in seen:
                    continue
                seen.add(href)
                out.append({"type_name": name, "type_id": href})
        return out

    @staticmethod
    def _merge_classes(base, extra):
        out, seen = [], set()
        for c in (base or []) + (extra or []):
            tid = (c.get("type_id") or "").strip()
            if not tid or tid in seen:
                continue
            seen.add(tid)
            out.append(c)
        return out

    def _augment_with_filters(self, main_categories):
        """对全部一级分类并发访问抓筛选栏子分类"""
        if not main_categories:
            return main_categories

        # 排除首页 / 空路径
        targets = [c for c in main_categories
                   if (c.get("type_id") or "") not in ("", "/", "#")]
        if not targets:
            return main_categories

        print(f"[classes] 并发抓取 {len(targets)} 个一级分类的筛选栏 ...")
        results_by_tid = {}
        try:
            with ThreadPoolExecutor(max_workers=min(6, len(targets))) as ex:
                futs = {ex.submit(self._fetch_category_filters, cat): cat
                        for cat in targets}
                try:
                    for f in as_completed(futs, timeout=self.CONFIG.FILTER_TOTAL_TIMEOUT):
                        try:
                            tid, subs = f.result()
                            if subs:
                                results_by_tid[tid] = subs
                        except Exception:
                            continue
                except Exception:
                    pass
        except Exception as e:
            LOG.debug("筛选并发异常: %s", e)

        if not results_by_tid:
            return main_categories

        merged = []
        for c in main_categories:
            merged.append(c)
            subs = results_by_tid.get(c.get("type_id"), [])
            merged.extend(subs)
        return merged

    def _fetch_category_filters(self, cat):
        """访问一个分类页，抓取筛选栏子分类"""
        tid = cat.get("type_id") or ""
        url = self._abs(tid)
        if not url:
            return tid, []
        if not url.endswith("/"):
            url += "/"

        r = self._request(url, timeout=self.CONFIG.FILTER_PROBE_TIMEOUT)
        if r is None or r.status_code != 200:
            return tid, []

        data = self.getpq(r.text)
        subs = []
        base_tid = tid.rstrip("/")
        seen = {base_tid, base_tid + "/", tid,
                "/" + tid.lstrip("/")}

        for sel in self.CONFIG.SEL_FILTER:
            try:
                for a in data(sel).items():
                    href = (a.attr("href") or "").strip()
                    name = (a.text() or "").strip()
                    if not href or not name:
                        continue
                    if href in seen:
                        continue
                    if href.startswith("http"):
                        if self._final_host(href) != self.host:
                            continue
                        try:
                            p = urlparse(href)
                            href = p.path or "/"
                        except Exception:
                            continue
                    if not href.startswith("/"):
                        continue
                    seen.add(href)
                    subs.append({
                        "type_name": "%s · %s" % (cat.get("type_name", ""), name),
                        "type_id": href,
                    })
            except Exception:
                continue
        return tid, subs

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

            title = self._extract_title(k, a)
            # 兜底：从 URL 拿最后一段
            if not title:
                m = re.search(r"/([^/]+)/?$", href)
                if m and m.group(1):
                    title = m.group(1)
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

    def _extract_title(self, k, a):
        # 1. 属性
        for elem in (a, k):
            if not elem:
                continue
            for attr in ("aria-label", "title", "data-title", "data-original-title"):
                v = (elem.attr(attr) or "").strip()
                if v:
                    return v
        # 2. img alt
        for elem in (a, k):
            if not elem:
                continue
            try:
                img = elem("img").eq(0)
            except Exception:
                img = None
            if img:
                v = (img.attr("alt") or "").strip()
                if v:
                    return v
        # 3. h1~h4
        for tag in ("h1", "h2", "h3", "h4"):
            try:
                v = (k(tag).eq(0).text() or "").strip()
            except Exception:
                v = ""
            if v:
                return v
        # 4. 常见类名
        for sel in (".post-title", ".entry-title", ".video-title", ".card-title",
                    ".item-title", ".post-card-title", ".media-title", ".title",
                    ".post-name", ".name"):
            try:
                v = (k(sel).eq(0).text() or "").strip()
            except Exception:
                v = ""
            if v:
                return v
        # 5. meta itemprop name/headline
        try:
            for meta in k("meta").items():
                prop = (meta.attr("itemprop") or "").lower()
                if "headline" in prop:
                    v = (meta.attr("content") or "").strip()
                    if v:
                        return v
        except Exception:
            pass
        # 6. 文本兜底
        if k.is_("a"):
            return (k.text() or "").strip()
        if a:
            return (a.text() or "").strip()
        return ""

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

    # -------------------- 日期 / 图片 --------------------
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
            html = elem.outer_html() if hasattr(elem, "outer_html") else str(elem)
        except Exception:
            html = str(elem or "")
        html = (html.replace("&quot;", '"')
                    .replace("&apos;", "'")
                    .replace("&amp;", "&"))

        # 1. background-image
        m = re.search(r'background(?:-image)?\s*:\s*url\(\s*[\'"]?([^"\')\s]+)[\'"]?\s*\)',
                      html, re.I)
        if m:
            u = m.group(1).strip()
            if u and not u.startswith("#"):
                return self._proc_url(u)

        # 2. 懒加载属性
        try:
            img = elem if elem.is_("img") else elem("img").eq(0)
        except Exception:
            img = None
        if img:
            for attr in ("data-xkrkllgl", "data-src", "data-original",
                         "data-lazy-src", "data-echo", "data-url", "data-bg",
                         "data-original-src", "data-ll-lazy"):
                v = img.attr(attr)
                if v and not str(v).startswith("data:"):
                    return self._proc_url(v)
            v = img.attr("src")
            if v:
                return self._proc_url(v)

        # 3. loadBannerDirect
        try:
            txt = elem("script").text() or ""
        except Exception:
            txt = ""
        if m := re.search(r"loadBannerDirect\('([^']+)'", txt):
            return self._proc_url(m.group(1))

        # 4. 正则兜底
        m = re.search(r'(https?://[^"\'\s)]+\.(?:jpg|png|jpeg|webp|gif))', html, re.I)
        if m:
            return self._proc_url(m.group(1))
        m = re.search(r"(data:image/[a-zA-Z0-9+/=;,]+)", html)
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
