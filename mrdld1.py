# -*- coding: utf-8 -*-
"""
通用多域名跳转站点爬虫模板
================================
适用站点特征：
  1) 拥有 4-6 个固定长期主域名（种子）
  2) 主域名跳转到"网址发布页"（JS 跳转 / Base64 混淆 / 文本域名列表）
  3) 发布页给出 3-4 个不定期变动的二级域名
  4) 二级域名实际承载内容（同构模板）

换站指引：
  - 只改 SiteConfig（SEED_HOSTS / SEL_* / IMG_AES_KEYS / RE_* / SITE_KEYWORDS）
  - 特殊行为通过钩子覆盖：_site_ok / _js_jump / _pub_hosts / _extract_playlist
"""
import json
import re
import hashlib
import logging
from base64 import b64decode, b64encode
from urllib.parse import urljoin

import requests
from Crypto.Cipher import AES
from Crypto.Util.Padding import unpad
from pyquery import PyQuery as pq

try:
    from base.spider import Spider as BaseSpider
except ImportError:
    class BaseSpider:
        def getCache(self, k):   return None
        def setCache(self, k, v): pass
        def getProxyUrl(self):   return ""

LOG = logging.getLogger(__name__)


# ==========================================================================
# ① 配置层：所有"可变"集中在这里，换站只改本段
# ==========================================================================
class SiteConfig:
    # ---- 种子域名（固定长期域名，稳定性高的排前）----
    SEED_HOSTS = [
        "https://mrdld1.com/",
        "https://mrdld2.com/",
        "https://mrdld3.com/",
    ]
    FALLBACK_HOST  = "https://www.ajuokwof.cc/"
    HOST_CACHE_KEY = "mrds_host"

    # ---- 探测参数 ----
    PROBE_TIMEOUT     = 4        # 单次探测超时
    PROBE_MAX_STEPS   = 16       # BFS 最大步数
    PROBE_MIN_HTML    = 8000     # 判定"真站点"的最小 HTML 长度
    PROBE_MIN_ARTICLE = 5        # 判定"真站点"的最小 article 数

    # ---- 站点身份特征（二次判定）----
    SITE_KEYWORDS = ["每日大赛"]
    SITE_MARKERS  = ["<article", "post-title"]

    # ---- 发布页混淆/跳转模式 ----
    RE_B64_DOMAIN_BLOB = r"Base64\.decode\('([A-Za-z0-9+/=]+)'\)"
    RE_RANDOM_SUFFIX   = r"words\.random\(\)\s*\+\s*'\.([a-z0-9.-]+\.[a-z]{2,})'"
    RE_JUMP_ANCHOR     = r'<a[^>]*href="(https://[^"]+)"[^>]*>\s*加载中'
    RE_ANY_ANCHOR      = r'href="(https://[^"]+)"'
    PUB_DOMAIN_TLDS    = ["cc"]                                   # 关注的 TLD
    RE_LITERAL_DOMAIN  = r"'([a-z0-9-]+\.(?:%s))'" % "|".join(PUB_DOMAIN_TLDS)
    PUB_HOST_PREFIX    = "https://www.%s/"

    # ---- CSS 选择器 ----
    SEL_ARTICLE      = "#index article, #archive article, article"
    SEL_ARTICLE_HOME = "#index article, article"
    SEL_NAV          = [".category-list ul li", ".nav-menu li", ".menu li", "nav ul li"]
    SEL_PLAYER       = ".dplayer"
    SEL_CONTENT      = ".post-content, article"
    SEL_TAGS         = ".post-tags a, .tags a, .keywords a"
    SEL_SUMMARY      = ".post-content"
    SEL_TITLE        = ".post-title, h1"

    # ---- 播放链接识别 ----
    LINK_KEYWORDS = ("点击观看", "观看", "播放", "视频", "第一弹")
    DEFAULT_CATEGORY = {"type_name": "每日大赛", "type_id": "/category/mrds/"}

    # ---- 图片 AES 解密候选 (key, iv) ；iv=None 表示 ECB ----
    IMG_AES_KEYS = [
        (b"f5d965df75336270", b"97b60394abc2fbe1"),
        (b"75336270f5d965df", b"abc2fbe197b60394"),
    ]

    # ---- 请求头 ----
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


# ==========================================================================
# ② 域名解析层：独立类，可单测，可复用
# ==========================================================================
class DomainResolver:
    """
    多域名 BFS 探测器
    -------------------
    输入：种子域名列表（SiteConfig.SEED_HOSTS）
    输出：可达的真站点根 URL

    探测流程：
      种子域名 ──┬─► 真站点？ ──► 命中缓存/返回
                 ├─► JS 跳转？──► 入队
                 └─► 发布页？──► 提取二级域名 ──► 入队
    """

    def __init__(self, cfg, fetcher, cache_get=None, cache_set=None):
        self.cfg       = cfg
        self.fetch     = fetcher
        self.cache_get = cache_get
        self.cache_set = cache_set

    # ---- 站点有效性 ----
    def _site_ok(self, html):
        if not html or len(html) < self.cfg.PROBE_MIN_HTML:
            return False
        low = html.lower()
        if low.count("<article") >= self.cfg.PROBE_MIN_ARTICLE:
            return True
        has_kw = any(kw in html for kw in self.cfg.SITE_KEYWORDS)
        has_mk = any(m in low for m in self.cfg.SITE_MARKERS)
        return has_kw and has_mk

    # ---- JS 跳转 ----
    @staticmethod
    def _js_jump(html):
        if not html:
            return ""
        m = re.search(SiteConfig.RE_JUMP_ANCHOR, html)
        if m:
            return m.group(1).rstrip("/") + "/"
        if "加载中" in html:
            m = re.search(SiteConfig.RE_ANY_ANCHOR, html)
            if m:
                return m.group(1).rstrip("/") + "/"
        return ""

    # ---- 从发布页提取二级域名 ----
    @staticmethod
    def _pub_hosts(html):
        cfg  = SiteConfig
        text = html or ""
        # 先尝试解开 Base64 混淆块（有些站点会整段加密）
        m = re.search(cfg.RE_B64_DOMAIN_BLOB, text)
        if m:
            try:
                text = b64decode(m.group(1) + "===").decode("utf-8", "ignore")
            except Exception:
                pass
        suffixes = re.findall(cfg.RE_RANDOM_SUFFIX, text) or \
                   re.findall(cfg.RE_LITERAL_DOMAIN, text)
        out, seen = [], set()
        for s in suffixes:
            s = s.lstrip(".")
            if not s or s in seen:
                continue
            seen.add(s)
            out.append(cfg.PUB_HOST_PREFIX % s)
        return out

    # ---- 主入口 ----
    def resolve(self):
        cfg    = self.cfg
        cached = ""
        if self.cache_get:
            try:
                cached = str(self.cache_get(cfg.HOST_CACHE_KEY) or "").rstrip("/")
            except Exception:
                cached = ""

        seeds = ([cached + "/"] if cached else []) + list(cfg.SEED_HOSTS)
        queue, seen = [], set()
        for u in seeds:
            if u and u not in seen:
                seen.add(u)
                queue.append(u)

        steps = 0
        while queue and steps < cfg.PROBE_MAX_STEPS:
            url = queue.pop(0)
            steps += 1
            r = self.fetch(url, timeout=cfg.PROBE_TIMEOUT)
            if r is None:
                continue
            html  = r.text or ""
            final = (r.url or url).rstrip("/") + "/"

            if self._site_ok(html):
                host = final.rstrip("/")
                if self.cache_set:
                    try:
                        self.cache_set(cfg.HOST_CACHE_KEY, host)
                    except Exception:
                        pass
                return host

            jump = self._js_jump(html)
            if jump and jump not in seen:
                seen.add(jump)
                queue.append(jump)
            for h in self._pub_hosts(html):
                if h not in seen:
                    seen.add(h)
                    queue.append(h)

        return cached or cfg.FALLBACK_HOST


# ==========================================================================
# ③ 主爬虫层：与具体站点解耦
# ==========================================================================
class BaseMultiDomainSpider(BaseSpider):
    """多域名跳转站点通用爬虫基类（子类覆盖 CONFIG + 少量钩子即可复用）"""

    CONFIG = SiteConfig

    def __init__(self):
        try:
            super().__init__()
        except Exception:
            pass
        self.proxies   = {}
        self.headers   = dict(self.CONFIG.HEADERS)
        self.host      = ""
        self._img_cache = {}

    # ---------- 生命周期 ----------
    def init(self, extend=""):
        try:
            self.proxies = json.loads(extend) if extend else {}
        except Exception:
            self.proxies = {}
        self.host = self._resolve_host()
        self.headers.update({
            "Origin":  self.host,
            "Referer": self.host + "/",
        })

    def getName(self):
        return "🌈 通用多域名站点"

    def isVideoFormat(self, url):
        return any(e in (url or "") for e in (".m3u8", ".mp4", ".ts"))

    def manualVideoCheck(self):
        return False

    def destroy(self):
        self._img_cache.clear()

    # ---------- 域名 ----------
    def _resolve_host(self):
        return DomainResolver(
            self.CONFIG, self._get,
            cache_get=getattr(self, "getCache", None),
            cache_set=getattr(self, "setCache", None),
        ).resolve()

    # ---------- 网络 ----------
    def _get(self, url, timeout=None, **kw):
        try:
            return requests.get(
                url, headers=self.headers, proxies=self.proxies,
                timeout=timeout or self.CONFIG.PROBE_TIMEOUT,
                verify=False, allow_redirects=True, **kw,
            )
        except Exception as e:
            LOG.debug("GET %s failed: %s", url, e)
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

    # ---------- 工具 ----------
    @staticmethod
    def e64(s):   return b64encode(str(s).encode()).decode()
    @staticmethod
    def d64(s):   return b64decode(str(s).encode()).decode()

    def _abs(self, href):
        if not href:
            return ""
        if href.startswith("http"):
            return href
        return self.host + (href if href.startswith("/") else "/" + href)

    @staticmethod
    def _unique(name, seen):
        if name not in seen:
            seen.add(name)
            return name
        c = 2
        while f"{name} {c}" in seen:
            c += 1
        new = f"{name} {c}"
        seen.add(new)
        return new

    # ---------- 首页 / 分类 ----------
    def homeContent(self, filter=False):
        r, data = self._get_soup(self.host)
        if data is None:
            return {"class": [], "list": []}
        return {
            "class": self._parse_classes(data),
            "list":  self._parse_list(data(self.CONFIG.SEL_ARTICLE_HOME)),
        }

    def homeVideoContent(self):
        r, data = self._get_soup(self.host)
        if data is None:
            return {"list": []}
        return {"list": self._parse_list(data(self.CONFIG.SEL_ARTICLE_HOME))}

    def _parse_classes(self, data):
        for sel in self.CONFIG.SEL_NAV:
            classes = []
            for k in data(sel).items():
                a = k("a")
                href = (a.attr("href") or "").strip()
                name = (a.text() or "").strip()
                if not href or href in ("#", "/") or not name:
                    continue
                if not href.startswith("http"):
                    href = "/" + href.lstrip("/")
                classes.append({"type_name": name, "type_id": href})
            if classes:
                return classes
        return [self.CONFIG.DEFAULT_CATEGORY]

    def categoryContent(self, tid, pg=1, filter=False, extend=None):
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
            return f"{host_ns}/page/{pg}/"
        if "/category/" in base or "/tag/" in base:
            return f"{base}/{pg}/"
        if "/page/" in base:
            return f"{base}/{pg}/"
        return f"{base}/page/{pg}/"

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
            videos.append({
                "vod_id":      f"{href}{'@folder' if is_folder else ''}",
                "vod_name":    title,
                "vod_pic":     self._parse_pic(k),
                "vod_remarks": self._parse_date(k),
                "vod_tag":     "folder" if is_folder else "",
                "style":       {"type": "rect", "ratio": 1.33},
            })
        return videos

    def _parse_folder(self, id):
        url = self._abs(id)
        r, data = self._get_soup(url)
        if data is None:
            return []
        videos = []
        for i, h2 in enumerate(data(".post-content h2").items()):
            p_txt = data(".post-content p").eq(i * 2)
            p_img = data(".post-content p").eq(i * 2 + 1)
            videos.append({
                "vod_id":      p_txt("a").attr("href"),
                "vod_name":    p_txt.text().strip(),
                "vod_pic":     self._parse_pic(p_img),
                "vod_remarks": h2.text().strip(),
            })
        return videos

    # ---------- 搜索 ----------
    def searchContent(self, key, quick=False, pg=1):
        pg  = int(pg or 1)
        url = f"{self.host}/search/{key}/" + (f"{pg}/" if pg > 1 else "")
        r, data = self._get_soup(url)
        if data is None:
            return {"list": [], "page": pg, "pagecount": 9999}
        return {
            "list": self._parse_list(data("article")),
            "page": pg, "pagecount": 9999,
        }

    # ---------- 详情 ----------
    def detailContent(self, ids):
        url = ids[0] if ids[0].startswith("http") else self.host + ids[0]
        r, data = self._get_soup(url)
        if data is None:
            return {"list": [{"vod_play_from": "线路",
                              "vod_play_url":  "获取失败"}]}

        playlist = self._extract_playlist(data)
        play_url = "#".join(playlist) or f"未找到视频源，请访问网页${url}"

        return {"list": [{
            "vod_play_from": "线路",
            "vod_play_url":  play_url,
            "vod_content":   self._extract_content(data),
        }]}

    # ---------- 播放源提取（可覆盖）----------
    def _extract_playlist(self, data):
        if data(self.CONFIG.SEL_PLAYER):
            plist = self._from_dplayer(data)
            if plist:
                return plist
        return self._from_links(data)

    def _from_dplayer(self, data):
        plist, used = [], set()
        for i, k in enumerate(data(self.CONFIG.SEL_PLAYER).items(), 1):
            try:
                cfg = json.loads(k.attr("data-config") or "{}")
                url = cfg.get("video", {}).get("url", "")
                if not url:
                    continue
                base = self._near_heading(k) or f"视频{i}"
                plist.append(f"{self._unique(base, used)}${url}")
            except Exception:
                continue
        return plist

    def _from_links(self, data):
        plist = []
        area = data(self.CONFIG.SEL_CONTENT)
        for i, link in enumerate(area("a").items(), 1):
            txt  = (link.text() or "").strip()
            href = link.attr("href")
            if not href or not any(kw in txt for kw in self.CONFIG.LINK_KEYWORDS):
                continue
            name = (txt.replace("点击观看：", "").replace("点击观看", "").strip()
                    or f"视频{i}")
            plist.append(f"{name}${self._abs(href)}")
        return plist

    @staticmethod
    def _near_heading(k, levels=4):
        parent = k.parents().eq(0)
        for _ in range(levels):
            if not parent:
                break
            h = parent.find("h2, h3, h4").eq(0).text().strip()
            if h:
                return h
            parent = parent.parents().eq(0)
        return ""

    def _extract_content(self, data):
        tags = []
        for k in data(self.CONFIG.SEL_TAGS).items():
            title = (k.text() or "").strip()
            href  = k.attr("href")
            if title and href:
                target = json.dumps({"id": self._abs(href), "name": title})
                tags.append(f"[a=cr:{target}/]{title}[/a]")
        if tags:
            summary = (data(self.CONFIG.SEL_SUMMARY).text() or "")[:150]
            return " ".join(tags) + "\n\n" + summary
        return (data(self.CONFIG.SEL_TITLE).text() or "每日大赛")

    # ---------- 图片 ----------
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
        html = (html.replace("&quot;", '"')
                    .replace("&apos;", "'")
                    .replace("&amp;", "&"))
        for pattern in (
            r"(data:image/[a-zA-Z0-9+/=;,]+)",
            r'(https?://[^"\'\s)]+\.(?:jpg|png|jpeg|webp))',
            r'url\s*\(\s*[\'"]?([^"\'\)]+)[\'"]?\s*\)',
        ):
            m = re.search(pattern, html, re.I)
            if m:
                return self._proc_url(m.group(1))
        return ""

    def _proc_url(self, url):
        if not url:
            return ""
        url = url.strip("'\" ")
        if url.startswith("data:"):
            try:
                _, b64_str = url.split(",", 1)
                raw = b64decode(b64_str)
                if not self._is_image(raw):
                    raw = self.aesimg(raw)
                key = hashlib.md5(raw).hexdigest()
                self._img_cache[key] = raw
                return f"{self.getProxyUrl()}&type=cache&key={key}"
            except Exception:
                return ""
        return f"{self.getProxyUrl()}&url={self.e64(self._abs(url))}&type=img"

    @staticmethod
    def _is_image(blob):
        return (blob.startswith(b"\xff\xd8")
                or blob.startswith(b"\x89PNG")
                or blob.startswith(b"GIF8"))

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

    # ---------- 播放 & 代理 ----------
    def playerContent(self, flag, id, vipFlags=None):
        parse = 0 if self.isVideoFormat(id) else 1
        url = self.proxy(id) if ".m3u8" in id else id
        return {"parse": parse, "url": url, "header": self.headers}

    def proxy(self, data, kind="m3u8"):
        if data and self.proxies:
            return f"{self.getProxyUrl()}&url={self.e64(data)}&type={kind}"
        return data

    def localProxy(self, param):
        try:
            t = param.get("type")
            if t == "cache":
                data = self._img_cache.get(param.get("key"))
                return [200, "image/jpeg", data] if data else [404, "text/plain", b"Expired"]
            if t == "img":
                raw  = param.get("url") or ""
                real = raw if raw.startswith("http") else self.d64(raw)
                res  = self._get(real, timeout=10)
                if res is None:
                    return [404, "text/plain", b""]
                return [200, "image/jpeg", self.aesimg(res.content)]
            if t == "m3u8":
                return self._m3_proxy(param.get("url"))
            return self._ts_proxy(param.get("url"))
        except Exception:
            return [404, "text/plain", b""]

    def _m3_proxy(self, url):
        real = url if url.startswith("http") else self.d64(url)
        res  = self._get(real)
        if res is None:
            return [404, "text/plain", b""]
        base = res.url.rsplit("/", 1)[0]
        out  = []
        for line in res.text.split("\n"):
            if "#EXT" not in line and line.strip():
                if not line.startswith("http"):
                    line = f"{base}/{line}"
                out.append(self.proxy(line, "ts"))
            else:
                out.append(line)
        return [200, "application/vnd.apple.mpegurl", "\n".join(out)]

    def _ts_proxy(self, url):
        real = url if url.startswith("http") else self.d64(url)
        res  = self._get(real)
        if res is None:
            return [404, "text/plain", b""]
        return [200, "video/mp2t", res.content]


# ==========================================================================
# ④ 具体站点类：只覆盖必要项
# ==========================================================================
class Spider(BaseMultiDomainSpider):
    """每日大赛站点：仅覆盖名称（其余全部走基类）"""

    CONFIG = SiteConfig

    def getName(self):
        return "🌈 每日大赛|终极完美版"


# ==========================================================================
# ⑤ 可选扩展：播放源聚合（保留原有逻辑，原样装回）
# ==========================================================================
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
            self.page_cache = {}
            self.page_index = {}
            self.page_keys  = []
            self._src_cache = {}

    def _clean(s):
        return str(s or "").replace("$", " ").replace("#", " ").strip()

    def _enc(s):
        try:
            from urllib.parse import quote
            return quote(str(s or ""), safe="")
        except Exception:
            return str(s or "")

    def _dec(s):
        try:
            from urllib.parse import unquote
            return unquote(str(s or ""))
        except Exception:
            return str(s or "")

    def _cache_page(self, key, items):
        _ensure(self)
        out = [x for x in (items or [])
               if isinstance(x, dict) and x.get("vod_id")]
        if not out:
            return
        self.page_cache[key] = out
        if key in self.page_keys:
            self.page_keys.remove(key)
        self.page_keys.append(key)
        for it in out:
            self.page_index[str(it["vod_id"])] = key
        while len(self.page_keys) > 30:
            old = self.page_keys.pop(0)
            self.page_cache.pop(old, None)

    def _page_of(self, vid):
        _ensure(self)
        key = self.page_index.get(str(vid))
        if key in self.page_cache:
            return list(self.page_cache[key])
        return []

    def _as_result(r):
        if r is None:
            return {}
        if isinstance(r, dict):
            return r
        if isinstance(r, (bytes, bytearray)):
            r = r.decode("utf-8", "ignore")
        if isinstance(r, str):
            s = r.strip()
            if s.startswith("{") or s.startswith("["):
                try:
                    import json as _j
                    return _j.loads(s)
                except Exception:
                    return {}
        return {}

    def _split_sources(vod):
        fr = str((vod or {}).get("vod_play_from") or "").split("$$$")
        ur = str((vod or {}).get("vod_play_url") or "").split("$$$")
        while len(ur) < len(fr):
            ur.append("")
        sources = []
        for i, name in enumerate(fr):
            parts = []
            for p in (ur[i] or "").split("#"):
                if not p:
                    continue
                n, u = p.split("$", 1) if "$" in p else (str(i + 1), p)
                parts.append((_clean(n), u))
            sources.append((_clean(name) or ("线路%d" % (i + 1)), parts))
        return [x for x in sources if x[1]]

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
                if src_idx < len(current_sources) and current_sources[src_idx][1]:
                    eps = current_sources[src_idx][1]
                else:
                    eps = current_sources[0][1]
            if len(eps) > 1:
                out = []
                for i, (en, u) in enumerate(eps):
                    label = _clean("%s %s" % (name, en or ("%02d" % (i + 1))))
                    out.append("%s$%s" % (label, u))
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
        play_from, play_urls = [], []
        for i, (sname, _eps) in enumerate(sources):
            parts = []
            for it in plist:
                parts.extend(self._pl_item_parts(it, i, sources, vid))
            if not parts:
                continue
            play_from.append(sname or ("线路%d" % (i + 1)))
            play_urls.append("#".join(parts))
        if not play_from:
            return vod
        vod = dict(vod)
        vod["vod_play_from"] = "$$$".join(play_from)
        vod["vod_play_url"]  = "$$$".join(play_urls)
        return vod

    def init(self, *args, **kwargs):
        _ensure(self)
        if _orig_init:
            return _orig_init(self, *args, **kwargs)

    def homeContent(self, *args, **kwargs):
        _ensure(self)
        r = _orig_home(self, *args, **kwargs) if _orig_home else {}
        try:
            _cache_page(self, ("home",), _as_result(r).get("list"))
        except Exception:
            pass
        return r

    def homeVideoContent(self, *args, **kwargs):
        _ensure(self)
        r = _orig_homev(self, *args, **kwargs) if _orig_homev else {"list": []}
        try:
            _cache_page(self, ("homev",), _as_result(r).get("list"))
        except Exception:
            pass
        return r

    def categoryContent(self, *args, **kwargs):
        _ensure(self)
        r = _orig_cate(self, *args, **kwargs) if _orig_cate else {"list": []}
        try:
            tid = args[0] if args else kwargs.get("tid", "")
            pg  = args[1] if len(args) > 1 else kwargs.get("pg", "1")
            ext = args[3] if len(args) > 3 else kwargs.get("extend", "")
            _cache_page(self, ("cate", str(tid), str(pg), str(ext)),
                        _as_result(r).get("list"))
        except Exception:
            pass
        return r

    def searchContent(self, *args, **kwargs):
        _ensure(self)
        if not _orig_search:
            return {"list": []}
        r = _orig_search(self, *args, **kwargs)
        try:
            key = args[0] if args else kwargs.get("key", "")
            pg  = args[2] if len(args) > 2 else kwargs.get("pg", "1")
            _cache_page(self, ("search", str(key), str(pg)),
                        _as_result(r).get("list"))
        except Exception:
            pass
        return r

    def searchContentPage(self, *args, **kwargs):
        _ensure(self)
        if not _orig_searchp:
            return {"list": []}
        r = _orig_searchp(self, *args, **kwargs)
        try:
            key = args[0] if args else kwargs.get("key", "")
            pg  = args[2] if len(args) > 2 else kwargs.get(
                "page", kwargs.get("pg", "1"))
            _cache_page(self, ("searchp", str(key), str(pg)),
                        _as_result(r).get("list"))
        except Exception:
            pass
        return r

    def detailContent(self, ids, *args, **kwargs):
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
                r = _orig_detail(self, call_ids, *args, **kwargs)
            except TypeError:
                r = _orig_detail(self, call_ids)
        else:
            r = {"list": []}

        try:
            rr  = _as_result(r)
            lst = rr.get("list") or []
            if not lst or not isinstance(lst[0], dict):
                return r
            vod = dict(lst[0])
            vod["vod_id"] = str(vod.get("vod_id") or vid)
            if not vod.get("vod_name"):
                hit = next((x for x in cached
                            if str(x.get("vod_id")) == vid), None)
                if hit:
                    vod["vod_name"] = hit.get("vod_name") or vid
            if cached:
                vod = self._pl_apply_playlist(vid, vod, cached)
            rr = dict(rr)
            rr["list"] = [vod]
            if isinstance(r, dict) or r is None:
                return rr
            try:
                import json as _j
                return _j.dumps(rr, ensure_ascii=False)
            except Exception:
                return rr
        except Exception:
            return r

    def playerContent(self, flag, id, vipFlags=None, *args, **kwargs):
        _ensure(self)
        s = str(id)
        if s.startswith("nid:"):
            vid     = _dec(s[4:])
            sources = self._pl_load_src(vid)
            real    = ""
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
            if real and not str(real).startswith("nid:"):
                id = real
            else:
                id = vid
        if not _orig_player:
            return {"parse": 0, "url": id}
        try:
            return _orig_player(self, flag, id, vipFlags, *args, **kwargs)
        except TypeError:
            try:
                return _orig_player(self, flag, id, vipFlags)
            except TypeError:
                return _orig_player(self, flag, id)

    _C._pl_call_detail    = _call_detail
    _C._pl_load_src       = _load_src
    _C._pl_item_parts     = _item_parts
    _C._pl_apply_playlist = _apply_playlist
    if _orig_init:   _C.init               = init
    if _orig_home:   _C.homeContent        = homeContent
    if _orig_homev:  _C.homeVideoContent   = homeVideoContent
    if _orig_cate:   _C.categoryContent    = categoryContent
    if _orig_search: _C.searchContent      = searchContent
    if _orig_searchp:_C.searchContentPage  = searchContentPage
    if _orig_detail: _C.detailContent      = detailContent
    if _orig_player: _C.playerContent      = playerContent
    return _C

try:
    _install_playlist_extension(Spider)
except Exception:
    pass
