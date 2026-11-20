# -*- coding: utf-8 -*-
"""
每日大赛 · 快速跳转 + 自愈抓取 + 播放相关推荐聚合（入口页并发优化版）
=========================================================================
本版新增 / 修复
-------------------------------------------------------------------------
- 【优化】DomainResolver._collect_candidates()
    · 导航页 + 发布页合并为一个并发池（max_workers=6）
    · as_completed + 超时回收，最坏 6×12s → ~12s
- 【增强】DomainResolver._ENTRY_CACHE（类级）
    · 入口页抓取结果按 URL 缓存，TTL 30 分钟
    · 同进程多次 init / 重连时跳过重复抓取
- 快路径 / 内容校验 / 播放推荐聚合等其余逻辑，与上一版一致
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
    FAST_HOSTS = [
        "https://dwatg7dnnvd2f.cloudfront.net",
        "https://among.mturgjfv.cc/",
        "https://annual.mturgjfv.cc/",
        "https://alone.mturgjfv.cc/",
        "https://admit.mturgjfv.cc/",
        "https://affair.mturgjfv.cc/",
    ]

    NAV_URLS = [
        "https://mrdld5.com",
        "https://mrdld1.com",
    ]

    PUBLISH_URLS = [
        "https://mrdld7.com",
        "https://mrdld6.com",
        "https://mrdld4.com",
    ]

    SEED_HOSTS = [
        "https://dwatg7dnnvd2f.cloudfront.net",
        "https://among.mturgjfv.cc/",
        "https://annual.mturgjfv.cc/",
        "https://alone.mturgjfv.cc/",
        "https://admit.mturgjfv.cc/",
        "https://affair.mturgjfv.cc/",
    ]

    FALLBACK_HOST  = None
    HOST_CACHE_KEY = "mrdld_host_fix_v10"
    HOST_CACHE_TTL = 6 * 3600

    FAST_TIMEOUT         = 6
    PROBE_TIMEOUT        = 12
    PROBE_MIN_HTML       = 2000
    PROBE_MIN_ARTICLE    = 1
    PROBE_MAX_ROUNDS     = 2
    PROBE_MAX_CANDIDATES = 30

    # 入口页结果缓存 TTL（秒）—— 同一进程内多次 init 时跳过重复抓取
    ENTRY_CACHE_TTL      = 1800

    SITE_KEYWORDS = ["每日大乱斗v10"]
    SITE_MARKERS  = ["post-title", "entry-title", "<article", 'class="post']

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
# ② 慢路径域名解析器（入口页并发 + 结果缓存）
# ==================================================================
class DomainResolver:
    SKIP_HREF = (
        '.js', '.css', '.jpg', '.jpeg', '.png', '.gif', '.webp', '.svg', '.ico',
        '.woff', '.woff2', '.ttf', '.eot', '.map', 'mailto:', 'javascript:', 'tel:',
        '/sese.html', '/ybml.html', '/qun.html', '/github.html', '/telegram.html',
        '/about.html', '/contact.html', 'mrds1.app',
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

    # ---- 类级缓存：跨实例保留，多次 init / 重连时复用 ----
    _ENTRY_CACHE = {}          # src → (ts, final_host, ext_list, bare_list)
    _ENTRY_LOCK  = None        # 惰性初始化（避免 import threading 开销）

    def __init__(self, cfg, fetcher):
        self.cfg, self.fetch = cfg, fetcher
        if DomainResolver._ENTRY_LOCK is None:
            import threading
            DomainResolver._ENTRY_LOCK = threading.Lock()

    # ---------- 抓取与提取 ----------
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
        if self._is_blocked_page(html):
            return False, "CloudFlare/验证页"
        if self._is_nav_page(html):
            return False, "导航页特征"
        low = html.lower()
        has_article = low.count("<article") >= self.cfg.PROBE_MIN_ARTICLE
        has_marker = any(m in low for m in self.cfg.SITE_MARKERS)
        has_keyword = any(kw in html for kw in self.cfg.SITE_KEYWORDS)
        if not (has_article or has_marker or has_keyword):
            return False, "无内容结构(article=%d,marker=%s,kw=%s)" % (
                low.count("<article"),
                "Y" if has_marker else "N",
                "Y" if has_keyword else "N")
        return True, "OK"

    # ---------- 六源提取 ----------
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

    # ---------- 候选收集：入口页并发 + 缓存 ----------
    def _read_entry_cache(self, src, now):
        """返回缓存命中的 (final_host, ext, bare)；未命中或过期返回 None"""
        with self._ENTRY_LOCK:
            cached = self._ENTRY_CACHE.get(src)
        if not cached:
            return None
        ts, final_h, ext, bare = cached
        if now - ts >= getattr(self.cfg, "ENTRY_CACHE_TTL", 1800):
            return None
        return final_h, ext, bare

    def _write_entry_cache(self, src, now, final_h, ext, bare):
        with self._ENTRY_LOCK:
            self._ENTRY_CACHE[src] = (now, final_h, list(ext), list(bare))
            # 简单清理：超量时丢掉最早的
            if len(self._ENTRY_CACHE) > 40:
                ordered = sorted(self._ENTRY_CACHE.items(), key=lambda kv: kv[1][0])
                for k, _ in ordered[:len(ordered) - 40]:
                    self._ENTRY_CACHE.pop(k, None)

    def _collect_candidates(self):
        candidates = []
        stats = {"nav_hit": 0, "pub_hit": 0, "struct": 0, "bare": 0, "seed": 0}

        nav_srcs = list(self.cfg.NAV_URLS)
        pub_srcs = list(getattr(self.cfg, "PUBLISH_URLS", []))
        all_srcs = [(u, False) for u in nav_srcs] + [(u, True) for u in pub_srcs]

        now = time.time()
        fresh_srcs = []

        # ① 先查缓存
        for src, is_pub in all_srcs:
            hit = self._read_entry_cache(src, now)
            if hit is None:
                fresh_srcs.append((src, is_pub))
                continue
            final_h, ext, bare = hit
            tag = "发布" if is_pub else "导航"
            print(f"  [{tag}缓存] {src} → {final_h or '(无跳转)'} | "
                  f"结构化 {len(ext)} | 裸扫 {len(bare)}")
            if final_h:
                candidates.append(final_h)
            candidates.extend(ext)
            stats["struct"] += len(ext)
            candidates.extend(bare)
            stats["bare"] += len(bare)
            stats["pub_hit" if is_pub else "nav_hit"] += 1

        # ② 未命中的走并发
        if fresh_srcs:
            print(f"--- 并发抓取入口页 {len(fresh_srcs)} 个 "
                  f"(导航 {len(nav_srcs)} + 发布 {len(pub_srcs)}，已缓存 "
                  f"{len(all_srcs) - len(fresh_srcs)}) ---")
            try:
                with ThreadPoolExecutor(max_workers=min(6, len(fresh_srcs))) as ex:
                    futs = {ex.submit(self._fetch_and_report, src, is_pub): (src, is_pub)
                            for src, is_pub in fresh_srcs}
                    for f in as_completed(futs, timeout=self.cfg.PROBE_TIMEOUT + 8):
                        src, is_pub = futs[f]
                        try:
                            r, ext, bare = f.result()
                        except Exception as e:
                            print(f"  [入口异常] {src}: {e}")
                            continue
                        if r is None:
                            continue
                        final_h = self._final_host(r.url) if r.url else ""
                        # 写缓存（无论是否提取到结果，避免短时间内反复重试）
                        self._write_entry_cache(src, now, final_h, ext, bare)

                        stats["pub_hit" if is_pub else "nav_hit"] += 1
                        if final_h:
                            candidates.append(final_h)
                        candidates.extend(ext)
                        stats["struct"] += len(ext)
                        candidates.extend(bare)
                        stats["bare"] += len(bare)
            except Exception as e:
                LOG.debug("入口并发异常: %s", e)

        # ③ 种子域名兜底
        candidates.extend([u.rstrip("/") for u in self.cfg.SEED_HOSTS])
        stats["seed"] = len(self.cfg.SEED_HOSTS)

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

    # ---------- 三轮回流探测 ----------
    def resolve(self):
        queue = self._collect_candidates()
        if not queue:
            print("[诊断] 无任何候选域名")
            return self._fallback("无候选")

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
        return self._fallback("所有轮失败")

    def _fallback(self, reason):
        if getattr(self.cfg, "FALLBACK_HOST", None):
            fb = self.cfg.FALLBACK_HOST.rstrip("/")
            print(f"【警告】回退 FALLBACK_HOST: {fb}")
            return fb
        if self.cfg.SEED_HOSTS:
            fb = self.cfg.SEED_HOSTS[0].rstrip("/")
            print(f"【警告】回退 SEED[0]: {fb}")
            return fb
        print(f"【错误】域名探测彻底失败: {reason}")
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
        return "🍑每日大赛|终极完美版"

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
        if low.count("<article") >= 1 or low.count('class="post') >= 3:
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
        has_article = low.count("<article") >= 1
        has_marker = any(m in low for m in self.CONFIG.SITE_MARKERS)
        has_keyword = any(kw in html for kw in self.CONFIG.SITE_KEYWORDS)
        if not (has_article or has_marker or has_keyword):
            return False, "无内容结构"
        return True, "OK"

    # -------------------- host 探测（快路径 → 慢路径）--------------------
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
            if r is None:
                print(f"  [快路径] {u} 无响应")
                continue
            if r.status_code != 200:
                print(f"  [快路径] {u} HTTP={r.status_code}")
                continue
            ok, reason = self._is_site(r.text)
            if not ok:
                print(f"  [快路径] {u} 不通过: {reason} 长度={len(r.text or '')}")
                continue
            final = self._final_host(r.url) or u
            print(f"  [快路径] {u} → {final} 命中")
            return final
        return ""

    def _slow_probe(self):
        print("[慢路径] 启动六源 + 三轮回流解析引擎 ...")
        resolver = DomainResolver(self.CONFIG, self._request)
        return resolver.resolve()

    def get_working_host(self):
        cached = self._read_host_cache()
        if cached:
            final = self._verify_host(cached)
            if final:
                print(f"缓存有效: {cached}" + (f" → {final}" if final != cached else ""))
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

    # -------------------- 页面级 items 缓存（供相关推荐使用）--------------------
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

    # -------------------- nid 编解码 --------------------
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
        return {"list": lst, "page": pg, "pagecount": 9999, "limit": 90, "total": 999999}

    # -------------------- 列表 / 目录 --------------------
    def _getlist(self, data, tid=""):
        videos, seen = [], set()
        is_folder = "/mrdg" in (tid or "")
        for k in data.items():
            a = k if k.is_("a") else k("a").eq(0)
            href = a.attr("href") or k.attr("href")
            title = (k("h2").text() or k(".entry-title").text()
                     or k(".post-title").text() or "").strip()
            if not title and k.is_("a"):
                title = (k.text() or "").strip()
            if not href or not title:
                continue

            vid = "%s%s" % (href, "@folder" if is_folder else "")
            if vid in seen:
                continue
            seen.add(vid)

            videos.append({
                "vod_id": vid,
                "vod_name": title,
                "vod_pic": self._extract_img(k),
                "vod_remarks": self._parse_date(k),
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

    # -------------------- 详情：核心抓取 + 相关推荐聚合 --------------------
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
        content = self._extract_content(data) or "每日大乱斗"
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
            return {"list": [{"vod_play_from": "每日大乱斗", "vod_play_url": "获取失败"}]}

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
            "vod_play_from": "每日大乱斗",
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
                    cur_name = self._clean(it.get("vod_name") or "") or ""
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

    # -------------------- 播放源提取 --------------------
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

        try:
            html = elem.outer_html() if hasattr(elem, "outer_html") else str(elem)
        except Exception:
            html = str(elem or "")
        html = (html.replace("&quot;", '"')
                    .replace("&apos;", "'")
                    .replace("&amp;", "&"))

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
        lst = self._getlist(data("article"))
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

    # -------------------- 编码工具 --------------------
    @staticmethod
    def e64(s):
        return base64.b64encode(str(s).encode()).decode()

    @staticmethod
    def d64(s):
        return base64.b64decode(str(s).encode()).decode()
