# -*- coding: utf-8 -*-
"""
多域名自愈模板（通用版）
================================
链路：种子域名列表 → (302 自动跟随) → 主站
      → 取 response.url 最终域名作为 self.host
      → 6 小时缓存，失效自动重探
      → 探测全部失败时回退到 SEED_HOSTS[0]，避免全空白
"""
import json
import re
import sys
import time
import hashlib
import logging
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
# ① 配置层
# ==================================================================
class SiteConfig:
    # ---- 4 个三级域名（来自发布页；失效后旧域名一般仍可 302 到新域名）----
    SEED_HOSTS = [
        "https://ceo.kludlvje.cc/",
        "https://cause.kludlvje.cc/",
        "https://amazing.kludlvje.cc/",
    ]
    FALLBACK_HOST  = None
    HOST_CACHE_KEY = "mrds_host"          # 每个站点必须唯一
    HOST_CACHE_TTL = 6 * 3600

    # ---- 探测参数 ----
    PROBE_TIMEOUT        = 8
    PROBE_MIN_HTML       = 3000
    PROBE_MIN_ARTICLE    = 3

    # ---- 站点特征（务必带引号！）----
    SITE_KEYWORDS    = ["每日大赛"]
    SITE_MARKERS     = ["post-title", "entry-title", "<article"]

    # ---- 列表 / 详情选择器 ----
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
# ② 域名解析器
# ==================================================================
class DomainResolver:
    def __init__(self, cfg, fetcher, cache_get=None, cache_set=None):
        self.cfg, self.fetch = cfg, fetcher
        self.cache_get, self.cache_set = cache_get, cache_set

    def _site_ok(self, html):
        if not html or len(html) < self.cfg.PROBE_MIN_HTML:
            return False
        if self.cfg.SITE_KEYWORDS:
            return any(kw in html for kw in self.cfg.SITE_KEYWORDS)
        low = html.lower()
        if low.count("<article") >= self.cfg.PROBE_MIN_ARTICLE:
            return True
        return any(m in low for m in self.cfg.SITE_MARKERS) and len(html) > 20000

    def _safe_fetch(self, url, timeout):
        try:
            return self.fetch(url, timeout=timeout)
        except Exception:
            return None

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
            self.cache_set(
                self.cfg.HOST_CACHE_KEY,
                json.dumps({"host": host, "ts": int(time.time())})
            )
        except Exception:
            pass

    def resolve(self):
        cached = self._read_cache()

        # 1) 缓存优先
        if cached and self._cache_fresh(cached):
            r = self._safe_fetch(cached["host"] + "/", self.cfg.PROBE_TIMEOUT)
            if r is not None and r.status_code == 200 and self._site_ok(r.text):
                final = (r.url or cached["host"]).rstrip("/")
                LOG.info("缓存有效: %s → %s", cached["host"], final)
                print(f"缓存有效: {cached['host']} → {final}")
                if final != cached["host"]:
                    self._write_cache(final)
                return final
            LOG.info("缓存失效: %s", cached["host"])
            print(f"缓存失效: {cached['host']}")

        # 2) 并发探测 SEED_HOSTS（带详细日志）
        urls = list(self.cfg.SEED_HOSTS)
        if cached:
            urls.insert(0, cached["host"] + "/")
        if not urls:
            return ""

        with ThreadPoolExecutor(max_workers=min(6, len(urls))) as ex:
            futs = {ex.submit(self._safe_fetch, u, self.cfg.PROBE_TIMEOUT): u for u in urls}
            try:
                for f in as_completed(futs, timeout=self.cfg.PROBE_TIMEOUT + 8):
                    u = futs[f]
                    try:
                        r = f.result()
                    except Exception as e:
                        print(f"探测异常 {u}: {e}")
                        continue
                    if r is None:
                        print(f"探测无响应: {u}")
                        continue
                    if r.status_code != 200:
                        print(f"探测 HTTP {r.status_code}: {u}")
                        continue
                    if not self._site_ok(r.text):
                        kws = self.cfg.SITE_KEYWORDS or '结构判断'
                        print(f"探测内容不匹配: {u} (len={len(r.text or '')}, 关键词={kws})")
                        continue
                    final = (r.url or u).rstrip("/")
                    self._write_cache(final)
                    if final.rstrip("/") != u.rstrip("/"):
                        LOG.info("探测成功（含跳转）: %s → %s", u, final)
                        print(f"探测成功（含跳转）: {u} → {final}")
                    else:
                        LOG.info("探测成功: %s", final)
                        print(f"探测成功: {final}")
                    return final
            except Exception as e:
                LOG.debug("并发探测异常: %s", e)

        # 3) 全部失败
        if cached:
            LOG.warning("使用过期缓存: %s", cached["host"])
            print(f"使用过期缓存: {cached['host']}")
            return cached["host"]

        # ============ 兜底：与 51/91 模板一致 ============
        if self.cfg.SEED_HOSTS:
            fallback = self.cfg.SEED_HOSTS[0].rstrip("/")
            print(f"【警告】所有域名探测失败，回退到种子域名: {fallback}")
            print(f"【提示】如内容为空或报错，请检查 SITE_KEYWORDS 是否与站点实际标题匹配")
            return fallback
        # ================================================

        LOG.error("域名探测失败，请更新 SEED_HOSTS")
        print("域名探测失败，请更新 SEED_HOSTS")
        return ""


# ==================================================================
# ③ 主爬虫基类
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
            self.proxies = json.loads(extend) if extend else {}
        except Exception:
            self.proxies = {}
        self.headers = dict(self.CONFIG.HEADERS)
        self.host = DomainResolver(
            self.CONFIG, self._get,
            cache_get=getattr(self, "getCache", None),
            cache_set=getattr(self, "setCache", None),
        ).resolve()
        if self.host:
            self.headers.update({"Origin": self.host, "Referer": self.host + "/"})
        print(f"使用站点: {self.host}")

    def getName(self):          return "🌈 每日系列自愈版"
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
        classes = []
        seen = set()

        def _add(href, name):
            href = (href or "").strip()
            name = (name or "").strip()
            if not href or not name:
                return
            if href == "#":
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
            for k in data(sel).items():
                a = k if k.is_("a") else k("a").eq(0)
                _add(a.attr("href"), a.text())
                hit = True
            if hit and classes:
                break

        for sel in self.CONFIG.SEL_SUB_NAV:
            hit = False
            for a in data(sel).items():
                _add(a.attr("href"), a.attr("title") or a.text())
                hit = True
            if hit:
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
        pg  = int(pg or 1)
        url = "%s/search/%s/%s" % (self.host, key, ("%d/" % pg) if pg > 1 else "")
        r, data = self._get_soup(url)
        if data is None:
            return {"list": [], "page": pg, "pagecount": 9999}
        return {
            "list": self._parse_list(data("article")),
            "page": pg, "pagecount": 9999,
        }

    def detailContent(self, ids):
        vid = str(ids[0] if isinstance(ids, (list, tuple)) else ids)
        if not self.host:
            return {"list": [{"vod_play_from": "线路", "vod_play_url": "获取失败"}]}

        url = vid if vid.startswith("http") else self.host + vid
        r, data = self._get_soup(url)
        if data is None:
            return {"list": [{"vod_play_from": "线路", "vod_play_url": "获取失败"}]}

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
            hit_text = any(kw in txt for kw in self.CONFIG.LINK_KEYWORDS)
            hit_url = any(re.search(p, href, re.I)
                          for p in self.CONFIG.LINK_URL_PATTERNS)
            if not (hit_text or hit_url):
                continue
            name = (txt.replace("点击观看：", "").replace("点击观看", "").strip()
                    or "视频%d" % i)
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
                target = json.dumps({"id": self._abs(h), "name": t})
                tags.append("[a=cr:%s/]%s[/a]" % (target, t))
        if tags:
            summary = (data(self.CONFIG.SEL_SUMMARY).text() or "")[:150]
            return " ".join(tags) + "\n\n" + summary
        return data(self.CONFIG.SEL_TITLE).text() or "未命名"

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
        out = []
        iskey = True
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


# ==================================================================
# ④ 具体站点类
# ==================================================================
class Spider(BaseMultiDomainSpider):
    CONFIG = SiteConfig

    def getName(self):
        return "❇️ 每日系列三级自愈版"


# ==================================================================
# ⑤ 播放源聚合扩展
# ==================================================================
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
            self.page_cache, self.page_index, self.page_keys, self._src_cache = {}, {}, [], {}

    def _clean(s): return str(s or "").replace("$", " ").replace("#", " ").strip()

    def _enc(s):
        try:
            return quote(str(s or ""), safe="")
        except Exception:
            return str(s or "")

    def _dec(s):
        try:
            return unquote(str(s or ""))
        except Exception:
            return str(s or "")

    def _cache_page(self, key, items):
        _ensure(self)
        out = [x for x in (items or []) if isinstance(x, dict) and x.get("vod_id")]
        if not out:
            return
        self.page_cache[key] = out
        if key in self.page_keys:
            self.page_keys.remove(key)
        self.page_keys.append(key)
        for it in out:
            self.page_index[str(it["vod_id"])] = key
        while len(self.page_keys) > 30:
            self.page_cache.pop(self.page_keys.pop(0), None)

    def _page_of(self, vid):
        _ensure(self)
        key = self.page_index.get(str(vid))
        return list(self.page_cache.get(key, [])) if key in self.page_cache else []

    def _as_result(r):
        if r is None:
            return {}
        if isinstance(r, dict):
            return r
        if isinstance(r, (bytes, bytearray)):
            r = r.decode("utf-8", "ignore")
        if isinstance(r, str):
            s = r.strip()
            if s[:1] in "{[": 
                try:
                    return json.loads(s)
                except Exception:
                    return {}
        return {}

    def _split_sources(vod):
        fr = str((vod or {}).get("vod_play_from") or "").split("$$$")
        ur = str((vod or {}).get("vod_play_url") or "").split("$$$")
        while len(ur) < len(fr):
            ur.append("")
        src = []
        for i, name in enumerate(fr):
            parts = []
            for p in (ur[i] or "").split("#"):
                if not p:
                    continue
                n, u = p.split("$", 1) if "$" in p else (str(i + 1), p)
                parts.append((_clean(n), u))
            src.append((_clean(name) or "线路%d" % (i + 1), parts))
        return [x for x in src if x[1]]

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
                    label = _clean("%s %s" % (name, en or "%02d" % (i + 1)))
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
        pf, pu = [], []
        for i, (sname, _e) in enumerate(sources):
            parts = []
            for it in plist:
                parts.extend(self._pl_item_parts(it, i, sources, vid))
            if not parts:
                continue
            pf.append(sname or "线路%d" % (i + 1))
            pu.append("#".join(parts))
        if not pf:
            return vod
        vod = dict(vod)
        vod["vod_play_from"] = "$$$".join(pf)
        vod["vod_play_url"]  = "$$$".join(pu)
        return vod

    def init(self, *a, **kw):
        _ensure(self)
        if _orig_init:
            return _orig_init(self, *a, **kw)

    def homeContent(self, *a, **kw):
        _ensure(self)
        r = _orig_home(self, *a, **kw) if _orig_home else {}
        try:
            _cache_page(self, ("home",), _as_result(r).get("list"))
        except Exception:
            pass
        return r

    def homeVideoContent(self, *a, **kw):
        _ensure(self)
        r = _orig_homev(self, *a, **kw) if _orig_homev else {"list": []}
        try:
            _cache_page(self, ("homev",), _as_result(r).get("list"))
        except Exception:
            pass
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
        except Exception:
            pass
        return r

    def searchContent(self, *a, **kw):
        _ensure(self)
        if not _orig_search:
            return {"list": []}
        r = _orig_search(self, *a, **kw)
        try:
            key = a[0] if a else kw.get("key", "")
            pg  = a[2] if len(a) > 2 else kw.get("pg", "1")
            _cache_page(self, ("search", str(key), str(pg)),
                        _as_result(r).get("list"))
        except Exception:
            pass
        return r

    def searchContentPage(self, *a, **kw):
        _ensure(self)
        if not _orig_searchp:
            return {"list": []}
        r = _orig_searchp(self, *a, **kw)
        try:
            key = a[0] if a else kw.get("key", "")
            pg  = a[2] if len(a) > 2 else kw.get("page", kw.get("pg", "1"))
            _cache_page(self, ("searchp", str(key), str(pg)),
                        _as_result(r).get("list"))
        except Exception:
            pass
        return r

    def detailContent(self, ids, *a, **kw):
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
                r = _orig_detail(self, call_ids, *a, **kw)
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
            if not vod.get("vod_name") and cached:
                hit = next((x for x in cached if str(x.get("vod_id")) == vid), None)
                if hit:
                    vod["vod_name"] = hit.get("vod_name") or vid
            if cached:
                vod = self._pl_apply_playlist(vid, vod, cached)
            rr = dict(rr)
            rr["list"] = [vod]
            if isinstance(r, dict) or r is None:
                return rr
            try:
                return json.dumps(rr, ensure_ascii=False)
            except Exception:
                return rr
        except Exception:
            return r

    def playerContent(self, flag, id, vipFlags=None, *a, **kw):
        _ensure(self)
        s = str(id)
        if s.startswith("nid:"):
            vid = _dec(s[4:])
            sources = self._pl_load_src(vid)
            real = ""
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
            id = real if real and not str(real).startswith("nid:") else vid
        if not _orig_player:
            return {"parse": 0, "url": id}
        try:
            return _orig_player(self, flag, id, vipFlags, *a, **kw)
        except TypeError:
            try:
                return _orig_player(self, flag, id, vipFlags)
            except TypeError:
                return _orig_player(self, flag, id)

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
