# -*- coding: utf-8 -*-
"""
51大赛 · 使用【导航探测标准模板v2】域名自愈，原有网页/目录/播放业务逻辑完全保留
源文件：51cg1.py
变更：移除原有自定义PublishResolver，接入标准模板PublishResolver+auto_install；网址沿用51cg1原始配置，业务解析全部不动
"""
import json
import re
import sys
import time
import base64
import hashlib
import logging
from urllib.parse import unquote, urlparse, urljoin
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
LOG = logging.getLogger("publish_resolver")
if not LOG.handlers:
    _h = logging.StreamHandler()
    _h.setFormatter(logging.Formatter("[%(name)s] %(message)s"))
    LOG.addHandler(_h)
    LOG.setLevel(logging.INFO)

# ==================================================================
# ① Config类：融合【标准探测模板配置】+【51cg1原有全部业务配置】
# 注意：PUBLISH_URLS / SEED_HOSTS 沿用51cg1原始网址，不修改！
# ==================================================================
class Config:
    # ----------------------【导航探测标准模板配置】----------------------
    SITE_NAME     = "51吃瓜1"
    SITE_KEYWORDS = ["51吃瓜1", "51cg"]
    PLAY_FROM = "51吃瓜1"
    PLAY_FALLBACK_TITLE  = "51吃瓜1"

    HOST_CACHE_KEY = "51cg_host_v1"
    PUB_CACHE_KEY  = "51cg_pub_v1"

    # ========== 按照业务优先级填入网址 ==========
    # PUBLISH_URLS：二级【真正发布页导航页，有效期约6个月】主发布源
    PUBLISH_URLS = [
        "https://www.sunkdjlla.cc/",
        "https://www.gvhafcbw.cc/",
    ]
    # SECONDARY_PUBLISH_URLS：一级【跳转域名，保底，有效期约1年，会跳转至二级发布页】
    SECONDARY_PUBLISH_URLS = [
        "https://51cgf24.com/",
    ]
    # SEED_HOSTS：三级【直达内容站，速度最快，有效期最短约1个月，优先直接探测】
    SEED_HOSTS = [
        "https://d2bklv1j32lvpc.cloudfront.net/",
    ]
    FALLBACK_HOST = None

    # 探测超时参数（模板标准）
    PUBLISH_TIMEOUT   = 12
    PROBE_TIMEOUT     = 12
    FAST_TIMEOUT      = 8
    PROBE_MIN_HTML    = 1500
    PROBE_MIN_ARTICLE = 1
    PROBE_PATHS       = ("/",)
    MAX_JUMP          = 3   # 跳转链最大追踪层数，满足 一级域名跳转→二级发布页 的跳转需求

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
    EXTRA_BLACKLIST = ('beian.miit.gov.cn', 'w3.org', 'example.com')

    VERIFY_SSL = False
    @classmethod
    def match_keyword(cls, text):
        if not text:
            return False
        for kw in cls.SITE_KEYWORDS:
            try:
                if hasattr(kw, "search"):
                    if kw.search(text):
                        return True
                elif kw and kw in text:
                    return True
            except Exception:
                continue
        return False

    # ----------------------【51cg1原有全部业务配置，完整保留不动】----------------------
    SITE_MARKERS = [
        "post-title", "entry-title", "<article", 'class="post',
        "realtime-card", "candid-video", "video-card",
    ]
    NAV_PAGE_KEYWORDS = (
        "线路一", "线路二", "线路三", "推荐访问", "线路正常",
        "官方导航", "发布页", "备用线路", "地址发布页", "永久地址", "最新地址",
    )
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
    SEL_NAV_ROOT = "ul.navbar-nav.mr-auto"
    SEL_NAV_ITEM = "li.nav-item"
    SEL_NAV_LINK = "a.nav-link"
    SEL_NAV_TOGGLE = "button.nav-link"
    SEL_SUB_MENU_ITEM = "li.dropdown-item a"
    NAV_VALID_PREFIXES = ("/category/",)
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
    
# ==================================================================
# ②【完整复制导航探测标准模板】PublishResolver，零修改
# ==================================================================
class PublishResolver:
    META_REFRESH_RE = re.compile(
        r'<meta[^>]+http-equiv\s*=\s*["\']?refresh["\']?[^>]*?'
        r'content\s*=\s*["\']?\s*\d+\s*;\s*url\s*=\s*([^"\'>\s]+)',
        re.I,
    )
    JS_LOCATION_RE = re.compile(
        r'(?:window\.|document\.|top\.)?location(?:\.href)?\s*=\s*["\']([^"\']+)["\']'
        r'|'
        r'(?:window\.|document\.|top\.)?location\.(?:replace|assign)\s*\(\s*["\']([^"\']+)["\']',
        re.I,
    )
    def __init__(self, cfg, fetcher, cache_get=None, cache_set=None, logger=None):
        self.cfg = cfg
        self.fetch = fetcher
        self.cache_get = cache_get
        self.cache_set = cache_set
        self.log = logger or LOG
        self._publish_origins = set()
        for u in list(cfg.PUBLISH_URLS) + list(cfg.SECONDARY_PUBLISH_URLS):
            o = self._origin(u)
            if o:
                self._publish_origins.add(o)
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
    def _normalize_url(u, base_url=""):
        u = unquote(str(u or "")).strip().strip('"\' ')
        if not u:
            return ""
        u = u.replace("\\/", "/")
        if u.startswith("//"):
            u = "https:" + u
        if not u.startswith("http"):
            u = urljoin(base_url or "", u)
        return u
    def _is_publish_origin(self, url):
        o = self._origin(url)
        return bool(o and o in self._publish_origins)
    def _fetch(self, url, timeout=None, allow_redirects=True):
        try:
            return self.fetch(url, timeout=timeout, allow_redirects=allow_redirects)
        except TypeError:
            try:
                return self.fetch(url, timeout=timeout)
            except Exception as e:
                self.log.debug("fetch 异常 %s: %s", url, e)
                return None
        except Exception as e:
            self.log.debug("fetch 异常 %s: %s", url, e)
            return None
    def _is_blocked(self, html):
        if not html:
            return False
        low = html.lower()
        markers = (
            'just a moment', 'cf-browser-verification', 'cf-challenge',
            'checking your browser', '__cf_chl_', 'ddos-guard',
            'cf-ray', 'cloudflare-nginx', 'enable javascript and cookies',
            '请开启 javascript', '请启用 javascript', '请稍候',
        )
        return any(m in low for m in markers)
    def _site_ok(self, html):
        if not html or len(html) < self.cfg.PROBE_MIN_HTML:
            return False
        if self._is_blocked(html):
            return False
        low = html.lower()
        article_cnt = low.count("<article")
        marker_hit = any((m.lower() in low) for m in self.cfg.SITE_MARKERS)
        has_article = (article_cnt >= self.cfg.PROBE_MIN_ARTICLE) or marker_hit
        return has_article or self.cfg.match_keyword(html)
    def _looks_like_publish(self, html):
        if not html:
            return False
        markers = ('发布页', '最新地址', '永久地址', '新地址',
                   '收藏本站', '请收藏', '防走失', '导航页')
        return any(m in html for m in markers)
    def _extract_candidates(self, html, base_url=""):
        if not html:
            return []
        html = html[:100000]
        hosts, seen = [], set()
        def _add(raw):
            h = self._normalize_url(raw, base_url)
            h = self._origin(h)
            if not h:
                return
            hl = h.lower()
            if any(b in hl for b in self.cfg.DOMAIN_BLACKLIST):
                return
            if any(b in hl for b in getattr(self.cfg, "EXTRA_BLACKLIST", ())):
                return
            if self._is_publish_origin(h):
                return
            if h in seen:
                return
            seen.add(h)
            hosts.append(h)
        for m in re.finditer(r'<a\b[^>]+href=["\']([^"\']+)["\']', html, re.I):
            _add(m.group(1))
        for m in re.finditer(r'https?://[^\s"\'<>()\[\]{},;]+', html):
            _add(m.group(0))
        for m in re.finditer(r'["\'](https?://[^"\']+)["\']', html):
            _add(m.group(1))
        for b64_match in re.finditer(r'["\']([A-Za-z0-9+/=]{80,})["\']', html):
            try:
                decoded = base64.b64decode(b64_match.group(1)).decode("utf-8", "ignore")
                for m in re.finditer(r'(https?://[^\s"\']+)', decoded):
                    _add(m.group(1))
            except Exception:
                continue
        for m in re.finditer(
            r'(?:新地址|新网址|永久地址|最新地址|最新域名|官方入口|请访问|访问地址|'
            r'线路[一二三四五六七八九十\d]+)[：:\s]*'
            r'((?:https?://)?[a-zA-Z0-9][a-zA-Z0-9.\-]{3,}\.[a-zA-Z]{2,10})',
            html
        ):
            u = m.group(1)
            if not u.startswith("http"):
                u = "https://" + u
            _add(u)
        for m in re.finditer(
            r'(?<![\w.\-])((?:[a-zA-Z0-9](?:[a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?\.)+[a-zA-Z]{2,10})(?![\w.\-])',
            html
        ):
            d = m.group(1).lower().strip('.')
            if d.split('.')[-1] not in self.cfg.VALID_TLDS:
                continue
            _add("https://" + d)
        return hosts[:30]
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
    def _resolve_publish_chain(self, start_url):
        cur = start_url.rstrip("/") + "/"
        visited = set()
        last_publish = ""
        candidates = []
        for _ in range(self.cfg.MAX_JUMP + 1):
            if not cur or cur in visited:
                break
            visited.add(cur)
            r = self._fetch(cur, self.cfg.PUBLISH_TIMEOUT, allow_redirects=True)
            if r is None or r.status_code != 200:
                break
            final_url = (getattr(r, "url", None) or cur).rstrip("/") + "/"
            html = r.text or ""
            if not self._is_publish_origin(final_url) and self._site_ok(html):
                return [final_url], ""
            if self._is_publish_origin(final_url) or self._looks_like_publish(html):
                last_publish = final_url
                candidates.extend(self._extract_candidates(html, final_url))
                jump = self._extract_html_jump(html, final_url)
                if jump and (jump.rstrip("/") + "/") not in visited:
                    cur = jump
                    continue
                break
            candidates.extend(self._extract_candidates(html, final_url))
            break
        seen, uniq = set(), []
        for c in candidates:
            c = c.rstrip("/")
            if c and c not in seen:
                seen.add(c)
                uniq.append(c)
        return uniq, last_publish
    def _probe_one(self, host, timeout=None):
        base = self._origin(host) or host.rstrip("/")
        if not base:
            return ""
        paths = self.cfg.PROBE_PATHS or ("/",)
        for path in paths:
            if not path.startswith("/"):
                path = "/" + path
            url = base + path
            r = self._fetch(url, timeout or self.cfg.PROBE_TIMEOUT,
                            allow_redirects=True)
            if r is None or r.status_code != 200:
                continue
            if not self._site_ok(r.text):
                continue
            final = self._origin(getattr(r, "url", None) or base) or base
            if self._is_publish_origin(final):
                continue
            return final
        return ""
    def _probe_hosts(self, hosts):
        if not hosts:
            return ""
        try:
            ex = ThreadPoolExecutor(max_workers=min(8, len(hosts)))
        except Exception:
            return ""
        try:
            futs = {ex.submit(self._probe_one, h): h for h in hosts}
            try:
                for f in as_completed(futs, timeout=self.cfg.PROBE_TIMEOUT + 5):
                    try:
                        hit = f.result()
                    except Exception:
                        continue
                    if hit:
                        self.log.info("[探测] 命中 %s", hit)
                        for x in futs:
                            x.cancel()
                        return hit
            except Exception:
                pass
        finally:
            try:
                ex.shutdown(wait=False)
            except Exception:
                pass
        return ""
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
            raw = raw.decode("utf-8", "ignore")
        if isinstance(raw, dict):
            return str(raw.get(field) or "").strip()
        s = str(raw).strip()
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
            d = dict(data)
            d.setdefault("ts", int(time.time()))
            self.cache_set(key, json.dumps(d))
        except Exception:
            pass
    def resolve(self):
        cached_host = self._read_cache(self.cfg.HOST_CACHE_KEY, "host")
        if cached_host and not self._is_publish_origin(cached_host):
            hit = self._probe_one(cached_host, self.cfg.FAST_TIMEOUT)
            if hit:
                self.log.info("[HOST缓存] 有效: %s", hit)
                if hit != cached_host:
                    self._write_cache(self.cfg.HOST_CACHE_KEY, {"host": hit})
                return hit
            self.log.info("[HOST缓存] 失效: %s", cached_host)
        pub_cached = self._read_cache(self.cfg.PUB_CACHE_KEY, "pub")
        if pub_cached:
            r = self._fetch(pub_cached.rstrip("/") + "/",
                            self.cfg.FAST_TIMEOUT, allow_redirects=True)
            if r is not None and r.status_code == 200:
                final_url = (getattr(r, "url", None) or pub_cached).rstrip("/")
                if not self._is_publish_origin(final_url) and self._site_ok(r.text):
                    self.log.info("[PUB缓存] 直达内容站: %s", final_url)
                    self._write_cache(self.cfg.HOST_CACHE_KEY, {"host": final_url})
                    return final_url
                hit = self._probe_hosts(
                    self._extract_candidates(r.text or "", final_url))
                if hit:
                    self.log.info("[PUB缓存] %s → 命中 %s", pub_cached, hit)
                    self._write_cache(self.cfg.HOST_CACHE_KEY, {"host": hit})
                    return hit
            self.log.info("[PUB缓存] 失效: %s", pub_cached)
        for pub_url in self.cfg.PUBLISH_URLS:
            self.log.info("[一级页] 解析: %s", pub_url)
            cands, pub_final = self._resolve_publish_chain(pub_url)
            if pub_final:
                self._write_cache(self.cfg.PUB_CACHE_KEY, {"pub": pub_final})
            hit = self._probe_hosts(cands)
            if hit:
                self.log.info("[一级页] 命中: %s", hit)
                self._write_cache(self.cfg.HOST_CACHE_KEY, {"host": hit})
                return hit
        for fb_url in self.cfg.SECONDARY_PUBLISH_URLS:
            self.log.info("[二级页] 解析: %s", fb_url)
            cands, pub_final = self._resolve_publish_chain(fb_url)
            if pub_final:
                self._write_cache(self.cfg.PUB_CACHE_KEY, {"pub": pub_final})
            hit = self._probe_hosts(cands)
            if hit:
                self.log.info("[二级页] 命中: %s", hit)
                self._write_cache(self.cfg.HOST_CACHE_KEY, {"host": hit})
                return hit
        if self.cfg.SEED_HOSTS:
            self.log.info("[SEED] 探测 %d 个种子", len(self.cfg.SEED_HOSTS))
            hit = self._probe_hosts(list(self.cfg.SEED_HOSTS))
            if hit:
                self._write_cache(self.cfg.HOST_CACHE_KEY, {"host": hit})
                return hit
        if cached_host and not self._is_publish_origin(cached_host):
            self.log.warning("[回退] 过期 HOST 缓存: %s", cached_host)
            return cached_host
        if self.cfg.FALLBACK_HOST:
            fb = self.cfg.FALLBACK_HOST.rstrip("/")
            self.log.warning("[回退] FALLBACK_HOST: %s", fb)
            return fb
        self.log.error("[失败] 未解析到可用内容站")
        return ""

# ==================================================================
# ③【完整复制导航探测标准模板】auto_install 挂载函数
# ==================================================================
def auto_install(SpiderCls, cfg=None):
    cfg = cfg or Config
    if getattr(SpiderCls, "_auto_install_done", False):
        return
    SpiderCls._auto_install_done = True
    original_init = getattr(SpiderCls, "init", None)
    def _resolve_host(self):
        def _fetch(url, timeout=None, allow_redirects=True):
            try:
                return requests.get(
                    url,
                    headers=getattr(self, "headers", None) or dict(cfg.HEADERS),
                    proxies=getattr(self, "proxies", None) or {},
                    timeout=timeout or cfg.PROBE_TIMEOUT,
                    verify=getattr(cfg, "VERIFY_SSL", False),
                    allow_redirects=allow_redirects,
                )
            except Exception:
                return None
        resolver = PublishResolver(
            cfg, _fetch,
            cache_get=getattr(self, "getCache", None),
            cache_set=getattr(self, "setCache", None),
        )
        return resolver.resolve()
    def _inject(self, host):
        for attr in ("host", "baseUrl", "base_url", "url",
                     "siteUrl", "main_url", "domain", "api"):
            if hasattr(self, attr):
                try:
                    setattr(self, attr, host)
                except Exception:
                    pass
        try:
            self.host = host
        except Exception:
            pass
        try:
            if not getattr(self, "headers", None):
                self.headers = dict(cfg.HEADERS)
            self.headers.update({"Origin": host, "Referer": host + "/"})
        except Exception:
            pass
        try:
            if not hasattr(self, "proxies") or self.proxies is None:
                self.proxies = {}
        except Exception:
            pass
        for hook_name in ("_detect_cdn_host", "_on_host_injected", "_after_host_inject"):
            hook = getattr(self, hook_name, None)
            if callable(hook):
                try:
                    hook()
                except Exception as e:
                    LOG.debug("%s 执行失败: %s", hook_name, e)
    def _is_proxies_like(d):
        return isinstance(d, dict) and any(k in d for k in ("http", "https", "all"))
    def _build_extend(extend, host):
        if not host:
            return extend
        if isinstance(extend, dict):
            if _is_proxies_like(extend):
                return extend
            d = dict(extend)
            d.setdefault("host", host)
            return d
        if isinstance(extend, str) and extend.strip().startswith("{"):
            try:
                d = json.loads(extend)
                if _is_proxies_like(d):
                    return extend
                if isinstance(d, dict):
                    d.setdefault("host", host)
                    return json.dumps(d)
            except Exception:
                pass
            return extend
        if not extend:
            return host
        return extend
    def _early_parse_proxies(self, extend):
        try:
            if isinstance(extend, dict) and _is_proxies_like(extend):
                self.proxies = dict(extend)
            elif isinstance(extend, str) and extend.strip().startswith("{"):
                d = json.loads(extend)
                if _is_proxies_like(d):
                    self.proxies = d
        except Exception:
            pass
    def patched_init(self, extend="", *args, **kwargs):
        _early_parse_proxies(self, extend)
        host = ""
        raw_extend = {}
        if isinstance(extend, dict):
            raw_extend = dict(extend)
        elif isinstance(extend, str) and extend.strip().startswith("{"):
            try:
                raw_extend = json.loads(extend)
            except Exception:
                raw_extend = {}
        manual = ""
        if isinstance(raw_extend, dict):
            manual = raw_extend.get("host", "") or ""
        if not manual and isinstance(extend, str) and extend.strip().startswith("http"):
            manual = extend.strip()
        if manual:
            manual = manual.strip().rstrip("/")
            if not manual.startswith("http"):
                manual = "https://" + manual
            host = manual
            print(f"【extend 指定】使用域名: {manual}")
        else:
            try:
                host = _resolve_host(self)
            except Exception as e:
                LOG.warning("自动解析 host 失败: %s", e)
        new_extend = _build_extend(extend, host)
        if original_init:
            try:
                original_init(self, new_extend, *args, **kwargs)
            except TypeError:
                try:
                    original_init(self, new_extend)
                except TypeError:
                    original_init(self)
        if host:
            _inject(self, host)
            try:
                print(f"使用站点: {host}")
            except Exception:
                pass
    SpiderCls.init = patched_init

# ==================================================================
# ④ Spider类：全部沿用51cg1业务代码；删除旧PublishResolver、删除get_working_host方法
# init本体仅重置缓存，探测逻辑交给auto_install的patched_init接管
# 二级目录平铺解析、列表、详情、播放、图片解密、搜索全部原样不动
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
        # 仅重置内部缓存；域名探测、extend解析全部交给auto_install的patched_init
        self._img_cache = {}
        self._page_cache = {}
        self._page_index = {}
        self._page_keys = []
        self._detail_cache = {}
        self.proxies = {}

    def getName(self):
        return "🍉%s|发布页直达版" % self.CONFIG.SITE_NAME
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
    def _request(self, url, timeout=None,** kw):
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
        """一级 + 二级目录平铺：
        - 遍历主导航根节点下的一级 li（含直接链接项和下拉项）
        - 下拉项取其 ul.dropdown-menu 里的二级链接，全部平铺进 classes
        - 仅保留站内的 /category/ 内容栏目，自动剔除广告、TG、活动页等干扰链接
        """
        classes, seen = [], set()
        C = self.CONFIG
        def _clean_name(name):
            return " ".join(str(name or "").split())
        def _add(href, name, parent=""):
            href = (href or "").strip()
            name = _clean_name(name)
            if not href or not name or href == "#":
                return
            low = href.lower()
            if low.startswith(("javascript:", "mailto:", "tel:", "data:")):
                return
            # 只保留站内路径，剔除 t.me / 联盟广告等站外链接
            if not low.startswith("/"):
                return
            # 只保留“首页”与内容栏目（/category/ 前缀），剔除 share.html、
            # archives 单页、wish/contribute 等功能页、TG/联盟广告等站外链接
            if href.rstrip("/") != "" and not any(low.startswith(p) for p in C.NAV_VALID_PREFIXES):
                return
            if not href.startswith("http"):
                href = "/" + href.lstrip("/")
            if href in seen:
                return
            seen.add(href)
            # 重名栏目用父级名区分，如“官方活动”下若有同名子项
            show = name
            if any(c["type_name"] == show for c in classes) and parent:
                show = "%s·%s" % (parent, name)
            classes.append({"type_name": show, "type_id": href})
        root = data(C.SEL_NAV_ROOT).eq(0)
        if root.length:
            for li in root.children(C.SEL_NAV_ITEM).items():
                # 一级项名称：直接 <a> 或 <button>（下拉开关）里的文字
                a = li.children(C.SEL_NAV_LINK).eq(0)
                btn = li.children(C.SEL_NAV_TOGGLE).eq(0)
                menu = li("ul.dropdown-menu")
                if menu.length:
                    # 下拉容器：取父级名，平铺其全部二级链接
                    parent = _clean_name(
                        (a.text() or "").strip() or (btn.text() or "").strip()
                        or (li("button.nav-link div").eq(0).text() or "").strip())
                    for sa in menu(C.SEL_SUB_MENU_ITEM).items():
                        _add(sa.attr("href"),
                             (sa.attr("title") or "").strip() or (sa.text() or "").strip(),
                             parent)
                else:
                    # 一级直链（如 首页 / 今日吃瓜 / AI成人短剧）
                    _add(a.attr("href"),
                         (a.attr("title") or "").strip() or (a.text() or "").strip())
        # 兜底：兼容旧结构（个别版本没有 mr-auto 根节点）
        if not classes:
            for sel in C.SEL_NAV + C.SEL_SUB_NAV:
                try:
                    for a in data(sel).items():
                        _add(a.attr("href"),
                             (a.attr("title") or "").strip() or (a.text() or "").strip())
                except Exception:
                    continue
                if classes:
                    break
        # 去重后保证“首页”在前
        uniq, seen_names = [], set()
        for c in classes:
            if c["type_id"] in seen_names:
                continue
            seen_names.add(c["type_id"])
            uniq.append(c)
        if any(c["type_id"] == "/" for c in uniq):
            uniq = ([c for c in uniq if c["type_id"] == "/"] +
                    [c for c in uniq if c["type_id"] != "/"])
        if not uniq:
            uniq = [dict(C.DEFAULT_CATEGORY)]
        return uniq
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
            base = re.sub(r"/page/\d+/?$", "", base.rstrip("/"))
            return "%s/page/%d/" % (base, pg)
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
               else "%s/search/%s/page/%d/" % (self.host, key, pg))
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

# =========【文件末尾必须执行补丁，完成Spider.init包装】=========
auto_install(Spider, Config)
