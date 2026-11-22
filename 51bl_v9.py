# -*- coding: utf-8 -*-
"""
51系列网站 · 标准通用模板 v11（发布页跳链自愈版）
========================================================
合并来源：
  A.《51吃瓜导航探测版》   —— 发布页直达：JS/meta 混淆跳转链跟随、
                              二级导航发布页兜底、导航页缓存、跳转目标多策略提取
  B.《51系列标准模板 v10》 —— 多域自愈：快路径、入口页缓存、CF盾识别、
                              分类全合并+筛选栏子分类发现、播放源聚合扩展、
                              AES图片解密、m3u8/ts/mkey 本地代理

v11 合并要点
------------
【域名解析优先级】
  1. 有效缓存直验          （1 次请求确认，失败即进下一步）
  2. FAST_HOSTS 快路径      （已知可用内容域名，并发探测，命中即返回）
  3. 一级导航发布页          （跟随 JS/meta 跳转链 ≤JUMP_MAX_HOPS 跳，逐页提取候选；
                             支持 GitLab raw README；结果写导航页缓存）
  4. 二级导航发布页兜底      （一级全部被拦/拿不到候选时自动加载，
                             即一级跳转后的落地导航页，可直接配置）
  5. 种子域名并入候选，多轮并发探测（页面内新域名滚动发现）

【免维护/自愈】
  - 一级发布页即使换成混淆跳转页，跳链跟随也能拿到二级导航页再提取三级内容域名
  - 所有提取策略带黑白名单 + TLD + 资源后缀过滤，误提取率低
  - HOST / PUB / 分类 三级缓存，TTL 可配

换站只改 SiteConfig：站点身份 6 项 + PUBLISH_URLS（一级）+
PUBLISH_FALLBACK_URLS（二级）+ FAST_HOSTS/SEED_HOSTS + SEL_* 选择器
"""
import json
import re
import sys
import time
import base64
import hashlib
import logging
import threading
from base64 import b64decode, b64encode
from urllib.parse import quote, unquote, urljoin, urlparse
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
from Crypto.Cipher import AES
from Crypto.Util.Padding import unpad
from pyquery import PyQuery as pq

sys.path.append("..")
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
# ① 配置层（换站只改本类）
# ==================================================================
class SiteConfig:
    # ============ 站点身份（换站改这一段）============
    SITE_NAME       = "51吃瓜"
    SITE_KEYWORDS   = ["51吃瓜", "51cg"]      # 多个备选，任一命中即可，支持正则
    PLAY_FROM       = "51吃瓜"
    PLAY_FALLBACK   = "51吃瓜"
    HOST_CACHE_KEY  = "51cg_host_v11"
    PUB_CACHE_KEY   = "51cg_pub_v11"
    CLASS_CACHE_KEY = "51cg_classes_v11"
    CLASS_CACHE_TTL = 3600
    HOST_CACHE_TTL  = 25000
    PUB_CACHE_TTL   = 25000

    # ============ 一级导航发布页（主锚点；可能是JS混淆跳转页）============
    PUBLISH_URLS = [
        "https://51cgf24.com/",
    ]
    # ============ 二级导航发布页（一级全部被拦/拿不到候选时的兜底；
    #               也是一级跳转链的落地导航页，可直接写死在这里）============
    PUBLISH_FALLBACK_URLS = [
        "https://www.sunkdjlla.cc/",
        "https://www.nqvudlbn.cc/",
    ]
    # 跟随 JS/meta 跳转的最大跳数（防循环）
    JUMP_MAX_HOPS = 2

    # ============ 快路径（已知可用内容域名，最先探测）============
    FAST_HOSTS = [
        "https://art.ufwyylsgb.cc/",
        "https://be.gadoatcl.cc/",
        "https://awful.gadoatcl.cc/",
    ]

    # ============ 旧版平面导航页（可选；非跳链型导航可直接解析）============
    NAV_URLS = []

    # ============ 种子域名（可能承载 HTML 主站的域名）============
    SEED_HOSTS = []

    FALLBACK_HOST = None

    # ============ 探测参数 ============
    PUBLISH_TIMEOUT      = 15   # 发布页单跳抓取超时
    PROBE_TIMEOUT        = 15   # 候选域名探测超时
    FAST_TIMEOUT         = 10   # 快路径/缓存校验超时
    PROBE_MIN_HTML       = 1500
    PROBE_MIN_ARTICLE    = 1
    PROBE_MAX_ROUNDS     = 2
    PROBE_MAX_CANDIDATES = 30
    ENTRY_CACHE_TTL      = 1800   # 发布页入口结果缓存 30 分钟
    FILTER_PROBE_TIMEOUT = 5
    FILTER_TOTAL_TIMEOUT = 25

    # ============ 站点结构特征 ============
    SITE_MARKERS = [
        "post-title", "entry-title", "<article", 'class="post',
        "realtime-card", "candid-video", "video-card",
    ]

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

    EXTRA_BLACKLIST = ('beian.miit.gov.cn', 'w3.org', 'example.com')

    # ============ 页面选择器 ============
    SEL_ARTICLE      = (
        "#index article, #archive article, article, "
        ".realtime-card, .video-card, .video-item, .post-item, .card-item"
    )
    SEL_ARTICLE_HOME = (
        "#index article, article, "
        ".realtime-card, .video-card, .video-item, .post-item, .card-item"
    )
    SEL_SEARCH_ARTICLE = "article, .realtime-card, .video-card, .video-item"
    SEL_PLAYER       = ".dplayer"
    SEL_CONTENT      = ".post-content, article"
    SEL_TAGS         = ".post-tags a, .tags a, .keywords a"
    SEL_SUMMARY      = ".post-content"
    SEL_TITLE        = ".post-title, h1"

    # 导航 - 抓全类放前面，遍历全部合并（不再命中即 break）
    SEL_NAV = [
        ".category-list ul li",
        ".category-list a",
        ".nav-menu li",
        ".nav-menu a",
        ".menu li",
        ".menu a",
        "nav ul li",
        "nav a",
        "header nav a",
        "ul.navbar-nav.mr-auto > li.nav-item > a.nav-link",
        "ul.navbar-nav > li.nav-item > a.nav-link",
        "ul.navbar-nav li a.nav-link",
        "#navbarCollapse a.nav-link",
        ".navbar-nav a.nav-link",
        ".realtime-tabs a",
        ".category-tabs a",
        ".tabs a",
    ]

    SEL_SUB_NAV = [
        "ul.navbar-nav.mr-auto li.nav-item.dropdown > ul.dropdown-menu > li.dropdown-item > a",
        "ul.dropdown-menu > li.dropdown-item > a",
        ".dropdown-menu a",
    ]

    # 筛选栏（分类页内的子分类切换）
    SEL_FILTER = [
        ".filter-tabs a", ".filter-nav a", ".filter-list a", ".filter-links a",
        ".sub-cats a", ".subcategories a", ".sub-categories a", ".sub-nav a",
        ".sub-nav-list a", ".sub-cate a", ".category-children a", ".child-cats a",
        ".children-cat a", ".tag-filter a", ".tag-list a", ".tag-links a",
        ".category-filter a", ".screening a", ".screening-tabs a",
        ".category-tabs a", ".archive-tabs a", ".type-tabs a", ".content-tabs a",
        ".post-categories a", ".tabs a", ".tab-list a",
    ]

    # 分类总览页
    SEL_OVERVIEW = [
        ".category-list a", ".categories a", ".category-item a", ".cat-list a",
        ".cat-item a", ".category-name a", ".archive-list a", ".type-list a",
        ".taxonomy-list a", ".terms-list a",
    ]

    DEFAULT_CATEGORY = {"type_name": "首页", "type_id": "/"}

    LINK_KEYWORDS = (
        "点击观看","点击播放","点击进入","进入观看","前往观看",
        "观看","播放","视频","立即观看","在线观看","在线播放","完整版","高清",
        "第一弹","第二弹","第三弹","第四弹","第五弹",
        "第六弹","第七弹","第八弹","第九弹","第十弹",
        "第1集","第2集","第3集","第4集","第5集",
        "第6集","第7集","第8集","第9集","第10集",
        "第1话","第2话","第3话","第4话","第5话",
        "episode","watch","play","full",
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

    # ============ 通用关键词匹配 ============
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
# ② 发布页解析器（跳链跟随 + 二级兜底 + 多域探测）
# ==================================================================
class PublishResolver:
    """以一级/二级导航发布页为锚点的自愈解析器。"""

    SKIP_HREF = (
        '.js','.css','.jpg','.jpeg','.png','.gif','.webp','.svg','.ico',
        '.woff','.woff2','.ttf','.eot','.map','mailto:','javascript:','tel:',
        '/sese.html','/ybml.html','/qun.html','/github.html','/telegram.html',
        '/about.html','/contact.html',
    )

    RES_SUFFIX_RE = re.compile(
        r'\.(?:jpg|jpeg|png|gif|webp|svg|ico|bmp|tif|tiff|'
        r'mp4|mp3|m4a|aac|wav|flac|ogg|m3u8|ts|flv|avi|mkv|wmv|mov|webm|'
        r'pdf|zip|rar|7z|tar|gz|bz2|xz|'
        r'txt|log|csv|xml|json|doc|docx|xls|xlsx|ppt|pptx|'
        r'css|js|jsx|ts|tsx|vue|php|asp|jsp|aspx|cgi|pl|rb|py|go|rs|java|'
        r'html|htm|shtml|xhtml|'
        r'woff|woff2|ttf|eot|otf|map|wasm|'
        r'conf|config|ini|yaml|yml|toml|lock|env)$',
        re.I
    )

    DOMAIN_RE = re.compile(
        r'(?<![\w.\-])'
        r'((?:[a-zA-Z0-9](?:[a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?\.)+[a-zA-Z]{2,10})'
        r'(?![\w.\-])'
    )

    # JS/meta 跳转目标提取（取自发布页直达版）
    JUMP_PATTERNS = (
        r'<meta[^>]+http-equiv=["\']?refresh["\']?[^>]*?url\s*=\s*([^"\'>\s]+)',
        r'url\s*=\s*([^"\'>\s;]+)["\'][^>]*http-equiv=["\']?refresh',
        r'(?:window\s*\.\s*)?location(?:\s*\.\s*href)?\s*=\s*["\'](https?://[^"\']+)["\']',
        r'(?:window\s*\.\s*)?location\s*\.\s*(?:replace|assign)\s*\(\s*["\'](https?://[^"\']+)["\']',
        r'(?:var\s+)?(?:url|href|targetUrl|jumpUrl)\s*=\s*["\'](https?://[^"\']+)["\']',
    )

    _ENTRY_CACHE = {}
    _ENTRY_LOCK = threading.Lock()

    def __init__(self, cfg, fetcher, cache_get=None, cache_set=None, cache_del=None):
        self.cfg = cfg
        self.fetch = fetcher
        self.cache_get = cache_get
        self.cache_set = cache_set
        self.cache_del = cache_del

    # ---------- 缓存 ----------
    def _read_cache(self):
        if not self.cache_get:
            return None
        try:
            raw = self.cache_get(self.cfg.HOST_CACHE_KEY)
        except Exception:
            return None
        if not raw:
            return None
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8", "ignore")
        if isinstance(raw, str) and raw.startswith("http"):
            return {"host": raw.rstrip("/"), "ts": 0}
        try:
            if isinstance(raw, str):
                raw = json.loads(raw)
            if isinstance(raw, dict) and raw.get("host"):
                return raw
        except Exception:
            pass
        return None

    def _cache_fresh(self, c):
        ttl = int(getattr(self.cfg, "HOST_CACHE_TTL", 0) or 0)
        if ttl <= 0:
            return True
        return (time.time() - int(c.get("ts") or 0)) < ttl

    def _write_cache(self, host):
        if not self.cache_set:
            return
        try:
            self.cache_set(self.cfg.HOST_CACHE_KEY,
                           json.dumps({"host": host, "ts": int(time.time())}))
        except Exception:
            pass

    def _read_pub_cache(self):
        """导航页缓存：跳转链最终落地页，二次 init 直接复用。"""
        if not self.cache_get:
            return ""
        try:
            raw = self.cache_get(self.cfg.PUB_CACHE_KEY)
        except Exception:
            return ""
        if not raw:
            return ""
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8", "ignore")
        s = str(raw).strip()
        if s.startswith("http"):
            return s.rstrip("/")
        try:
            d = json.loads(s)
            if isinstance(d, dict) and str(d.get("url") or "").startswith("http"):
                ttl = int(getattr(self.cfg, "PUB_CACHE_TTL", 0) or 0)
                if ttl > 0 and time.time() - int(d.get("ts") or 0) >= ttl:
                    return ""
                return str(d["url"]).rstrip("/")
        except Exception:
            pass
        return ""

    def _write_pub_cache(self, url):
        if not self.cache_set or not url:
            return
        try:
            self.cache_set(self.cfg.PUB_CACHE_KEY,
                           json.dumps({"url": url, "ts": int(time.time())}))
        except Exception:
            try:
                self.cache_set(self.cfg.PUB_CACHE_KEY, str(url).rstrip("/"))
            except Exception:
                pass

    def _read_entry_cache(self, src, now):
        with self._ENTRY_LOCK:
            cached = self._ENTRY_CACHE.get(src)
        if not cached:
            return None
        ts, final_h, hosts = cached
        if now - ts >= getattr(self.cfg, "ENTRY_CACHE_TTL", 1800):
            return None
        return final_h, list(hosts)

    def _write_entry_cache(self, src, now, final_h, hosts):
        with self._ENTRY_LOCK:
            self._ENTRY_CACHE[src] = (now, final_h, list(hosts))
            if len(self._ENTRY_CACHE) > 40:
                ordered = sorted(self._ENTRY_CACHE.items(), key=lambda kv: kv[1][0])
                for k, _ in ordered[:len(ordered) - 40]:
                    self._ENTRY_CACHE.pop(k, None)

    # ---------- 基础工具 ----------
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
        has_content = low.count("<article") >= 1 or low.count('class="post') >= 3
        if has_content:
            return False
        hits = sum(1 for kw in getattr(self.cfg, "NAV_PAGE_KEYWORDS", ()) if kw in html)
        return hits >= 3

    def _site_check(self, html):
        """内容站校验：长度 + CF盾 + 导航页特征 + 内容结构/关键词。"""
        if not html:
            return False, "空响应"
        if len(html) < self.cfg.PROBE_MIN_HTML:
            return False, "HTML过短(%d<%d)" % (len(html), self.cfg.PROBE_MIN_HTML)
        if self._is_blocked_page(html):
            return False, "CF/验证页"
        if self._is_nav_page(html):
            return False, "导航页特征"
        low = html.lower()
        has_article = (low.count("<article") >= self.cfg.PROBE_MIN_ARTICLE
                       or low.count("realtime-card") >= self.cfg.PROBE_MIN_ARTICLE
                       or low.count("video-card") >= self.cfg.PROBE_MIN_ARTICLE)
        has_marker  = any(m in low for m in self.cfg.SITE_MARKERS)
        has_keyword = self.cfg.match_keyword(html)
        if not (has_article or has_marker or has_keyword):
            return False, "无内容结构(article=%d,marker=%s,kw=%s)" % (
                low.count("<article"),
                "Y" if has_marker else "N",
                "Y" if has_keyword else "N")
        return True, "OK"

    # ---------- 跳转链跟随（核心：一级发布页 → 二级导航页）----------
    def _extract_jump_targets(self, html, base_url):
        """多策略提取混淆跳转页的真实目标（含 base64 混淆脚本解码）。"""
        if not html:
            return []
        out, seen = [], set()

        def _norm(u):
            try:
                u = unquote(str(u)).strip().strip('"\' ')
            except Exception:
                return ""
            if not u or u.startswith(("javascript:", "data:", "mailto:")):
                return ""
            if u.startswith("//"):
                u = "https:" + u
            if not u.startswith("http"):
                u = urljoin(base_url or "", u)
            low = u.lower()
            if any(bl in low for bl in self.cfg.DOMAIN_BLACKLIST):
                return ""
            try:
                parts = urlparse(u).netloc.lower().split(".")
                if parts and parts[-1] not in self.cfg.VALID_TLDS:
                    return ""
            except Exception:
                return ""
            if u.rstrip("/") == (base_url or "").rstrip("/"):
                return ""
            return u

        texts = [html]
        for b64 in re.finditer(r'["\']([A-Za-z0-9+/=]{40,})["\']', html):
            try:
                d = base64.b64decode(b64.group(1)).decode("utf-8", "ignore")
                if "location" in d or "url" in d or "http" in d:
                    texts.append(d)
            except Exception:
                continue

        last_idx = len(self.JUMP_PATTERNS) - 1
        for t in texts:
            for idx, p in enumerate(self.JUMP_PATTERNS):
                for m in re.finditer(p, t, re.I):
                    # 最后一条通用 var url= 需排除标签内属性误匹配
                    if idx == last_idx:
                        lt, gt = t.rfind("<", 0, m.start()), t.rfind(">", 0, m.start())
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

    def _resolve_publish_chain(self, start_url):
        """抓取发布页并跟随 JS/meta 跳转链，返回 [(最终host, html), ...]。"""
        pages, visited = [], set()
        cur = (start_url or "").rstrip("/") + "/"
        for _ in range(int(getattr(self.cfg, "JUMP_MAX_HOPS", 2)) + 1):
            if not cur or cur in visited:
                break
            visited.add(cur)
            r = self._safe_fetch(cur, self.cfg.PUBLISH_TIMEOUT)
            if r is None or r.status_code != 200:
                break
            html = r.text or ""
            final = self._final_host(r.url) or cur
            pages.append((final, html))
            targets = self._extract_jump_targets(html, final)
            if not targets:
                break
            cur = targets[0].rstrip("/") + "/"
        return pages

    # ---------- 候选域名提取（5 策略，黑白名单 + TLD + 资源后缀过滤）----------
    def _extract_hosts_from_publish(self, html, trusted=True):
        if not html:
            return []
        hosts, seen = [], set()

        pub_like = [u.rstrip("/") for u in list(self.cfg.PUBLISH_URLS)
                    + list(getattr(self.cfg, "PUBLISH_FALLBACK_URLS", []))
                    + list(getattr(self.cfg, "NAV_URLS", []))]

        def _add(h):
            h = self._final_host(h)
            if not h:
                return
            hl = h.lower()
            if any(bl in hl for bl in self.cfg.DOMAIN_BLACKLIST):
                return
            if any(bl in hl for bl in getattr(self.cfg, "EXTRA_BLACKLIST", ())):
                return
            if h.rstrip("/") in pub_like:
                return
            if h in seen:
                return
            seen.add(h)
            hosts.append(h)

        # 策略1 a标签链接
        for m in re.finditer(r'<a\b[^>]+href=["\'](https?://[^"\']+)["\']', html):
            href = m.group(1)
            if any(skip in href for skip in self.SKIP_HREF):
                continue
            _add(href)

        # 策略2 js字符串中的url（过滤静态资源后缀）
        for m in re.finditer(r'["\'](https?://[^"\']+)["\']', html):
            u = m.group(1)
            try:
                if self.RES_SUFFIX_RE.search(urlparse(u).path or ""):
                    continue
            except Exception:
                pass
            _add(u)

        # 策略3 base64混淆脚本（含JSON站点列表）
        for b64_match in re.finditer(r'["\']([A-Za-z0-9+/=]{80,})["\']', html):
            try:
                decoded = base64.b64decode(b64_match.group(1)).decode("utf-8", "ignore")
                if not ("http" in decoded or self.cfg.match_keyword(decoded)):
                    continue
                decoded = unquote(decoded)
                if "[" in decoded and self.cfg.match_keyword(decoded):
                    try:
                        site_list = json.loads(decoded)
                        for item in site_list:
                            if not isinstance(item, dict):
                                continue
                            if not self.cfg.match_keyword(str(item.get("name", ""))):
                                continue
                            u = item.get("url", "")
                            if u:
                                _add(u)
                            for u_obj in (item.get("urls") or []):
                                if isinstance(u_obj, dict) and u_obj.get("url"):
                                    _add(u_obj["url"])
                        continue
                    except Exception:
                        pass
                for m in re.finditer(r'(https?://[^\s"\'\]},]+)', decoded):
                    _add(m.group(1))
            except Exception:
                continue

        # 策略4 中文提示附近域名
        for m in re.finditer(
            r'(?:迁移到|迁移至|新地址|新网址|永久地址|永久域名|最新地址|最新域名|最新入口|最新网址|官方入口|官网入口|请访问|访问地址|线路[一二三四五六七八九十\d]+)'
            r'[：:\s]*((?:https?://)?[a-zA-Z0-9][a-zA-Z0-9.\-]{3,}\.[a-zA-Z]{2,10})',
            html
        ):
            u = m.group(1)
            if not u.startswith("http"):
                u = "https://" + u
            _add(u)

        # 策略5 裸域名扫描（先去邮箱/资源后缀，再走黑白名单）
        text = re.sub(r'\b[\w.\-+]+@[\w.\-]+\b', ' ', html)
        text = self.RES_SUFFIX_RE.sub(' ', text)
        for m in self.DOMAIN_RE.finditer(text):
            d = m.group(1).lower().strip('.')
            parts = d.split('.')
            if len(parts) < 2 or parts[-1] not in self.cfg.VALID_TLDS:
                continue
            if len(parts[0]) < 2 and not trusted:
                continue
            _add("https://" + d)
        return hosts[:20]

    # ---------- GitLab 发布页 raw README ----------
    def _fetch_gitlab_readme(self, src):
        base = src.rstrip("/")
        paths = [
            "/-/raw/master/README.md",
            "/-/raw/main/README.md",
            "/raw/master/README.md",
            "/raw/main/README.md",
        ]
        for p in paths:
            url = base + p
            r = self._safe_fetch(url, self.cfg.PUBLISH_TIMEOUT)
            if r is None:
                continue
            if r.status_code == 200 and r.text:
                print("  [gitlab raw成功] %s 长度=%d" % (url, len(r.text)))
                return r.text
        print("  [gitlab raw失败] %s 所有 raw 路径均失败" % src)
        return ""

    # ---------- 发布页组候选收集（入口缓存 + 并发跳链）----------
    def _collect_from_publish(self, urls, tag="发布页"):
        urls = [u.rstrip("/") + "/" for u in (urls or []) if u]
        if not urls:
            return []
        now = time.time()
        candidates = []
        fresh = []

        # ① 入口缓存
        for u in urls:
            hit = self._read_entry_cache(u, now)
            if hit is None:
                fresh.append(u)
                continue
            final_h, hosts = hit
            print("  [%s缓存] %s → %s | 候选 %d" % (tag, u, final_h or "(无跳转)", len(hosts)))
            candidates.extend(hosts)

        # ② 未命中并发跳链抓取
        if fresh:
            print("--- 并发抓取%s %d 个（跟随跳转链 ≤%d 跳）---"
                  % (tag, len(fresh), self.cfg.JUMP_MAX_HOPS))
            try:
                with ThreadPoolExecutor(max_workers=min(8, len(fresh))) as ex:
                    futs = {ex.submit(self._resolve_publish_chain, u): u for u in fresh}
                    total_timeout = self.cfg.PUBLISH_TIMEOUT * (self.cfg.JUMP_MAX_HOPS + 1) + 10
                    for f in as_completed(futs, timeout=total_timeout):
                        u = futs[f]
                        try:
                            pages = f.result() or []
                        except Exception as e:
                            print("  [%s异常] %s: %s" % (tag, u, e))
                            continue
                        if not pages:
                            print("  [%s失败] %s 无响应或非200" % (tag, u))
                            continue
                        print("  [%s] %s 跳转链: %s"
                              % (tag, u, " → ".join(p[0] for p in pages)))
                        hosts, seen = [], set()
                        for _pu, _ph in pages:
                            for h in self._extract_hosts_from_publish(_ph):
                                if h not in seen:
                                    seen.add(h)
                                    hosts.append(h)
                        print("  [%s] 提取 %d 个候选: %s" % (tag, len(hosts), hosts[:5]))
                        candidates.extend(hosts)
                        self._write_entry_cache(u, now, pages[-1][0], hosts)
                        self._write_pub_cache(pages[-1][0])

                        # GitLab 发布页：追加 raw README 解析
                        if "gitlab.com" in u:
                            readme = self._fetch_gitlab_readme(u)
                            if readme:
                                extra, eseen = [], set()
                                for h in self._extract_hosts_from_publish(readme):
                                    if h not in eseen:
                                        eseen.add(h)
                                        extra.append(h)
                                if extra:
                                    print("  [gitlab] 额外提取 %d 个: %s" % (len(extra), extra[:5]))
                                    candidates.extend(extra)
            except Exception as e:
                LOG.debug("%s 并发异常: %s", tag, e)
        return candidates

    # ---------- 快路径 ----------
    def _fast_probe(self):
        urls = [u.rstrip("/") for u in getattr(self.cfg, "FAST_HOSTS", []) if u]
        if not urls:
            return ""
        results = {}
        try:
            with ThreadPoolExecutor(max_workers=min(8, len(urls))) as ex:
                futs = {ex.submit(self._safe_fetch, u + "/", self.cfg.FAST_TIMEOUT): u
                        for u in urls}
                for f in as_completed(futs, timeout=self.cfg.FAST_TIMEOUT + 6):
                    u = futs[f]
                    try:
                        results[u] = f.result()
                    except Exception:
                        results[u] = None
        except Exception as e:
            LOG.debug("快路径并发异常: %s", e)

        for u in urls:
            r = results.get(u)
            if r is None:
                print("  [快路径] %s 无响应" % u)
                continue
            if r.status_code != 200:
                print("  [快路径] %s HTTP=%s" % (u, r.status_code))
                continue
            ok, reason = self._site_check(r.text)
            if not ok:
                print("  [快路径] %s 不通过: %s" % (u, reason))
                continue
            final = self._final_host(r.url) or u
            print("  [快路径] %s → %s 命中" % (u, final))
            return final
        return ""

    # ---------- 主入口 ----------
    def resolve(self):
        # 1) 有效缓存直验
        cached = self._read_cache()
        if cached and self._cache_fresh(cached):
            r = self._safe_fetch(cached["host"] + "/", self.cfg.FAST_TIMEOUT)
            if r is not None and r.status_code == 200:
                ok, reason = self._site_check(r.text)
                if ok:
                    final = self._final_host(r.url or cached["host"]) or cached["host"]
                    print("缓存有效: %s" % cached["host"]
                          + (" → %s" % final if final != cached["host"] else ""))
                    if final != cached["host"]:
                        self._write_cache(final)
                    return final
                print("缓存失效: %s 原因=%s" % (cached["host"], reason))
            else:
                print("缓存失效: %s 无响应" % cached["host"])

        # 2) 快路径
        fast = self._fast_probe()
        if fast:
            self._write_cache(fast)
            return fast

        candidates = []

        # 3) 导航页缓存快取（上次跳链的落地页，1 次请求直接提取候选）
        pub_cached = self._read_pub_cache()
        if pub_cached:
            r = self._safe_fetch(pub_cached + "/", self.cfg.FAST_TIMEOUT)
            if r is not None and r.status_code == 200:
                hosts = self._extract_hosts_from_publish(r.text or "")
                if hosts:
                    print("[导航页缓存] %s 直接提取 %d 个候选" % (pub_cached, len(hosts)))
                    candidates.extend(hosts)

        # 4) 一级导航发布页（跟随跳转链）
        if not candidates and self.cfg.PUBLISH_URLS:
            candidates = self._collect_from_publish(self.cfg.PUBLISH_URLS, tag="一级发布页")

        # 5) 二级导航发布页兜底（一级全部被拦/解析不到候选时）
        if not candidates and getattr(self.cfg, "PUBLISH_FALLBACK_URLS", []):
            print("[兜底] 一级发布页无候选，加载二级导航发布页")
            candidates = self._collect_from_publish(self.cfg.PUBLISH_FALLBACK_URLS,
                                                    tag="二级发布页")

        # 6) 并入种子与旧缓存
        candidates.extend([u.rstrip("/") for u in getattr(self.cfg, "SEED_HOSTS", [])])
        if cached:
            candidates.insert(0, cached["host"].rstrip("/"))

        seen, queue = set(), []
        for u in candidates:
            u = (u or "").rstrip("/")
            if u and u not in seen:
                seen.add(u)
                queue.append(u)
        queue = queue[:self.cfg.PROBE_MAX_CANDIDATES]

        if not queue:
            print("[诊断] 发布页均未提取到候选域名")
            return self._fallback(cached, "无候选")

        # 7) 多轮并发探测（页面内新域名滚动发现）
        tried = set()
        for round_no in range(1, int(self.cfg.PROBE_MAX_ROUNDS) + 1):
            cur = [u for u in queue if u not in tried]
            if not cur:
                print("第 %d 轮无新候选" % round_no)
                break

            print("=== 第 %d 轮探测: %d 个 ===" % (round_no, len(cur)))
            next_queue = []

            with ThreadPoolExecutor(max_workers=min(8, len(cur))) as ex:
                futs = {ex.submit(self._safe_fetch, u + "/", self.cfg.PROBE_TIMEOUT): u
                        for u in cur}
                try:
                    for f in as_completed(futs, timeout=self.cfg.PROBE_TIMEOUT + 12):
                        u = futs[f]
                        tried.add(u)
                        try:
                            r = f.result()
                        except Exception as e:
                            print("  [失败] %s 异常: %s" % (u, e))
                            continue
                        if r is None:
                            print("  [失败] %s 无响应" % u)
                            continue
                        if r.status_code != 200:
                            print("  [失败] %s HTTP=%s" % (u, r.status_code))
                            loc = (r.headers or {}).get("Location", "")
                            if loc:
                                nh = self._final_host(loc)
                                if nh and nh not in tried and nh not in next_queue:
                                    next_queue.append(nh)
                                    print("    ↳ Location: %s" % nh)
                            continue

                        ok, reason = self._site_check(r.text)
                        if ok:
                            final = self._final_host(r.url or u) or u
                            self._write_cache(final)
                            print("  [成功] %s" % final
                                  + (" (来自 %s)" % u if final != u else ""))
                            return final

                        print("  [不匹配] %s 原因=%s 长度=%d" % (u, reason, len(r.text or "")))
                        for d in self._extract_hosts_from_publish(r.text or ""):
                            if d not in tried and d not in next_queue:
                                next_queue.append(d)
                                print("    ↳ 新候选: %s" % d)
                except Exception as e:
                    LOG.debug("并发异常: %s", e)

            for d in next_queue:
                if d not in tried and d not in queue:
                    queue.append(d)
            if round_no < self.cfg.PROBE_MAX_ROUNDS and next_queue:
                print("第 %d 轮结束，新增 %d 个，进下一轮" % (round_no, len(next_queue)))

        print("[诊断] 已试 %d 个域名，全部失败" % len(tried))
        return self._fallback(cached, "所有轮失败")

    def _fallback(self, cached, reason):
        if cached:
            print("【警告】回退过期缓存: %s" % cached["host"])
            return cached["host"]
        if getattr(self.cfg, "FALLBACK_HOST", None):
            print("【警告】回退 FALLBACK_HOST: %s" % self.cfg.FALLBACK_HOST)
            return self.cfg.FALLBACK_HOST.rstrip("/")
        if getattr(self.cfg, "SEED_HOSTS", []):
            print("【警告】回退 SEED[0]: %s" % self.cfg.SEED_HOSTS[0])
            return self.cfg.SEED_HOSTS[0].rstrip("/")
        if self.cfg.PUBLISH_URLS:
            fb = self.cfg.PUBLISH_URLS[0].rstrip("/")
            print("【警告】回退第一个发布页（这不是内容站）: %s" % fb)
            return fb
        print("【错误】域名探测彻底失败: %s" % reason)
        return ""


# ==================================================================
# ③ 主爬虫基类（标准模板业务逻辑全保留）
# ==================================================================
class BaseSeriesSpider(BaseSpider):
    CONFIG = SiteConfig

    def __init__(self, extend="", *a, **kw):
        try:
            super().__init__(*a, **kw)
        except Exception:
            pass
        self.proxies, self.host, self._img_cache = {}, "", {}

    def init(self, extend=""):
        try:
            self.extend_raw = extend
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
            print("【extend 指定】使用域名: %s" % manual_host)
            self.host = manual_host
        else:
            resolver = PublishResolver(
                self.CONFIG, self._get,
                cache_get=getattr(self, "getCache", None),
                cache_set=getattr(self, "setCache", None),
                cache_del=getattr(self, "delCache", None),
            )
            self.host = resolver.resolve()

        if self.host:
            self.headers.update({"Origin": self.host, "Referer": self.host + "/"})
        print("使用站点: %s" % self.host)

    def getName(self):
        return "🌈 %s|发布页跳链自愈版" % self.CONFIG.SITE_NAME

    def manualVideoCheck(self): return False
    def isVideoFormat(self, u): return any(e in (u or "") for e in (".m3u8", ".mp4", ".ts"))
    def destroy(self):          self._img_cache.clear()

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

    # -------------------- 首页 --------------------
    def homeContent(self, filter=False):
        if not self.host:
            print("[homeContent] self.host 为空，直接返回空列表")
            return {"class": [], "list": []}
        r, data = self._get_soup(self.host)
        if data is None:
            print("[homeContent] 抓取 %s 失败" % self.host)
            return {"class": [], "list": []}
        lst = self._parse_list(data(self.CONFIG.SEL_ARTICLE_HOME))
        if not lst:
            print("[homeContent] 列表解析为空，HTML长度=%d" % len(r.text or ""))
        return {"class": self._parse_classes(data), "list": lst}

    def homeVideoContent(self):
        if not self.host:
            return {"list": []}
        r, data = self._get_soup(self.host)
        if data is None:
            return {"list": []}
        return {"list": self._parse_list(data(self.CONFIG.SEL_ARTICLE_HOME))}

    # -------------------- 分类结构（全合并 + 子目录发现 + 缓存）--------------------
    def _parse_classes(self, data):
        cached = self._read_classes_cache()
        if cached:
            print("[classes] 命中缓存 → %d 个" % len(cached))
            return cached

        classes = self._parse_home_nav(data)
        print("[classes] 首页导航 → %d 个" % len(classes))

        extra = self._scan_category_links(data)
        if extra:
            classes = self._merge_classes(classes, extra)
            print("[classes] 首页链接补充 → %d 个" % len(classes))

        for path in ("/category/", "/categories/", "/category/index/"):
            ov = self._get_soup(self._abs(path),
                                timeout=self.CONFIG.FILTER_PROBE_TIMEOUT)[1]
            if ov is None:
                continue
            ov_classes = self._parse_category_overview(ov)
            if ov_classes:
                classes = self._merge_classes(classes, ov_classes)
                print("[classes] 总览页 %s 补充 → %d 个" % (path, len(classes)))
                break

        if not classes:
            classes = [dict(self.CONFIG.DEFAULT_CATEGORY)]

        try:
            merged = self._augment_with_filters(classes)
            if merged and len(merged) > len(classes):
                print("[classes] 筛选栏合并 %d → %d 个" % (len(classes), len(merged)))
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

    def _parse_home_nav(self, data):
        """遍历所有 SEL_NAV 全合并（不再命中即 break）"""
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
        if not main_categories:
            return main_categories
        targets = [c for c in main_categories
                   if (c.get("type_id") or "") not in ("", "/", "#")]
        if not targets:
            return main_categories

        print("[classes] 并发抓取 %d 个一级分类的筛选栏 ..." % len(targets))
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
        seen = {base_tid, base_tid + "/", tid, "/" + tid.lstrip("/")}

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

    # -------------------- 分类 / 搜索 --------------------
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
        """列表解析：多策略标题识别 + 去重（合并两版之长）。"""
        is_folder = "/mrdg" in (tid or "")
        videos, seen = [], set()
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
            videos.append({
                "vod_id":      vid,
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

    def searchContent(self, key, quick=False, pg=1):
        if not self.host:
            return {"list": [], "page": 1, "pagecount": 1}
        pg = int(pg or 1)
        url = "%s/search/%s/%s" % (self.host, key, ("%d/" % pg) if pg > 1 else "")
        r, data = self._get_soup(url)
        if data is None:
            return {"list": [], "page": pg, "pagecount": 9999}
        return {"list": self._parse_list(data(self.CONFIG.SEL_SEARCH_ARTICLE)),
                "page": pg, "pagecount": 9999}

    # -------------------- 详情 / 播放列表 --------------------
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
                tags.append("[a=cr:%s/]%s[/a]" % (json.dumps({"id": self._abs(h), "name": t}), t))
        if tags:
            return " ".join(tags) + "\n\n" + (data(self.CONFIG.SEL_SUMMARY).text() or "")[:150]
        return data(self.CONFIG.SEL_TITLE).text() or self.CONFIG.PLAY_FALLBACK

    # -------------------- 图片 / 日期 --------------------
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

    # -------------------- 播放 / 代理 --------------------
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
                return [200, "image/jpeg", self.aesimg(res.content)] if res else [404, "text/plain", b""]
            if t == "m3u8":
                return self._m3_proxy(param.get("url"))
            if t == "mkey":
                raw = param.get("url") or ""
                real = raw if raw.startswith("http") else self.d64(raw)
                res = self._get(real, timeout=10)
                return ([200, "application/octet-stream", res.content]
                        if res is not None else [404, "text/plain", b""])
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
        return [200, "video/mp2t", res.content] if res else [404, "text/plain", b""]


# ==================================================================
# ④ 具体站点类
# ==================================================================
class Spider(BaseSeriesSpider):
    CONFIG = SiteConfig

    def getName(self):
        return "🌈 %s|发布页跳链自愈版" % self.CONFIG.SITE_NAME


# ==================================================================
# ⑤ 播放源聚合扩展（同列表视频合成多集播放单，原样保留）
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
