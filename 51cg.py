# ============================================================
# 51通用模板 · 三级域名自动跳转 + 目录自动抓取（最终版）
#
# 核心：
#   1) 域名探测：91 代码同款 —— 硬编码列表 + requests 跟随 302 + 取最终域名
#   2) 探活选择器：基于真实结构 #navbarCollapse / .navbar-nav / a.nav-link
#   3) 目录抓取：优先精确匹配主站导航，自动提取一级 + 二级分类
#   4) default_classes 仅作最后兜底
# ============================================================
import json
import os
import re
import sys
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
        lambda: os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), CACHE_FILE_NAME),
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

    # ------- 硬编码可用域名列表（按优先级排序）-------
    "dynamic_urls": [
        "https://brother.bqtvyoxk.cc/",
        "https://career.bqtvyoxk.cc/",
        "https://aspect.bqtvyoxk.cc/",
    ],

    # ------- 探活选择器（基于真实主站结构）-------
    # 主站真实结构：<div class="collapse navbar-collapse" id="navbarCollapse">
    #             <ul class="navbar-nav mr-auto">
    "host_check_selector": "#navbarCollapse, .navbar-nav, nav.navbar, a.nav-link",

    # ------- 分类选择器（精确 → 通用依次尝试）-------
    # 主站一级目录：ul.navbar-nav.mr-auto > li.nav-item > a.nav-link
    # 主站二级目录：li.nav-item.dropdown > ul.dropdown-menu > li.dropdown-item > a
    "category_selectors": [
        "ul.navbar-nav.mr-auto > li.nav-item > a.nav-link",
        "ul.navbar-nav > li.nav-item > a.nav-link",
        "ul.navbar-nav li a.nav-link",
        ".category-list ul li",
        ".nav-menu li",
        ".menu li",
        "nav ul li",
    ],

    # 二级下拉菜单选择器（单独处理）
    "sub_category_selector": (
        "ul.navbar-nav.mr-auto li.nav-item.dropdown > ul.dropdown-menu > li.dropdown-item > a"
    ),

    # ------- 仅在完全抓取失败时兜底 -------
    "default_classes": [
        {"type_name": "首页", "type_id": "/"},
    ],

    # ------- 列表选择器（91 代码同款）-------
    "list_selector": "article, #index article, #archive article",
    "home_list_selector": "article, #index article, #archive article",
    "folder_id_marker": "/mrdg",

    "title_selector": ".post-title, h1",
    "tag_selector": ".tags .keywords a, .tags a",
    "player_selector": ".dplayer",
    "player_config_attr": "data-config",
    "player_heading_selector": "h2, h3, h4",

    "folder_content_selector": ".post-content[itemprop='articleBody'], .post-content",
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
    # 域名探测（91 代码同款逻辑）
    # ============================================================
    def get_working_host(self):
        cached = self._cache_get()
        if cached:
            final = self._probe_one(cached, self.cfg["fast_timeout"])
            if final:
                self.log(f"缓存命中: {cached} → {final}")
                print(f"缓存命中: {cached} → {final}")
                if final != cached:
                    self._cache_set(final)
                return final
            self.log(f"缓存失效: {cached}")
            self._cache_del()

        urls = self.cfg.get("dynamic_urls", [])
        if not urls:
            self.log("未配置任何动态域名")
            return ""

        print(f"待探测域名({len(urls)}): {urls}")
        host = self._probe_concurrent(urls, self.cfg["probe_timeout"])
        if host:
            self._cache_set(host)
            self.log(f"自愈成功: {host}")
            print(f"自愈成功: {host}")
            return host

        self.log("所有域名均未通过探活")
        print("所有域名均未通过探活")
        return ""

    def _probe_one(self, url, timeout):
        """返回重定向后的最终根域名；失败返回空字符串"""
        try:
            r = requests.get(url, headers=self.headers, proxies=self.proxies,
                             timeout=timeout, allow_redirects=True)
            if r.status_code != 200:
                return ""
            try:
                doc = self.getpq(r.text)
                # 使用配置中的探活选择器（基于真实主站结构）
                if not doc(self.cfg["host_check_selector"]):
                    return ""
            except Exception:
                return ""

            try:
                parsed = urlparse(r.url)
                if not parsed.netloc:
                    return ""
                return f"{parsed.scheme}://{parsed.netloc}"
            except Exception:
                return ""
        except Exception:
            return ""

    def _probe_concurrent(self, urls, timeout):
        if not urls:
            return ""
        if len(urls) == 1:
            return self._probe_one(urls[0], timeout)

        results = {}
        with ThreadPoolExecutor(max_workers=min(4, len(urls))) as ex:
            future_map = {ex.submit(self._probe_one, u, timeout): u for u in urls}
            try:
                for fut in as_completed(future_map, timeout=timeout + 5):
                    u = future_map[fut]
                    try:
                        results[u] = fut.result(timeout=0)
                    except Exception:
                        results[u] = ""
                    if results.get(u):
                        idx = urls.index(u)
                        if all(urls[i] in results for i in range(idx)):
                            for i in range(idx + 1):
                                if results.get(urls[i]):
                                    return results[urls[i]]
            except Exception:
                pass
        for u in urls:
            if results.get(u):
                return results[u]
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
    # 首页：自动抓取一级 + 二级目录
    # ============================================================
    def homeContent(self, filter):
        try:
            if not self.host:
                return {"class": [], "list": []}
            r = self._fetch(self.host)
            if not r or r.status_code != 200:
                return {"class": [], "list": []}

            doc = self.getpq(r.text)
            classes = self._parse_categories(doc)

            return {
                "class": classes,
                "list": self.getlist(doc(self.cfg["home_list_selector"])),
            }
        except Exception as e:
            print(f"homeContent error: {e}")
            return {"class": [], "list": []}

    def _parse_categories(self, doc):
        """自动抓取主站导航分类：一级 + 二级下拉"""
        classes = []
        seen_href = set()

        try:
            self_host = urlparse(self.host).netloc if self.host else ""
        except Exception:
            self_host = ""

        def _add(name, href):
            name = (name or "").strip()
            href = (href or "").strip()
            if not name or not href or href in ("#", ""):
                return
            # 排除伪链接
            if href.startswith(("javascript:", "mailto:", "tel:")):
                return
            # 排除外链
            if href.startswith("http"):
                try:
                    if urlparse(href).netloc != self_host:
                        return
                except Exception:
                    return
            # 相对路径统一成 / 开头
            if not href.startswith("http") and not href.startswith("/"):
                href = "/" + href
            if href in seen_href:
                return
            seen_href.add(href)
            classes.append({"type_name": name, "type_id": href})

        # ---- 策略1：一级目录（真实结构）----
        # <li class="nav-item"><a class="nav-link dropdown-toggle" href="/category/wpcz/"><div>今日吃瓜</div></a></li>
        try:
            for li in doc("ul.navbar-nav.mr-auto > li.nav-item, ul.navbar-nav > li.nav-item").items():
                # 只处理带 <a> 的，跳过只有 <button> 的 dropdown
                a = li("> a.nav-link").eq(0)
                if not a:
                    a = li("> a").eq(0)
                if not a:
                    continue
                href = a.attr("href") or ""
                name = a.text().strip()
                if name:
                    _add(name, href)
        except Exception as e:
            print(f"一级目录抓取失败: {e}")

        # ---- 策略2：二级下拉目录 ----
        # <li class="dropdown-item"><a href="/category/mrds/" title="每日大赛">每日大赛</a></li>
        try:
            for a in doc(self.cfg["sub_category_selector"]).items():
                href = a.attr("href") or ""
                name = (a.attr("title") or "").strip() or a.text().strip()
                if name:
                    _add(name, href)
        except Exception as e:
            print(f"二级目录抓取失败: {e}")

        # ---- 策略3：通用选择器兜底 ----
        if not classes:
            for selector in self.cfg["category_selectors"]:
                for item in doc(selector).items():
                    a = item("a") if item.is_("li") else item
                    href = (a.attr("href") or "").strip()
                    name = (a.text() or "").strip()
                    if not href or href == "#" or not name:
                        continue
                    _add(name, href)
                if classes:
                    break

        # ---- 策略4：default_classes 最后兜底 ----
        if not classes:
            classes = list(self.cfg["default_classes"])

        print(f"自动抓取到 {len(classes)} 个分类")
        return classes

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

    # ============================================================
    # 分类内容
    # ============================================================
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

            # 首页 tid="/" 直接请求根路径
            if tid == "" or tid == "/":
                url = f"{self.host}/" if pg == 1 else f"{self.host}/page/{pg}/"
            else:
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

    # ============================================================
    # 详情 / 搜索 / 播放
    # ============================================================
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
            name = k("h2").text() or k(".entry-title").text() or k(".post-title").text()
            if not href:
                a = k("a").eq(0)
                href = a.attr("href")
            if not name:
                name = k("a").eq(0).text() or k.text()
            remark = (k("span[itemprop='datePublished']").text()
                      or k(".post-meta, .entry-meta, time").text())
            if href and name:
                videos.append({
                    "vod_id": f"{href}{'@folder' if is_folder else ''}",
                    "vod_name": name.replace("\n", " ").strip(),
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
