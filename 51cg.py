# ============================================================
# 51通用模板 · 动态发布页自愈版 V2（融合 rouav 自愈引擎）
# 核心改进：
#   1) requests + urllib 双引擎抓发布页（防反爬/证书拦截）
#   2) 多策略验活（选择器 → 内容特征 → 页面大小）
#   3) 请求失败自动触发域名刷新 + 重试（参考 rouav _fetch）
#   4) 发布页自身也作为候选（处理"发布页即主站"场景）
#   5) 框架 getCache/setCache 优先，文件缓存兜底
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
# 本地 host 文件缓存（框架缓存失效时的兜底）
# ============================================================
CACHE_FILE_NAME = "spider_host_cache.json"
CACHE_TTL = 48 * 3600


def _cache_file_candidates():
    paths = []
    try:
        paths.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), CACHE_FILE_NAME))
    except Exception:
        pass
    try:
        paths.append(os.path.join(os.getcwd(), CACHE_FILE_NAME))
    except Exception:
        pass
    try:
        paths.append(os.path.join(tempfile.gettempdir(), CACHE_FILE_NAME))
    except Exception:
        pass
    paths.append("/data/local/tmp/" + CACHE_FILE_NAME)
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

    # ------- 固定发布页（唯一自愈来源） -------
    # 说明：这些 URL 既可能是"独立导航发布页"（含 Base64 站点列表），
    #      也可能是"当前主站域名之一"。两种情况都由自愈引擎自动兼容。
    "publish_urls": [
        "https://51bla18.com/",
        "https://51bla19.com/",
        "https://51bla20.com/",
    ],
    "publish_url": "https://51bla20.com/",
    "publish_decode": "plain",

    # ------- Base64 JSON 站点列表的名称匹配关键词 -------
    # 发布页解码后可能出现 {"name": "51blaxx", ...}，按关键词包含匹配
    # 留空 [] 表示不过滤（全接受，由探活筛选）
    "site_names": ["51bla", "稀缺资源"],

    # ------- 完全依赖自愈，无兜底域名 -------
    "fallback_hosts": [],

    # ------- 探活 -------
    "host_check_selector": "#index article a",
    # 辅助探活：页面大小阈值 + 错误页特征（选择器匹配失败时使用）
    "probe_min_size": 2000,
    "probe_bad_markers": [
        "域名已过期", "站点关闭", "无法访问", "404 Not Found",
        "this domain", "parked domain", "under construction",
        "域名到期", "已停止服务",
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
    "probe_timeout": 5,
    "fast_timeout": 3,
    "probe_workers": 6,
}
# ====================配置区结束===================


class Spider(Spider):
    cfg = SITE_CONFIG
    _cached_host = ""

    # ================= 生命周期 =================
    def init(self, extend=""):
        try:
            if isinstance(extend, dict):
                self.proxies = extend
            else:
                self.proxies = json.loads(extend) if extend else {}
        except Exception:
            self.proxies = {}

        self.cfg = SITE_CONFIG
        self.headers = dict(self.cfg["headers"])

        # urllib 兜底 opener（处理 requests 被抓反爬/证书拦截的场景）
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
            self.headers.update({
                "Origin": self.host,
                "Referer": f"{self.host}/",
            })
            self.log(f"使用站点: {self.host}")
            print(f"使用站点: {self.host}")
        else:
            self.log("警告: 无可用站点（发布页均未提取到有效域名）")
            print("警告: 无可用站点（发布页均未提取到有效域名）")

    def getName(self):
        return SITE_CONFIG.get("name", "51模板")

    def isVideoFormat(self, url):
        return any(ext in (url or "") for ext in [".m3u8", ".mp4", ".ts"])

    def manualVideoCheck(self):
        return False

    def destroy(self):
        pass

    # ============================================================
    # 统一请求入口：失败自动触发域名刷新并重试（参考 rouav _fetch）
    # ============================================================
    def _get(self, url, retry_on_fail=True, **kwargs):
        kwargs.setdefault("timeout", self.cfg["timeout"])
        try:
            r = requests.get(url, headers=self.headers, proxies=self.proxies, **kwargs)
            if r.status_code == 200:
                return r
            if retry_on_fail and r.status_code in (404, 451, 502, 503):
                self.log(f"HTTP {r.status_code}，触发域名刷新重试: {url}")
                print(f"HTTP {r.status_code}，触发域名刷新重试: {url}")
                if self._refresh_host():
                    new_url = self._replace_host(url)
                    if new_url != url:
                        return requests.get(new_url, headers=self.headers,
                                            proxies=self.proxies, **kwargs)
            return r
        except Exception as e:
            self.log(f"请求异常: {e}")
            print(f"请求异常: {e}")
            if retry_on_fail:
                if self._refresh_host():
                    new_url = self._replace_host(url)
                    try:
                        return requests.get(new_url, headers=self.headers,
                                            proxies=self.proxies, **kwargs)
                    except Exception as e2:
                        self.log(f"重试仍失败: {e2}")
            return None

    def _replace_host(self, url):
        """把 URL 中的旧 host 替换为当前 self.host"""
        try:
            parsed = urlparse(url)
            old_base = f"{parsed.scheme}://{parsed.netloc}"
            if old_base != self.host and self.host:
                return url.replace(old_base, self.host, 1)
        except Exception:
            pass
        return url

    def _refresh_host(self):
        """运行时重新探测域名（请求失败时调用，参考 rouav 的自动重试）"""
        self.log("触发运行时域名刷新")
        print("触发运行时域名刷新")
        _clear_host_cache()
        try:
            self.delCache("51_host")
            self.delCache("51_host_ts")
        except Exception:
            pass
        Spider._cached_host = ""
        new_host = self.get_working_host()
        if new_host:
            self.host = new_host
            self.headers.update({
                "Origin": new_host,
                "Referer": f"{new_host}/",
            })
            self.log(f"域名刷新成功: {new_host}")
            print(f"域名刷新成功: {new_host}")
            return True
        self.log("域名刷新失败")
        print("域名刷新失败")
        return False

    # ============================================================
    # 发布页抓取：requests → urllib 双引擎（rouav 核心）
    # ============================================================
    def _fetch_publish_page(self, url, timeout):
        """先 requests，失败或空响应则切 urllib（含 SSL 关校验 + gzip）"""
        # 尝试 1: requests
        try:
            r = requests.get(url, headers=self.headers, proxies=self.proxies,
                             timeout=timeout, allow_redirects=True)
            if r.status_code == 200 and len(r.text or "") > 200:
                return r.text, r.url
        except Exception as e:
            self.log(f"requests 抓取发布页失败: {e}")

        # 尝试 2: urllib（rouav 引擎，绕反爬）
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
                text = raw.decode("utf-8", errors="ignore")
                if text:
                    return text, final_url
        except urllib.error.HTTPError as e:
            try:
                raw = e.read()
                if raw.startswith(b"\x1f\x8b"):
                    raw = gzip.decompress(raw)
                text = raw.decode("utf-8", errors="ignore")
                if text:
                    return text, url
            except Exception:
                pass
            self.log(f"urllib HTTPError: {e.code}")
        except Exception as e:
            self.log(f"urllib 抓取发布页失败: {e}")
        return "", url

    # ============================================================
    # 多策略验活（rouav 只验 200，这里兼顾 51 首页选择器）
    # ============================================================
    def _probe_one(self, url, timeout):
        try:
            r = requests.get(url, headers=self.headers, proxies=self.proxies,
                             timeout=timeout, allow_redirects=True)
            if r.status_code != 200:
                return False
            text = r.text or ""

            # 策略 1: 选择器命中（首选，最精确）
            try:
                doc = self.getpq(text)
                if doc(self.cfg["host_check_selector"]):
                    return True
            except Exception:
                pass

            # 策略 2: 内容大小 + 无错误页特征（首页改版时的兜底）
            if len(text) >= self.cfg.get("probe_min_size", 2000):
                bad = self.cfg.get("probe_bad_markers", [])
                if not any(m in text for m in bad):
                    self.log(f"探活通过（内容策略）: {url}")
                    print(f"探活通过（内容策略）: {url}")
                    return True

            return False
        except Exception:
            return False

    def _probe_concurrent(self, urls, timeout):
        if not urls:
            return ""
        if len(urls) == 1:
            return urls[0] if self._probe_one(urls[0], timeout) else ""

        results = {}
        workers = min(self.cfg.get("probe_workers", 6), len(urls))
        with ThreadPoolExecutor(max_workers=workers) as ex:
            future_map = {ex.submit(self._probe_one, u, timeout): u for u in urls}
            try:
                for fut in as_completed(future_map, timeout=timeout + 2):
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
    # 缓存：框架 getCache/setCache 优先，文件缓存兜底
    # ============================================================
    def _cache_get(self):
        # 1) 类内存
        if Spider._cached_host:
            return Spider._cached_host
        # 2) 框架缓存
        try:
            v = self.getCache("51_host")
            ts = self.getCache("51_host_ts")
            if v and isinstance(v, str) and v.startswith("http"):
                if ts:
                    try:
                        if time.time() - float(ts) < CACHE_TTL:
                            Spider._cached_host = v
                            return v
                    except Exception:
                        Spider._cached_host = v
                        return v
                else:
                    Spider._cached_host = v
                    return v
        except Exception:
            pass
        # 3) 文件缓存
        host, path = _read_host_cache()
        if host:
            print(f"命中文件缓存: {path}")
            Spider._cached_host = host
        return host

    def _cache_set(self, host):
        Spider._cached_host = host
        try:
            self.setCache("51_host", host)
            self.setCache("51_host_ts", str(time.time()))
        except Exception:
            pass
        _write_host_cache(host)

    def _cache_del(self):
        Spider._cached_host = ""
        try:
            self.delCache("51_host")
            self.delCache("51_host_ts")
        except Exception:
            pass
        _clear_host_cache()

    # ============================================================
    # 域名解析主流程
    # ============================================================
    def get_working_host(self):
        # 1) 缓存优先
        cached = self._cache_get()
        if cached:
            if self._probe_one(cached, self.cfg["fast_timeout"]):
                self.log(f"命中缓存站点: {cached}")
                print(f"命中缓存站点: {cached}")
                return cached
            self.log(f"缓存站点失效，重新探测: {cached}")
            print(f"缓存站点失效，重新探测: {cached}")
            self._cache_del()

        # 2) 从发布页提取候选（含发布页自身）
        candidates = self.extract_domains_from_publish_page()

        # 补充可选兜底（默认为空）
        for u in (self.cfg.get("fallback_hosts") or []):
            if u and u not in candidates:
                candidates.append(u)

        if not candidates:
            self.log("发布页未提取到任何候选域名")
            print("发布页未提取到任何候选域名")
            return ""

        # 3) 并发探活
        host = self._probe_concurrent(candidates, self.cfg["probe_timeout"])
        if host:
            self._cache_set(host)
            self.log(f"动态解析到可用站点: {host}")
            print(f"动态解析到可用站点: {host}")
            return host

        self.log("所有候选域名均不可用")
        print("所有候选域名均不可用")
        return ""

    # ============================================================
    # 发布页解析 —— Base64 JSON + HTML 选择器 + 发布页自身 + 跳转页
    # ============================================================
    def extract_domains_from_publish_page(self):
        cfg = self.cfg
        entries = cfg.get("publish_urls") or [cfg.get("publish_url", "")]
        entries = [e for e in entries if e]

        # 发布页自身也作为候选（关键：处理"发布页即主站"的场景）
        all_domains = []
        seen = set()
        for e in entries:
            try:
                parsed = urlparse(e)
                base = f"{parsed.scheme}://{parsed.netloc}"
                if base and base not in seen:
                    seen.add(base)
                    all_domains.append(base)
            except Exception:
                pass

        def _add(doms):
            for d in doms:
                if d and d not in seen:
                    seen.add(d)
                    all_domains.append(d)

        # 遍历每个入口，尝试 Base64 反解 / HTML 提取 / 跳转
        for entry in entries:
            try:
                text, final_url = self._fetch_publish_page(entry, cfg["probe_timeout"])
                if not text:
                    self.log(f"发布页无响应: {entry}")
                    continue

                # 策略 1: Base64 JSON 站点列表（rouav 核心）
                _add(self._extract_b64_sites(text))

                # 策略 2: HTML 选择器
                _add(self._extract_from_html(text, final_url or entry))

                # 策略 3 & 4: meta refresh / JS location 跳转
                target = self._find_meta_refresh(text)
                if target:
                    _add(self._fetch_and_extract(target, base=entry))
                target = self._find_js_location(text)
                if target:
                    _add(self._fetch_and_extract(target, base=entry))

            except Exception as e:
                self.log(f"发布页入口失败 [{entry}]: {e}")
                print(f"发布页入口失败 [{entry}]: {e}")
                continue

        if all_domains:
            self.log(f"发布页解析到 {len(all_domains)} 个候选域名: {all_domains[:8]}")
            print(f"发布页解析到 {len(all_domains)} 个候选域名: {all_domains[:8]}")
        else:
            self.log("所有发布页入口均未提取到候选域名")
            print("所有发布页入口均未提取到候选域名")
        return all_domains

    # ------------------------------------------------------------
    # Base64 JSON 站点列表反解（rouav 移植核心）
    # ------------------------------------------------------------
    def _safe_b64_decode(self, s):
        if not s:
            return ""
        missing = len(s) % 4
        if missing:
            s += "=" * (4 - missing)
        try:
            return b64decode(s).decode("utf-8", "ignore")
        except Exception:
            try:
                return b64decode(s, altchars=b"-_").decode("utf-8", "ignore")
            except Exception:
                return ""

    def _match_site_name(self, name):
        names = self.cfg.get("site_names") or []
        if not names:
            return True   # 空列表 = 全接受
        if not name:
            return False
        name_l = name.lower()
        for kw in names:
            if kw and kw.lower() in name_l:
                return True
        return False

    def _extract_b64_sites(self, text):
        domains = []
        seen = set()
        if not text:
            return domains

        # 匹配 >= 60 位的 Base64 字符串（rouav 阈值 100 太严，有编码变体会漏）
        b64_blocks = re.findall(r'["\']([A-Za-z0-9+/=_-]{60,})["\']', text)

        for block in b64_blocks:
            decoded = self._safe_b64_decode(block)
            if not decoded:
                continue
            try:
                decoded = unquote(decoded)
            except Exception:
                pass
            if "[" not in decoded or "name" not in decoded:
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

                cand_urls = []
                main_url = item.get("url", "")
                if isinstance(main_url, str) and main_url:
                    cand_urls.append(main_url)
                urls_field = item.get("urls", [])
                if isinstance(urls_field, list):
                    for u_obj in urls_field:
                        if isinstance(u_obj, dict):
                            u = u_obj.get("url", "")
                        elif isinstance(u_obj, str):
                            u = u_obj
                        else:
                            continue
                        if u and u not in cand_urls:
                            cand_urls.append(u)

                for c_url in cand_urls:
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
                        domains.append(base)

        if domains:
            self.log(f"Base64 站点列表匹配到: {domains[:6]}")
            print(f"Base64 站点列表匹配到: {domains[:6]}")
        return domains

    # ------------------------------------------------------------
    # HTML / 跳转页解析
    # ------------------------------------------------------------
    def _extract_from_html(self, text, base_url):
        try:
            html = self._decode_publish(text, self.cfg["publish_decode"])
        except Exception:
            html = text
        doc = self.getpq(html)

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
            self.log(f"发布页跳转目标: {target_url}")
            print(f"发布页跳转目标: {target_url}")
            text, final_url = self._fetch_publish_page(target_url, self.cfg["probe_timeout"])
            if not text:
                return []
            # 跳转页同样先 Base64 再 HTML
            doms = self._extract_b64_sites(text)
            if doms:
                return doms
            return self._extract_from_html(text, final_url or target_url)
        except Exception as e:
            self.log(f"跳转目标解析失败: {e}")
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
        patterns = [
            r'window\.location(?:\.href)?\s*=\s*["\']([^"\']+)["\']',
            r'document\.location(?:\.href)?\s*=\s*["\']([^"\']+)["\']',
            r'location\.replace\(\s*["\']([^"\']+)["\']',
            r'location\.assign\(\s*["\']([^"\']+)["\']',
        ]
        for p in patterns:
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
                    return text
            return text
        if mode == "js_atob":
            m = re.search(r"atob\(['\"]([^'\"]+)['\"]\)", text)
            if m:
                try:
                    return b64decode(m.group(1)).decode("utf-8", "ignore")
                except Exception:
                    return text
            return text
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
            videos = self.getlist(doc(self.cfg["list_selector"]))
            return {"list": videos, "page": pg}
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
        self.log(f"播放请求: parse={p}, url={url}")
        print(f"播放请求: parse={p}, url={url}")
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
        for index, string in enumerate(lines):
            if iskey and "URI" in string:
                pattern = r'URI="([^"]*)"'
                m = re.search(pattern, string)
                if m:
                    lines[index] = re.sub(pattern, f'URI="{self.proxy(m.group(1), "mkey")}"', string)
                    iskey = False
                    continue
            if "#EXT" not in string:
                if "http" not in string:
                    domain = last_r if string.count("/") < 2 else durl
                    string = domain + ("" if string.startswith("/") else "/") + string
                lines[index] = self.proxy(string, string.split(".")[-1].split("?")[0])
        return [200, "application/vnd.apple.mpegur", "\n".join(lines)]

    def tsProxy(self, url):
        url = self.d64(url)
        data = requests.get(url, headers=self.headers, proxies=self.proxies,
                            stream=True, timeout=self.cfg["timeout"])
        return [200, data.headers["Content-Type"], data.content]

    # ================= Base64 =================
    def e64(self, text):
        try:
            return b64encode(text.encode("utf-8")).decode("utf-8")
        except Exception as e:
            print(f"Base64编码错误: {e}")
            return ""

    def d64(self, text):
        try:
            return b64decode(text.encode("utf-8")).decode("utf-8")
        except Exception as e:
            print(f"Base64解码错误: {e}")
            return ""

    # ================= 播放器解析 =================
    def _parse_players(self, doc):
        plist = []
        used_names = set()
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
                    h = h.strip()
                    if h:
                        ep_name = h
                        break
                    parent = parent.parents().eq(0)
            except Exception:
                ep_name = ""
            base_name = ep_name or f"视频{idx}"
            name = base_name
            c = 2
            while name in used_names:
                name = f"{base_name} {c}"
                c += 1
            used_names.add(name)
            self.log(f"解析到视频: {name} -> {video_url}")
            print(f"解析到视频: {name} -> {video_url}")
            plist.append(f"{name}${video_url}")
        return plist

    # ================= 列表 =================
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

    # ================= 合集 =================
    def getfod(self, folder_id):
        url = f"{self.host}{folder_id}"
        r = self._get(url)
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

    # ================= 图片 =================
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
