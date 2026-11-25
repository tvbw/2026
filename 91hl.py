# -*- coding: utf-8 -*-
"""
91黑料 · 发布页自愈版（零侵入）
================================
- 前置模块：Config + PublishResolver + auto_install
- Spider 类：原代码一行不改
- 换站：只改 Config 里 [改] 字段
"""
import sys
import json
import re
import time
import base64
import logging
import hashlib
from base64 import b64decode, b64encode
from urllib.parse import urlparse, urljoin, unquote
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
        def getProxyUrl(self):    return ""

try:
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
except Exception:
    pass

img_cache = {}

LOG = logging.getLogger("publish_resolver")
if not LOG.handlers:
    _h = logging.StreamHandler()
    _h.setFormatter(logging.Formatter("[%(name)s] %(message)s"))
    LOG.addHandler(_h)
    LOG.setLevel(logging.INFO)


# ==================================================================
# ① 站点配置（换站只改这里）
# ==================================================================
class Config:
    # ---------- 站点身份 [改] ----------
    SITE_NAME     = "91黑料"
    SITE_KEYWORDS = ["91黑料", "91爆料", "91cg"]
    SITE_MARKERS  = (
        "post-title", "entry-title", "<article",
        'class="post', "realtime-card", "candid-video", "video-card",
    )
    PLAY_FROM = "91吃瓜中心"

    # ---------- 缓存键 [改] ----------
    HOST_CACHE_KEY = "sp91hl_host_v1"
    PUB_CACHE_KEY  = "sp91hl_pub_v1"

    # ---------- 发布页锚点 [改] ----------
    PUBLISH_URLS = [
        "https://91hl7.com/",
    ]
    SECONDARY_PUBLISH_URLS = [
        "https://hl91w.com/",
        "https://91hl6.com/",
    ]
    SEED_HOSTS = []
    FALLBACK_HOST = None

    # ---------- 超时与判定（一般不用改） ----------
    PUBLISH_TIMEOUT   = 12
    PROBE_TIMEOUT     = 12
    FAST_TIMEOUT      = 8
    PROBE_MIN_HTML    = 1500
    PROBE_MIN_ARTICLE = 1
    PROBE_PATHS       = ("/",)
    MAX_JUMP          = 3

    # ---------- TLD / 黑名单（一般不用改） ----------
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
    EXTRA_BLACKLIST = ()

    # ---------- HTTP ----------
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


# ==================================================================
# ② 发布页解析器（无需修改）
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
# ③ 零侵入挂载（Spider 类一行不改）
# ==================================================================
def auto_install(SpiderCls, cfg=None):
    cfg = cfg or Config
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
        # 覆盖所有常见 base url 属性名
        for attr in ("host", "baseUrl", "base_url", "url",
                     "siteUrl", "main_url", "domain", "api"):
            try:
                setattr(self, attr, host)
            except Exception:
                pass
        # headers 补 Origin / Referer
        try:
            if not getattr(self, "headers", None):
                self.headers = dict(cfg.HEADERS)
            self.headers.update({"Origin": host, "Referer": host + "/"})
        except Exception:
            pass
        # proxies 兜底
        try:
            if not hasattr(self, "proxies") or self.proxies is None:
                self.proxies = {}
        except Exception:
            pass

    def _build_extend(extend, host):
        """安全地决定是否把 host 注入 extend，避免污染 proxies JSON"""
        if not host:
            return extend
        if isinstance(extend, dict):
            # 看起来像 proxies（含 http/https/all 键）就不注入
            if any(k in extend for k in ("http", "https", "all")):
                return extend
            d = dict(extend)
            d.setdefault("host", host)
            return d
        if isinstance(extend, str) and extend.strip().startswith("{"):
            try:
                d = json.loads(extend)
                if isinstance(d, dict) and any(k in d for k in ("http", "https", "all")):
                    return extend          # proxies JSON，原样返回
                if isinstance(d, dict):
                    d.setdefault("host", host)
                    return json.dumps(d)
            except Exception:
                pass
            return extend
        if not extend:
            return host                    # 空 extend 才注入 host 字符串
        return extend

    def patched_init(self, extend="", *args, **kwargs):
        # 先解析 host（不依赖 spider 状态，用 cfg.HEADERS）
        host = ""
        try:
            host = _resolve_host(self)
        except Exception as e:
            LOG.warning("自动解析 host 失败: %s", e)

        # 安全注入 extend
        new_extend = _build_extend(extend, host)

        # 调原 init
        if original_init:
            try:
                original_init(self, new_extend, *args, **kwargs)
            except TypeError:
                try:
                    original_init(self, new_extend)
                except TypeError:
                    original_init(self)

        # 事后覆盖 host（覆盖原 init 里写死的旧域名）
        if host:
            _inject(self, host)

    SpiderCls.init = patched_init


# ==================================================================
# ④ 原 Spider 类：一行不改
# ==================================================================
class Spider(BaseSpider):

    def init(self, extend=""):
        try:
            self.proxies = json.loads(extend)
        except:
            self.proxies = {}
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
            'Accept-Language': 'zh-CN,zh;q=0.9',
            'Connection': 'keep-alive',
            'Cache-Control': 'no-cache',
        }
        self.host = self.get_working_host()
        self.headers.update({'Origin': self.host, 'Referer': f"{self.host}/"})
        print(f"使用站点: {self.host}")

    def getName(self):
        return "🌈 91吃瓜中心|终极完美版"

    def isVideoFormat(self, url):
        return any(ext in (url or '') for ext in ['.m3u8', '.mp4', '.ts'])

    def manualVideoCheck(self):
        return False

    def destroy(self):
        global img_cache
        img_cache.clear()

    def get_working_host(self):
        dynamic_urls = [
            'https://hl91w.com/',
            'https://but.vncchqw.cc/',
        ]
        for url in dynamic_urls:
            try:
                response = requests.get(url, headers=self.headers, proxies=self.proxies, timeout=10)
                if response.status_code == 200:
                    return url
            except Exception:
                continue
        return dynamic_urls[0]

    def homeContent(self, filter):
        try:
            response = requests.get(self.host, headers=self.headers, proxies=self.proxies, timeout=15)
            if response.status_code != 200: return {'class': [], 'list': []}
            data = self.getpq(response.text)

            classes = []
            category_selectors = ['.category-list ul li', '.nav-menu li', '.menu li', 'nav ul li']
            for selector in category_selectors:
                for k in data(selector).items():
                    link = k('a')
                    href = (link.attr('href') or '').strip()
                    name = (link.text() or '').strip()
                    if not href or href == '#' or not name: continue
                    classes.append({'type_name': name, 'type_id': href})
                if classes: break

            if not classes:
                classes = [{'type_name': '最新', 'type_id': '/latest/'}, {'type_name': '热门', 'type_id': '/hot/'}]

            return {'class': classes, 'list': self.getlist(data('#index article, article'))}
        except Exception as e:
            return {'class': [], 'list': []}

    def homeVideoContent(self):
        try:
            response = requests.get(self.host, headers=self.headers, proxies=self.proxies, timeout=15)
            if response.status_code != 200: return {'list': []}
            data = self.getpq(response.text)
            return {'list': self.getlist(data('#index article, article'))}
        except Exception as e:
            return {'list': []}

    def categoryContent(self, tid, pg, filter, extend):
        try:
            if '@folder' in tid:
                v = self.getfod(tid.replace('@folder', ''))
                return {'list': v, 'page': 1, 'pagecount': 1, 'limit': 90, 'total': len(v)}

            pg = int(pg) if pg else 1

            if tid.startswith('http'):
                base_url = tid.rstrip('/')
            else:
                path = tid if tid.startswith('/') else f"/{tid}"
                base_url = f"{self.host}{path}".rstrip('/')

            if pg == 1:
                url = f"{base_url}/"
            else:
                url = f"{base_url}/{pg}/"

            response = requests.get(url, headers=self.headers, proxies=self.proxies, timeout=15)
            if response.status_code != 200: return {'list': [], 'page': pg, 'pagecount': 9999, 'limit': 90, 'total': 0}

            data = self.getpq(response.text)
            videos = self.getlist(data('#archive article, #index article, article'), tid)

            return {'list': videos, 'page': pg, 'pagecount': 9999, 'limit': 90, 'total': 999999}
        except Exception as e:
            return {'list': [], 'page': pg, 'pagecount': 9999, 'limit': 90, 'total': 0}

    def detailContent(self, ids):
        try:
            url = ids[0] if ids[0].startswith('http') else f"{self.host}{ids[0]}"
            response = requests.get(url, headers=self.headers, proxies=self.proxies, timeout=15)
            data = self.getpq(response.text)

            plist = []
            used_names = set()
            if data('.dplayer'):
                for c, k in enumerate(data('.dplayer').items(), start=1):
                    try:
                        config_attr = k.attr('data-config')
                        if config_attr:
                            config = json.loads(config_attr)
                            video_url = config.get('video', {}).get('url', '')

                            if video_url:
                                ep_name = ''
                                parent = k.parents().eq(0)
                                for _ in range(4):
                                    if not parent: break
                                    heading = parent.find('h2, h3, h4').eq(0).text().strip()
                                    if heading:
                                        ep_name = heading
                                        break
                                    parent = parent.parents().eq(0)

                                base_name = ep_name if ep_name else f"视频{c}"
                                name = base_name
                                count = 2
                                while name in used_names:
                                    name = f"{base_name} {count}"
                                    count += 1
                                used_names.add(name)

                                plist.append(f"{name}${video_url}")
                    except: continue

            if not plist:
                content_area = data('.post-content, article')
                for i, link in enumerate(content_area('a').items(), start=1):
                    link_text = link.text().strip()
                    link_href = link.attr('href')

                    if link_href and any(kw in link_text for kw in ['点击观看', '观看', '播放', '视频', '第一弹', '第二弹', '第三弹', '第四弹', '第五弹', '第六弹', '第七弹', '第八弹', '第九弹', '第十弹']):
                        ep_name = link_text.replace('点击观看：', '').replace('点击观看', '').strip()
                        if not ep_name: ep_name = f"视频{i}"

                        if not link_href.startswith('http'):
                            link_href = f"{self.host}{link_href}" if link_href.startswith('/') else f"{self.host}/{link_href}"

                        plist.append(f"{ep_name}${link_href}")

            play_url = '#'.join(plist) if plist else f"未找到视频源${url}"

            vod_content = ''
            try:
                tags = []
                seen_names = set()
                seen_ids = set()

                tag_links = data('.tags a, .keywords a, .post-tags a')

                candidates = []
                for k in tag_links.items():
                    title = k.text().strip()
                    href = k.attr('href')
                    if title and href:
                        candidates.append({'name': title, 'id': href})

                candidates.sort(key=lambda x: len(x['name']), reverse=True)

                for item in candidates:
                    name = item['name']
                    id_ = item['id']

                    if id_ in seen_ids: continue

                    is_duplicate = False
                    for seen in seen_names:
                        if name in seen:
                            is_duplicate = True
                            break

                    if not is_duplicate:
                        target = json.dumps({'id': id_, 'name': name})
                        tags.append(f'[a=cr:{target}/]{name}[/a]')
                        seen_names.add(name)
                        seen_ids.add(id_)

                if tags:
                    vod_content = ' '.join(tags)
                else:
                    vod_content = data('.post-title').text()
            except Exception:
                vod_content = '获取标签失败'

            if not vod_content:
                vod_content = data('h1').text() or '91吃瓜中心'

            return {'list': [{'vod_play_from': '91吃瓜中心', 'vod_play_url': play_url, 'vod_content': vod_content}]}
        except:
            return {'list': [{'vod_play_from': '91吃瓜中心', 'vod_play_url': '获取失败'}]}

    def searchContent(self, key, quick, pg="1"):
        try:
            pg = int(pg) if pg else 1

            if pg == 1:
                url = f"{self.host}/search/{key}/"
            else:
                url = f"{self.host}/search/{key}/{pg}/"

            response = requests.get(url, headers=self.headers, proxies=self.proxies, timeout=15)
            return {'list': self.getlist(self.getpq(response.text)('article')), 'page': pg, 'pagecount': 9999}
        except:
            return {'list': [], 'page': pg, 'pagecount': 9999}

    def playerContent(self, flag, id, vipFlags):
        parse = 0 if self.isVideoFormat(id) else 1
        url = self.proxy(id) if '.m3u8' in id else id
        return {'parse': parse, 'url': url, 'header': self.headers}

    def localProxy(self, param):
        try:
            type_ = param.get('type')
            url = param.get('url')
            if type_ == 'cache':
                key = param.get('key')
                if content := img_cache.get(key):
                    return [200, 'image/jpeg', content]
                return [404, 'text/plain', b'Expired']
            elif type_ == 'img':
                real_url = self.d64(url) if not url.startswith('http') else url
                res = requests.get(real_url, headers=self.headers, proxies=self.proxies, timeout=10)
                content = self.aesimg(res.content)
                return [200, 'image/jpeg', content]
            elif type_ == 'm3u8':
                return self.m3Proxy(url)
            else:
                return self.tsProxy(url)
        except:
            return [404, 'text/plain', b'']

    def proxy(self, data, type='m3u8'):
        if data and self.proxies: return f"{self.getProxyUrl()}&url={self.e64(data)}&type={type}"
        return data

    def m3Proxy(self, url):
        url = self.d64(url)
        res = requests.get(url, headers=self.headers, proxies=self.proxies)
        data = res.text
        base = res.url.rsplit('/', 1)[0]
        lines = []
        for line in data.split('\n'):
            if '#EXT' not in line and line.strip():
                if not line.startswith('http'):
                    line = f"{base}/{line}"
                lines.append(self.proxy(line, 'ts'))
            else:
                lines.append(line)
        return [200, "application/vnd.apple.mpegurl", '\n'.join(lines)]

    def tsProxy(self, url):
        return [200, 'video/mp2t', requests.get(self.d64(url), headers=self.headers, proxies=self.proxies).content]

    def e64(self, text):
        return b64encode(str(text).encode()).decode()

    def d64(self, text):
        return b64decode(str(text).encode()).decode()

    def aesimg(self, data):
        if len(data) < 16: return data
        keys = [(b'f5d965df75336270', b'97b60394abc2fbe1'), (b'75336270f5d965df', b'abc2fbe197b60394')]
        for k, v in keys:
            try:
                dec = unpad(AES.new(k, AES.MODE_CBC, v).decrypt(data), 16)
                if dec.startswith(b'\xff\xd8') or dec.startswith(b'\x89PNG'): return dec
            except: pass
            try:
                dec = unpad(AES.new(k, AES.MODE_ECB).decrypt(data), 16)
                if dec.startswith(b'\xff\xd8'): return dec
            except: pass
        return data

    def getlist(self, data, tid=''):
        videos = []
        is_folder = '/mrdg' in (tid or '')
        for k in data.items():
            card_html = k.outer_html() if hasattr(k, 'outer_html') else str(k)
            a = k if k.is_('a') else k('a').eq(0)
            href = a.attr('href')
            title = k('h2').text() or k('.entry-title').text() or k('.post-title').text()
            if not title and k.is_('a'): title = k.text()

            if href and title:
                img = self.getimg(k('script').text(), k, card_html)
                videos.append({
                    'vod_id': f"{href}{'@folder' if is_folder else ''}",
                    'vod_name': title.strip(),
                    'vod_pic': img,
                    'vod_remarks': k('time').text() or '',
                    'vod_tag': 'folder' if is_folder else '',
                    'style': {"type": "rect", "ratio": 1.33}
                })
        return videos

    def getfod(self, id):
        url = f"{self.host}{id}"
        data = self.getpq(requests.get(url, headers=self.headers, proxies=self.proxies).text)
        videos = []
        for i, h2 in enumerate(data('.post-content h2').items()):
            p_txt = data('.post-content p').eq(i * 2)
            p_img = data('.post-content p').eq(i * 2 + 1)
            p_html = p_img.outer_html() if hasattr(p_img, 'outer_html') else str(p_img)
            videos.append({
                'vod_id': p_txt('a').attr('href'),
                'vod_name': p_txt.text().strip(),
                'vod_pic': self.getimg('', p_img, p_html),
                'vod_remarks': h2.text().strip()
            })
        return videos

    def getimg(self, text, elem=None, html_content=None):
        if m := re.search(r"loadBannerDirect\('([^']+)'", text or ''):
            return self._proc_url(m.group(1))

        if html_content is None and elem is not None:
             html_content = elem.outer_html() if hasattr(elem, 'outer_html') else str(elem)
        if not html_content: return ''

        html_content = html_content.replace('&quot;', '"').replace('&apos;', "'").replace('&amp;', '&')

        if 'data:image' in html_content:
            m = re.search(r'(data:image/[a-zA-Z0-9+/=;,]+)', html_content)
            if m: return self._proc_url(m.group(1))

        m = re.search(r'(https?://[^"\'\s)]+\.(?:jpg|png|jpeg|webp))', html_content, re.I)
        if m: return self._proc_url(m.group(1))

        if 'url(' in html_content:
            m = re.search(r'url\s*\(\s*[\'"]?([^"\'\)]+)[\'"]?\s*\)', html_content, re.I)
            if m: return self._proc_url(m.group(1))

        return ''

    def _proc_url(self, url):
        if not url: return ''
        url = url.strip('\'" ')
        if url.startswith('data:'):
            try:
                _, b64_str = url.split(',', 1)
                raw = b64decode(b64_str)
                if not (raw.startswith(b'\xff\xd8') or raw.startswith(b'\x89PNG') or raw.startswith(b'GIF8')):
                    raw = self.aesimg(raw)
                key = hashlib.md5(raw).hexdigest()
                img_cache[key] = raw
                return f"{self.getProxyUrl()}&type=cache&key={key}"
            except: return ""
        if not url.startswith('http'):
            url = f"{self.host}{url}" if url.startswith('/') else f"{self.host}/{url}"
        return f"{self.getProxyUrl()}&url={self.e64(url)}&type=img"

    def getpq(self, data):
        try: return pq(data)
        except: return pq(data.encode('utf-8'))


# ==================================================================
# ⑤ 挂载：必须放在 Spider 类定义之后
# ==================================================================
auto_install(Spider, Config)
