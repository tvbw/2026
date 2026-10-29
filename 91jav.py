#!/usr/bin/python
# -*- coding: utf-8 -*-
"""
91JAV · 多域名自愈版（业务逻辑完全沿用原 91av.py）
================================
只做三件事：
  1. init 用 DomainResolver 并发探测种子域名（cabin + 用户提供的三级域名）
  2. _get 只用 self.host 请求，失败才 re_resolve 换域名，不再遍历多个 host 拖时间
  3. playerContent 同理，不遍历全部 host
其它（分类 / 主题 / 女优 / 详情 / 搜索 / 图片 AES）一律照抄原 91av.py，保证可用性。
"""
import base64
import json
import re
import time
import logging
from urllib.parse import quote, urljoin
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests

from base.spider import Spider as BaseSpider

try:
    from Crypto.Cipher import AES
    from Crypto.Util.Padding import unpad
    _HAS_CRYPTO = True
except Exception:
    _HAS_CRYPTO = False

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
    # ---- 种子域名（cabin 已验证可用；其余为用户提供的三级域名）----
    SEED_HOSTS = [
        "https://cabin.zbywlcc.com/",
        "https://born.zbywlcc.com/",
        "https://blow.xhjug.cc/",
        "https://assume.xhjug.cc/",
    ]
    HOST_CACHE_KEY = "91jav_host"       # 缓存 key 必须唯一
    HOST_CACHE_TTL = 6 * 3600

    PROBE_TIMEOUT  = 8
    PROBE_MIN_HTML = 3000

    # ---- 站点特征 ----
    SITE_KEYWORDS = [91jav]
    SITE_MARKERS  = ["bind_video_img", "/videos/"]

    # ---- 通用 Header ----
    HEADERS = {
        "User-Agent": ("Mozilla/5.0 (Linux; Android 10; SM-G981B) "
                       "AppleWebKit/537.36 (KHTML, like Gecko) "
                       "Chrome/120.0.0.0 Mobile Safari/537.36"),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9",
        "Connection": "keep-alive",
        "Cache-Control": "no-cache",
    }


# ==================================================================
# ② 域名解析器（并发探测 + 302 跟随 + TTL 缓存 + 兜底）
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
        return any(m in html for m in self.cfg.SITE_MARKERS)

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
            self.cache_set(self.cfg.HOST_CACHE_KEY,
                           json.dumps({"host": host, "ts": int(time.time())}))
        except Exception:
            pass

    def _clear_cache(self):
        if not self.cache_set:
            return
        try:
            if hasattr(self, "cache_del") and self.cache_del:
                self.cache_del(self.cfg.HOST_CACHE_KEY)
        except Exception:
            pass

    def resolve(self):
        cached = self._read_cache()

        # 1) 缓存优先
        if cached and self._cache_fresh(cached):
            r = self._safe_fetch(cached["host"] + "/", self.cfg.PROBE_TIMEOUT)
            if r is not None and r.status_code == 200 and self._site_ok(r.text):
                final = (r.url or cached["host"]).rstrip("/")
                print(f"缓存有效: {cached['host']} → {final}")
                if final != cached["host"]:
                    self._write_cache(final)
                return final
            print(f"缓存失效: {cached['host']}")

        # 2) 并发探测
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
                        print(f"探测内容不匹配: {u} (len={len(r.text or '')})")
                        continue
                    final = (r.url or u).rstrip("/")
                    self._write_cache(final)
                    if final.rstrip("/") != u.rstrip("/"):
                        print(f"探测成功（含跳转）: {u} → {final}")
                    else:
                        print(f"探测成功: {final}")
                    return final
            except Exception as e:
                LOG.debug("并发探测异常: %s", e)

        # 3) 全部失败
        if cached:
            print(f"使用过期缓存: {cached['host']}")
            return cached["host"]
        if self.cfg.SEED_HOSTS:
            fallback = self.cfg.SEED_HOSTS[0].rstrip("/")
            print(f"【警告】所有域名探测失败，回退到种子域名: {fallback}")
            return fallback
        return ""


# ==================================================================
# ③ 主爬虫
# ==================================================================
class Spider(BaseSpider):
    CONFIG = SiteConfig

    def getName(self):
        return "91JAV"

    # ---------------- 初始化 ----------------
    def init(self, extend=""):
        self.name = "91JAV"
        self.proxies = {}
        self.backup_hosts = []
        self.shield = []
        self._img_cache = {}
        self.aes_key = b"f5d965df75336270"
        self.aes_iv  = b"97b60394abc2fbe1"

        # 用户 extend 覆盖
        user_host = None
        if isinstance(extend, str) and extend.strip():
            s = extend.strip()
            if s.startswith("{"):
                try:
                    cfg = json.loads(s)
                    user_host = cfg.get("host")
                    self.backup_hosts = cfg.get("backup_hosts", []) or []
                    self.shield = cfg.get("shield", []) or []
                    if isinstance(cfg.get("proxies"), dict):
                        self.proxies = cfg["proxies"]
                except Exception:
                    pass
            elif "://" in s:
                user_host = s

        self.headers = dict(self.CONFIG.HEADERS)
        self.session = requests.Session()
        self.session.headers.update(self.headers)

        # 自愈：用户指定 or 并发探测
        if user_host:
            self._set_host(user_host.rstrip("/"))
            print(f"使用用户指定站点: {self.host}")
        else:
            resolver = DomainResolver(
                self.CONFIG, self._probe_fetch,
                cache_get=getattr(self, "getCache", None),
                cache_set=getattr(self, "setCache", None),
            )
            try:
                resolver.cache_del = getattr(self, "delCache", None)
            except Exception:
                pass
            resolved = resolver.resolve()
            self._set_host(resolved or self.CONFIG.SEED_HOSTS[0].rstrip("/"))
            print(f"使用站点: {self.host}")

        # ========= 业务保留（原 91av.py 全部手工分类不动）=========
        self.themes = [
            ("2", "角色剧情"), ("3", "中文字幕"), ("4", "制服诱惑"),
            ("5", "直接开啪"), ("6", "丝袜美腿"), ("7", "捆绑调教"),
            ("8", "多P群交"), ("10", "羞辱强暴"), ("11", "无码高清"),
            ("14", "乱伦伦理"), ("15", "人妻诱惑"), ("17", "网黄精选"),
        ]
        self.theme_sorts = [
            {"n": "近期最佳", "v": "hot"},
            {"n": "今日更新", "v": "update"},
            {"n": "最多观看", "v": "watch"},
            {"n": "最高收藏", "v": "favorite"},
        ]
        self.categories = [
            {"type_id": "/new",                   "type_name": "最新更新"},
            {"type_id": "/theme/detail/3/update", "type_name": "中文字幕"},
            {"type_id": "/theme/detail/11/hot",   "type_name": "无码高清"},
            {"type_id": "/theme",                 "type_name": "专题合集"},
            {"type_id": "/actress/hot",           "type_name": "热门女优"},
        ]
        self.filters = {
            "/theme/detail/3/update":  [{"key": "sort", "name": "排序", "value": self.theme_sorts}],
            "/theme/detail/11/hot":    [{"key": "sort", "name": "排序", "value": self.theme_sorts}],
            "/theme": [{"key": "sort", "name": "排序", "value": [
                {"n": "预设排序", "v": "sort"},
                {"n": "热度优先", "v": "check_num"},
                {"n": "最多影片", "v": "count"},
            ]}],
            "/actress/hot": [{"key": "sort", "name": "排序", "value": [
                {"n": "热度优先", "v": "hot"},
                {"n": "最多影片", "v": "count"},
            ]}],
        }
        self.tids = {"/new": "/new", "/theme": "/theme", "/actress/hot": "/actress/hot"}
        self._filters_actress = []
        for tid, _n in self.themes:
            self.tids["/theme/detail/%s/update" % tid] = "/theme/detail/%s/update" % tid
            self.tids["/theme/detail/%s/hot"    % tid] = "/theme/detail/%s/hot"    % tid

    # ---------------- host 工具 ----------------
    def _set_host(self, h):
        self.host = h.rstrip("/")
        self.headers["Referer"] = self.host + "/"
        if hasattr(self, "session"):
            self.session.headers.update(self.headers)

    def _hosts(self):
        return list(dict.fromkeys([self.host] + self.backup_hosts + self.shield))

    def _probe_fetch(self, url, timeout=None):
        """独立探测请求，init 阶段可安全调用（不依赖 self.host）。"""
        try:
            return self.session.get(
                url,
                headers=self.CONFIG.HEADERS,
                timeout=timeout or self.CONFIG.PROBE_TIMEOUT,
                verify=False,
                allow_redirects=True,
            )
        except Exception:
            return None

    def _re_resolve(self):
        """域名挂了：清缓存 → 重新并发探测，成功则切换。"""
        try:
            resolver = DomainResolver(
                self.CONFIG, self._probe_fetch,
                cache_get=getattr(self, "getCache", None),
                cache_set=getattr(self, "setCache", None),
            )
            try:
                resolver.cache_del = getattr(self, "delCache", None)
            except Exception:
                pass
            resolver._clear_cache()
            new_host = resolver.resolve()
            if new_host and new_host.rstrip("/") != self.host.rstrip("/"):
                self._set_host(new_host)
                print(f"域名切换: → {new_host}")
                return True
            return bool(new_host)
        except Exception as e:
            LOG.debug("re_resolve 异常: %s", e)
            return False

    # ---------------- 通用请求（关键：不再遍历所有 host）----------------
    def _get(self, url):
        """只用 self.host 请求；失败 re_resolve 换域名再试一次。"""
        url = self._fix(url)
        for attempt in range(2):
            try:
                r = self.session.get(
                    url,
                    headers=self.headers,
                    timeout=12,
                    verify=False,
                    proxies=self.session.proxies or None,
                )
                r.encoding = r.apparent_encoding or "utf-8"
                if r.status_code == 200 and r.text:
                    return r.text
            except Exception as e:
                LOG.debug("GET %s 异常: %s", url, e)
            if attempt == 0:
                if not self._re_resolve():
                    break
                url = self._fix(url)
        return ""

    def _fix(self, url):
        return urljoin(self.host + "/", (url or "").strip().replace("`", "").replace("\\/", "/"))

    # ---------------- 图片处理（原样保留）----------------
    def _aes_dec(self, data):
        if not data or not _HAS_CRYPTO:
            return b""
        try:
            return unpad(AES.new(self.aes_key, AES.MODE_CBC, self.aes_iv).decrypt(data), AES.block_size)
        except Exception:
            return b""

    def _pic(self, url):
        u = self._fix(url)
        if not u.startswith("http"):
            return u
        if "assets/images/categories" in u:
            return u
        b64 = base64.b64encode(u.encode()).decode()
        try:
            proxy = self.getProxyUrl() + "&url=" + b64 + "&type=img"
        except Exception:
            proxy = ""
        if proxy and proxy.startswith("http"):
            return proxy
        return "localProxy?type=img&url=" + b64

    def localProxy(self, param):
        if not param or str(param.get("type") or "") != "img":
            return [404, "text/plain", "", ""]
        try:
            u = base64.b64decode(str(param.get("url") or "")).decode("utf-8")
            if u in self._img_cache:
                return [200, "image/jpeg", self._img_cache[u], ""]
            r = self.session.get(
                u,
                headers={
                    "User-Agent": self.headers.get("User-Agent", "Mozilla/5.0"),
                    "Referer": self.host + "/",
                },
                timeout=20, verify=False, proxies=self.session.proxies or None,
            )
            data = r.content or b""
            if not data:
                return [404, "text/plain", "", ""]
            dec = self._aes_dec(data)
            if dec and (dec[:3] == b"\xff\xd8\xff" or dec[:4] == b"\x89PNG" or dec[:3] == b"GIF"):
                self._img_cache[u] = dec
                return [200, "image/jpeg", dec, ""]
            self._img_cache[u] = data
            return [200, "image/jpeg", data, ""]
        except Exception:
            return [500, "text/plain", "", ""]

    def _ext(self, extend):
        if isinstance(extend, dict):
            return extend
        if isinstance(extend, str) and extend.strip().startswith("{"):
            try:
                return json.loads(extend)
            except Exception:
                return {}
        return {}

    # ---------------- 分页 ----------------
    def _pagecount(self, html, pg):
        nums = []
        for m in re.finditer(r'<a[^>]*class="[^"]*page-link[^"]*"[^>]*href="([^"]*)"', html or ""):
            mm = re.search(r"/(\d+)(?:[;?]|$)", m.group(1))
            if mm:
                nums.append(int(mm.group(1)))
        for m in re.finditer(r'<a[^>]*class="[^"]*page-link[^"]*"[^>]*>\s*(\d+)\s*</a>', html or ""):
            nums.append(int(m.group(1)))
        nxt = re.search(r'<a[^>]*rel="next"[^>]*>', html or "") or ("下一页" in (html or ""))
        return max(nums + [pg + 1 if nxt else pg])

    # ---------------- 列表解析（原样保留）----------------
    def _list(self, html):
        out = []
        seen = set()
        for b in re.split(r'bind_video_img', html or "")[1:]:
            try:
                m = re.search(r'<a\s+href="([^"]*videos/[^"]+)"[^>]*>', b)
                if not m:
                    continue
                href = self._fix(m.group(1))
                if href in seen:
                    continue
                seen.add(href)
                im = re.search(r'<img[^>]*?(?:z-image-loader-url|data-src|src)="([^"]*)"', b)
                pic = self._pic(im.group(1)) if im else ""
                nm = re.search(r'<h3[^>]*class="[^"]*title[^"]*"[^>]*>\s*<a[^>]*>([^<]+)</a>', b)
                name = ""
                if nm:
                    name = re.sub(r"\s+", " ", nm.group(1)).strip()
                if not name:
                    am = re.search(r'<img[^>]*alt="([^"]*)"', b)
                    name = am.group(1) if am else ""
                if not name:
                    name = href.rsplit("/", 1)[-1]
                rm = re.search(r'<span class="label">([^<]+)</span>', b)
                remarks = rm.group(1) if rm else ""
                if "广告" in remarks:
                    remarks = ""
                out.append({"vod_id": href, "vod_name": name, "vod_pic": pic, "vod_remarks": remarks})
            except Exception:
                continue
        return out

    def _theme_list(self, html):
        out = []
        seen = set()
        for m in re.finditer(
            r'<a href="/theme/detail/(\d+)/([a-z]*)"[^>]*>\s*<div class="overlay"></div>\s*'
            r'<img[^>]*src="([^"]*)"[^>]*alt="([^"]*)"(.*?)</a>',
            html or "", re.S,
        ):
            try:
                tid = m.group(1)
                if tid in seen:
                    continue
                seen.add(tid)
                name = m.group(4).strip()
                pic = self._fix(m.group(3))
                seg = m.group(5)
                cm = re.search(r'<span class="label">(\d+)\s*部影片</span>', seg)
                remarks = (cm.group(1) + " 部影片") if cm else ""
                out.append({"vod_id": "theme$" + tid, "vod_name": name,
                            "vod_pic": pic, "vod_remarks": remarks, "vod_tag": "folder"})
            except Exception:
                continue
        return out

    def _actress_list(self, html):
        out = []
        seen = set()
        for m in re.finditer(
            r'<a href="/actress/detail/(\d+)/([a-z]+)"[^>]*>\s*<div class="media">(.*?)</a>',
            html or "", re.S,
        ):
            try:
                aid = m.group(1)
                if aid in seen:
                    continue
                seen.add(aid)
                if aid not in self._filters_actress:
                    self._filters_actress.append(aid)
                seg = m.group(3)
                nm = re.search(r'alt="([^"]*)"', seg)
                name = nm.group(1) if nm else "女优" + aid
                pm = re.search(r'z-image-loader-url="([^"]*)"', seg)
                pic = self._pic(pm.group(1)) if pm else ""
                cm = re.search(r'<span>(\d+)\s*部影片</span>', seg)
                remarks = (cm.group(1) + " 部影片") if cm else ""
                out.append({"vod_id": "actress$" + aid, "vod_name": name,
                            "vod_pic": pic, "vod_remarks": remarks, "vod_tag": "folder"})
            except Exception:
                continue
        return out

    # ---------------- 首页 / 分类 ----------------
    def homeContent(self, filter):
        fl = dict(self.filters)
        for t, _n in self.themes:
            fl["theme$" + t] = [{"key": "sort", "name": "排序", "value": self.theme_sorts}]
        for t in self._filters_actress:
            fl["actress$" + t] = [{"key": "sort", "name": "排序", "value": [
                {"n": "近期最佳", "v": "hot"},
                {"n": "今日更新", "v": "latest"},
                {"n": "最多观看", "v": "watch"},
                {"n": "最高收藏", "v": "favorite"},
            ]}]
        return {"class": self.categories,
                "list":  self._list(self._get(self.host)),
                "filters": fl}

    def homeVideoContent(self):
        return {"list": self._list(self._get(self.host + "/new"))}

    def categoryContent(self, tid, pg, filter, extend):
        pg = int(pg) if str(pg).isdigit() else 1
        tid = str(tid)
        ex = self._ext(extend)
        sort = ex.get("sort", "") or ""

        if tid.startswith("theme$"):
            t = tid.split("$")[1]
            st = sort if sort in ("hot", "update", "watch", "favorite") else "update"
            ht = self._get(self.host + "/theme/detail/%s/%s/" % (t, st))
            items = self._list(ht)
            return {"page": pg, "pagecount": self._pagecount(ht, pg),
                    "limit": len(items) or 24, "total": 0, "list": items}

        if tid.startswith("actress$"):
            aid = tid.split("$")[1]
            st = sort if sort in ("hot", "latest", "watch", "favorite") else "latest"
            ht = self._get(self.host + "/actress/detail/%s/%s/" % (aid, st))
            items = self._list(ht)
            if "actress$" + aid not in self.filters:
                self.filters["actress$" + aid] = [{"key": "sort", "name": "排序", "value": [
                    {"n": "近期最佳", "v": "hot"},
                    {"n": "今日更新", "v": "latest"},
                    {"n": "最多观看", "v": "watch"},
                    {"n": "最高收藏", "v": "favorite"},
                ]}]
            return {"page": pg, "pagecount": self._pagecount(ht, pg),
                    "limit": len(items) or 24, "total": 0, "list": items}

        if tid == "/theme":
            st = sort if sort in ("sort", "check_num", "count") else "sort"
            ht = self._get(self.host + "/theme/%s" % st)
            items = self._theme_list(ht)
            return {"page": pg, "pagecount": pg,
                    "limit": len(items) or 12, "total": len(items), "list": items}

        if tid == "/actress/hot":
            st = sort if sort in ("hot", "count") else "hot"
            ht = self._get(self.host + "/actress/%s/" % st)
            items = self._actress_list(ht)
            return {"page": pg, "pagecount": self._pagecount(ht, pg) or 1,
                    "limit": len(items) or 24, "total": 0, "list": items}

        base = self.tids.get(tid, tid)
        if sort in ("hot", "update", "watch", "favorite"):
            base = re.sub(r"/(?:hot|update|watch|favorite)$", "/" + sort, base)
        url = self.host + base + (("/" + str(pg)) if pg > 1 else "/")
        ht = self._get(url)
        items = self._list(ht)
        return {"page": pg, "pagecount": self._pagecount(ht, pg),
                "limit": len(items) or 24, "total": 0, "list": items}

    # ---------------- 详情 ----------------
    def detailContent(self, ids):
        out = []
        for vid in ids if isinstance(ids, list) else [ids]:
            try:
                sv = str(vid)
                if sv.startswith("theme$") or sv.startswith("actress$"):
                    continue
                url = self._fix(sv)
                html = self._get(url)
                title, pic, desc, tags, dur = "", "", "", "", ""
                v = re.search(r'<video[^>]*id="player"[^>]*>', html) or \
                    re.search(r'<video[^>]*class="[^"]*dplayer[^"]*"[^>]*>', html)
                if v:
                    tag = v.group(0)
                    tm = re.search(r'data-video_title="([^"]*)"', tag)
                    if tm:
                        title = tm.group(1)
                    pm = re.search(r'data-src="([^"]*)"', tag)
                    if pm:
                        pic = pm.group(1)
                    tg = re.search(r'data-video_tag_name="([^"]*)"', tag)
                    if tg:
                        tags = tg.group(1)
                if not title:
                    hm = re.search(r'<h1[^>]*>(.*?)</h1>', html, re.S) or \
                         re.search(r'<h2[^>]*>(.*?)</h2>', html, re.S)
                    if hm:
                        title = re.sub(r"<[^>]+>", "", hm.group(1)).strip()
                if not title:
                    title = sv
                if not pic:
                    pm = re.search(r'<img[^>]*?z-image-loader-url="([^"]*)"', html)
                    if pm:
                        pic = pm.group(1)
                jd = re.search(r'<script[^>]*application/ld\+json[^>]*>(.*?)</script>', html, re.S)
                if jd:
                    m2 = re.search(r'"description"\s*:\s*"([^"]+)"', jd.group(1))
                    if m2:
                        desc = m2.group(1)
                    m2 = re.search(r'"duration"\s*:\s*"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?"', jd.group(1))
                    if m2:
                        hh = int(m2.group(1) or 0)
                        mm = int(m2.group(2) or 0)
                        ss = int(m2.group(3) or 0)
                        dur = ("%02d:%02d:%02d" % (hh, mm, ss)) if hh else ("%02d:%02d" % (mm, ss))
                if not desc:
                    m2 = re.search(r'<meta[^>]*name="description"[^>]*content="([^"]*)"', html)
                    if m2:
                        desc = m2.group(1)
                desc = (desc or "")[:500]
                remarks = " ".join(x for x in [dur, tags] if x)
                out.append({"vod_id": sv, "vod_name": title, "vod_pic": self._pic(pic),
                            "vod_content": desc, "vod_remarks": remarks,
                            "vod_play_from": "91JAV",
                            "vod_play_url": "正片$" + sv})
            except Exception:
                continue
        return {"list": out}

    # ---------------- 搜索 ----------------
    def searchContent(self, key, quick, pg="1"):
        try:
            html = self._get(self.host + "/cn/search/" + quote(str(key)))
            i = html.find('list_videos_common_videos_list')
            if i >= 0:
                j = html.find("</section>", i)
                if j > i:
                    html = html[i:j]
            return {"list": self._list(html), "page": int(pg)}
        except Exception:
            return {"list": [], "page": int(pg)}

    # ---------------- m3u8 提取（原样保留）----------------
    def _m3u8(self, body):
        m = re.search(r'var\s+hlsUrl\s*=\s*["\']([^"\']+)', body or "")
        if m:
            return m.group(1).replace("&amp;", "&")
        ms = re.findall(r'https?://[^"\'\s<>]+\.(?:m3u8|mp4)[^"\'\s<>]*', body or "", re.I)
        if ms:
            return ms[0].replace("&amp;", "&")
        return ""

    def _probe(self, url):
        try:
            r = self.session.get(
                url,
                headers={**self.headers, "Range": "bytes=0-4096"},
                timeout=15, verify=False, stream=True,
                proxies=self.session.proxies or None,
            )
            data = next(r.iter_content(4096), b"")
            if r.ok and b"#EXTM3U" in data:
                return r.url
            if r.ok and ("video/" in r.headers.get("Content-Type", "").lower()
                         or data[4:12].find(b"ftyp") >= 0):
                return r.url
        except Exception:
            pass
        return ""

    # ---------------- 播放（关键：不再遍历所有 host）----------------
    def playerContent(self, flag, id, vipFlags):
        hd = dict(self.headers)
        u = str(id or "").strip()
        if not u:
            return {"parse": 0, "url": "", "header": hd}

        # 完整 URL
        if u.startswith("http"):
            if u.endswith(".m3u8") or ".m3u8?" in u or u.endswith(".mp4"):
                ok = self._probe(u)
                return {"parse": 0, "url": ok or u, "header": hd}
            body = self._get(u)
            url = self._m3u8(body)
            if url:
                ok = self._probe(url)
                return {"parse": 0, "url": ok or url, "header": hd}
            return {"parse": 1, "url": u, "header": hd}

        # 相对路径 → 拼 self.host
        full = self.host + (u if u.startswith("/") else "/" + u)
        if full.endswith(".m3u8") or ".m3u8?" in full or full.endswith(".mp4"):
            ok = self._probe(full)
            return {"parse": 0, "url": ok or full, "header": hd}
        body = self._get(u)   # _get 内部会 _fix
        url = self._m3u8(body)
        if url:
            if not url.startswith("http"):
                url = self.host + ("/" + url.lstrip("/"))
            ok = self._probe(url)
            return {"parse": 0, "url": ok or url, "header": hd}
        return {"parse": 1, "url": full, "header": hd}
