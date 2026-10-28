# ============================================================
# 51通用模板 · 动态发布页自愈版 V3（对齐 Zaka/rouav 原理）
# 
# 原理对齐要点：
#   1) Zaka/rouav 的 navUrls 是"发布页导航站"，从不作为主站候选
#   2) 51bla18/19/20.com 同样只是导航页，主站 xxx.luwhogpx.cc 藏在 HTML 明文里
#   3) 探活必须严格 —— Zaka 只验 HTTP 200，rouav 只验 /vodtype 页面
#   4) 绝不因为"页面大小正常"就误判成功（本次修复核心）
# ============================================================
import json
import os
import re
import sys
import tempfile
import time
import gzip
import zlib
import ssl
import urllib.request
import urllib.error
import urllib.parse
import http.cookiejar
from base64 import b64decode, b64encode
from urllib.parse import urlparse, unquote
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
from Crypto.Cipher import AES
from Crypto.Util.Padding import unpad
from pyquery import PyQuery as pq

sys.path.append('..')
from base.spider import Spider

# ============================================================
# 本地文件缓存（框架缓存失效兜底）
# ============================================================
CACHE_FILE_NAME = "spider_host_cache.json"
CACHE_TTL = 48 * 3600


def _cache_file_candidates():
    paths = []
    for getter in (
        lambda: os.path.join(os.path.dirname(os.path.abspath(__file__)), CACHE_FILE_NAME),
        lambda: os.path.join(os.getcwd(), CACHE_FILE_NAME),
        lambda: os.path.join(tempfile.gettempdir(), CACHE_FILE_NAME),
        lambda: "/data/local/tmp/" + CACHE_FILE_NAME,
    ):
        try:
            paths.append(getter())
        except Exception:
            pass
    return paths


def _read_host_cache():
    for p in _cache_file_candidates():
        try:
            if os.path.exists(p):
                with open(p, "r", encoding="utf-8") as f:
                    data = json.load(f)
                host = data.get("host", "")
                ts = float(data.get("ts", 0))
                if host and time.time() - ts < CACHE_TTL:
                    return host, p
        except Exception:
            continue
    return "", ""


def _write_host_cache(host):
    payload = json.dumps({"host": host, "ts": time.time()}, ensure_ascii=False)
    for p in _cache_file_candidates():
        try:
            with open(p, "w", encoding="utf-8") as f:
                f.write(payload)
            return True
        except Exception:
            continue
    return False


def _clear_host_cache():
    for p in _cache_file_candidates():
        try:
            if os.path.exists(p):
                os.remove(p)
        except Exception:
            continue


# ====================配置区开始===================
SITE_CONFIG = {
    "name": "51通用合一缓存版",
    "play_from": "51通用合一缓存板",
    "style": {"type": "rect", "ratio": 1.33},

    # ------- 发布页（导航站，不是主站！） -------
    "publish_urls": [
        "https://51bla18.com/",
        "https://51bla19.com/",
        "https://51bla20.com/",
    ],
    "publish_url": "https://51bla20.com/",
    "publish_decode": "plain",

    # Base64 JSON name 关键词（如果发布页含此结构则可用）
    "site_names": ["51bla", "luwhogpx", "稀缺资源"],

    # 完全无兜底
    "fallback_hosts": [],

    # 探活：只接受选择器命中（严格）
    "host_check_selector": "#index article a",

    # 主站域名白名单模式（51特色：xxx.luwhogpx.cc）
    # 不填则从发布页解析到的所有非黑名单域名都会尝试
    "host_pattern_hints": [".luwhogpx.cc", "51"],

    # CDN/统计/框架黑名单（域名包含这些词的排除）
    "host_blacklist": [
        "google", "facebook", "twitter", "cloudflare", "cdn",
        "static", "analytics", "doubleclick", "gstatic",
        "jsdelivr", "bootstrap", "jquery", "fontawesome",
        "cdnjs", "unpkg", "baidu", "51.la", "cnzz", "umeng",
        "gtag", "googletagmanager", "adservice", "adsterra",
        "themes", "wp-content", "wp-includes", "beacon",
        "telemetry", "statistics", "clarity", "hotjar",
        "yandex", "bing", "w3.org", "schema.org", "gmpg.org",
        "json-schema", "wordpress", "elementor", "jquery",
    ],

    "list_selector": "#index article a, #archive article a",
    "home_list_selector": "#index article a",
    "category_selectors": [
        ".category-list ul li",
        ".nav-menu li",
        ".menu li",
        "nav ul li",
    ],
    "default_classes": [
        {"type_name": "首页", "type_id": "/"},
        {"type_name": "最新", "type_id": "/latest/"},
        {"type_name": "热门", "type_id": "/hot/"},
    ],
    "folder_id_marker": "/mrdg",

    "title_selector": ".post-title",
    "tag_selector": ".tags .keywords a",
    "player_selector": ".dplayer",
    "player_config_attr": "data-config",
    "player_heading_selector": "h2, h3, h4",

    "folder_content_selector": ".post-content[itemprop='articleBody']",
    "folder_remove_selectors": [".txt-apps", ".line", "blockquote", ".tags", ".content-tabs"],
    "folder_img_attr": "data-xkrkllgl",

    "img_regex": r"loadBannerDirect\('([^']+)'",
    "aes_key": b"f5d965df75336270",
    "aes_iv": b"97b60394abc2fbe1",

    "search_url_tpl": "{host}/search/{key}/",
    "search_url_tpl_paged": "{host}/search/{key}/{pg}/",

    "headers": {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                      "AppleWebKit/537.36 (KHTML, like Gecko) "
                      "Chrome/134.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,"
                  "image/avif,image/webp,image/apng,*/*;q=0.8,"
                  "application/signed-exchange;v=b3;q=0.7",
        "Accept-Language": "zh-CN,zh;q=0.9",
        "Accept-Encoding": "gzip, deflate",
        "Connection": "keep-alive",
        "Cache-Control": "no-cache",
    },

    "timeout": 15,
    "probe_timeout": 6,
    "fast_timeout": 3,
    "probe_workers": 8,
}
# ====================配置区结束===================


class Spider(Spider):
    cfg = SITE_CONFIG
    _cached_host = ""

    # ================= 生命周期 =================
    def init(self, extend=""):
        try:
            self.proxies = extend if isinstance(extend, dict) else (
                json.loads(extend) if extend else {})
        except Exception:
            self.proxies = {}

        self.cfg = SITE_CONFIG
        self.headers = dict(self.cfg["headers"])

        # urllib 兜底 opener（对齐 rouav，绕证书/反爬）
        try:
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            self._cj = http.cookiejar.CookieJar()
            self._opener = urllib.request.build_opener(
                urllib.request.HTTPCookieProcessor(self._cj),
                urllib.request.HTTPSHandler(context=ctx)
            )
        except Exception:
            self._opener = None

        self.host = self.get_working_host()

        if self.host:
            self.headers.update({"Origin": self.host, "Referer": f"{self.host}/"})
            self.log(f"使用站点: {self.host}")
            print(f"使用站点: {self.host}")
        else:
            self.log("警告: 无可用站点")
            print("警告: 无可用站点")

    def getName(self):
        return SITE_CONFIG.get("name", "51模板")

    def isVideoFormat(self, url):
        return any(ext in (url or "") for ext in [".m3u8", ".mp4", ".ts"])

    def manualVideoCheck(self):
        return False

    def destroy(self):
        pass

    # ============================================================
    # 【修复1】统一请求：失败自动刷新域名重试（对齐 rouav _fetch）
    # ============================================================
    def _get(self, url, retry_on_fail=True, **kwargs):
        kwargs.setdefault("timeout", self.cfg["timeout"])
        try:
            r = requests.get(url, headers=self.headers, proxies=self.proxies, **kwargs)
            if r.status_code == 200:
                return r
            if retry_on_fail and r.status_code in (404, 451, 502, 503):
                self.log(f"HTTP {r.status_code} 触发重探: {url}")
                print(f"HTTP {r.status_code} 触发重探: {url}")
                if self._refresh_host():
                    new_url = self._replace_host(url)
                    if new_url != url:
                        return requests.get(new_url, headers=self.headers,
                                            proxies=self.proxies, **kwargs)
            return r
        except Exception as e:
            self.log(f"请求异常: {e}")
            if retry_on_fail and self._refresh_host():
                try:
                    return requests.get(self._replace_host(url), headers=self.headers,
                                        proxies=self.proxies, **kwargs)
                except Exception:
                    pass
            return None

    def _replace_host(self, url):
        try:
            p = urlparse(url)
            old_base = f"{p.scheme}://{p.netloc}"
            if self.host and old_base != self.host:
                return url.replace(old_base, self.host, 1)
        except Exception:
            pass
        return url

    def _refresh_host(self):
        self.log("运行时刷新域名")
        _clear_host_cache()
        try:
            self.delCache("51_host")
        except Exception:
            pass
        Spider._cached_host = ""
        new = self.get_working_host()
        if new:
            self.host = new
            self.headers.update({"Origin": new, "Referer": f"{new}/"})
            return True
        return False

    # ============================================================
    # 发布页抓取：requests → urllib 双引擎
    # ============================================================
    def _fetch_publish_page(self, url, timeout):
        try:
            r = requests.get(url, headers=self.headers, proxies=self.proxies,
                             timeout=timeout, allow_redirects=True)
            if r.status_code == 200 and len(r.text or "") > 100:
                return r.text, r.url
        except Exception as e:
            self.log(f"requests 失败: {e}")

        if not self._opener:
            return "", url
        try:
            req = urllib.request.Request(url, headers=self.headers)
            with self._opener.open(req, timeout=timeout) as resp:
                raw = resp.read()
                final_url = resp.geturl()
                enc = (resp.headers.get("Content-Encoding", "") or "").lower()
                if raw.startswith(b"\x1f\x8b") or enc == "gzip":
                    raw = gzip.decompress(raw)
                elif enc == "deflate":
                    try:
                        raw = zlib.decompress(raw)
                    except Exception:
                        raw = zlib.decompress(raw, -zlib.MAX_WBITS)
                return raw.decode("utf-8", errors="ignore"), final_url
        except urllib.error.HTTPError as e:
            try:
                raw = e.read()
                if raw.startswith(b"\x1f\x8b"):
                    raw = gzip.decompress(raw)
                return raw.decode("utf-8", errors="ignore"), url
            except Exception:
                pass
        except Exception as e:
            self.log(f"urllib 失败: {e}")
        return "", url

    # ============================================================
    # 【修复2 · 核心】探活严格化：只允许选择器命中通过
    # 对齐 Zaka 的 chk.get("code") == 200 —— 绝不宽容误判
    # ============================================================
    def _probe_one(self, url, timeout):
        try:
            r = requests.get(url, headers=self.headers, proxies=self.proxies,
                             timeout=timeout, allow_redirects=True)
            if r.status_code != 200:
                return False
            # 唯一判据：主站首页必须有 #index article a 文章列表
            try:
                doc = self.getpq(r.text)
                return bool(doc(self.cfg["host_check_selector"]))
            except Exception:
                return False
        except Exception:
            return False

    def _probe_concurrent(self, urls, timeout):
        if not urls:
            return ""
        if len(urls) == 1:
            return urls[0] if self._probe_one(urls[0], timeout) else ""

        results = {}
        workers = min(self.cfg.get("probe_workers", 8), len(urls))
        with ThreadPoolExecutor(max_workers=workers) as ex:
            future_map = {ex.submit(self._probe_one, u, timeout): u for u in urls}
            try:
                for fut in as_completed(future_map, timeout=timeout + 3):
                    u = future_map[fut]
                    try:
                        results[u] = fut.result(timeout=0)
                    except Exception:
                        results[u] = False
                    if results.get(u):
                        idx = urls.index(u)
                        if all(urls[i] in results for i in range(idx)):
                            for i in range(idx + 1):
                                if results.get(urls[i]):
                                    return urls[i]
            except Exception:
                pass
        for u in urls:
            if results.get(u):
                return u
        return ""

    # ============================================================
    # 缓存：框架 getCache 优先 + 文件兜底
    # ============================================================
    def _cache_get(self):
        if Spider._cached_host:
            return Spider._cached_host
        try:
            v = self.getCache("51_host")
            if v and isinstance(v, str) and v.startswith("http"):
                Spider._cached_host = v
                return v
        except Exception:
            pass
        host, path = _read_host_cache()
        if host:
            Spider._cached_host = host
        return host

    def _cache_set(self, host):
        Spider._cached_host = host
        try:
            self.setCache("51_host", host)
        except Exception:
            pass
        _write_host_cache(host)

    def _cache_del(self):
        Spider._cached_host = ""
        try:
            self.delCache("51_host")
        except Exception:
            pass
        _clear_host_cache()

    # ============================================================
    # 域名解析主流程
    # ============================================================
    def get_working_host(self):
        cached = self._cache_get()
        if cached:
            if self._probe_one(cached, self.cfg["fast_timeout"]):
                self.log(f"缓存命中: {cached}")
                print(f"缓存命中: {cached}")
                return cached
            self.log(f"缓存失效: {cached}")
            self._cache_del()

        candidates = self.extract_domains_from_publish_page()

        for u in (self.cfg.get("fallback_hosts") or []):
            if u and u not in candidates:
                candidates.append(u)

        if not candidates:
            self.log("发布页未提取到任何候选")
            print("发布页未提取到任何候选")
            return ""

        print(f"待探测候选域名({len(candidates)}): {candidates[:10]}")
        host = self._probe_concurrent(candidates, self.cfg["probe_timeout"])
        if host:
            self._cache_set(host)
            self.log(f"自愈成功: {host}")
            print(f"自愈成功: {host}")
            return host

        self.log("所有候选域名均未通过探活")
        print("所有候选域名均未通过探活")
        return ""

    # ============================================================
    # 【修复3 · 核心】发布页解析：Zaka/rouav 原理 + 51 明文扫描
    # ============================================================
    def extract_domains_from_publish_page(self):
        entries = self.cfg.get("publish_urls") or [self.cfg.get("publish_url", "")]
        entries = [e for e in entries if e]

        all_domains = []
        seen = set()

        def _add(doms):
            for d in doms:
                if d and d not in seen:
                    seen.add(d)
                    all_domains.append(d)

        for entry in entries:
            try:
                text, final_url = self._fetch_publish_page(entry, self.cfg["probe_timeout"])
                if not text:
                    self.log(f"发布页无响应: {entry}")
                    continue

                # ---- 关键补充：发布页发生跨域 302，跳转目标就是主站候选 ----
                p_entry = urlparse(entry)
                p_final = urlparse(final_url or entry)
                if p_final.netloc and p_final.netloc != p_entry.netloc:
                    cand = f"{p_final.scheme}://{p_final.netloc}"
                    self.log(f"发布页跨域跳转 → 候选: {cand}")
                    _add([cand])

                # ---- 策略1: Base64 JSON 站点列表（Zaka/rouav 核心） ----
                _add(self._extract_b64_sites(text))

                # ---- 策略2: HTML 选择器（a.route 等） ----
                _add(self._extract_from_html(text, final_url or entry))

                # ---- 策略3: 【51 核心】全文本 URL 正则扫描 ----
                # 51bla 发布页把 *.luwhogpx.cc 明文写在 <a> / <div> / <script> 里
                _add(self._extract_urls_by_regex(text))

                # ---- 策略4: meta refresh 跳转 ----
                target = self._find_meta_refresh(text)
                if target:
                    _add(self._fetch_and_extract(target, base=entry))

                # ---- 策略5: JS location 跳转 ----
                target = self._find_js_location(text)
                if target:
                    _add(self._fetch_and_extract(target, base=entry))

            except Exception as e:
                self.log(f"发布页入口失败 [{entry}]: {e}")
                continue

        if all_domains:
            self.log(f"发布页共提取 {len(all_domains)} 个候选: {all_domains[:10]}")
            print(f"发布页共提取 {len(all_domains)} 个候选: {all_domains[:10]}")
        else:
            self.log("发布页未提取到任何候选域名")
            print("发布页未提取到任何候选域名")
        return all_domains

    # ------------------------------------------------------------
    # 过滤工具
    # ------------------------------------------------------------
    def _is_publish_domain(self, host):
        """过滤发布页自身域名"""
        entries = self.cfg.get("publish_urls") or []
        host_l = host.lower()
        for e in entries:
            try:
                p = urlparse(e)
                if p.netloc and p.netloc.lower() == host_l:
                    return True
            except Exception:
                pass
        return False

    def _is_blacklisted(self, host):
        """过滤 CDN/统计/框架/广告域名"""
        host_l = host.lower()
        for kw in self.cfg.get("host_blacklist", []):
            if kw and kw.lower() in host_l:
                return True
        return False

    def _looks_like_main_site(self, host):
        """白名单校验：优先接受匹配 host_pattern_hints 的域名"""
        hints = self.cfg.get("host_pattern_hints", [])
        if not hints:
            return True   # 无白名单配置时全接受（由探活筛选）
        host_l = host.lower()
        # 任意 hint 匹配即可（包含匹配）
        for h in hints:
            if h and h.lower() in host_l:
                return True
        return False

    # ------------------------------------------------------------
    # 【修复4 · 核心】全文本 URL 正则扫描（51 发布页专用）
    # ------------------------------------------------------------
    def _extract_urls_by_regex(self, text):
        """从页面全文本提取所有 xxx.yyy.zzz 形式的域名"""
        out, seen = [], set()
        if not text:
            return out

        # 匹配 https?://host/path 或 //host
        for m in re.finditer(
            r'https?://([a-zA-Z0-9][a-zA-Z0-9\-\.]{3,}\.[a-zA-Z]{2,})(?::\d+)?',
            text
        ):
            host = m.group(1).lower()
            if self._is_blacklisted(host) or self._is_publish_domain(host):
                continue
            base_url = "https://" + host
            if base_url not in seen:
                seen.add(base_url)
                out.append(base_url)

        # 协议相对 URL（//xxx.luwhogpx.cc/）
        for m in re.finditer(
            r'(?<![:/])//([a-zA-Z0-9][a-zA-Z0-9\-\.]{3,}\.[a-zA-Z]{2,})(?::\d+)?',
            text
        ):
            host = m.group(1).lower()
            if self._is_blacklisted(host) or self._is_publish_domain(host):
                continue
            base_url = "https://" + host
            if base_url not in seen:
                seen.add(base_url)
                out.append(base_url)

        # 特殊：51 主站域名模式（白名单，即使不带 http 前缀也接受）
        for hint in self.cfg.get("host_pattern_hints", []):
            if not hint or "." not in hint:
                continue
            hint_esc = re.escape(hint.lstrip("."))
            for m in re.finditer(
                r'([a-zA-Z0-9][a-zA-Z0-9\-]{1,30}\.' + hint_esc + r')',
                text, re.I
            ):
                host = m.group(1).lower()
                if self._is_blacklisted(host):
                    continue
                base_url = "https://" + host
                if base_url not in seen:
                    seen.add(base_url)
                    out.append(base_url)

        # 白名单过滤：如果配了 host_pattern_hints，仅保留匹配项
        if self.cfg.get("host_pattern_hints"):
            out = [u for u in out if self._looks_like_main_site(urlparse(u).netloc)]

        if out:
            self.log(f"URL 正则扫描到 {len(out)} 个候选: {out[:8]}")
            print(f"URL 正则扫描到 {len(out)} 个候选: {out[:8]}")
        return out

    # ------------------------------------------------------------
    # Base64 JSON（Zaka/rouav 核心移植）
    # ------------------------------------------------------------
    def _safe_b64_decode(self, s):
        if not s:
            return ""
        try:
            pad = len(s) % 4
            if pad:
                s += "=" * (4 - pad)
            return b64decode(s, altchars=b"-_").decode("utf-8", "ignore")
        except Exception:
            return ""

    def _match_site_name(self, name):
        names = self.cfg.get("site_names") or []
        if not names:
            return True
        if not name:
            return False
        nl = name.lower()
        return any(kw and kw.lower() in nl for kw in names)

    def _extract_b64_sites(self, text):
        out, seen = [], set()
        if not text:
            return out

        for block in re.findall(r'["\']([A-Za-z0-9+/=_-]{60,})["\']', text):
            decoded = self._safe_b64_decode(block)
            if not decoded or "[" not in decoded:
                continue
            try:
                decoded = unquote(decoded)
            except Exception:
                pass
            if "name" not in decoded:
                continue
            try:
                data = json.loads(decoded)
            except Exception:
                continue
            if not isinstance(data, list):
                continue

            for item in data:
                if not isinstance(item, dict):
                    continue
                name = (item.get("name") or "").strip()
                if not self._match_site_name(name):
                    continue

                cand = []
                main = item.get("url", "")
                if isinstance(main, str) and main:
                    cand.append(main)
                for u_obj in item.get("urls", []) or []:
                    u = u_obj.get("url", "") if isinstance(u_obj, dict) else (
                        u_obj if isinstance(u_obj, str) else "")
                    if u and u not in cand:
                        cand.append(u)

                for c_url in cand:
                    c_url = (c_url or "").strip()
                    if not c_url.startswith("http"):
                        continue
                    try:
                        p = urlparse(c_url)
                        base = f"{p.scheme}://{p.netloc}"
                    except Exception:
                        continue
                    if base and base not in seen:
                        seen.add(base)
                        out.append(base)
        return out

    # ------------------------------------------------------------
    # HTML 选择器 / 跳转
    # ------------------------------------------------------------
    def _extract_from_html(self, text, base_url):
        try:
            doc = self.getpq(self._decode_publish(text, self.cfg["publish_decode"]))
        except Exception:
            return []
        domains = []
        for a in doc("a.route, a[data-line4], .routes a").items():
            href = (a.attr("href") or "").strip()
            if href:
                domains.append(href)
        if not domains:
            domains = self._pick_domains(doc, base_url)
        seen, uniq = set(), []
        for u in domains:
            u = self._normalize_url(u, base_url)
            if u and u not in seen:
                seen.add(u)
                uniq.append(u)
        return uniq

    def _fetch_and_extract(self, target_url, base):
        try:
            target_url = self._normalize_url(target_url, base)
            if not target_url:
                return []
            self.log(f"跳转目标: {target_url}")
            text, final_url = self._fetch_publish_page(target_url, self.cfg["probe_timeout"])
            if not text:
                return []
            doms = self._extract_b64_sites(text)
            if not doms:
                doms = self._extract_from_html(text, final_url or target_url)
            if not doms:
                doms = self._extract_urls_by_regex(text)
            return doms
        except Exception as e:
            self.log(f"跳转解析失败: {e}")
            return []

    def _find_meta_refresh(self, html):
        m = re.search(
            r'<meta[^>]+http-equiv=["\']?refresh["\']?[^>]+'
            r'content=["\'][^"\']*url=([^"\'>\s]+)',
            html or "", re.I,
        )
        return m.group(1).strip("'\"") if m else ""

    def _find_js_location(self, html):
        if not html:
            return ""
        for p in [
            r'window\.location(?:\.href)?\s*=\s*["\']([^"\']+)["\']',
            r'document\.location(?:\.href)?\s*=\s*["\']([^"\']+)["\']',
            r'location\.replace\(\s*["\']([^"\']+)["\']',
            r'location\.assign\(\s*["\']([^"\']+)["\']',
        ]:
            m = re.search(p, html)
            if m:
                return m.group(1)
        return ""

    def _normalize_url(self, u, base):
        if not u:
            return ""
        u = u.strip()
        if u.startswith("//"):
            u = "https:" + u
        if u.startswith("/") and base:
            try:
                p = urlparse(base)
                u = f"{p.scheme}://{p.netloc}{u}"
            except Exception:
                pass
        if not u.startswith("http") or "." not in u:
            return ""
        if any(x in u for x in ["javascript:", "mailto:", "#"]):
            return ""
        return u

    def _decode_publish(self, text, mode):
        if mode == "js_base64":
            m = re.search(r"Base64\.decode\(['\"]([^'\"]+)['\"]\)", text)
            if m:
                try:
                    return b64decode(m.group(1)).decode("utf-8", "ignore")
                except Exception:
                    pass
        if mode == "js_atob":
            m = re.search(r"atob\(['\"]([^'\"]+)['\"]\)", text)
            if m:
                try:
                    return b64decode(m.group(1)).decode("utf-8", "ignore")
                except Exception:
                    pass
        return text

    def _pick_domains(self, doc, base):
        seen, out = set(), []
        for a in doc("a").items():
            href = (a.attr("href") or "").strip()
            u = self._normalize_url(href, base)
            if u and u not in seen:
                seen.add(u)
                out.append(u)
        return out

    # ================= 首页 =================
    def homeContent(self, filter):
        try:
            if not self.host:
                return {"class": [], "list": []}
            r = self._get(self.host)
            if not r or r.status_code != 200:
                return {"class": [], "list": []}
            doc = self.getpq(r.text)
            classes = []
            for selector in self.cfg["category_selectors"]:
                for item in doc(selector).items():
                    a = item("a")
                    href = (a.attr("href") or "").strip()
                    name = (a.text() or "").strip()
                    if not href or href == "#" or not name:
                        continue
                    classes.append({"type_name": name, "type_id": href})
                if classes:
                    break
            if not classes:
                classes = list(self.cfg["default_classes"])
            return {
                "class": classes,
                "list": self.getlist(doc(self.cfg["home_list_selector"])),
            }
        except Exception as e:
            print(f"homeContent error: {e}")
            return {"class": [], "list": []}

    def homeVideoContent(self):
        try:
            if not self.host:
                return {"list": []}
            r = self._get(self.host)
            if not r or r.status_code != 200:
                return {"list": []}
            doc = self.getpq(r.text)
            return {"list": self.getlist(doc(self.cfg["list_selector"]))}
        except Exception as e:
            print(f"homeVideoContent error: {e}")
            return {"list": []}

    # ================= 分类 =================
    def categoryContent(self, tid, pg, filter, extend):
        try:
            if not self.host:
                return {"list": [], "page": pg, "pagecount": 1, "limit": 90, "total": 0}
            if "@folder" in tid:
                folder_id = tid.replace("@folder", "")
                videos = self.getfod(folder_id)
                return {"list": videos, "page": pg, "pagecount": 1,
                        "limit": 90, "total": len(videos)}
            pg = int(pg)
            tid = tid.rstrip("/")
            url = f"{self.host}{tid}/{pg}/" if pg > 1 else f"{self.host}{tid}/"
            r = self._get(url)
            if not r or r.status_code != 200:
                return {"list": [], "page": pg, "pagecount": 1, "limit": 90, "total": 0}
            doc = self.getpq(r.text)
            videos = self.getlist(doc(self.cfg["list_selector"]), tid)
            total_pages = 1
            page_info = doc(".pagination .pages, .page-nav, .pagenavi").text()
            if "共" in page_info and "页" in page_info:
                try:
                    total_pages = int(page_info.split("共")[-1].split("页")[0])
                except Exception:
                    pass
            next_url = doc('a.next, .pagination a.next, .pagenavi .next, a:contains("下一页")').attr("href")
            has_next = bool(next_url)
            return {
                "list": videos, "page": pg,
                "pagecount": total_pages if total_pages > 1 else (99999 if has_next else pg),
                "limit": 90, "total": 999999 if has_next else len(videos),
            }
        except Exception as e:
            print(f"categoryContent error: {e}")
            return {"list": [], "page": pg, "pagecount": 1, "limit": 90, "total": 0}

    # ================= 详情 =================
    def detailContent(self, ids):
        try:
            raw_id = ids[0] if ids else ""
            url = raw_id if raw_id.startswith("http") else f"{self.host}{raw_id}"
            r = self._get(url)
            if not r or r.status_code != 200:
                return {"list": [{"vod_play_from": self.cfg["play_from"],
                                  "vod_play_url": f"页面加载失败${url}"}]}
            doc = self.getpq(r.text)
            vod = {"vod_play_from": self.cfg["play_from"]}
            try:
                clist = []
                tag_sel = self.cfg["tag_selector"]
                if tag_sel and doc(tag_sel):
                    for k in doc(tag_sel).items():
                        title = k.text()
                        href = k.attr("href")
                        if title and href:
                            clist.append("[a=cr:" + json.dumps({"id": href, "name": title}) + "/]"
                                         + title + "[/a]")
                vod["vod_content"] = " ".join(clist) if clist else doc(self.cfg["title_selector"]).text()
            except Exception:
                vod["vod_content"] = doc(self.cfg["title_selector"]).text() or self.cfg["name"]
            try:
                plist = self._parse_players(doc)
                vod["vod_play_url"] = "#".join(plist) if plist else f"未找到视频源${url}"
            except Exception:
                vod["vod_play_url"] = f"视频解析失败${url}"
            return {"list": [vod]}
        except Exception as e:
            print(f"detailContent error: {e}")
            return {"list": [{"vod_play_from": self.cfg["play_from"],
                              "vod_play_url": f"详情页加载失败${ids[0] if ids else ''}"}]}

    # ================= 搜索 =================
    def searchContent(self, key, quick, pg="1"):
        try:
            if not self.host:
                return {"list": [], "page": pg}
            if str(pg) != "1":
                url = self.cfg["search_url_tpl_paged"].format(host=self.host, key=key, pg=pg)
            else:
                url = self.cfg["search_url_tpl"].format(host=self.host, key=key)
            r = self._get(url)
            if not r or r.status_code != 200:
                return {"list": [], "page": pg}
            doc = self.getpq(r.text)
            return {"list": self.getlist(doc(self.cfg["list_selector"])), "page": pg}
        except Exception as e:
            print(f"searchContent error: {e}")
            return {"list": [], "page": pg}

    # ================= 播放 =================
    def playerContent(self, flag, id, vipFlags):
        url = id
        p = 1
        if self.isVideoFormat(url):
            if ".m3u8" in url:
                url = self.proxy(url)
            p = 0
        self.log(f"播放: parse={p}, url={url}")
        return {"parse": p, "url": url, "header": self.headers}

    def localProxy(self, param):
        t = param.get("type")
        if t == "img":
            res = requests.get(param["url"], headers=self.headers,
                               proxies=self.proxies, timeout=10)
            return [200, res.headers.get("Content-Type"), self.aesimg(res.content)]
        if t == "m3u8":
            return self.m3Proxy(param["url"])
        return self.tsProxy(param["url"])

    def proxy(self, data, type="m3u8"):
        if data and len(self.proxies):
            return f"{self.getProxyUrl()}&url={self.e64(data)}&type={type}"
        return data

    def m3Proxy(self, url):
        url = self.d64(url)
        ydata = requests.get(url, headers=self.headers, proxies=self.proxies,
                             allow_redirects=False, timeout=self.cfg["timeout"])
        data = ydata.content.decode("utf-8")
        if ydata.headers.get("Location"):
            url = ydata.headers["Location"]
            data = requests.get(url, headers=self.headers, proxies=self.proxies,
                                timeout=self.cfg["timeout"]).content.decode("utf-8")
        lines = data.strip().split("\n")
        last_r = url[:url.rfind("/")]
        parsed = urlparse(url)
        durl = parsed.scheme + "://" + parsed.netloc
        iskey = True
        for i, line in enumerate(lines):
            if iskey and "URI" in line:
                m = re.search(r'URI="([^"]*)"', line)
                if m:
                    lines[i] = re.sub(r'URI="[^"]*"',
                                      f'URI="{self.proxy(m.group(1), "mkey")}"', line)
                    iskey = False
                    continue
            if "#EXT" not in line:
                if "http" not in line:
                    domain = last_r if line.count("/") < 2 else durl
                    line = domain + ("" if line.startswith("/") else "/") + line
                lines[i] = self.proxy(line, line.split(".")[-1].split("?")[0])
        return [200, "application/vnd.apple.mpegur", "\n".join(lines)]

    def tsProxy(self, url):
        url = self.d64(url)
        data = requests.get(url, headers=self.headers, proxies=self.proxies,
                            stream=True, timeout=self.cfg["timeout"])
        return [200, data.headers["Content-Type"], data.content]

    def e64(self, text):
        try:
            return b64encode(text.encode("utf-8")).decode("utf-8")
        except Exception:
            return ""

    def d64(self, text):
        try:
            return b64decode(text.encode("utf-8")).decode("utf-8")
        except Exception:
            return ""

    # ================= 播放器 / 列表 / 合集 / 图片 =================
    def _parse_players(self, doc):
        plist, used = [], set()
        sel = self.cfg["player_selector"]
        attr = self.cfg["player_config_attr"]
        if not doc(sel):
            for idx, node in enumerate(doc("video[src]").items(), start=1):
                src = (node.attr("src") or "").strip()
                if src:
                    plist.append(f"视频{idx}${src}")
            if plist:
                return plist
            for idx, node in enumerate(doc("iframe[src]").items(), start=1):
                src = (node.attr("src") or "").strip()
                if src:
                    plist.append(f"视频{idx}${src}")
            return plist
        for idx, node in enumerate(doc(sel).items(), start=1):
            raw = node.attr(attr)
            if not raw:
                continue
            try:
                cfg = json.loads(raw)
            except Exception:
                continue
            video_url = cfg.get("video", {}).get("url", "")
            if not video_url:
                continue
            ep_name = ""
            try:
                parent = node.parents().eq(0)
                for _ in range(3):
                    if not parent:
                        break
                    h = parent.find(self.cfg["player_heading_selector"]).eq(0).text() or ""
                    if h.strip():
                        ep_name = h.strip()
                        break
                    parent = parent.parents().eq(0)
            except Exception:
                pass
            base_name = ep_name or f"视频{idx}"
            name = base_name
            c = 2
            while name in used:
                name = f"{base_name} {c}"
                c += 1
            used.add(name)
            self.log(f"解析视频: {name} -> {video_url}")
            plist.append(f"{name}${video_url}")
        return plist

    def getlist(self, data, tid=""):
        videos = []
        is_folder = self.cfg["folder_id_marker"] in (tid or "")
        for k in data.items():
            href = k.attr("href")
            name = k("h2").text()
            remark = (k("span[itemprop='datePublished']").text()
                      or k(".post-meta, .entry-meta, time").text())
            if href and name:
                videos.append({
                    "vod_id": f"{href}{'@folder' if is_folder else ''}",
                    "vod_name": name.replace("\n", " "),
                    "vod_pic": self.getimg(k("script").text()),
                    "vod_remarks": remark or "",
                    "vod_tag": "folder" if is_folder else "",
                    "style": self.cfg["style"],
                })
        return videos

    def getfod(self, folder_id):
        r = self._get(f"{self.host}{folder_id}")
        if not r:
            return []
        doc = self.getpq(r.text)
        vdata = doc(self.cfg["folder_content_selector"])
        for sel in self.cfg["folder_remove_selectors"]:
            vdata.remove(sel)
        p = vdata("p")
        img_attr = self.cfg["folder_img_attr"]
        videos = []
        for i, x in enumerate(vdata("h2").items()):
            c = i * 2
            videos.append({
                "vod_id": p.eq(c)("a").attr("href"),
                "vod_name": p.eq(c).text(),
                "vod_pic": f"{self.getProxyUrl()}&url={p.eq(c + 1)('img').attr(img_attr)}&type=img",
                "vod_remarks": x.text(),
            })
        return videos

    def getimg(self, text):
        m = re.search(self.cfg["img_regex"], text or "")
        if m:
            return f"{self.getProxyUrl()}&url={m.group(1)}&type=img"
        return ""

    def aesimg(self, word):
        cipher = AES.new(self.cfg["aes_key"], AES.MODE_CBC, self.cfg["aes_iv"])
        return unpad(cipher.decrypt(word), AES.block_size)

    def getpq(self, data):
        try:
            return pq(data)
        except Exception as e:
            print(f"{e}")
            return pq(data.encode("utf-8"))


try:
    BaseSpider.register(Spider())
except NameError:
    pass
