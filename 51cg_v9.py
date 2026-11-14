# -*- coding: utf-8 -*-
"""
51吃瓜 · 多域自愈 + 播放页关联推荐 融合版
=========================================
整合来源：
  - 51new.txt：多域名自愈探测链（导航页 → 发布页 → 种子 → 回流）
  - 51old.txt：站点抓取与播放解析逻辑（列表、详情、DPlayer、图片 AES）

新增：
  - 播放页关联推荐：将详情页中的相关文章作为“线路”挂入播放列表，
    在播放器选集/线路弹窗中可直接切换，无需退出播放画面。

换站只需修改 SiteConfig 中的四段：
  NAV_URLS / PUBLISH_URLS / SEED_HOSTS / SITE_KEYWORDS
"""
import json
import re
import sys
import time
import base64
import hashlib
import logging
from base64 import b64decode, b64encode
from urllib.parse import quote, unquote, urlparse
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
# ① 配置层（换站只改这一段）
# ==================================================================
class SiteConfig:
    # ---- 导航页（从 51new 保留） ----
    NAV_URLS = [
        "https://51cgo25.com",
        "https://51cge23.com",
        "https://51cge26.com",
        "https://51cgf25.com",
        "https://51cgo22.com",
        "https://51cgo23.com",
        "https://51cgo24.com",
    ]

    # ---- 发布页 / 永久锚点（从 51new 保留） ----
    PUBLISH_URLS = [
        "https://51cgo20.com",
        "https://51cgo21.com",
        "https://51cge20.com",
        "https://51cge21.com",
        "https://51cge22.com",
        "https://51cge24.com",
        "https://51cge25.com",
    ]

    # ---- 种子域名（从 51new 保留） ----
    SEED_HOSTS = [
        "https://belt.wxxqhhht.cc/",
        "https://capture.wxxqhhht.cc/",
        "https://both.wxxqhhht.cc/",
        "https://attract.wxxqhhht.cc/",
        "https://achieve.wxxqhhht.cc/",
        "https://bridge.wxxqhhht.cc/",
    ]

    FALLBACK_HOST  = None
    HOST_CACHE_KEY = "51cg_host_v10.0"
    HOST_CACHE_TTL = 6 * 3600

    PROBE_TIMEOUT        = 10
    PROBE_MIN_HTML       = 1500
    PROBE_MIN_ARTICLE    = 1
    PROBE_MAX_ROUNDS     = 3
    PROBE_MAX_CANDIDATES = 30

    SITE_KEYWORDS    = ["51吃瓜"]
    SITE_MARKERS     = ["post-title", "entry-title", "<article", 'class="post']

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

    EXTRA_BLACKLIST = ('beian.miit.gov.cn','w3.org','example.com')

    # ---- 列表 / 详情选择器（融合 51old 的字段提取习惯） ----
    SEL_ARTICLE      = "#index article, #archive article, article"
    SEL_ARTICLE_HOME = "#index article, article"
    SEL_PLAYER       = ".dplayer"
    SEL_CONTENT      = ".post-content, article"
    SEL_TAGS         = ".tags .keywords a, .post-tags a, .tags a"
    SEL_SUMMARY      = ".post-content"
    SEL_TITLE        = ".post-title, h1"

    # ---- 相关推荐区域选择器（按优先级尝试） ----
    RELATED_SELECTORS = [
        ".related-posts article",
        ".yarpp-related article",
        ".post-content + .related article",
        ".related article",
        "#related article",
        ".recommend-list article",
        "aside article",
        ".sidebar article",
        ".post-content ~ .navigation article",
    ]

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

    HEADERS = {
        "User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                       "AppleWebKit/537.36 (KHTML, like Gecko) "
                       "Chrome/134.0.0.0 Safari/537.36"),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9",
        "Connection": "keep-alive",
        "Cache-Control": "no-cache",
    }


# ==================================================================
# ② 域名解析器（保留 51new 的完整逻辑，微调）
# ==================================================================
class DomainResolver:
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

    JS_REDIRECT_PATS = [
        r'''(?:window\.|document\.|top\.|self\.|parent\.)?location(?:\.href)?\s*=\s*["'](https?://[^"']+)["']''',
        r'''(?:window\.|document\.|top\.|self\.|parent\.)?location\.assign\(\s*["'](https?://[^"']+)["']''',
        r'''(?:window\.|document\.|top\.|self\.|parent\.)?location\.replace\(\s*["'](https?://[^"']+)["']''',
        r'''window\.open\(\s*["'](https?://[^"']+)["']''',
        r'''<meta[^>]+http-equiv=["']refresh["'][^>]+content=["'][^"']*url=([^"'\s>]+)''',
        r'''<meta[^>]+http-equiv=["']refresh["'][^>]+url=([^"'\s>]+)''',
    ]

    def __init__(self, cfg, fetcher, cache_get=None, cache_set=None, cache_del=None):
        self.cfg, self.fetch = cfg, fetcher
        self.cache_get, self.cache_set, self.cache_del = cache_get, cache_set, cache_del

    def _read_cache(self):
        if not self.cache_get:
            return None
        try:
            raw = self.cache_get(self.cfg.HOST_CACHE_KEY)
        except Exception:
            return None
        if not raw:
            return None
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
        if not html:
            return False, "空响应"
        if len(html) < self.cfg.PROBE_MIN_HTML:
            return False, "HTML过短(%d<%d)" % (len(html), self.cfg.PROBE_MIN_HTML)
        if self._is_nav_page(html):
            return False, "导航页特征"
        low = html.lower()
        has_article = low.count("<article") >= self.cfg.PROBE_MIN_ARTICLE
        has_marker  = any(m in low for m in self.cfg.SITE_MARKERS)
        has_keyword = any(kw in html for kw in self.cfg.SITE_KEYWORDS)
        if not (has_article or has_marker or has_keyword):
            return False, "无内容结构(article=%d,marker=%s,kw=%s)" % (
                low.count("<article"),
                "Y" if has_marker else "N",
                "Y" if has_keyword else "N")
        return True, "OK"

    def _seed_suffixes(self):
        out = set()
        for u in self.cfg.SEED_HOSTS:
            try:
                host = urlparse(u).netloc.lower()
                parts = host.split(".")
                if len(parts) >= 3:
                    out.add(".".join(parts[-2:]))
            except Exception:
                pass
        return out

    def _extract_sibling_domains(self, html):
        if not html:
            return []
        suffixes = self._seed_suffixes()
        if not suffixes:
            return []
        out = []
        for suf in suffixes:
            pat = r'(?<![\w.\-])([a-zA-Z0-9][a-zA-Z0-9\-]{0,20}\.' + re.escape(suf) + r')(?![\w.\-])'
            for m in re.finditer(pat, html):
                h = "https://" + m.group(1).lower()
                if h not in out:
                    out.append(h)
        return out

    def _extract_bare_domains(self, html, trusted=False):
        if not html:
            return []
        text = re.sub(r'\b[\w.\-+]+@[\w.\-]+\b', ' ', html)
        text = self.RES_SUFFIX_RE.sub(' ', text)
        out, seen = [], set()
        for m in self.DOMAIN_RE.finditer(text):
            d = m.group(1).lower().strip('.')
            if not d or d in seen:
                continue
            parts = d.split('.')
            tld = parts[-1]
            if tld not in self.cfg.VALID_TLDS:
                continue
            if len(parts[0]) < 2 and not trusted:
                continue
            if any(bl in d for bl in self.cfg.DOMAIN_BLACKLIST):
                continue
            if not trusted and any(bl in d for bl in getattr(self.cfg, "EXTRA_BLACKLIST", ())):
                continue
            seen.add(d)
            out.append("https://" + d)
        return out

    def _extract_js_redirects(self, html):
        if not html:
            return []
        out = []
        cn_pats = [
            r'(?:迁移到|迁移至|新地址|新网址|永久域名|永久地址|最新域名|最新地址|最新入口|最新网址|请访问|访问地址|官方入口|官网入口)[：:\s]*((?:https?://)?[a-zA-Z0-9][a-zA-Z0-9.\-]{3,}\.[a-zA-Z]{2,10})',
            r'(?:线路[\s]*[一二三四五六七八九十\dA-Za-z]+|推荐访问|备用线路|线路正常)[\s\S]{0,200}?((?:https?://)?(?:[a-zA-Z0-9][a-zA-Z0-9\-]{0,62}\.)+[a-zA-Z]{2,10})',
        ]
        for p in self.JS_REDIRECT_PATS + cn_pats:
            for m in re.finditer(p, html, re.I):
                u = m.group(1).strip().rstrip('/.,;）)】」')
                if not u:
                    continue
                if u.startswith("http"):
                    h = self._final_host(u)
                elif "." in u and " " not in u:
                    h = self._final_host("https://" + u)
                else:
                    continue
                if h and h not in out:
                    out.append(h)
        return out

    def _extract_hosts_from_html(self, html, trusted=False):
        if not html:
            return []
        primary, backup, others = [], [], []

        for m in re.finditer(r'<a\b[^>]*\bdata-base="(https?://[^"]+)"[^>]*>', html):
            tag, base = m.group(0), m.group(1)
            (backup if ('data-group="backup"' in tag or "备用" in tag) else primary).append(base)

        primary.extend(self._extract_js_redirects(html))
        primary.extend(self._extract_sibling_domains(html))

        for b in re.findall(r'["\']([A-Za-z0-9+/=]{100,})["\']', html):
            try:
                decoded = base64.b64decode(b).decode("utf-8", errors="ignore")
                unquoted = unquote(decoded)
                if "[" not in unquoted:
                    continue
                if not any(kw in unquoted for kw in self.cfg.SITE_KEYWORDS):
                    continue
                site_list = json.loads(unquoted)
                for item in site_list:
                    if not any(kw in str(item.get("name", "")) for kw in self.cfg.SITE_KEYWORDS):
                        continue
                    u = item.get("url", "")
                    if u:
                        primary.append(u)
                    for u_obj in item.get("urls", []):
                        u2 = u_obj.get("url", "")
                        if u2:
                            primary.append(u2)
            except Exception:
                continue

        for m in re.finditer(r'<a\b[^>]+href="(https?://[^"]+)"[^>]*>', html):
            tag, href = m.group(0), m.group(1)
            if any(skip in href for skip in self.SKIP_HREF):
                continue
            if 'data-page=' in tag:
                continue
            others.append(href)

        primary.extend(self._extract_bare_domains(html, trusted=trusted))

        out, seen = [], set()
        for h in primary + backup + others:
            base = self._final_host(h)
            if base and base not in seen:
                seen.add(base)
                out.append(base)
        return out

    def _fetch_and_report(self, src, is_publish):
        tag = "发布" if is_publish else "导航"
        r = self._safe_fetch(src, self.cfg.PROBE_TIMEOUT)
        if r is None:
            print(f"  [{tag}源失败] {src} 无响应(超时/DNS/连接失败)")
            return None, [], []
        print(f"  [{tag}源成功] {src} → HTTP={r.status_code} 最终URL={r.url} 长度={len(r.text or '')}")

        if r.status_code != 200:
            return r, [], []

        text = r.text or ""
        if self._is_blocked_page(text):
            print(f"  [{tag}拦截] {src} 被 CloudFlare/验证页拦截 (前80字符: {text[:80]!r})")
            return r, [], []

        extracted = self._extract_hosts_from_html(text, trusted=is_publish)
        bare = self._extract_bare_domains(text, trusted=True)

        if extracted:
            print(f"  [{tag}结构化] {src} → {len(extracted)} 个: {extracted[:3]}")
        if bare:
            print(f"  [{tag}裸扫] {src} → {len(bare)} 个: {bare[:3]}")
        if not extracted and not bare:
            print(f"  [{tag}提取为空] {src} HTML前200字符:")
            print(f"    {text[:200]!r}")

        return r, extracted, bare

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
            r = self._safe_fetch(url, self.cfg.PROBE_TIMEOUT)
            if r is None:
                continue
            if r.status_code == 200 and r.text:
                print(f"  [gitlab raw成功] {url} 长度={len(r.text)}")
                return r.text
        print(f"  [gitlab raw失败] {src} 所有 raw 路径均失败")
        return ""

    def _collect_candidates(self, cached):
        candidates = []
        stats = {"nav_hit": 0, "pub_hit": 0, "struct": 0, "bare": 0, "seed": 0}

        nav_srcs = list(self.cfg.NAV_URLS)
        pub_srcs = list(getattr(self.cfg, "PUBLISH_URLS", []))

        if nav_srcs:
            print(f"--- 抓取导航页 {len(nav_srcs)} 个 ---")
            for src in nav_srcs:
                r, ext, bare = self._fetch_and_report(src, is_publish=False)
                if r is None:
                    continue
                stats["nav_hit"] += 1
                if r.url and self._final_host(r.url):
                    candidates.append(self._final_host(r.url))
                candidates.extend(ext)
                stats["struct"] += len(ext)
                candidates.extend(bare)
                stats["bare"] += len(bare)

        if pub_srcs:
            print(f"--- 抓取发布页 {len(pub_srcs)} 个 ---")
            for src in pub_srcs:
                r, ext, bare = self._fetch_and_report(src, is_publish=True)
                if r is None:
                    continue
                stats["pub_hit"] += 1
                if r.url and self._final_host(r.url):
                    candidates.append(self._final_host(r.url))
                candidates.extend(ext)
                stats["struct"] += len(ext)
                candidates.extend(bare)
                stats["bare"] += len(bare)

                if 'gitlab.com' in src:
                    readme = self._fetch_gitlab_readme(src)
                    if readme:
                        ext2 = self._extract_hosts_from_html(readme, trusted=True)
                        bare2 = self._extract_bare_domains(readme, trusted=True)
                        print(f"  [gitlab提取] 结构化={len(ext2)} 裸扫={len(bare2)}")
                        candidates.extend(ext2)
                        candidates.extend(bare2)
                        stats["struct"] += len(ext2)
                        stats["bare"] += len(bare2)

        candidates.extend([u.rstrip("/") for u in self.cfg.SEED_HOSTS])
        stats["seed"] = len(self.cfg.SEED_HOSTS)

        if cached:
            candidates.insert(0, cached["host"].rstrip("/"))

        seen, urls = set(), []
        for u in candidates:
            u = (u or "").rstrip("/")
            if u and u not in seen:
                seen.add(u)
                urls.append(u)
        urls = urls[:self.cfg.PROBE_MAX_CANDIDATES]

        print(f"[candidates] 导航 {stats['nav_hit']}/{len(nav_srcs)} | "
              f"发布 {stats['pub_hit']}/{len(pub_srcs)} | "
              f"结构化 {stats['struct']} | 裸扫 {stats['bare']} | "
              f"种子 {stats['seed']} → 最终 {len(urls)} 个")
        return urls

    def resolve(self):
        cached = self._read_cache()

        if cached and self._cache_fresh(cached):
            r = self._safe_fetch(cached["host"] + "/", self.cfg.PROBE_TIMEOUT)
            if r is not None and r.status_code == 200:
                ok, reason = self._site_check(r.text)
                if ok:
                    final = self._final_host(r.url or cached["host"]) or cached["host"]
                    print(f"缓存有效: {cached['host']} → {final}")
                    if final != cached["host"]:
                        self._write_cache(final)
                    return final
                else:
                    print(f"缓存失效: {cached['host']} 原因={reason}")
            else:
                print(f"缓存失效: {cached['host']} 无响应")

        queue = self._collect_candidates(cached)
        if not queue:
            print("[诊断] 无任何候选域名")
            return self._fallback(cached, "无候选")

        tried = set()
        for round_no in range(1, int(self.cfg.PROBE_MAX_ROUNDS) + 1):
            cur = [u for u in queue if u not in tried]
            if not cur:
                print(f"第 {round_no} 轮无新候选")
                break

            print(f"=== 第 {round_no} 轮探测: {len(cur)} 个 ===")
            next_queue = []

            with ThreadPoolExecutor(max_workers=min(8, len(cur))) as ex:
                futs = {ex.submit(self._safe_fetch, u + "/", self.cfg.PROBE_TIMEOUT): u for u in cur}
                try:
                    for f in as_completed(futs, timeout=self.cfg.PROBE_TIMEOUT + 12):
                        u = futs[f]
                        tried.add(u)
                        try:
                            r = f.result()
                        except Exception as e:
                            print(f"  [失败] {u} 异常: {e}")
                            continue
                        if r is None:
                            print(f"  [失败] {u} 无响应")
                            continue
                        if r.status_code != 200:
                            print(f"  [失败] {u} HTTP={r.status_code}")
                            loc = (r.headers or {}).get("Location", "")
                            if loc:
                                nh = self._final_host(loc)
                                if nh and nh not in tried and nh not in next_queue:
                                    next_queue.append(nh)
                                    print(f"    ↳ Location: {nh}")
                            continue

                        ok, reason = self._site_check(r.text)
                        if ok:
                            final = self._final_host(r.url or u) or u
                            self._write_cache(final)
                            print(f"  [成功] {final}" + (f" (来自 {u})" if final != u else ""))
                            return final

                        print(f"  [不匹配] {u} 原因={reason} 长度={len(r.text or '')}")
                        for d in self._extract_hosts_from_html(r.text or ""):
                            if d not in tried and d not in next_queue:
                                next_queue.append(d)
                                print(f"    ↳ 结构化: {d}")
                        for d in self._extract_bare_domains(r.text or "", trusted=False):
                            if d not in tried and d not in next_queue:
                                next_queue.append(d)
                                print(f"    ↳ 裸扫: {d}")
                except Exception as e:
                    LOG.debug("并发异常: %s", e)

            for d in next_queue:
                if d not in tried and d not in queue:
                    queue.append(d)
            if round_no < self.cfg.PROBE_MAX_ROUNDS and next_queue:
                print(f"第 {round_no} 轮结束，新增 {len(next_queue)} 个，进下一轮")

        print(f"[诊断] 已试 {len(tried)} 个域名，全部失败")
        return self._fallback(cached, "所有轮失败")

    def _fallback(self, cached, reason):
        if cached:
            print(f"使用过期缓存: {cached['host']}")
            return cached["host"]
        if getattr(self.cfg, "FALLBACK_HOST", None):
            print(f"【警告】回退 FALLBACK_HOST: {self.cfg.FALLBACK_HOST}")
            return self.cfg.FALLBACK_HOST.rstrip("/")
        if self.cfg.SEED_HOSTS:
            print(f"【警告】回退 SEED[0]: {self.cfg.SEED_HOSTS[0]}")
            return self.cfg.SEED_HOSTS[0].rstrip("/")
        print(f"【错误】域名探测彻底失败: {reason}")
        return ""


# ==================================================================
# ③ 主爬虫基类（融合 51new 的域名自愈 + 51old 的抓取/播放）
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
            self.extend_raw = extend
            self.proxies = json.loads(extend) if extend and isinstance(extend, str) and extend.startswith("{") else {}
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
            resolver = DomainResolver(
                self.CONFIG, self._get,
                cache_get=getattr(self, "getCache", None),
                cache_set=getattr(self, "setCache", None),
                cache_del=getattr(self, "delCache", None),
            )
            self.host = resolver.resolve()

        if self.host:
            self.headers.update({"Origin": self.host, "Referer": self.host + "/"})
        print(f"使用站点: {self.host}")

    def getName(self):          return "🌈 51爆料|多域自愈+关联推荐"
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

    # ---------------- 列表解析（融合 51old 的 getlist 习惯） ----------------
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
            # 日期：优先 datePublished，其次 time / post-meta
            remarks = (k('span[itemprop="datePublished"]').text()
                       or k("time").text()
                       or k(".post-meta, .entry-meta").text() or "").strip()
            if not remarks:
                m = re.search(r"(\d{4}\s*年\s*\d{1,2}\s*月\s*\d{1,2}\s*日)", k.text())
                if not m:
                    m = re.search(r"(\d{4}-\d{1,2}-\d{1,2})", k.text())
                remarks = m.group(1) if m else ""
            videos.append({
                "vod_id":      "%s%s" % (href, "@folder" if is_folder else ""),
                "vod_name":    title.replace("\n", " "),
                "vod_pic":     self._parse_pic(k),
                "vod_remarks": remarks,
                "vod_tag":     "folder" if is_folder else "",
                "style":       {"type": "rect", "ratio": 1.33},
            })
        return videos

    def _parse_pic(self, k):
        # 沿用 51old 的 loadBannerDirect，同时回退到 51new 的 _extract_img
        script_text = k("script").text()
        m = re.search(r"loadBannerDirect\('([^']+)'", script_text or "")
        if m:
            return self._proc_url(m.group(1))
        return self._extract_img(script_text, k)

    # ---------------- 相关推荐提取（新功能） ----------------
    def _extract_related(self, data, current_href=""):
        """
        从详情页提取相关推荐/相邻文章。
        返回 [(title, href), ...]
        """
        out, seen = [], {current_href.rstrip("/")}
        for sel in self.CONFIG.RELATED_SELECTORS:
            items = data(sel)
            if not items:
                continue
            for k in items.items():
                a = k("a").eq(0)
                href = a.attr("href") or k.attr("href")
                title = (k("h2").text() or k(".entry-title").text()
                         or k(".post-title").text() or a.text() or "").strip()
                if not href or not title:
                    continue
                href = self._abs(href)
                if href.rstrip("/") in seen:
                    continue
                seen.add(href.rstrip("/"))
                out.append((title, href))
            if out:
                break
        # 如果没命中专用选择器，尝试从文章底部的“上一篇/下一篇”或相邻 article 补
        if not out:
            for sel in (".post-navigation a", ".nav-links a", "a[rel='prev'], a[rel='next']"):
                for a in data(sel).items():
                    href, title = a.attr("href"), a.text().strip()
                    if href and title:
                        href = self._abs(href)
                        if href.rstrip("/") not in seen:
                            seen.add(href.rstrip("/"))
                            out.append((title, href))
        return out[:12]  # 限制数量，避免播放列表过长

    # ---------------- 详情页 ----------------
    def detailContent(self, ids):
        vid = str(ids[0] if isinstance(ids, (list, tuple)) else ids)
        if not self.host:
            return {"list": [{"vod_play_from": "51爆料", "vod_play_url": "获取失败"}]}
        url = vid if vid.startswith("http") else self.host + vid
        r, data = self._get_soup(url)
        if data is None:
            return {"list": [{"vod_play_from": "51爆料", "vod_play_url": "获取失败"}]}

        # 1) 当前视频播放列表
        playlist = self._extract_playlist(data)

        # 2) 相关推荐（作为额外线路）
        related = self._extract_related(data, current_href=url)
        related_lines_from, related_lines_url = [], []
        for idx, (title, href) in enumerate(related, 1):
            related_lines_from.append(f"📌 相关推荐 {idx}")
            related_lines_url.append(f"{title}${href}")

        # 3) 合并：当前播放线路 + 相关推荐线路
        play_from_list = ["51爆料"] + related_lines_from
        play_url_list = ["#".join(playlist) if playlist else f"未找到视频源，请访问网页${url}"]
        play_url_list.extend(related_lines_url)

        return {"list": [{
            "vod_play_from": "$$$".join(play_from_list),
            "vod_play_url":  "$$$".join(play_url_list),
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

    # ---------------- 图片 / 播放代理（沿用 51new，补充 51old 的 AES） ----------------
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

    # ---------------- 首页 / 分类 / 搜索（保持 51new 骨架，列表用融合后的 _parse_list） ----------------
    def homeContent(self, filter=False):
        if not self.host:
            return {"class": [], "list": []}
        r, data = self._get_soup(self.host)
        if data is None:
            return {"class": [], "list": []}
        return {
            "class": self._parse_classes(data),
            "list":  self._parse_list(data(self.CONFIG.SEL_ARTICLE_HOME)),
        }

    def homeVideoContent(self):
        if not self.host:
            return {"list": []}
        r, data = self._get_soup(self.host)
        if data is None:
            return {"list": []}
        return {"list": self._parse_list(data(self.CONFIG.SEL_ARTICLE_HOME))}

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
        return {"list": self._parse_list(data("article")), "page": pg, "pagecount": 9999}


# ==================================================================
# ④ 具体站点类
# ==================================================================
class Spider(BaseMultiDomainSpider):
    CONFIG = SiteConfig

    def getName(self):
        return "🌈 51爆料|多域自愈+关联推荐"
