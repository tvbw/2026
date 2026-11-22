# -*- coding: utf-8 -*-
"""
51系列标准模板 · 发布页秒跳自愈版
================================
核心链路：一级跳板页 → 秒跳（HTTP 3xx / meta refresh / location.href）→
        二级发布页 → 提取候选 → 并发探测 → 三级内容站
换站只改 SiteConfig 顶部站点身份 + 发布页两段 + SEL_* 选择器
"""
import json
import re
import sys
import time
import hashlib
import logging
from base64 import b64decode, b64encode
from urllib.parse import quote, unquote, urlparse, urljoin
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
# ① 站点配置（换站只改本类顶部）
# ==================================================================
class SiteConfig:
    # ---------- 站点身份 ----------
    SITE_NAME       = "51大赛"
    SITE_KEYWORDS   = ["51大赛", "51吃瓜", "51爆料", "51cg"]
    PLAY_FROM       = "51大赛"
    PLAY_FALLBACK   = "51大赛"
    HOST_CACHE_KEY  = "sp51_host_v11"
    PUB_CACHE_KEY   = "sp51_pub_v11"
    CLASS_CACHE_KEY = "sp51_classes_v11"
    CLASS_CACHE_TTL = 3600
    HOST_CACHE_TTL  = 25000
    FALLBACK_HOST   = None

    # ---------- 发布页（一级跳板 + 二级保底）----------
    PUBLISH_URLS = ["https://51cgf24.com/"]
    PUBLISH_FALLBACK_AFTER_JUMP = [
        "https://www.sunkdjlla.cc/",
        "https://www.nqvudlbn.cc/",
    ]

    # ---------- 超时 ----------
    PUBLISH_TIMEOUT = 12
    PROBE_TIMEOUT   = 12
    FAST_TIMEOUT    = 8
    FILTER_PROBE_TIMEOUT = 5
    FILTER_TOTAL_TIMEOUT = 20

    # ---------- 站点特征 ----------
    PROBE_MIN_HTML    = 1500
    PROBE_MIN_ARTICLE = 1
    SITE_MARKERS = (
        "post-title", "entry-title", "<article", 'class="post',
        "realtime-card", "candid-video", "video-card",
    )
    NAV_PAGE_KEYWORDS = (
        "线路一", "线路二", "线路三", "推荐访问", "线路正常",
        "官方导航", "发布页", "备用线路", "地址发布页", "永久地址", "最新地址",
    )

    VALID_TLDS = {
        'com','net','org','cc','xyz','lol','vip','app','top','cn','co','io','me',
        'tv','club','site','online','info','biz','pro','link','live','shop','fun',
        'work','icu','life','world','store','tech','space','website','host',
        'pw','tk','ml','ga','cf','gq','su','ws','ly','to','st','in','tw',
        'hk','jp','kr','ru','us','uk','de','fr','nl','eu','au','ca','sg','my',
        'sbs','bet','cam','one','plus','now','today','pub','dev','cool','cloud',
    }
    DOMAIN_BLACKLIST = (
        'google','gstatic','bing.com','baidu.com','so.com','sogou.com','yandex',
        'facebook','fbcdn','instagram','twitter','twimg','youtube','ytimg',
        't.me','telegram','whatsapp','discord','reddit','tiktok','pinterest',
        'apple.com','icloud','microsoft','windows','amazonaws','cloudflare',
        'cloudfront','azureedge','github','gitlab','gitee','bitbucket',
        'w3.org','wikipedia','mozilla.org','stackoverflow','jsdelivr','unpkg',
        'bootstrapcdn','jquery','fontawesome','gmail','outlook','hotmail',
        'yahoo','protonmail','qq.com','163.com','126.com','sina.com','weibo.com',
        'statcounter','google-analytics','umeng','cnzz','beian.miit.gov.cn',
        'wordpress.org','wix.com','weebly','shopify','51.la','cnzz.com','51yes',
        'navone.cloud',
    )

    # ---------- 页面选择器 ----------
    SEL_ARTICLE      = "#index article, #archive article, article"
    SEL_ARTICLE_HOME = "#index article, article"
    SEL_PLAYER       = ".dplayer"
    SEL_CONTENT      = ".post-content, article"
    SEL_TAGS         = ".post-tags a, .tags a, .keywords a"
    SEL_SUMMARY      = ".post-content"
    SEL_TITLE        = ".post-title, h1"

    SEL_NAV = [
        ".category-list ul li", ".category-list a",
        ".nav-menu li", ".nav-menu a",
        ".menu li", ".menu a",
        "nav ul li", "nav a", "header nav a",
        "ul.navbar-nav.mr-auto > li.nav-item > a.nav-link",
        "ul.navbar-nav > li.nav-item > a.nav-link",
        "ul.navbar-nav li a.nav-link",
        "#navbarCollapse a.nav-link",
        ".navbar-nav a.nav-link",
    ]
    SEL_FILTER = [
        ".filter-tabs a", ".filter-nav a", ".filter-list a",
        ".filter-links a", ".sub-cats a", ".subcategories a",
        ".sub-categories a", ".sub-nav a", ".sub-nav-list a",
        ".sub-cate a", ".category-children a", ".child-cats a",
        ".children-cat a", ".tag-filter a", ".tag-list a",
        ".tag-links a", ".category-filter a", ".screening a",
        ".screening-tabs a", ".category-tabs a", ".archive-tabs a",
        ".type-tabs a", ".content-tabs a", ".post-categories a",
        ".tabs a", ".tab-list a",
    ]
    SEL_OVERVIEW = [
        ".category-list a", ".categories a", ".category-item a",
        ".cat-list a", ".cat-item a", ".category-name a",
        ".archive-list a", ".type-list a", ".taxonomy-list a",
        ".terms-list a",
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
# ② 发布页秒跳自愈解析器
# ==================================================================
class PublishResolver:
    """一级跳板页 → 二级发布页 → 三级内容站域名
    只识别 HTTP 3xx（requests 自动跟随）、meta refresh、location.href/replace/assign
    """

    META_REFRESH_RE = re.compile(
        r'<meta[^>]+http-equiv=["\']?refresh["\']?[^>]*?'
        r'content=["\']?\s*\d+\s*;\s*url=([^"\'>\s]+)',
        re.I)
    JS_LOCATION_RE = re.compile(
        r'(?:window\.|document\.|top\.|self\.)?location(?:\.href)?\s*=\s*["\'](https?://[^"\']+)["\']'
        r'|(?:window\.|document\.|top\.|self\.)?location\.(?:replace|assign)\s*\(\s*["\'](https?://[^"\']+)["\']',
        re.I)
    HTTP_URL_RE = re.compile(r'https?://[^\s"\'<>()\[\]{},;]+')
    DOMAIN_RE = re.compile(
        r'(?<![\w.\-])((?:[a-zA-Z0-9](?:[a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?\.)+[a-zA-Z]{2,10})(?![\w.\-])')

    def __init__(self, cfg, fetcher, cache_get=None, cache_set=None):
        self.cfg = cfg
        self.fetch = fetcher
        self.cache_get = cache_get
        self.cache_set = cache_set
        self._jump_origins = {self._origin(u) for u in getattr(cfg, "PUBLISH_URLS", []) if u}
        self._publish_origins = {self._origin(u) for u in (
            list(getattr(cfg, "PUBLISH_URLS", [])) +
            list(getattr(cfg, "PUBLISH_FALLBACK_AFTER_JUMP", []))
        ) if u}

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
    def _normalize_url(u, base_url):
        u = unquote(str(u or "")).strip().strip('"\' ')
        if not u:
            return ""
        if u.startswith("//"):
            u = "https:" + u
        if not u.startswith("http"):
            u = urljoin(base_url or "", u)
        return u

    def _safe_fetch(self, url, timeout):
        try:
            return self.fetch(url, timeout=timeout)
        except Exception:
            return None

    # ---------- 发布页跳转 ----------
    def _extract_jump_target(self, html, base_url):
        if not html:
            return ""
        m = self.META_REFRESH_RE.search(html)
        if m:
            return self._normalize_url(m.group(1), base_url)
        m = self.JS_LOCATION_RE.search(html)
        if m:
            return self._normalize_url(m.group(1) or m.group(2), base_url)
        return ""

    def _resolve_jump(self, start_url):
        """返回 (二级发布页URL, html)；失败返回 ("","")"""
        start_url = start_url.rstrip("/") + "/"
        r = self._safe_fetch(start_url, self.cfg.PUBLISH_TIMEOUT)
        if r is None:
            return "", ""
        final_url = r.url.rstrip("/") + "/"
        html = r.text or ""
        # HTTP 3xx 已跳出跳板页
        if self._origin(final_url) not in self._jump_origins:
            return final_url, html
        # 仍是跳板页 → 尝试 HTML/JS 跳转
        target = self._extract_jump_target(html, final_url)
        if not target:
            return "", ""
        target = target.rstrip("/") + "/"
        r2 = self._safe_fetch(target, self.cfg.PUBLISH_TIMEOUT)
        if r2 is None:
            return "", ""
        return r2.url.rstrip("/") + "/", (r2.text or "")

    # ---------- 二级发布页 → 候选域名 ----------
    def _extract_candidates(self, html):
        if not html:
            return []
        cands, seen = [], set()

        def _add(raw):
            h = self._origin(raw)
            if not h:
                return
            if h in self._publish_origins:      # 排除发布页自身
                return
            hl = h.lower()
            if any(b in hl for b in self.cfg.DOMAIN_BLACKLIST):
                return
            if h in seen:
                return
            seen.add(h)
            cands.append(h)

        # 策略1：所有 http(s) 链接
        for m in self.HTTP_URL_RE.finditer(html):
            _add(m.group(0))

        # 策略2：base64 混淆脚本（发布页常见）
        for m in re.finditer(r'["\']([A-Za-z0-9+/=]{80,})["\']', html[:20000]):
            try:
                dec = b64decode(m.group(1)).decode("utf-8", "ignore")
                for u in self.HTTP_URL_RE.finditer(dec):
                    _add(u.group(0))
            except Exception:
                continue

        # 策略3：裸域名扫描（限前 10000 字符）
        text = re.sub(r'\b[\w.\-+]+@[\w.\-]+\b', ' ', html[:10000])
        text = re.sub(r'\.(?:jpg|jpeg|png|gif|webp|svg|ico|mp4|mp3|m3u8|ts|'
                      r'css|js|woff|woff2|ttf|eot|map|html?|php)\b', ' ', text, flags=re.I)
        for m in self.DOMAIN_RE.finditer(text):
            d = m.group(1).lower().strip('.')
            if d.split('.')[-1] not in self.cfg.VALID_TLDS:
                continue
            if any(b in d for b in self.cfg.DOMAIN_BLACKLIST):
                continue
            _add("https://" + d)

        return cands[:20]

    # ---------- 站点有效性 ----------
    def _site_check(self, html):
        if not html or len(html) < self.cfg.PROBE_MIN_HTML:
            return False
        low = html.lower()
        blocked = ('just a moment', 'cf-browser-verification',
                   'checking your browser', '__cf_chl_', 'ddos-guard',
                   'enable javascript and cookies',
                   '请开启 javascript', '请启用 javascript')
        if any(m in low for m in blocked):
            return False
        # 导航页特征（避免把发布页误认为内容站）
        if 'data-base=' in html and 'id="list-wrap"' in html:
            return False
        hits = sum(1 for kw in self.cfg.NAV_PAGE_KEYWORDS if kw in html)
        if hits >= 3 and low.count("<article") < 1:
            return False
        # 内容结构
        has_article = (low.count("<article") >= self.cfg.PROBE_MIN_ARTICLE
                       or low.count('class="post') >= 2)
        has_marker  = any(m in low for m in self.cfg.SITE_MARKERS)
        has_kw      = self.cfg.match_keyword(html)
        return has_article or has_marker or has_kw

    def _probe_one(self, url, timeout=None):
        r = self._safe_fetch(url, timeout or self.cfg.PROBE_TIMEOUT)
        if r is None or r.status_code != 200:
            return ""
        if not self._site_check(r.text):
            return ""
        return self._origin(r.url) or url.rstrip("/")

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
    def _cache_read(self, key, field):
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

    def _cache_write(self, key, data):
        if not self.cache_set or not data:
            return
        try:
            self.cache_set(key, json.dumps(data))
        except Exception:
            pass

    # ---------- 主入口 ----------
    def resolve(self):
        # 1) HOST 缓存快校验
        cached_host = self._cache_read(self.cfg.HOST_CACHE_KEY, "host")
        if cached_host:
            hit = self._probe_one(cached_host.rstrip("/") + "/", self.cfg.FAST_TIMEOUT)
            if hit:
                print(f"[HOST缓存] 有效: {hit}")
                if hit != cached_host:
                    self._cache_write(self.cfg.HOST_CACHE_KEY, {"host": hit})
                return hit
            print(f"[HOST缓存] 失效: {cached_host}")

        # 2) PUB 缓存（上次成功的二级发布页）
        pub_cached = self._cache_read(self.cfg.PUB_CACHE_KEY, "pub")
        if pub_cached:
            r = self._safe_fetch(pub_cached.rstrip("/") + "/", self.cfg.FAST_TIMEOUT)
            if r is not None and r.status_code == 200:
                cands = self._extract_candidates(r.text or "")
                host = self._probe_hosts(cands)
                if host:
                    print(f"[PUB缓存] {pub_cached} → {host}")
                    self._cache_write(self.cfg.HOST_CACHE_KEY, {"host": host})
                    return host
            print(f"[PUB缓存] 失效: {pub_cached}")

        # 3) 一级跳板页 → 秒跳 → 二级发布页
        for pub in getattr(self.cfg, "PUBLISH_URLS", []):
            print(f"[一级页] 解析: {pub}")
            jump_url, html = self._resolve_jump(pub)
            if not jump_url:
                print(f"[一级页] {pub} 无跳转目标")
                continue
            print(f"[一级页] {pub} → {jump_url}")
            self._cache_write(self.cfg.PUB_CACHE_KEY, {"pub": jump_url})
            cands = self._extract_candidates(html)
            host = self._probe_hosts(cands)
            if host:
                print(f"[一级页] 命中: {host}")
                self._cache_write(self.cfg.HOST_CACHE_KEY, {"host": host})
                return host

        # 4) 二级发布页硬编码保底
        for fb in getattr(self.cfg, "PUBLISH_FALLBACK_AFTER_JUMP", []):
            fb = fb.rstrip("/") + "/"
            print(f"[二级保底] 解析: {fb}")
            r = self._safe_fetch(fb, self.cfg.PUBLISH_TIMEOUT)
            if r is None or r.status_code != 200:
                print(f"[二级保底] {fb} 访问失败")
                continue
            final = r.url.rstrip("/") + "/"
            self._cache_write(self.cfg.PUB_CACHE_KEY, {"pub": final})
            cands = self._extract_candidates(r.text or "")
            host = self._probe_hosts(cands)
            if host:
                print(f"[二级保底] 命中: {host}")
                self._cache_write(self.cfg.HOST_CACHE_KEY, {"host": host})
                return host

        # 5) 全部失败 → 回退旧缓存
        print("[发布页] 全部策略失败，回退旧缓存")
        return cached_host or ""


# ==================================================================
# ③ 主爬虫基类（业务层）
# ==================================================================
class BaseMultiDomainSpider(BaseSpider):
    CONFIG = SiteConfig

    def __init__(self, extend="", *a, **kw):
        try:
            super().__init__(*a, **kw)
        except Exception:
            pass
        self.proxies, self.host, self._img_cache = {}, "", {}

    def init(self, extend=""):
        try:
            self.proxies = (json.loads(extend)
                            if extend and isinstance(extend, str) and extend.startswith("{")
                            else {})
        except Exception:
            self.proxies = {}
        self.headers = dict(self.CONFIG.HEADERS)

        manual_host = ""
        try:
            if isinstance(extend, dict):
                manual_host = extend.get("host", "") or ""
            elif isinstance(extend, str) and extend.startswith("{"):
                manual_host = json.loads(extend).get("host", "") or ""
            elif isinstance(extend, str) and extend.startswith("http"):
                manual_host = extend
        except Exception:
            pass

        if manual_host:
            manual_host = manual_host.rstrip("/")
            if not manual_host.startswith("http"):
                manual_host = "https://" + manual_host
            print(f"【extend 指定】使用域名: {manual_host}")
            self.host = manual_host
        else:
            resolver = PublishResolver(
                self.CONFIG, self._get,
                cache_get=getattr(self, "getCache", None),
                cache_set=getattr(self, "setCache", None),
            )
            self.host = resolver.resolve()

        if self.host:
            self.headers.update({"Origin": self.host, "Referer": self.host + "/"})
        print(f"使用站点: {self.host}")

    def getName(self):
        return "🌈 %s|发布页秒跳自愈版" % self.CONFIG.SITE_NAME

    def manualVideoCheck(self): return False
    def isVideoFormat(self, u): return any(e in (u or "") for e in (".m3u8", ".mp4", ".ts"))
    def destroy(self):          self._img_cache.clear()

    # ---------- 基础工具 ----------
    def _get(self, url, timeout=None, **kw):
        try:
            return requests.get(
                url, headers=self.headers, proxies=self.proxies,
                timeout=timeout or self.CONFIG.PROBE_TIMEOUT,
                verify=False, allow_redirects=True, **kw)
        except Exception as e:
            LOG.debug("GET 异常 %s: %s", url, e)
            return None

    def _get_soup(self, url, timeout=15):
        r = self._get(url, timeout=timeout)
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
        if not href:
            return ""
        if href.startswith("http"):
            return href
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

    # ---------- 首页 ----------
    def homeContent(self, filter=False):
        if not self.host:
            return {"class": [], "list": []}
        r, data = self._get_soup(self.host)
        if data is None:
            return {"class": [], "list": []}
        return {"class": self._parse_classes(data),
                "list": self._parse_list(data(self.CONFIG.SEL_ARTICLE_HOME))}

    def homeVideoContent(self):
        if not self.host:
            return {"list": []}
        r, data = self._get_soup(self.host)
        if data is None:
            return {"list": []}
        return {"list": self._parse_list(data(self.CONFIG.SEL_ARTICLE_HOME))}

    # ---------- 分类结构 ----------
    def _parse_classes(self, data):
        cached = self._read_classes_cache()
        if cached:
            print(f"[classes] 缓存命中 → {len(cached)} 个")
            return cached

        classes = self._parse_home_nav(data)
        print(f"[classes] 首页导航 → {len(classes)} 个")

        extra = self._scan_category_links(data)
        if extra:
            classes = self._merge_classes(classes, extra)
            print(f"[classes] 首页链接补充 → {len(classes)} 个")

        for path in ("/category/", "/categories/", "/category/index/"):
            ov = self._get_soup(self._abs(path),
                                timeout=self.CONFIG.FILTER_PROBE_TIMEOUT)[1]
            if ov is None:
                continue
            ov_classes = self._parse_category_overview(ov)
            if ov_classes:
                classes = self._merge_classes(classes, ov_classes)
                print(f"[classes] 总览页 {path} 补充 → {len(classes)} 个")
                break

        if not classes:
            classes = [dict(self.CONFIG.DEFAULT_CATEGORY)]

        try:
            merged = self._augment_with_filters(classes)
            if merged and len(merged) > len(classes):
                print(f"[classes] 筛选栏合并 {len(classes)} → {len(merged)} 个")
                classes = merged
        except Exception as e:
            LOG.debug("筛选子分类异常: %s", e)

        self._write_classes_cache(classes)
        return classes

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
            if time.time() - int(d.get("ts") or 0) >= self.CONFIG.CLASS_CACHE_TTL:
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

    def _parse_home_nav(self, data):
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
                if href.startswith("http"):
                    try:
                        p = urlparse(href)
                        href = p.path or "/"
                    except Exception:
                        continue
                if href in seen:
                    continue
                seen.add(href)
                out.append({"type_name": name, "type_id": href})
        return out

    def _scan_category_links(self, data):
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
                    try:
                        p = urlparse(href)
                        href = p.path or "/"
                    except Exception:
                        continue
                if not href.startswith("/") or href in seen:
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
        if not main_categories:
            return main_categories
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
            merged.extend(results_by_tid.get(c.get("type_id"), []))
        return merged

    # ---------- 修复：二级目录平铺 + 名字截断 ----------
    def _fetch_category_filters(self, cat):
        tid = cat.get("type_id") or ""
        url = self._abs(tid)
        if not url:
            return tid, []
        if not url.endswith("/"):
            url += "/"

        r = self._get(url, timeout=self.CONFIG.FILTER_PROBE_TIMEOUT)
        if r is None or r.status_code != 200:
            return tid, []

        data = self.getpq(r.text)
        subs = []
        base_tid = tid.rstrip("/")
        base_norm = base_tid if base_tid.startswith("/") else "/" + base_tid
        seen = {base_tid, base_tid + "/", tid, base_norm, base_norm + "/"}

        # 明显非分类筛选项
        skip_names = {"全部", "最新", "最热", "推荐", "更多", "首页",
                      "返回", "上一页", "下一页", "热门", "精选"}
        skip_paths = ("?", "/page/", "/search/", "/about", "/contact",
                      "/login", "/register", "/sitemap", "/rss", "/feed",
                      "/policy", "/privacy", "/terms")

        for sel in self.CONFIG.SEL_FILTER:
            try:
                for a in data(sel).items():
                    href = (a.attr("href") or "").strip()
                    name = (a.text() or "").strip()
                    if not href or not name:
                        continue
                    if href.startswith(("javascript:", "mailto:", "tel:", "#")):
                        continue
                    if href.startswith("http"):
                        try:
                            p = urlparse(href)
                            href = p.path or "/"
                        except Exception:
                            continue
                    if not href.startswith("/"):
                        continue
                    # 关键：必须是当前分类的子路径
                    if href == base_norm or href == base_norm + "/":
                        continue
                    if not (href.startswith(base_norm + "/")
                            or href.startswith(base_norm + "-")):
                        # 允许 tag 类筛选作为二级
                        if not href.startswith("/tag/") and not href.startswith("/tags/"):
                            continue
                    if any(sp in href for sp in skip_paths):
                        continue
                    if href in seen:
                        continue
                    if name in skip_names:
                        continue
                    # 关键：type_name 只取子类名，超长截断
                    clean_name = name if len(name) <= 15 else name[:13] + "…"
                    seen.add(href)
                    subs.append({"type_name": clean_name, "type_id": href})
            except Exception:
                continue
        return tid, subs

    # ---------- 分类内容 ----------
    def categoryContent(self, tid, pg=1, filter=False, extend=None):
        if not self.host:
            return {"list": [], "page": 1, "pagecount": 1, "limit": 90, "total": 0}
        pg = int(pg or 1)
        if "@folder" in tid:
            v = self._parse_folder(tid.replace("@folder", ""))
            return {"list": v, "page": 1, "pagecount": 1,
                    "limit": 90, "total": len(v)}
        url = self._build_page_url(tid, pg)
        r, data = self._get_soup(url)
        if data is None:
            return {"list": [], "page": pg, "pagecount": 9999,
                    "limit": 90, "total": 0}
        return {
            "list": self._parse_list(data(self.CONFIG.SEL_ARTICLE), tid),
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
        return {"list": self._parse_list(data("article")),
                "page": pg, "pagecount": 9999}

    # ---------- 详情 ----------
    def detailContent(self, ids):
        vid = str(ids[0] if isinstance(ids, (list, tuple)) else ids)
        if not self.host:
            return {"list": [{"vod_play_from": self.CONFIG.PLAY_FROM,
                              "vod_play_url": "获取失败"}]}
        url = vid if vid.startswith("http") else self.host + vid
        r, data = self._get_soup(url)
        if data is None:
            return {"list": [{"vod_play_from": self.CONFIG.PLAY_FROM,
                              "vod_play_url": "获取失败"}]}
        playlist = self._extract_playlist(data)
        play_url = "#".join(playlist) or "未找到视频源，请访问网页$%s" % url
        return {"list": [{
            "vod_play_from": self.CONFIG.PLAY_FROM,
            "vod_play_url":  play_url,
            "vod_content":   self._extract_content(data),
        }]}

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
            name = (txt.replace("点击观看：", "").replace("点击观看", "").strip()
                    or "视频%d" % i)
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
                tags.append("[a=cr:%s/]%s[/a]" % (
                    json.dumps({"id": self._abs(h), "name": t}), t))
        if tags:
            return " ".join(tags) + "\n\n" + (data(self.CONFIG.SEL_SUMMARY).text() or "")[:150]
        return data(self.CONFIG.SEL_TITLE).text() or self.CONFIG.PLAY_FALLBACK

    # ---------- 图片 ----------
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
        return (b.startswith(b"\xff\xd8") or b.startswith(b"\x89PNG")
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

    # ---------- 播放 ----------
    def playerContent(self, flag, id, vipFlags=None):
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
                res = self._get(real, timeout=10)
                return ([200, "image/jpeg", self.aesimg(res.content)]
                        if res else [404, "text/plain", b""])
            if t == "m3u8":
                return self._m3_proxy(param.get("url"))
            return self._ts_proxy(param.get("url"))
        except Exception:
            return [404, "text/plain", b""]

    def _m3_proxy(self, url):
        real = url if url.startswith("http") else self.d64(url)
        res = self._get(real)
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
        res = self._get(real)
        return ([200, "video/mp2t", res.content]
                if res else [404, "text/plain", b""])


# ==================================================================
# ④ 具体站点类
# ==================================================================
class Spider(BaseMultiDomainSpider):
    CONFIG = SiteConfig


# ==================================================================
# ⑤ 播放源聚合扩展（关联推荐）
# ==================================================================
def _install_playlist_extension(_C):
    if getattr(_C, "_pl_patched", False):
        return _C
    _C._pl_patched = True
    _orig_init    = getattr(_C, "init", None)
    _orig_home    = getattr(_C, "homeContent", None)
    _orig_homev   = getattr(_C, "homeVideoContent", None)
    _orig_cate    = getattr(_C, "categoryContent", None)
    _orig_detail  = getattr(_C, "detailContent", None)
    _orig_search  = getattr(_C, "searchContent", None)
    _orig_player  = getattr(_C, "playerContent", None)

    def _ensure(self):
        if not hasattr(self, "page_cache"):
            self.page_cache, self.page_index, self.page_keys = {}, {}, []
            self._src_cache = {}

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
                    out.append("%s$%s" % (
                        _clean("%s %s" % (name, en or "%02d" % (i + 1))), u))
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
    if _orig_init:    _C.init             = init
    if _orig_home:    _C.homeContent      = homeContent
    if _orig_homev:   _C.homeVideoContent = homeVideoContent
    if _orig_cate:    _C.categoryContent  = categoryContent
    if _orig_search:  _C.searchContent    = searchContent
    if _orig_detail:  _C.detailContent    = detailContent
    if _orig_player:  _C.playerContent    = playerContent
    return _C

try:
    _install_playlist_extension(Spider)
except Exception:
    pass
