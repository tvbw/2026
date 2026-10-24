# -*- coding: utf-8 -*-
import json, re, sys, time, hashlib, logging
from base64 import b64decode, b64encode
from urllib.parse import quote, unquote
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
        def getProxyUrl(self):    return ""

try:
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
except Exception:
    pass

LOG = logging.getLogger(__name__)

# ==================================================================
# ★ 全局诊断：TVBox 屏幕上能直接看到的探测日志
# ==================================================================
PROBE_DIAG = {"logs": [], "host": "", "ok": False}
DIAG_TID = "/__diag__"
DIAG_VID = "diag://root"

def _diag(msg):
    try:
        s = str(msg)
    except Exception:
        s = "?"
    PROBE_DIAG["logs"].append(s)
    if len(PROBE_DIAG["logs"]) > 60:
        PROBE_DIAG["logs"] = PROBE_DIAG["logs"][-60:]
    try:
        print("[PROBE] " + s)
    except Exception:
        pass


# ==================================================================
# ① 配置层：换站只改这里
# ==================================================================
class SiteConfig:
    SEED_HOSTS = [
        "https://mrdsa2.com/",
        "https://mrdsa1.com/",
        "https://mrdsy1.com/",
        "https://mrdsy2.com/",
        "https://mrdsy3.com/",
    ]
    FALLBACK_HOST   = None            # 设为 None 表示不用硬兜底
    HOST_CACHE_KEY  = "mrds_host"
    HOST_CACHE_TTL  = 6 * 3600

    # 探测
    PROBE_TIMEOUT        = 6
    PROBE_MAX_ROUNDS     = 4
    PROBE_MAX_STEPS      = 24
    PROBE_TOTAL_DEADLINE = 40          # 秒；超时立刻返回，避免 TVBox 卡死
    PROBE_MIN_HTML       = 3000
    PROBE_MIN_ARTICLE    = 3

    SITE_KEYWORDS    = ["每日大赛"]
    SITE_MARKERS     = ["post-title", "entry-title", "<article"]
    PUB_PAGE_MARKERS = ["发布页", "最新地址", "备用地址", "永久地址", "网址发布"]

    # 发布页解析
    RE_B64_DOMAIN_BLOB = r"Base64\.decode\('([A-Za-z0-9+/=]+)'\)"
    RE_RANDOM_SUFFIX   = r"words\.random\(\)\s*\+\s*'\.([a-z0-9.-]+\.[a-z]{2,})'"
    RE_JUMP_ANCHOR     = r'<a[^>]*href="(https://[^"]+)"[^>]*>\s*加载中'
    RE_ANY_ANCHOR      = r'href="(https://[^"]+)"'
    PUB_DOMAIN_TLDS    = ["cc","com","net","org","xyz","top","club","site","vip"]
    RE_LITERAL_DOMAIN  = r"'([a-z0-9-]+\.(?:%s))'" % "|".join(PUB_DOMAIN_TLDS)
    RE_ANY_URL         = r"https?://([a-z0-9-]+(?:\.[a-z0-9-]+)+)(?:[/\"'\s?#]|$)"
    PUB_HOST_PREFIX    = "https://www.%s/"
    EXCLUDE_DOMAINS    = [
        "google","gstatic","cloudflare","jsdelivr","cdn","fonts","bootstrap",
        "jquery","w3.org","schema.org","youtube","twitter","facebook",
        "beian","gov.cn","mozilla","github","unpkg","bootcdn",
    ]

    # CSS
    SEL_ARTICLE      = "#index article, #archive article, article"
    SEL_ARTICLE_HOME = "#index article, article"
    SEL_NAV          = [".category-list ul li", ".nav-menu li", ".menu li", "nav ul li"]
    SEL_PLAYER       = ".dplayer"
    SEL_CONTENT      = ".post-content, article"
    SEL_TAGS         = ".post-tags a, .tags a, .keywords a"
    SEL_SUMMARY      = ".post-content"
    SEL_TITLE        = ".post-title, h1"

    LINK_KEYWORDS    = ("点击观看", "观看", "播放", "视频", "第一弹")
    DEFAULT_CATEGORY = {"type_name": "每日大赛", "type_id": "/category/mrds/"}

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
# ② 域名解析器：所有判定/提取走实例方法，不硬引用 SiteConfig
# ==================================================================
class DomainResolver:
    def __init__(self, cfg, fetcher, cache_get=None, cache_set=None):
        self.cfg, self.fetch = cfg, fetcher
        self.cache_get, self.cache_set = cache_get, cache_set
        self._visited, self._count, self._start_ts = set(), 0, time.time()

    def _deadline_ok(self):
        return time.time() - self._start_ts < self.cfg.PROBE_TOTAL_DEADLINE

    def _site_ok(self, html):
        if not html or len(html) < self.cfg.PROBE_MIN_HTML:
            return False
        low = html.lower()
        if low.count("<article") >= self.cfg.PROBE_MIN_ARTICLE:
            return True
        has_kw = any(kw in html for kw in self.cfg.SITE_KEYWORDS)
        has_mk = any(m in low for m in self.cfg.SITE_MARKERS)
        return has_kw and has_mk

    def _js_jump(self, html):
        if not html: return ""
        m = re.search(self.cfg.RE_JUMP_ANCHOR, html)
        if m: return m.group(1).rstrip("/") + "/"
        if "加载中" in html:
            m = re.search(self.cfg.RE_ANY_ANCHOR, html)
            if m: return m.group(1).rstrip("/") + "/"
        return ""

    def _pub_hosts(self, html, current_host=""):
        if not html: return []
        cfg, text = self.cfg, html
        m = re.search(cfg.RE_B64_DOMAIN_BLOB, text)
        if m:
            try:
                text += "\n" + b64decode(m.group(1) + "===").decode("utf-8", "ignore")
            except Exception:
                pass
        suffixes = re.findall(cfg.RE_RANDOM_SUFFIX, text)
        suffixes += re.findall(cfg.RE_LITERAL_DOMAIN, text)
        if any(mk in html for mk in cfg.PUB_PAGE_MARKERS):
            cur = re.sub(r"^https?://", "", (current_host or "").lower()).split("/")[0]
            for mm in re.finditer(cfg.RE_ANY_URL, text, re.I):
                dom = mm.group(1).lower()
                if dom == cur: continue
                if any(b in dom for b in cfg.EXCLUDE_DOMAINS): continue
                if len(dom) > 40: continue
                suffixes.append(dom)
        out, seen = [], set()
        for s in suffixes:
            s = s.lstrip(".")
            if not s or s in seen: continue
            seen.add(s)
            out.append(cfg.PUB_HOST_PREFIX % s)
        return out

    @staticmethod
    def _expand_schemes(urls):
        out, seen = [], set()
        for u in urls:
            if not u: continue
            for sc in ("https", "http"):
                v = re.sub(r"^https?://", sc + "://", u, count=1)
                if v not in seen:
                    seen.add(v); out.append(v)
        return out

    def _probe_batch(self, urls, timeout):
        results = {}
        urls = [u for u in urls if u and u not in self._visited]
        if not urls: return results
        self._visited.update(urls)
        workers = min(6, max(1, len(urls)))
        try:
            with ThreadPoolExecutor(max_workers=workers) as ex:
                futs = {ex.submit(self._safe_fetch, u, timeout): u for u in urls}
                for f in as_completed(futs, timeout=timeout + 5):
                    u = futs[f]
                    if not self._deadline_ok():
                        _diag("⏱ 总耗时超限，停止本批")
                        break
                    self._count += 1
                    if self._count > self.cfg.PROBE_MAX_STEPS:
                        _diag("⚠ 请求数超限")
                        break
                    try:
                        r = f.result()
                    except Exception as e:
                        _diag("✗ %s 异常: %s" % (u, str(e)[:50])); continue
                    if r is None:
                        _diag("✗ %s 无响应" % u); continue
                    html  = r.text or ""
                    final = (r.url or u).rstrip("/") + "/"
                    ok    = self._site_ok(html)
                    _diag("%s %s → %d字/%d篇" % (
                        "✅" if ok else "✗", u,
                        len(html), html.lower().count("<article")))
                    results[u] = (ok, final, html)
        except Exception as e:
            _diag("批量探测异常: %s" % str(e)[:60])
        return results

    def _safe_fetch(self, url, timeout):
        try: return self.fetch(url, timeout=timeout)
        except Exception: return None

    # ---------- 缓存 ----------
    def _read_cache(self):
        if not self.cache_get: return None
        try: raw = self.cache_get(self.cfg.HOST_CACHE_KEY)
        except Exception: return None
        if not raw: return None
        if isinstance(raw, str) and raw.startswith("http"):
            return {"host": raw.rstrip("/"), "ts": 0}
        try:
            if isinstance(raw, str): raw = json.loads(raw)
            if isinstance(raw, dict) and raw.get("host"):
                return raw
        except Exception:
            pass
        return None

    def _cache_fresh(self, c):
        ttl = int(getattr(self.cfg, "HOST_CACHE_TTL", 0) or 0)
        if ttl <= 0: return True
        return (time.time() - int(c.get("ts") or 0)) < ttl

    def _write_cache(self, host):
        if not self.cache_set: return
        try:
            self.cache_set(self.cfg.HOST_CACHE_KEY,
                           json.dumps({"host": host, "ts": int(time.time())}))
        except Exception:
            pass

    # ---------- 主流程 ----------
    def resolve(self):
        cfg = self.cfg
        PROBE_DIAG["logs"].clear()
        PROBE_DIAG["ok"] = False
        PROBE_DIAG["host"] = ""
        _diag("=== 开始域名探测 ===")

        cached = self._read_cache()
        if cached:
            fresh = self._cache_fresh(cached)
            _diag("缓存: %s (%s)" % (cached["host"], "有效期内" if fresh else "已过期"))
            if fresh:
                res = self._probe_batch([cached["host"] + "/"], cfg.PROBE_TIMEOUT)
                for u, (ok, final, _) in res.items():
                    if ok:
                        h = final.rstrip("/")
                        PROBE_DIAG.update(host=h, ok=True)
                        _diag("✅ 缓存有效: %s" % h)
                        return h
                _diag("✗ 缓存失效，重新探测")

        seeds = list(cfg.SEED_HOSTS)
        if cached: seeds.insert(0, cached["host"] + "/")
        current = self._expand_schemes(seeds)

        for rnd in range(cfg.PROBE_MAX_ROUNDS):
            if not current or not self._deadline_ok(): break
            _diag("--- 第 %d 轮(候选 %d) ---" % (rnd + 1, len(current)))
            res = self._probe_batch(current, cfg.PROBE_TIMEOUT)

            for u, (ok, final, _) in res.items():
                if ok:
                    h = final.rstrip("/")
                    self._write_cache(h)
                    PROBE_DIAG.update(host=h, ok=True)
                    _diag("✅ 命中: %s" % h)
                    return h

            nxt = []
            for u, (_ok, _f, html) in res.items():
                if not html: continue
                j = self._js_jump(html)
                if j:
                    _diag("  ↪ JS 跳转: %s" % j); nxt.append(j)
                pub = self._pub_hosts(html, u)
                if pub:
                    _diag("  ↪ 发布页候选(%d): %s" % (len(pub), ", ".join(x[8:] for x in pub[:3])))
                    nxt.extend(pub)
            current = self._expand_schemes(nxt)

        if cached:
            _diag("⚠ 使用过期缓存: %s" % cached["host"])
            PROBE_DIAG["host"] = cached["host"]
            return cached["host"]

        if getattr(cfg, "FALLBACK_HOST", None):
            _diag("⚠ 使用硬兜底: %s" % cfg.FALLBACK_HOST)
            PROBE_DIAG["host"] = cfg.FALLBACK_HOST.rstrip("/")
            return cfg.FALLBACK_HOST.rstrip("/")

        _diag("❌ 全部种子探测失败")
        _diag("👉 请把能访问的地址手填到 SEED_HOSTS 最前面")
        return ""


# ==================================================================
# ③ 主爬虫基类
# ==================================================================
class BaseMultiDomainSpider(BaseSpider):
    CONFIG = SiteConfig

    def __init__(self, extend="", *a, **kw):
        try: super().__init__(*a, **kw)
        except Exception: pass
        self.proxies, self.host, self._img_cache = {}, "", {}

    def init(self, extend=""):
        try: self.proxies = json.loads(extend) if extend else {}
        except Exception: self.proxies = {}
        self.headers = dict(self.CONFIG.HEADERS)
        self.host = DomainResolver(
            self.CONFIG, self._get,
            cache_get=getattr(self, "getCache", None),
            cache_set=getattr(self, "setCache", None),
        ).resolve()
        if self.host:
            self.headers.update({"Origin": self.host, "Referer": self.host + "/"})

    def getName(self):          return "🌈 多域名通用"
    def manualVideoCheck(self): return False
    def isVideoFormat(self, u): return any(e in (u or "") for e in (".m3u8", ".mp4", ".ts"))
    def destroy(self):          self._img_cache.clear()

    # ---- 网络 ----
    def _get(self, url, timeout=None, **kw):
        try:
            return requests.get(
                url, headers=self.headers, proxies=self.proxies,
                timeout=timeout or self.CONFIG.PROBE_TIMEOUT,
                verify=False, allow_redirects=True, **kw)
        except Exception as e:
            _diag("GET 异常 %s: %s" % (url[:60], str(e)[:50]))
            return None

    def _get_soup(self, url, timeout=15):
        r = self._get(url, timeout=timeout)
        if r is None or r.status_code != 200: return None, None
        return r, self.getpq(r.text)

    @staticmethod
    def getpq(data):
        try: return pq(data)
        except Exception: return pq(data.encode("utf-8"))

    @staticmethod
    def e64(s): return b64encode(str(s).encode()).decode()
    @staticmethod
    def d64(s): return b64decode(str(s).encode()).decode()

    def _abs(self, href):
        if not href: return ""
        if href.startswith("http"): return href
        if not self.host: return href
        return self.host + (href if href.startswith("/") else "/" + href)

    @staticmethod
    def _unique(name, seen):
        if name not in seen:
            seen.add(name); return name
        c = 2
        while "%s %d" % (name, c) in seen: c += 1
        new = "%s %d" % (name, c); seen.add(new); return new

    # ---------------- 诊断 UI ----------------
    def _diag_list_item(self):
        logs = PROBE_DIAG["logs"] or ["暂无日志"]
        host = PROBE_DIAG["host"] or "(未获取)"
        title = ("🔧 站点诊断 | " + ("✅ " + host if PROBE_DIAG["ok"] else "❌ 探测失败"))
        return {
            "vod_id": DIAG_VID,
            "vod_name": title[:60],
            "vod_pic": "",
            "vod_remarks": "%d 条日志" % len(logs),
            "vod_tag": "",
        }

    def _diag_detail(self):
        logs = PROBE_DIAG["logs"] or ["暂无日志"]
        host = PROBE_DIAG["host"] or "(未获取)"
        state = "✅ 已连接" if PROBE_DIAG["ok"] else "❌ 探测失败"
        head = ("状态: %s\n当前host: %s\n种子数: %d\n\n=== 探测日志 ===\n"
                % (state, host, len(self.CONFIG.SEED_HOSTS)))
        return {
            "vod_id": DIAG_VID,
            "vod_name": "🔧 站点诊断报告",
            "vod_pic": "",
            "vod_content": head + "\n".join(logs),
            "vod_play_from": "诊断",
            "vod_play_url": "占位$http://127.0.0.1/nothing.mp4",
        }

    # ---------------- 首页 / 分类 ----------------
    def homeContent(self, filter=False):
        # 探测失败 → 只显示诊断
        if not self.host:
            return {"class": [{"type_name": "🔧 站点诊断", "type_id": DIAG_TID}],
                    "list": [self._diag_list_item()]}

        r, data = self._get_soup(self.host)
        if data is None:
            return {"class": [{"type_name": "🔧 站点诊断", "type_id": DIAG_TID}],
                    "list": [self._diag_list_item()]}

        classes = [{"type_name": "🔧 站点诊断", "type_id": DIAG_TID}]
        classes.extend(self._parse_classes(data))
        return {"class": classes,
                "list": self._parse_list(data(self.CONFIG.SEL_ARTICLE_HOME))}

    def homeVideoContent(self):
        if not self.host:
            return {"list": [self._diag_list_item()]}
        r, data = self._get_soup(self.host)
        if data is None:
            return {"list": [self._diag_list_item()]}
        return {"list": self._parse_list(data(self.CONFIG.SEL_ARTICLE_HOME))}

    def _parse_classes(self, data):
        for sel in self.CONFIG.SEL_NAV:
            out = []
            for k in data(sel).items():
                a = k("a")
                href = (a.attr("href") or "").strip()
                name = (a.text() or "").strip()
                if not href or href in ("#", "/") or not name: continue
                if not href.startswith("http"):
                    href = "/" + href.lstrip("/")
                out.append({"type_name": name, "type_id": href})
            if out: return out
        return [dict(self.CONFIG.DEFAULT_CATEGORY)]

    def categoryContent(self, tid, pg=1, filter=False, extend=None):
        if tid == DIAG_TID:
            return {"list": [self._diag_list_item()],
                    "page": 1, "pagecount": 1, "limit": 20, "total": 1}
        if not self.host:
            return {"list": [self._diag_list_item()],
                    "page": 1, "pagecount": 1, "limit": 20, "total": 1}

        pg = int(pg or 1)
        if "@folder" in tid:
            v = self._parse_folder(tid.replace("@folder", ""))
            return {"list": v, "page": 1, "pagecount": 1,
                    "limit": 90, "total": len(v)}

        url = self._build_page_url(tid, pg)
        r, data = self._get_soup(url)
        if data is None:
            return {"list": [], "page": pg, "pagecount": 9999, "limit": 90, "total": 0}
        return {"list": self._parse_list(data(self.CONFIG.SEL_ARTICLE), tid),
                "page": pg, "pagecount": 9999, "limit": 90, "total": 999999}

    def _build_page_url(self, tid, pg):
        if tid.startswith("http"):
            base = tid.rstrip("/")
        else:
            base = (self.host + "/" + tid.lstrip("/")).rstrip("/")
        if pg == 1: return base + "/"
        host_ns = self.host.rstrip("/")
        if base == host_ns: return "%s/page/%d/" % (host_ns, pg)
        if "/category/" in base or "/tag/" in base: return "%s/%d/" % (base, pg)
        if "/page/" in base: return "%s/%d/" % (base, pg)
        return "%s/page/%d/" % (base, pg)

    # ---------------- 列表解析 ----------------
    def _parse_list(self, data, tid=""):
        is_folder = "/mrdg" in (tid or "")
        videos = []
        for k in data.items():
            href = k.attr("href") or k("a").eq(0).attr("href")
            title = (k("h2").text() or k(".entry-title").text()
                     or k(".post-title").text() or "").strip()
            if not title and k.is_("a"):
                title = (k.text() or "").strip()
            if not href or not title: continue
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
        if data is None: return []
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

    # ---------------- 搜索 ----------------
    def searchContent(self, key, quick=False, pg=1):
        if not self.host:
            return {"list": [self._diag_list_item()], "page": 1, "pagecount": 1}
        pg  = int(pg or 1)
        url = "%s/search/%s/%s" % (self.host, key, ("%d/" % pg) if pg > 1 else "")
        r, data = self._get_soup(url)
        if data is None:
            return {"list": [], "page": pg, "pagecount": 9999}
        return {"list": self._parse_list(data("article")),
                "page": pg, "pagecount": 9999}

    # ---------------- 详情 ----------------
    def detailContent(self, ids):
        vid = str(ids[0] if isinstance(ids, (list, tuple)) else ids)
        if vid.startswith("diag://"):
            return {"list": [self._diag_detail()]}
        if not self.host:
            return {"list": [self._diag_detail()]}

        url = vid if vid.startswith("http") else self.host + vid
        r, data = self._get_soup(url)
        if data is None:
            return {"list": [self._diag_detail()]}

        playlist = self._extract_playlist(data)
        play_url = "#".join(playlist) or "未找到视频源，请访问网页$%s" % url
        return {"list": [{
            "vod_play_from": "线路",
            "vod_play_url":  play_url,
            "vod_content":   self._extract_content(data),
        }]}

    def _extract_playlist(self, data):
        if data(self.CONFIG.SEL_PLAYER):
            pl = self._from_dplayer(data)
            if pl: return pl
        return self._from_links(data)

    def _from_dplayer(self, data):
        out, used = [], set()
        for i, k in enumerate(data(self.CONFIG.SEL_PLAYER).items(), 1):
            try:
                cfg = json.loads(k.attr("data-config") or "{}")
                url = cfg.get("video", {}).get("url", "")
                if not url: continue
                base = self._near_heading(k) or "视频%d" % i
                out.append("%s$%s" % (self._unique(base, used), url))
            except Exception:
                continue
        return out

    def _from_links(self, data):
        out = []
        for i, link in enumerate(data(self.CONFIG.SEL_CONTENT)("a").items(), 1):
            txt, href = (link.text() or "").strip(), link.attr("href")
            if not href or not any(kw in txt for kw in self.CONFIG.LINK_KEYWORDS):
                continue
            name = (txt.replace("点击观看：", "").replace("点击观看", "").strip()
                    or "视频%d" % i)
            out.append("%s$%s" % (name, self._abs(href)))
        return out

    @staticmethod
    def _near_heading(k, levels=4):
        p = k.parents().eq(0)
        for _ in range(levels):
            if not p: break
            h = p.find("h2, h3, h4").eq(0).text().strip()
            if h: return h
            p = p.parents().eq(0)
        return ""

    def _extract_content(self, data):
        tags = []
        for k in data(self.CONFIG.SEL_TAGS).items():
            t, h = (k.text() or "").strip(), k.attr("href")
            if t and h:
                target = json.dumps({"id": self._abs(h), "name": t})
                tags.append("[a=cr:%s/]%s[/a]" % (target, t))
        if tags:
            summary = (data(self.CONFIG.SEL_SUMMARY).text() or "")[:150]
            return " ".join(tags) + "\n\n" + summary
        return data(self.CONFIG.SEL_TITLE).text() or "每日大赛"

    # ---------------- 图片 ----------------
    def _parse_pic(self, k):  return self._extract_img(k("script").text(), k)

    def _parse_date(self, k):
        t = k("time").text()
        if t: return t.strip()
        full = k.text()
        m = re.search(r"(\d{4}\s*年\s*\d{1,2}\s*月\s*\d{1,2}\s*日)", full)
        if not m: m = re.search(r"(\d{4}-\d{1,2}-\d{1,2})", full)
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
            if m: return self._proc_url(m.group(1))
        return ""

    def _proc_url(self, url):
        if not url: return ""
        url = url.strip("'\" ")
        if url.startswith("data:"):
            try:
                _, b64s = url.split(",", 1)
                raw = b64decode(b64s)
                if not self._is_image(raw): raw = self.aesimg(raw)
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
        if len(data) < 16: return data
        for key, iv in self.CONFIG.IMG_AES_KEYS:
            if iv:
                try:
                    dec = unpad(AES.new(key, AES.MODE_CBC, iv).decrypt(data), 16)
                    if self._is_image(dec): return dec
                except Exception: pass
            try:
                dec = unpad(AES.new(key, AES.MODE_ECB).decrypt(data), 16)
                if self._is_image(dec): return dec
            except Exception: pass
        return data

    # ---------------- 播放 / 代理 ----------------
    def playerContent(self, flag, id, vipFlags=None):
        if id and id.startswith("diag://"):
            return {"parse": 0, "url": id}
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
        if res is None: return [404, "text/plain", b""]
        base = res.url.rsplit("/", 1)[0]
        out = []
        for line in res.text.split("\n"):
            if "#EXT" not in line and line.strip():
                if not line.startswith("http"): line = "%s/%s" % (base, line)
                out.append(self.proxy(line, "ts"))
            else:
                out.append(line)
        return [200, "application/vnd.apple.mpegurl", "\n".join(out)]

    def _ts_proxy(self, url):
        real = url if url.startswith("http") else self.d64(url)
        res = self._get(real)
        return [200, "video/mp2t", res.content] if res else [404, "text/plain", b""]


# ==================================================================
# ④ 具体站点
# ==================================================================
class Spider(BaseMultiDomainSpider):
    CONFIG = SiteConfig
    def getName(self):
        return "🌈 每日大赛|终极完美版"


# ==================================================================
# ⑤ 播放源聚合扩展（原逻辑保留）
# ==================================================================
def _install_playlist_extension(_C):
    if getattr(_C, "_pl_patched", False): return _C
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
        if not out: return
        self.page_cache[key] = out
        if key in self.page_keys: self.page_keys.remove(key)
        self.page_keys.append(key)
        for it in out: self.page_index[str(it["vod_id"])] = key
        while len(self.page_keys) > 30:
            self.page_cache.pop(self.page_keys.pop(0), None)

    def _page_of(self, vid):
        _ensure(self)
        key = self.page_index.get(str(vid))
        return list(self.page_cache.get(key, [])) if key in self.page_cache else []

    def _as_result(r):
        if r is None: return {}
        if isinstance(r, dict): return r
        if isinstance(r, (bytes, bytearray)): r = r.decode("utf-8", "ignore")
        if isinstance(r, str):
            s = r.strip()
            if s[:1] in "{[":
                try: return json.loads(s)
                except Exception: return {}
        return {}

    def _split_sources(vod):
        fr = str((vod or {}).get("vod_play_from") or "").split("$$$")
        ur = str((vod or {}).get("vod_play_url")  or "").split("$$$")
        while len(ur) < len(fr): ur.append("")
        src = []
        for i, name in enumerate(fr):
            parts = []
            for p in (ur[i] or "").split("#"):
                if not p: continue
                n, u = p.split("$", 1) if "$" in p else (str(i + 1), p)
                parts.append((_clean(n), u))
            src.append((_clean(name) or "线路%d" % (i + 1), parts))
        return [x for x in src if x[1]]

    def _call_detail(self, vid):
        if not _orig_detail: return {}
        try:    return _as_result(_orig_detail(self, [vid]))
        except TypeError:
            try:    return _as_result(_orig_detail(self, vid))
            except Exception: return {}
        except Exception:
            return {}

    def _load_src(self, vid):
        _ensure(self); vid = str(vid)
        if vid in self._src_cache: return self._src_cache[vid]
        r = self._pl_call_detail(vid)
        vod = ((r.get("list") or [None])[0]) or {}
        src = _split_sources(vod)
        self._src_cache[vid] = src
        return src

    def _item_parts(self, it, src_idx, current_sources, current_vid):
        iid = str(it.get("vod_id") or "")
        if not iid: return []
        name = _clean(it.get("vod_name") or iid) or iid
        if iid == str(current_vid):
            eps = []
            if current_sources:
                if src_idx < len(current_sources) and current_sources[src_idx][1]:
                    eps = current_sources[src_idx][1]
                else:
                    eps = current_sources[0][1]
            if len(eps) > 1:
                out = []
                for i, (en, u) in enumerate(eps):
                    label = _clean("%s %s" % (name, en or "%02d" % (i + 1)))
                    out.append("%s$%s" % (label, u))
                return out
            if eps: return ["%s$%s" % (name, eps[0][1])]
            return ["%s$nid:%s" % (name, _enc(iid))]
        return ["%s$nid:%s" % (name, _enc(iid))]

    def _apply_playlist(self, vid, vod, items):
        sources = _split_sources(vod)
        _ensure(self); self._src_cache[str(vid)] = sources
        if not items: return vod
        ordered = [x for x in items if str(x.get("vod_id")) == str(vid)]
        ordered += [x for x in items if str(x.get("vod_id")) != str(vid)]
        plist, seen = [], set()
        for it in ordered:
            iid = str(it.get("vod_id") or "")
            if not iid or iid in seen: continue
            seen.add(iid); plist.append(it)
        if not plist: return vod
        if not sources:
            sources = [("线路1", [("播放", "nid:%s" % _enc(vid))])]
        pf, pu = [], []
        for i, (sname, _e) in enumerate(sources):
            parts = []
            for it in plist:
                parts.extend(self._pl_item_parts(it, i, sources, vid))
            if not parts: continue
            pf.append(sname or "线路%d" % (i + 1))
            pu.append("#".join(parts))
        if not pf: return vod
        vod = dict(vod)
        vod["vod_play_from"] = "$$$".join(pf)
        vod["vod_play_url"]  = "$$$".join(pu)
        return vod

    def init(self, *a, **kw):
        _ensure(self)
        if _orig_init: return _orig_init(self, *a, **kw)

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
        if not _orig_search: return {"list": []}
        r = _orig_search(self, *a, **kw)
        try:
            key = a[0] if a else kw.get("key", "")
            pg  = a[2] if len(a) > 2 else kw.get("pg", "1")
            _cache_page(self, ("search", str(key), str(pg)),
                        _as_result(r).get("list"))
        except Exception: pass
        return r

    def searchContentPage(self, *a, **kw):
        _ensure(self)
        if not _orig_searchp: return {"list": []}
        r = _orig_searchp(self, *a, **kw)
        try:
            key = a[0] if a else kw.get("key", "")
            pg  = a[2] if len(a) > 2 else kw.get("page", kw.get("pg", "1"))
            _cache_page(self, ("searchp", str(key), str(pg)),
                        _as_result(r).get("list"))
        except Exception: pass
        return r

    def detailContent(self, ids, *a, **kw):
        _ensure(self)
        if isinstance(ids, (list, tuple)):
            vid = str(ids[0]) if ids else ""
            call_ids = list(ids)
        else:
            vid = str(ids); call_ids = [vid]
        if vid.startswith("nid:"):
            vid = _dec(vid[4:]); call_ids[0] = vid
        cached = _page_of(self, vid)
        if _orig_detail:
            try: r = _orig_detail(self, call_ids, *a, **kw)
            except TypeError: r = _orig_detail(self, call_ids)
        else:
            r = {"list": []}
        try:
            rr  = _as_result(r)
            lst = rr.get("list") or []
            if not lst or not isinstance(lst[0], dict): return r
            vod = dict(lst[0]); vod["vod_id"] = str(vod.get("vod_id") or vid)
            if not vod.get("vod_name") and cached:
                hit = next((x for x in cached if str(x.get("vod_id")) == vid), None)
                if hit: vod["vod_name"] = hit.get("vod_name") or vid
            if cached: vod = self._pl_apply_playlist(vid, vod, cached)
            rr = dict(rr); rr["list"] = [vod]
            if isinstance(r, dict) or r is None: return rr
            try: return json.dumps(rr, ensure_ascii=False)
            except Exception: return rr
        except Exception:
            return r

    def playerContent(self, flag, id, vipFlags=None, *a, **kw):
        _ensure(self)
        s = str(id)
        if s.startswith("nid:"):
            vid = _dec(s[4:]); sources = self._pl_load_src(vid); real = ""
            if sources:
                picked = None
                for name, eps in sources:
                    if str(name) == str(flag) and eps: picked = eps; break
                if not picked: picked = sources[0][1]
                if picked: real = picked[0][1]
            id = real if real and not str(real).startswith("nid:") else vid
        if not _orig_player: return {"parse": 0, "url": id}
        try: return _orig_player(self, flag, id, vipFlags, *a, **kw)
        except TypeError:
            try: return _orig_player(self, flag, id, vipFlags)
            except TypeError: return _orig_player(self, flag, id)

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
