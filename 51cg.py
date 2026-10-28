# ============================================================
# 51通用模板 · 动态发布页自愈版 V7（基于真实页面结构）
# 关键修正：
#   - 探活选择器从 #index article a 改为 #navbar（主站真实结构）
#   - 域名提取改为全文本正则扫描（捕获 footer 明文域名）
#   - 发布页自身域名动态跟踪（避免 302 后误判）
#   - 保留原模板全部内容解析逻辑
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
from urllib.parse import urlparse
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
from Crypto.Cipher import AES
from Crypto.Util.Padding import unpad
from pyquery import PyQuery as pq

sys.path.append('..')
from base.spider import Spider

# ============================================================
# 本地文件缓存
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

    # 发布入口（302 到 djrqnywk.cc 这类中转页）
    "publish_urls": [
        "https://51bla18.com/",
        "https://51bla19.com/",
        "https://51bla20.com/",
    ],
    "publish_url": "https://51bla20.com/",

    # ------- 探活选择器（关键修复）-------
    # 主站首页真实存在的结构：<nav id="navbar" class="navbar ...">
    # 发布页(djrqnywk.cc)没有这些 → 自动排除
    "host_check_selector": "#navbar, nav.navbar, a.nav-link",

    # ------- 域名黑名单（统计/框架，非主站）-------
    # 不包含 cloudfront.net（它是真实线路四）
    "host_blacklist": [
        "googletagmanager.com", "google-analytics.com", "gstatic.com",
        "googlesyndication.com", "doubleclick.net",
        "jsdelivr.net", "cdnjs.cloudflare.com", "unpkg.com",
        "fontawesome.com", "bootcdn.net", "staticfile.org",
        "w3.org", "schema.org", "gmpg.org",
        "qihoo.com", "bdstatic.com", "360.cn",
        "telegram.org", "t.me", "twitter.com", "github.com",
        "facebook.com", "google.com", "youtube.com",
    ],

    # ------- 分类选择器（新增 ul.navbar-nav li a.nav-link）-------
    "category_selectors": [
        "ul.navbar-nav li.category-level-0 a.nav-link",
        "ul.navbar-nav > li > a.nav-link",
        ".category-list ul li",
        ".nav-menu li",
        ".menu li",
        "nav ul li",
    ],
    "default_classes": [
        {"type_name": "今日爆料", "type_id": "/category/jrbl/"},
        {"type_name": "必撸精品", "type_id": "/category/bljp/"},
        {"type_name": "热搜爆料", "type_id": "/category/rmdg/"},
    ],

    # ------- 列表选择器（保留原样，主站完整结构需进一步适配）-------
    "list_selector": "#index article a, #archive article a, article .post-title a",
    "home_list_selector": "#index article a, #archive article a, article .post-title a",
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
                  "image/avif,image/webp,image/apng,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9",
        "Accept-Encoding": "gzip, deflate",
        "Connection": "keep-alive",
    },

    "timeout": 15,
    "probe_timeout": 8,
    "fast_timeout": 4,
    "probe_workers": 8,
}
# ====================配置区结束===================


class Spider(Spider):
    cfg = SITE_CONFIG
    _cached_host = ""

    def init(self, extend=""):
        try:
            self.proxies = extend if isinstance(extend, dict) else (
                json.loads(extend) if extend else {})
        except Exception:
            self.proxies = {}

        self.cfg = SITE_CONFIG
        self.headers = dict(self.cfg["headers"])

        # 发布页自身域名集合（用于过滤候选）
        self._publish_hosts = set()
        for u in (self.cfg.get("publish_urls") or []):
            try:
                self._publish_hosts.add(urlparse(u).netloc.lower())
            except Exception:
                pass

        # urllib 兜底引擎（绕证书/反爬）
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
    # 统一请求：失败自动刷新域名并重试
    # ============================================================
    def _fetch(self, url, retry=True, **kwargs):
        kwargs.setdefault("timeout", self.cfg["timeout"])
        try:
            r = requests.get(url, headers=self.headers, proxies=self.proxies, **kwargs)
            if r.status_code == 200:
                return r
            if retry and r.status_code in (404, 451, 502, 503):
                self.log(f"HTTP {r.status_code} 触发自愈: {url}")
                print(f"HTTP {r.status_code} 触发自愈: {url}")
                if self._refresh_host():
                    new_url = self._replace_host(url)
                    if new_url != url:
                        return requests.get(new_url, headers=self.headers,
                                            proxies=self.proxies, **kwargs)
            return r
        except Exception as e:
            self.log(f"请求异常: {e}")
            if retry and self._refresh_host():
                try:
                    return requests.get(self._replace_host(url), headers=self.headers,
                                        proxies=self.proxies, **kwargs)
                except Exception:
                    pass
            return None

    def _replace_host(self, url):
        try:
            p = urlparse(url)
            old = f"{p.scheme}://{p.netloc}"
            if self.host and old != self.host:
                return url.replace(old, self.host, 1)
        except Exception:
            pass
        return url

    def _refresh_host(self):
        self.log("运行时刷新域名")
        print("运行时刷新域名")
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
    # 发布页抓取：requests + urllib 双引擎
    # 返回 (html_text, final_url)
    # ============================================================
    def _fetch_publish_page(self, url, timeout):
        # 尝试 1: requests（默认 allow_redirects=True 自动跟随 302）
        try:
            r = requests.get(url, headers=self.headers, proxies=self.proxies,
                             timeout=timeout, allow_redirects=True)
            if r.status_code == 200 and len(r.text or "") > 200:
                return r.text, r.url
        except Exception as e:
            self.log(f"requests 抓取发布页失败: {e}")

        # 尝试 2: urllib（自动跟随重定向）
        if not self._opener:
            return "", url
        try:
            req = urllib.request.Request(url, headers=self.headers)
            with self._opener.open(req, timeout=timeout) as resp:
                final_url = resp.geturl()
                raw = resp.read()
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
            self.log(f"urllib 抓取发布页失败: {e}")
        return "", url

    # ============================================================
    # 【核心修复】探活：只用主站真实结构判断
    # ============================================================
    def _probe_one(self, url, timeout):
        try:
            r = requests.get(url, headers=self.headers, proxies=self.proxies,
                             timeout=timeout, allow_redirects=True)
            if r.status_code != 200:
                return False
            try:
                doc = self.getpq(r.text)
                # #navbar / nav.navbar / a.nav-link 任一命中即通过
                if doc("#navbar") or doc("nav.navbar") or doc("a.nav-link"):
                    return True
            except Exception:
                pass
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
                for fut in as_completed(future_map, timeout=timeout + 5):
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
    # 缓存
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
        host, _ = _read_host_cache()
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

        candidates = self._extract_candidates_from_publish_pages()
        if not candidates:
            self.log("发布页未提取到候选域名")
            print("发布页未提取到候选域名")
            return ""

        print(f"待探活候选({len(candidates)}): {candidates[:12]}")
        host = self._probe_concurrent(candidates, self.cfg["probe_timeout"])
        if host:
            self._cache_set(host)
            self.log(f"自愈成功: {host}")
            print(f"自愈成功: {host}")
            return host

        self.log("所有候选均未通过探活")
        print("所有候选均未通过探活")
        return ""

    # ============================================================
    # 【核心】从发布页提取所有候选域名
    # ============================================================
    def _extract_candidates_from_publish_pages(self):
        entries = self.cfg.get("publish_urls") or [self.cfg.get("publish_url", "")]
        entries = [e for e in entries if e]

        all_cands = []
        seen = set()

        def _add(cands):
            for c in cands:
                if c and c not in seen:
                    seen.add(c)
                    all_cands.append(c)

        for entry in entries:
            try:
                text, final_url = self._fetch_publish_page(entry, self.cfg["probe_timeout"])
                if not text:
                    self.log(f"发布页无响应: {entry}")
                    continue

                # 动态记录发布页落地的域名
                try:
                    final_host = urlparse(final_url).netloc.lower()
                    if final_host:
                        self._publish_hosts.add(final_host)
                except Exception:
                    pass

                # 提取所有 https://xxx.xxx 形式的域名
                cands = self._extract_domains_from_text(text)
                _add(cands)

            except Exception as e:
                self.log(f"处理发布页失败 [{entry}]: {e}")
                continue

        if all_cands:
            self.log(f"共提取 {len(all_cands)} 个候选域名: {all_cands[:12]}")
            print(f"共提取 {len(all_cands)} 个候选域名: {all_cands[:12]}")
        return all_cands

    def _extract_domains_from_text(self, text):
        """从任意文本中提取所有绝对 https URL 的域名部分"""
        cands = []
        seen = set()
        # 匹配 https://host 或 http://host
        for m in re.finditer(
            r'https?://([a-zA-Z0-9][a-zA-Z0-9.\-]{3,}\.[a-zA-Z]{2,})(?::\d+)?',
            text
        ):
            host = m.group(1).lower()
            # 过滤发布页自身
            if host in self._publish_hosts:
                continue
            # 过滤统计/CDN/框架
            if self._is_blacklisted(host):
                continue
            # 统一用 https（大多数站点支持）
            base = "https://" + host
            if base not in seen:
                seen.add(base)
                cands.append(base)
        return cands

    def _is_blacklisted(self, host):
        host_l = host.lower()
        for kw in self.cfg.get("host_blacklist", []):
            if kw and kw.lower() in host_l:
                return True
        return False

    # ============================================================
    # 以下为内容解析（保留原模板逻辑，仅替换请求层）
    # ============================================================
    def homeContent(self, filter):
        try:
            if not self.host:
                return {"class": [], "list": []}
            r = self._fetch(self.host)
            if not r or r.status_code != 200:
                return {"class": [], "list": []}

            doc = self.getpq(r.text)
            classes = []
            for selector in self.cfg["category_selectors"]:
                for item in doc(selector).items():
                    a = item("a") if item.is_("li") else item
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
            r = self._fetch(self.host)
            if not r or r.status_code != 200:
                return {"list": []}
            doc = self.getpq(r.text)
            return {"list": self.getlist(doc(self.cfg["list_selector"]))}
        except Exception as e:
            print(f"homeVideoContent error: {e}")
            return {"list": []}

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
            r = self._fetch(url)
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

    def detailContent(self, ids):
        try:
            raw_id = ids[0] if ids else ""
            url = raw_id if raw_id.startswith("http") else f"{self.host}{raw_id}"
            r = self._fetch(url)
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

    def searchContent(self, key, quick, pg="1"):
        try:
            if not self.host:
                return {"list": [], "page": pg}
            if str(pg) != "1":
                url = self.cfg["search_url_tpl_paged"].format(host=self.host, key=key, pg=pg)
            else:
                url = self.cfg["search_url_tpl"].format(host=self.host, key=key)
            r = self._fetch(url)
            if not r or r.status_code != 200:
                return {"list": [], "page": pg}
            doc = self.getpq(r.text)
            return {"list": self.getlist(doc(self.cfg["list_selector"])), "page": pg}
        except Exception as e:
            print(f"searchContent error: {e}")
            return {"list": [], "page": pg}

    def playerContent(self, flag, id, vipFlags):
        url = id
        p = 1
        if self.isVideoFormat(url):
            if ".m3u8" in url:
                url = self.proxy(url)
            p = 0
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
        r = self._fetch(f"{self.host}{folder_id}")
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
