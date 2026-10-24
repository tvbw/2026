# -*- coding: utf-8 -*-
# ============================================================
# 51 模板 · 多域名跳转 + 易维护种子 + 兜底 改造版
# 改动点：
#   1. 新增 MultiDomainResolver：BFS 多域名探测
#      - seed_hosts      用户手动维护的长期固定域名（最优先）
#      - publish_urls    发布页列表（自动解析 base64 / meta / JS / 外链候选）
#      - fallback_hosts  末尾兜底（原 51 字段，兼容保留）
#      - TTL 缓存 + 并发探测 + http/https 双 scheme + 总耗时上限
#   2. get_working_host 改为调用 MultiDomainResolver
#   3. 新增钩子 _probe_fetch / _site_ok / _extract_candidates_from_page
#   4. 保留 51 原内容抓取、翻页、播放、AES 图片、m3u8 代理等全部功能
#   5. 保留原兼容接口 extract_domains_from_publish_page / _fetch_and_extract
# ============================================================
import json
import random
import re
import sys
import threading
import time
from base64 import b64decode, b64encode
from urllib.parse import urlparse

import requests
from Crypto.Cipher import AES
from Crypto.Util.Padding import unpad
from pyquery import PyQuery as pq

sys.path.append('..')
from base.spider import Spider

try:
    from concurrent.futures import ThreadPoolExecutor, as_completed
    _HAS_TPE = True
except Exception:
    _HAS_TPE = False


# ============================================================
# 站点配置：换站只改本段
# ============================================================
SITE_CONFIG = {
    "name": "51通用最终版",
    "play_from": "51通用最终版",
    "style": {"type": "rect", "ratio": 1.33},

    # ============ 域名探测配置（易维护） ============
    # ① 一级固定长期域名（用户手动维护；越稳定越靠前；可留空）
    "seed_hosts": [
        "https://51cgf19.com/",
        "https://51cgf20.com/",
        "https://51cgf18.com/",
    ],

    # ② 发布页（自动解析候选域名：base64 / meta / JS / <a href>）
    #    保留原 publish_url 字段（下面仍可用），此处用列表以支持多个发布页
    "publish_urls": [
        "https://51cgf18.com/",
    ],
    "publish_url":  "https://51cgf20.com/",   # 兼容原字段名

    # ③ 兜底域名（放 BFS 最后，做最终保底）
    "fallback_hosts": [
        "https://album.hhhepogu.cc/",
        "https://battle.hhhepogu.cc/",
        "https://black.hhhepogu.cc/",
        # "https://able.htinjysz.cc/",
    ],
    
    # ④ 缓存
    "host_cache_key": "51_host",
    "host_cache_ttl": 6 * 3600,          # 秒；0 表示永不过期

    # ⑤ 探测参数
    "probe_timeout": 10,
    "probe_total_deadline": 40,          # 秒；超时立即收尾
    "probe_max_rounds": 4,
    "probe_max_steps": 24,
    "probe_min_html": 1500,

    # ⑥ 站点有效性判定（host_check_selector 命中 OR (keyword 且 marker)）
    "host_check_selector": "#index article a",
    "site_keywords": [],                 # 如 ["51"]；空表示只用选择器
    "site_markers": [],                  # 如 ["post-title", "<article"]

    # ⑦ 发布页激进提取触发词（页面出现即把全部外链当作候选）
    "publish_page_markers": [
        "发布页", "最新地址", "备用地址", "永久地址", "网址发布",
    ],
    "exclude_domains": [
        "google", "gstatic", "cloudflare", "jsdelivr", "cdn", "fonts",
        "bootstrap", "jquery", "w3.org", "schema.org", "youtube",
        "twitter", "facebook", "beian", "gov.cn", "mozilla", "github",
        "unpkg", "bootcdn",
    ],

    # 发布页编码方式: js_base64 / js_atob / plain / redirect
    "publish_decode": "js_base64",

    # ============ 内容抓取（保持 51 原配置） ============
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
    "aes_iv":  b"97b60394abc2fbe1",

    "search_url_tpl":       "{host}/search/{key}/",
    "search_url_tpl_paged": "{host}/search/{key}/{pg}/",

    "headers": {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                      "AppleWebKit/537.36 (KHTML, like Gecko) "
                      "Chrome/134.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,"
                  "image/avif,image/webp,image/apng,*/*;q=0.8,"
                  "application/signed-exchange;v=b3;q=0.7",
        "Accept-Language": "zh-CN,zh;q=0.9",
        "Connection": "keep-alive",
        "Cache-Control": "no-cache",
    },

    "timeout": 15,
}


# ============================================================
# 多域名 BFS 探测器：独立类，无状态耦合，可复用
# ============================================================
class MultiDomainResolver:
    """
    输入：
      cfg           SITE_CONFIG
      fetcher(url, timeout) -> requests.Response | None
      site_ok(html) -> bool
      hook_extract(url, html, final_url) -> list[str]   # 从任意页面提取候选
      cache_get(key) -> raw | None
      cache_set(key, val) -> None
    输出：
      可用 host（不带尾斜杠）或 ""（全失败）
    """

    def __init__(self, cfg, fetcher, site_ok, hook_extract,
                 cache_get=None, cache_set=None):
        self.cfg          = cfg
        self.fetcher      = fetcher
        self.site_ok      = site_ok
        self.hook_extract = hook_extract
        self.cache_get    = cache_get
        self.cache_set    = cache_set
        self._visited     = set()
        self._count       = 0
        self._start_ts    = time.time()

    def _deadline_ok(self):
        return (time.time() - self._start_ts) < self.cfg.get("probe_total_deadline", 40)

    @staticmethod
    def _expand_schemes(urls):
        out, seen = [], set()
        for u in urls:
            if not u:
                continue
            for sc in ("https", "http"):
                v = re.sub(r"^https?://", sc + "://", u, count=1)
                if v not in seen:
                    seen.add(v)
                    out.append(v)
        return out

    def _safe_fetch(self, url, timeout):
        try:
            return self.fetcher(url, timeout)
        except Exception as e:
            print(f"[probe] 请求异常 {url}: {e}")
            return None

    def _probe_batch(self, urls, timeout):
        results = {}
        urls = [u for u in urls if u and u not in self._visited]
        if not urls:
            return results
        self._visited.update(urls)
        workers = min(6, max(1, len(urls)))

        if _HAS_TPE and len(urls) > 1:
            try:
                with ThreadPoolExecutor(max_workers=workers) as ex:
                    futs = {ex.submit(self._safe_fetch, u, timeout): u for u in urls}
                    for f in as_completed(futs, timeout=timeout + 5):
                        u = futs[f]
                        if not self._deadline_ok():
                            print(f"[probe] 总耗时超限，停止本批")
                            break
                        self._count += 1
                        if self._count > self.cfg.get("probe_max_steps", 24):
                            print(f"[probe] 请求数超限")
                            break
                        self._collect(results, u, f.result() if not f.exception() else None)
            except Exception as e:
                print(f"[probe] 批量探测异常: {e}")
        else:
            for u in urls:
                if not self._deadline_ok():
                    break
                self._count += 1
                if self._count > self.cfg.get("probe_max_steps", 24):
                    break
                r = self._safe_fetch(u, timeout)
                self._collect(results, u, r)
        return results

    def _collect(self, results, u, r):
        if r is None:
            print(f"[probe] ✗ {u} 无响应")
            return
        html  = r.text or ""
        final = (getattr(r, "url", None) or u).rstrip("/") + "/"
        ok    = self.site_ok(html)
        print(f"[probe] {'✅' if ok else '✗'} {u} → {final} ({len(html)}字)")
        results[u] = (ok, final, html)

    # ---- 缓存 ----
    def _read_cache(self):
        if not self.cache_get:
            return None
        try:
            raw = self.cache_get(self.cfg.get("host_cache_key", "51_host"))
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
        ttl = int(self.cfg.get("host_cache_ttl", 0) or 0)
        if ttl <= 0:
            return True
        return (time.time() - int(c.get("ts") or 0)) < ttl

    def _write_cache(self, host):
        if not self.cache_set:
            return
        try:
            self.cache_set(self.cfg.get("host_cache_key", "51_host"),
                           json.dumps({"host": host, "ts": int(time.time())}))
        except Exception:
            pass

    # ---- 主流程 ----
    def resolve(self):
        cfg = self.cfg
        cached = self._read_cache()

        if cached:
            state = "有效期内" if self._cache_fresh(cached) else "已过期"
            print(f"[probe] 缓存: {cached['host']} ({state})")

            if self._cache_fresh(cached):
                res = self._probe_batch([cached["host"] + "/"],
                                        cfg.get("probe_timeout", 10))
                for _u, (ok, final, _h) in res.items():
                    if ok:
                        h = final.rstrip("/")
                        print(f"[probe] ✅ 缓存仍有效: {h}")
                        return h
                print(f"[probe] ✗ 缓存失效，开始完整探测")

        # 队列：seed_hosts → publish_urls → fallback_hosts
        seeds = list(cfg.get("seed_hosts") or [])
        seeds.extend(cfg.get("publish_urls") or [])
        pu = cfg.get("publish_url")
        if pu and pu not in seeds:
            seeds.append(pu)
        seeds.extend(cfg.get("fallback_hosts") or [])
        if cached:
            seeds.insert(0, cached["host"] + "/")

        current = self._expand_schemes(seeds)

        for rnd in range(cfg.get("probe_max_rounds", 4)):
            if not current or not self._deadline_ok():
                break
            print(f"[probe] --- 第 {rnd + 1} 轮 (候选 {len(current)}) ---")
            res = self._probe_batch(current, cfg.get("probe_timeout", 10))

            # 命中即返回
            for _u, (ok, final, _h) in res.items():
                if ok:
                    h = final.rstrip("/")
                    self._write_cache(h)
                    print(f"[probe] ✅ 确定 host: {h}")
                    return h

            # 提取下一轮候选
            nxt = []
            for u, (_ok, final, html) in res.items():
                if not html:
                    continue
                try:
                    cands = self.hook_extract(u, html, final) or []
                except Exception as e:
                    print(f"[probe] 提取候选异常 {u}: {e}")
                    cands = []
                if cands:
                    print(f"[probe] {u} → 提取候选 {len(cands)} 个")
                    nxt.extend(cands)
            current = self._expand_schemes(nxt)

        if cached:
            print(f"[probe] ⚠ 使用过期缓存: {cached['host']}")
            return cached["host"]

        fb = cfg.get("fallback_hosts") or []
        if fb:
            print(f"[probe] ⚠ 使用 fallback[0]: {fb[0]}")
            return fb[0]

        print("[probe] ❌ 全部探测失败，请更新 seed_hosts")
        return ""


# ============================================================
# 主爬虫
# ============================================================
class Spider(Spider):

    cfg = SITE_CONFIG

    # ================= 生命周期 =================
    def init(self, extend=""):
        try:
            self.proxies = json.loads(extend)
        except Exception:
            self.proxies = {}

        self.cfg = SITE_CONFIG
        self.headers = dict(self.cfg["headers"])   # base，不含 Origin/Referer

        self.host = self.get_working_host()
        if self.host:
            self.headers.update({
                "Origin":  self.host,
                "Referer": f"{self.host}/",
            })
        self.log(f"使用站点: {self.host}")
        print(f"使用站点: {self.host}")

    def getName(self):
        return SITE_CONFIG.get("name", "51通用最终版")

    def isVideoFormat(self, url):
        return any(ext in (url or "") for ext in [".m3u8", ".mp4", ".ts"])

    def manualVideoCheck(self):
        return False

    def destroy(self):
        pass

    # ============================================================
    # 域名探测：新引擎 + 51 原钩子
    # ============================================================
    def get_working_host(self):
        resolver = MultiDomainResolver(
            cfg=self.cfg,
            fetcher=self._probe_fetch,
            site_ok=self._site_ok,
            hook_extract=self._extract_candidates_from_page,
            cache_get=self._cache_get,
            cache_set=self._cache_set,
        )
        return resolver.resolve()

    def _probe_fetch(self, url, timeout):
        try:
            return requests.get(url, headers=self.headers,
                                proxies=self.proxies,
                                timeout=timeout, allow_redirects=True)
        except Exception:
            return None

    def _site_ok(self, html):
        """选择器命中 OR (keyword 且 marker) 命中"""
        if not html or len(html) < self.cfg.get("probe_min_html", 1500):
            return False
        try:
            doc = self.getpq(html)
            sel = self.cfg.get("host_check_selector")
            if sel and doc(sel):
                return True
        except Exception:
            pass
        low = html.lower()
        has_kw = any(kw in html for kw in (self.cfg.get("site_keywords") or []))
        has_mk = any(mk in low for mk in (self.cfg.get("site_markers")  or []))
        return has_kw and has_mk

    def _extract_candidates_from_page(self, url, html, final_url):
        """从任意页面提取候选域名 URL（发布页解析统一入口）"""
        if not html:
            return []
        out = []

        # ① 51 原逻辑：Base64 / atob 混淆发布页
        if ("Base64.decode" in html) or ("atob(" in html):
            decoded = self._decode_publish(html, self.cfg.get("publish_decode", "js_base64"))
            if decoded and decoded != html:
                try:
                    doc = self.getpq(decoded)
                    out.extend(self._pick_domains(doc, final_url or url))
                except Exception as e:
                    print(f"[probe] base64 解码后解析异常: {e}")

        # ② meta refresh 跳转
        t = self._find_meta_refresh(html)
        if t:
            t = self._abs_url(t, final_url or url)
            if t:
                out.append(t)

        # ③ JS location 跳转
        t = self._find_js_location(html)
        if t:
            t = self._abs_url(t, final_url or url)
            if t:
                out.append(t)

        # ④ 发布页激进提取：页面有发布页标记就把所有外链 URL 拿出来
        if any(mk in html for mk in (self.cfg.get("publish_page_markers") or [])):
            for m in re.finditer(
                r'https?://[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}(?:/[^\s"\'<>]*)?',
                html
            ):
                u = m.group(0)
                if any(bad in u for bad in (self.cfg.get("exclude_domains") or [])):
                    continue
                out.append(u)

        # 去重
        seen, result = set(), []
        for u in out:
            if u and u not in seen:
                seen.add(u)
                result.append(u)
        return result

    def _abs_url(self, url, base):
        if not url:
            return ""
        url = url.strip().strip("'\"")
        if url.startswith("//"):
            return "https:" + url
        if url.startswith("/"):
            return base.rstrip("/") + url
        if url.startswith("http"):
            return url
        return ""

    # ---- 缓存钩子（兼容不同 TVBox 内核） ----
    def _cache_get(self, key):
        fn = getattr(self, "getCache", None)
        if not callable(fn):
            return None
        try:
            return fn(key)
        except Exception:
            return None

    def _cache_set(self, key, val):
        fn = getattr(self, "setCache", None)
        if not callable(fn):
            return
        try:
            fn(key, val)
        except Exception:
            pass

    # ---- 51 原发布页解析兼容接口（保留给外部/调试用） ----
    def extract_domains_from_publish_page(self):
        urls = list(self.cfg.get("publish_urls") or [])
        pu = self.cfg.get("publish_url")
        if pu and pu not in urls:
            urls.append(pu)
        if not urls:
            return []
        out = []
        for u in urls:
            try:
                r = requests.get(u, headers=self.headers,
                                 proxies=self.proxies,
                                 timeout=self.cfg["probe_timeout"],
                                 allow_redirects=True)
                if r.status_code != 200:
                    self.log(f"发布页请求失败: {u} HTTP {r.status_code}")
                    continue
                cands = self._extract_candidates_from_page(u, r.text, r.url or u)
                out.extend(cands)
            except Exception as e:
                self.log(f"解析发布页失败 {u}: {e}")
                continue
        # 去重
        seen, result = set(), []
        for u in out:
            if u not in seen:
                seen.add(u)
                result.append(u)
        print(f"[probe] 发布页累计候选: {len(result)}")
        return result

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

    def _fetch_and_extract(self, target_url, base):
        """兼容接口：原 51 的跳转拉取，保持签名不变"""
        try:
            t = self._abs_url(target_url, base)
            if not t:
                return []
            r = requests.get(t, headers=self.headers,
                             proxies=self.proxies,
                             timeout=self.cfg["probe_timeout"],
                             allow_redirects=True)
            if r.status_code != 200:
                return []
            return self._extract_candidates_from_page(t, r.text, r.url or t)
        except Exception as e:
            print(f"[probe] 请求跳转目标失败: {e}")
            return []

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
        if mode == "plain":
            return text
        if mode == "redirect":
            return ""
        return text

    def _pick_domains(self, doc, base):
        seen, out = set(), []
        for a in doc("a").items():
            href = (a.attr("href") or "").strip()
            if not href:
                continue
            if href.startswith("//"):
                href = "https:" + href
            if href.startswith("/") and base:
                href = base.rstrip("/") + href
            if not href.startswith("http") or "." not in href:
                continue
            if any(x in href for x in ["javascript:", "mailto:", "#"]):
                continue
            if href not in seen:
                seen.add(href)
                out.append(href)
        return out

    # ================= 首页（51 原样） =================
    def homeContent(self, filter):
        try:
            r = requests.get(self.host, headers=self.headers,
                             proxies=self.proxies, timeout=self.cfg["timeout"])
            if r.status_code != 200:
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
            r = requests.get(self.host, headers=self.headers,
                             proxies=self.proxies, timeout=self.cfg["timeout"])
            if r.status_code != 200:
                return {"list": []}
            doc = self.getpq(r.text)
            return {"list": self.getlist(doc(self.cfg["list_selector"]))}
        except Exception as e:
            print(f"homeVideoContent error: {e}")
            return {"list": []}

    # ================= 分类（51 原样 + 翻页修复） =================
    def categoryContent(self, tid, pg, filter, extend):
        try:
            if '@folder' in tid:
                id = tid.replace('@folder', '')
                videos = self.getfod(id)
                return {'list': videos, 'page': pg, 'pagecount': 1, 'limit': 90, 'total': len(videos)}

            pg = int(pg)
            tid = tid.rstrip('/')
            url = f"{self.host}{tid}/{pg}/" if pg > 1 else f"{self.host}{tid}/"

            rsp = requests.get(url, headers=self.headers, proxies=self.proxies, timeout=15)
            if rsp.status_code != 200:
                return {'list': [], 'page': pg, 'pagecount': 1, 'limit': 90, 'total': 0}

            doc = self.getpq(rsp.text)
            videos = self.getlist(doc('#archive article a, #index article a'), tid)

            total_pages = 1
            has_next = False

            pagenav = doc('ul.page-navigator')
            if pagenav:
                max_page = 0
                for a in pagenav('li a').items():
                    t = (a.text() or '').strip()
                    if t.isdigit():
                        max_page = max(max_page, int(t))
                if max_page > 0:
                    total_pages = max_page
                if pagenav('li.next a').attr('href'):
                    has_next = True

            if total_pages <= 1:
                page_info = doc('.pagination .pages, .page-nav, .pagenavi').text() or ''
                if '共' in page_info and '页' in page_info:
                    try:
                        total_pages = int(page_info.split('共')[-1].split('页')[0])
                    except Exception:
                        pass

            if not has_next:
                nxt = doc(
                    'ul.page-navigator li.next a, '
                    '.pagination a.next, .pagenavi a.next, '
                    'li.next a, a.next, a:contains("下一页")'
                ).attr('href')
                has_next = bool(nxt)

            if total_pages > 1:
                pagecount = total_pages
            elif has_next:
                pagecount = pg + 1
            else:
                pagecount = pg

            total_count = (pagecount * 90) if pagecount > 1 else len(videos)

            return {
                'list': videos,
                'page': pg,
                'pagecount': pagecount,
                'limit': 90,
                'total': total_count
            }
        except Exception as e:
            print(f"categoryContent error: {e}")
            return {'list': [], 'page': pg, 'pagecount': 1, 'limit': 90, 'total': 0}

    # ================= 详情（51 原样） =================
    def detailContent(self, ids):
        try:
            raw_id = ids[0] if ids else ""
            url = raw_id if raw_id.startswith("http") else f"{self.host}{raw_id}"

            r = requests.get(url, headers=self.headers,
                             proxies=self.proxies, timeout=self.cfg["timeout"])
            if r.status_code != 200:
                return {"list": [{
                    "vod_play_from": self.cfg["play_from"],
                    "vod_play_url": f"页面加载失败${url}",
                }]}

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
                            clist.append(
                                "[a=cr:" + json.dumps({"id": href, "name": title}) + "/]"
                                + title + "[/a]"
                            )
                vod["vod_content"] = (
                    " ".join(clist) if clist
                    else doc(self.cfg["title_selector"]).text()
                )
            except Exception:
                vod["vod_content"] = doc(self.cfg["title_selector"]).text() or self.cfg["name"]

            try:
                plist = self._parse_players(doc)
                if plist:
                    vod["vod_play_url"] = "#".join(plist)
                else:
                    vod["vod_play_url"] = f"未找到视频源${url}"
            except Exception:
                vod["vod_play_url"] = f"视频解析失败${url}"

            return {"list": [vod]}
        except Exception as e:
            print(f"detailContent error: {e}")
            return {"list": [{
                "vod_play_from": self.cfg["play_from"],
                "vod_play_url": f"详情页加载失败${ids[0] if ids else ''}",
            }]}

    # ================= 搜索（51 原样） =================
    def searchContent(self, key, quick, pg="1"):
        try:
            if str(pg) != "1":
                url = self.cfg["search_url_tpl_paged"].format(host=self.host, key=key, pg=pg)
            else:
                url = self.cfg["search_url_tpl"].format(host=self.host, key=key)

            r = requests.get(url, headers=self.headers,
                             proxies=self.proxies, timeout=self.cfg["timeout"])
            if r.status_code != 200:
                return {"list": [], "page": pg}

            doc = self.getpq(r.text)
            videos = self.getlist(doc(self.cfg["list_selector"]))
            return {"list": videos, "page": pg}
        except Exception as e:
            print(f"searchContent error: {e}")
            return {"list": [], "page": pg}

    # ================= 播放（51 原样） =================
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
        ydata = requests.get(url, headers=self.headers,
                             proxies=self.proxies, allow_redirects=False)
        data = ydata.content.decode("utf-8")
        if ydata.headers.get("Location"):
            url = ydata.headers["Location"]
            data = requests.get(url, headers=self.headers,
                                proxies=self.proxies).content.decode("utf-8")

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
                    lines[index] = re.sub(
                        pattern,
                        f'URI="{self.proxy(m.group(1), "mkey")}"',
                        string,
                    )
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
        data = requests.get(url, headers=self.headers,
                            proxies=self.proxies, stream=True)
        return [200, data.headers["Content-Type"], data.content]

    # ================= Base64（51 原样） =================
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

    # ================= 播放器解析（51 原样） =================
    def _parse_players(self, doc):
        plist = []
        used_names = set()
        sel = self.cfg["player_selector"]
        attr = self.cfg["player_config_attr"]

        if not doc(sel):
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

    # ================= 列表（51 原样） =================
    def getlist(self, data, tid=""):
        videos = []
        is_folder = self.cfg["folder_id_marker"] in (tid or "")
        for k in data.items():
            href = k.attr("href")
            name = k("h2").text()
            remark = (
                k("span[itemprop='datePublished']").text()
                or k(".post-meta, .entry-meta, time").text()
            )
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

    # ================= 合集（51 原样） =================
    def getfod(self, folder_id):
        url = f"{self.host}{folder_id}"
        r = requests.get(url, headers=self.headers,
                         proxies=self.proxies, timeout=self.cfg["timeout"])
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

    # ================= 图片（51 原样） =================
    def getimg(self, text):
        m = re.search(self.cfg["img_regex"], text or "")
        if m:
            return f"{self.getProxyUrl()}&url={m.group(1)}&type=img"
        return ""

    def aesimg(self, word):
        cipher = AES.new(self.cfg["aes_key"], AES.MODE_CBC, self.cfg["aes_iv"])
        return unpad(cipher.decrypt(word), AES.block_size)

    # ================= PyQuery（51 原样） =================
    def getpq(self, data):
        try:
            return pq(data)
        except Exception as e:
            print(f"{e}")
            return pq(data.encode("utf-8"))


# ==============  万能一键加速（2026-10五星无探测双 CDN 版）  ==============
_PIC_CDN_POOL = ('lib.baomitu.com', 'open.oppomobile.com')


def _cover_fallback(self, pic_url):
    import urllib.parse
    raw = pic_url or ''
    parent_impl = getattr(super(Spider, self), '_cover_fallback', None)
    if callable(parent_impl):
        try:
            raw = parent_impl(pic_url) or raw
        except Exception:
            pass
    if not raw:
        return ''
    url = raw
    for cdn in _PIC_CDN_POOL:
        if cdn in raw:
            url = raw.replace(cdn, _PIC_CDN_POOL[0])
            break
    proxy_base = getattr(self, 'proxy_base', None)
    if proxy_base:
        url = f'{proxy_base}{urllib.parse.quote(url)}'
    return url


Spider._cover_fallback = _cover_fallback

if __name__ == '__main__':
    from base.spider import Spider as BaseSpider
    BaseSpider.register(Spider)
