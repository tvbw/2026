# -*- coding: utf-8 -*-
# ============================================================
# 51 模板 · 零兜底 · 全自动 BFS 探测版
# 设计原则：
#   1. 只保留 seed_hosts（一级固定域名），不写死任何兜底域名
#   2. 探测引擎自动从种子出发：种子 → 发布页 → 二级域名 → 真站点
#   3. 探测失败返回空 host，UI 显示空，不静默用坏域名
#   4. 51 内容抓取逻辑全部保留，零改动
# ============================================================
import json
import re
import sys
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

    # ============ 域名探测配置 ============
    # ① 一级固定长期域名（用户维护）—— 唯一的域名入口
    #    可以是"发布页"或"真站点"，引擎会自动识别
    #    按稳定性从高到低排列，越靠前越快命中
    "seed_hosts": [
        "https://51cgf19.com/",
        "https://51cgf20.com/",
        "https://51cgf18.com/",
    ],

    # ② 缓存
    "host_cache_key": "51_host",
    "host_cache_ttl": 6 * 3600,          # 秒；0 表示永不过期

    # ③ 探测参数
    "probe_timeout": 8,
    "probe_total_deadline": 40,           # 秒；超时立即收尾
    "probe_max_rounds": 5,                # BFS 最多 5 轮
    "probe_max_steps": 30,                # 总请求数上限
    "probe_min_html": 3000,               # 判定真站点的最小 HTML 长度

    # ④ 站点特征（三路 OR 判定）
    "host_check_selector": "#index article a",
    "site_keywords": [],
    "site_markers": ["post-title", "entry-title", "<article"],

    # ⑤ 发布页激进提取触发词
    "publish_page_markers": [
        "发布页", "最新地址", "备用地址", "永久地址", "网址发布", "访问地址",
    ],

    # ⑥ 发布页解析
    "publish_decode": "js_base64",
    "pub_domain_tlds": [
        "cc", "com", "net", "org", "xyz", "top", "club", "site", "vip",
    ],
    "exclude_domains": [
        "google", "gstatic", "cloudflare", "jsdelivr", "cdn", "fonts",
        "bootstrap", "jquery", "w3.org", "schema.org", "youtube",
        "twitter", "facebook", "beian", "gov.cn", "mozilla", "github",
        "unpkg", "bootcdn",
    ],

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
    "folder_remove_selectors": [
        ".txt-apps", ".line", "blockquote", ".tags", ".content-tabs",
    ],
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
# 多域名 BFS 探测器（通用，零兜底）
# ============================================================
class DomainResolver:
    """
    从 seed_hosts 出发 BFS 探测，命中真站点即返回

    输入：
      cfg           SITE_CONFIG
      fetcher(url, timeout) -> requests.Response | None
      cache_get(key) -> raw | None
      cache_set(key, val) -> None
    输出：
      可用 host（不带尾斜杠）或 ""（全失败）
    """

    def __init__(self, cfg, fetcher, cache_get=None, cache_set=None):
        self.cfg       = cfg
        self.fetcher   = fetcher
        self.cache_get = cache_get
        self.cache_set = cache_set
        self._visited  = set()
        self._count    = 0
        self._start_ts = time.time()

    def _deadline_ok(self):
        return (time.time() - self._start_ts) < self.cfg.get("probe_total_deadline", 40)

    # ---------- 三路站点判定 ----------
    def _site_ok(self, html):
        if not html or len(html) < self.cfg.get("probe_min_html", 3000):
            return False
        # ① 选择器命中
        sel = self.cfg.get("host_check_selector")
        if sel:
            try:
                if pq(html)(sel):
                    return True
            except Exception:
                pass
        # ② 关键词 + 标记
        low = html.lower()
        has_kw = any(kw in html for kw in (self.cfg.get("site_keywords") or []))
        has_mk = any(m  in low  for m  in (self.cfg.get("site_markers")  or []))
        if has_kw and has_mk:
            return True
        # ③ 文章数兜底（发布页一般不会有 article 标签）
        if low.count("<article") >= 3:
            return True
        return False

    # ---------- JS / meta 跳转 ----------
    def _js_jump(self, html):
        if not html:
            return ""
        m = re.search(
            r'<meta[^>]+http-equiv=["\']?refresh["\']?[^>]+'
            r'content=["\'][^"\']*url=([^"\'>\s]+)',
            html, re.I,
        )
        if m:
            return m.group(1).strip("'\"")
        for p in (
            r'window\.location(?:\.href)?\s*=\s*["\']([^"\']+)["\']',
            r'document\.location(?:\.href)?\s*=\s*["\']([^"\']+)["\']',
            r'location\.replace\(\s*["\']([^"\']+)["\']',
            r'location\.assign\(\s*["\']([^"\']+)["\']',
        ):
            m = re.search(p, html)
            if m:
                return m.group(1)
        if "加载中" in html:
            m = re.search(r'href="(https://[^"]+)"', html)
            if m:
                return m.group(1).rstrip("/") + "/"
        return ""

    # ---------- 从发布页提取候选域名（多路） ----------
    def _pub_hosts(self, html, current_url=""):
        if not html:
            return []
        cfg = self.cfg
        text = html
        out, seen = [], set()

        # ① Base64 混淆
        m = re.search(r"Base64\.decode\(['\"]([^'\"]+)['\"]\)", text)
        if m:
            try:
                text += "\n" + b64decode(m.group(1)).decode("utf-8", "ignore")
            except Exception:
                pass

        # ② atob 混淆
        m = re.search(r"atob\(['\"]([^'\"]+)['\"]\)", text)
        if m:
            try:
                text += "\n" + b64decode(m.group(1)).decode("utf-8", "ignore")
            except Exception:
                pass

        # ③ words.random() + 'xxx.cc'
        suffixes = re.findall(
            r"words\.random\(\)\s*\+\s*'\.([a-z0-9.-]+\.[a-z]{2,})'", text
        )

        # ④ 字面量 'xxx.cc'
        tlds = cfg.get("pub_domain_tlds") or ["cc", "com"]
        suffixes += re.findall(
            r"'([a-z0-9-]+\.(?:%s))'" % "|".join(tlds), text
        )

        for s in suffixes:
            s = s.lstrip(".")
            if not s or s in seen:
                continue
            seen.add(s)
            out.append("https://www.%s/" % s)

        # ⑤ 发布页激进提取：页面出现"发布页"等标记时，提取所有外链
        if any(mk in html for mk in (cfg.get("publish_page_markers") or [])):
            cur = re.sub(r"^https?://", "", (current_url or "").lower()).split("/")[0]
            for mm in re.finditer(
                r"https?://([a-z0-9-]+(?:\.[a-z0-9-]+)+)(?:[/\"'\s?#]|$)",
                text, re.I,
            ):
                dom = mm.group(1).lower()
                if dom == cur:
                    continue
                if any(bad in dom for bad in (cfg.get("exclude_domains") or [])):
                    continue
                if len(dom) > 40:
                    continue
                out.append("https://www.%s/" % dom)

        # 去重
        seen2, result = set(), []
        for u in out:
            if u not in seen2:
                seen2.add(u)
                result.append(u)
        return result

    # ---------- 辅助 ----------
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
        except Exception:
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
                            break
                        self._count += 1
                        if self._count > self.cfg.get("probe_max_steps", 30):
                            break
                        try:
                            r = f.result()
                        except Exception:
                            r = None
                        self._collect(results, u, r)
            except Exception:
                pass
        else:
            for u in urls:
                if not self._deadline_ok():
                    break
                self._count += 1
                if self._count > self.cfg.get("probe_max_steps", 30):
                    break
                self._collect(results, u, self._safe_fetch(u, timeout))
        return results

    def _collect(self, results, u, r):
        if r is None:
            print(f"[probe] ✗ {u} 无响应")
            return
        html  = r.text or ""
        final = (getattr(r, "url", None) or u).rstrip("/") + "/"
        ok    = self._site_ok(html)
        print(f"[probe] {'✅' if ok else '✗'} {u} ({len(html)}字)")
        results[u] = (ok, final, html)

    # ---------- 缓存 ----------
    def _read_cache(self):
        if not self.cache_get:
            return None
        try:
            raw = self.cache_get(self.cfg.get("host_cache_key", "host"))
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
            self.cache_set(
                self.cfg.get("host_cache_key", "host"),
                json.dumps({"host": host, "ts": int(time.time())}),
            )
        except Exception:
            pass

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

    # ---------- 主流程 ----------
    def resolve(self):
        cfg = self.cfg
        cached = self._read_cache()

        # ① 缓存有效期内先验证
        if cached and self._cache_fresh(cached):
            print(f"[probe] 缓存验证: {cached['host']}")
            res = self._probe_batch([cached["host"] + "/"], cfg.get("probe_timeout", 8))
            for _u, (ok, final, _h) in res.items():
                if ok:
                    h = final.rstrip("/")
                    print(f"[probe] ✅ 缓存有效: {h}")
                    return h
            print(f"[probe] ✗ 缓存失效，重新探测")

        # ② 从 seed_hosts 出发
        seeds = list(cfg.get("seed_hosts") or [])
        if cached:
            seeds.insert(0, cached["host"] + "/")
        current = self._expand_schemes(seeds)

        # ③ BFS 多轮
        for rnd in range(cfg.get("probe_max_rounds", 5)):
            if not current or not self._deadline_ok():
                break
            print(f"[probe] --- 第 {rnd + 1} 轮 (候选 {len(current)}) ---")
            res = self._probe_batch(current, cfg.get("probe_timeout", 8))

            for _u, (ok, final, _h) in res.items():
                if ok:
                    h = final.rstrip("/")
                    self._write_cache(h)
                    print(f"[probe] ✅ 确定 host: {h}")
                    return h

            nxt = []
            for u, (_ok, final, html) in res.items():
                if not html:
                    continue
                j = self._js_jump(html)
                if j:
                    j = self._abs_url(j, final)
                    if j:
                        print(f"[probe] ↪ {u} JS跳转")
                        nxt.append(j)
                pub = self._pub_hosts(html, u)
                if pub:
                    print(f"[probe] ↪ {u} 发布页候选 {len(pub)} 个")
                    nxt.extend(pub)
            current = self._expand_schemes(nxt)

        # ④ 过期缓存作最后保底（比用坏兜底域名更靠谱）
        if cached:
            print(f"[probe] ⚠ 使用过期缓存: {cached['host']}")
            return cached["host"]

        print("[probe] ❌ 探测失败，请更新 seed_hosts")
        return ""


# ============================================================
# 主爬虫：51 内容抓取 + 新探测引擎
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
        self.headers = dict(self.cfg["headers"])   # 不含 Origin/Referer

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
    # 域名探测
    # ============================================================
    def get_working_host(self):
        return DomainResolver(
            cfg=self.cfg,
            fetcher=self._probe_fetch,
            cache_get=self._cache_get,
            cache_set=self._cache_set,
        ).resolve()

    def _probe_fetch(self, url, timeout):
        try:
            return requests.get(
                url, headers=self.headers, proxies=self.proxies,
                timeout=timeout, allow_redirects=True,
            )
        except Exception:
            return None

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

    # ---- 兼容接口：原 51 的公开方法，供外部/调试使用 ----
    def extract_domains_from_publish_page(self):
        """从 seed_hosts 中提取所有发布页候选域名（兼容原接口）"""
        resolver = DomainResolver(
            self.cfg, self._probe_fetch, self._cache_get, self._cache_set,
        )
        out = []
        for u in (self.cfg.get("seed_hosts") or []):
            r = self._probe_fetch(u, self.cfg.get("probe_timeout", 8))
            if r is not None and r.status_code == 200:
                out.extend(resolver._pub_hosts(r.text, u))
        # 去重
        seen, result = set(), []
        for u in out:
            if u not in seen:
                seen.add(u)
                result.append(u)
        return result

    # ================= 首页（51 原样） =================
    def homeContent(self, filter):
        if not self.host:
            return {"class": [], "list": []}
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
        if not self.host:
            return {"list": []}
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
        if not self.host:
            return {'list': [], 'page': pg, 'pagecount': 1, 'limit': 90, 'total': 0}
        try:
            if '@folder' in tid:
                id = tid.replace('@folder', '')
                videos = self.getfod(id)
                return {'list': videos, 'page': pg, 'pagecount': 1,
                        'limit': 90, 'total': len(videos)}

            pg = int(pg)
            tid = tid.rstrip('/')
            url = f"{self.host}{tid}/{pg}/" if pg > 1 else f"{self.host}{tid}/"

            rsp = requests.get(url, headers=self.headers,
                               proxies=self.proxies, timeout=15)
            if rsp.status_code != 200:
                return {'list': [], 'page': pg, 'pagecount': 1,
                        'limit': 90, 'total': 0}

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
                'list': videos, 'page': pg, 'pagecount': pagecount,
                'limit': 90, 'total': total_count,
            }
        except Exception as e:
            print(f"categoryContent error: {e}")
            return {'list': [], 'page': pg, 'pagecount': 1,
                    'limit': 90, 'total': 0}

    # ================= 详情（51 原样） =================
    def detailContent(self, ids):
        if not self.host:
            return {"list": [{
                "vod_play_from": self.cfg["play_from"],
                "vod_play_url": "探测失败",
            }]}
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
        if not self.host:
            return {"list": [], "page": pg}
        try:
            if str(pg) != "1":
                url = self.cfg["search_url_tpl_paged"].format(
                    host=self.host, key=key, pg=pg,
                )
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
