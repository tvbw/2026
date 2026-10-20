# ============================================================
# 通用发布页动态域名 Spider 模板（并发测活 + 本地 48h 缓存版）
# ============================================================
import json
import os
import re
import sys
import tempfile
import time
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
# 本地 host 缓存（48 小时），失败自动降级
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
    "name": "51模板",
    "play_from": "51模板",
    "style": {"type": "rect", "ratio": 1.33},

    "publish_urls": [
        "https://51cgf18.com/",
        "https://51cgf20.com/",
    ],
    "publish_url": "https://mrdld3.com/",
    "publish_decode": "plain",

    "host_check_selector": "#index article a",

    "fallback_hosts": [
        "https://21bn7.ocqxkylwn.cc/",
        "https://angle.ocqxkylwn.cc/",
        "https://alive.ocqxkylwn.cc/",
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
            self.proxies = json.loads(extend)
        except Exception:
            self.proxies = {}

        self.cfg = SITE_CONFIG
        self.headers = dict(self.cfg["headers"])

        self.host = self.get_working_host()
        self.headers.update({
            "Origin": self.host,
            "Referer": f"{self.host}/",
        })
        self.log(f"使用站点: {self.host}")
        print(f"使用站点: {self.host}")

    def getName(self):
        return SITE_CONFIG.get("name", "51模板")

    def isVideoFormat(self, url):
        return any(ext in (url or "") for ext in [".m3u8", ".mp4", ".ts"])

    def manualVideoCheck(self):
        return False

    def destroy(self):
        pass

    # ================= 首页 =================
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

    # ================= 分类 =================
    def categoryContent(self, tid, pg, filter, extend):
        try:
            if "@folder" in tid:
                folder_id = tid.replace("@folder", "")
                videos = self.getfod(folder_id)
                return {
                    "list": videos, "page": pg, "pagecount": 1,
                    "limit": 90, "total": len(videos),
                }

            pg = int(pg)
            tid = tid.rstrip("/")
            url = f"{self.host}{tid}/{pg}/" if pg > 1 else f"{self.host}{tid}/"

            r = requests.get(url, headers=self.headers,
                             proxies=self.proxies, timeout=self.cfg["timeout"])
            if r.status_code != 200:
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

            next_url = doc(
                'a.next, .pagination a.next, .pagenavi .next, a:contains("下一页")'
            ).attr("href")
            has_next = bool(next_url)

            return {
                "list": videos,
                "page": pg,
                "pagecount": total_pages if total_pages > 1 else (99999 if has_next else pg),
                "limit": 90,
                "total": 999999 if has_next else len(videos),
            }
        except Exception as e:
            print(f"categoryContent error: {e}")
            return {"list": [], "page": pg, "pagecount": 1, "limit": 90, "total": 0}

    # ================= 详情 =================
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
                vod["vod_play_url"] = "#".join(plist) if plist else f"未找到视频源${url}"
            except Exception:
                vod["vod_play_url"] = f"视频解析失败${url}"

            return {"list": [vod]}
        except Exception as e:
            print(f"detailContent error: {e}")
            return {"list": [{
                "vod_play_from": self.cfg["play_from"],
                "vod_play_url": f"详情页加载失败${ids[0] if ids else ''}",
            }]}

    # ================= 搜索 =================
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

    # ================= 发布页 / 动态域名（缓存 + 并发） =================
    def get_working_host(self):
        # 1) 先看缓存（类内存 -> 文件 48h）
        cached = ""
        if Spider._cached_host:
            cached = Spider._cached_host
        else:
            cached, cache_path = _read_host_cache()
            if cached:
                print(f"命中本地缓存文件: {cache_path}")

        if cached:
            if self._probe_one(cached, self.cfg["fast_timeout"]):
                self.log(f"命中缓存站点: {cached}")
                print(f"命中缓存站点: {cached}")
                Spider._cached_host = cached
                return cached
            else:
                self.log(f"缓存站点失效，重新探测: {cached}")
                print(f"缓存站点失效，重新探测: {cached}")
                Spider._cached_host = ""
                _clear_host_cache()

        # 2) 发布页 + 兜底
        candidates = self.extract_domains_from_publish_page()
        all_hosts = []
        seen = set()
        for u in list(candidates) + list(self.cfg["fallback_hosts"]):
            if u and u not in seen:
                seen.add(u)
                all_hosts.append(u)

        if not all_hosts:
            all_hosts = list(self.cfg["fallback_hosts"])

        # 3) 并发测活
        host = self._probe_concurrent(all_hosts, self.cfg["probe_timeout"])
        if host:
            Spider._cached_host = host
            _write_host_cache(host)
            if host in candidates:
                self.log(f"动态解析到可用站点: {host}")
                print(f"动态解析到可用站点: {host}")
            else:
                self.log(f"回退选用可用站点: {host}")
                print(f"回退选用可用站点: {host}")
            return host

        fb = self.cfg["fallback_hosts"][0]
        self.log(f"未检测到可用站点，回退: {fb}")
        print(f"未检测到可用站点，回退: {fb}")
        return fb

    def _probe_one(self, url, timeout):
        try:
            r = requests.get(url, headers=self.headers,
                             proxies=self.proxies, timeout=timeout)
            if r.status_code != 200:
                return False
            return bool(self.getpq(r.text)(self.cfg["host_check_selector"]))
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
            future_map = {
                ex.submit(self._probe_one, u, timeout): u for u in urls
            }
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

    def extract_domains_from_publish_page(self):
        cfg = self.cfg
        entries = cfg.get("publish_urls") or [cfg.get("publish_url", "")]
        entries = [e for e in entries if e]

        for entry in entries:
            try:
                r = requests.get(entry, headers=self.headers,
                                 proxies=self.proxies,
                                 timeout=cfg["probe_timeout"],
                                 allow_redirects=True)
                if r.status_code != 200:
                    continue

                domains = self._extract_from_html(r.text, r.url)
                if domains:
                    return domains

                target = self._find_meta_refresh(r.text)
                if target:
                    domains = self._fetch_and_extract(target, base=entry)
                    if domains:
                        return domains

                target = self._find_js_location(r.text)
                if target:
                    domains = self._fetch_and_extract(target, base=entry)
                    if domains:
                        return domains

            except Exception as e:
                self.log(f"发布页入口失败 [{entry}]: {e}")
                print(f"发布页入口失败 [{entry}]: {e}")
                continue

        self.log("所有发布页入口均未提取到候选域名")
        print("所有发布页入口均未提取到候选域名")
        return []

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
            if not u:
                continue
            if u not in seen:
                seen.add(u)
                uniq.append(u)

        if uniq:
            self.log(f"发布页解析到 {len(uniq)} 个候选域名: {uniq[:6]}")
            print(f"发布页解析到 {len(uniq)} 个候选域名: {uniq[:6]}")
        return uniq

    def _fetch_and_extract(self, target_url, base):
        try:
            target_url = self._normalize_url(target_url, base)
            if not target_url:
                return []
            self.log(f"发布页跳转目标: {target_url}")
            print(f"发布页跳转目标: {target_url}")

            r = requests.get(target_url, headers=self.headers,
                             proxies=self.proxies,
                             timeout=self.cfg["probe_timeout"],
                             allow_redirects=True)
            if r.status_code != 200:
                return []
            return self._extract_from_html(r.text, r.url)
        except Exception as e:
            self.log(f"请求跳转目标失败: {e}")
            print(f"请求跳转目标失败: {e}")
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
        if not u.startswith("http"):
            return ""
        if "." not in u:
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
        if mode == "plain":
            return text
        if mode == "redirect":
            return ""
        return text

    def _pick_domains(self, doc, base):
        seen, out = set(), []
        for a in doc("a").items():
            href = (a.attr("href") or "").strip()
            u = self._normalize_url(href, base)
            if not u:
                continue
            if u not in seen:
                seen.add(u)
                out.append(u)
        return out

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

    # ================= 合集 =================
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

    # ================= 图片 =================
    def getimg(self, text):
        m = re.search(self.cfg["img_regex"], text or "")
        if m:
            return f"{self.getProxyUrl()}&url={m.group(1)}&type=img"
        return ""

    def aesimg(self, word):
        cipher = AES.new(self.cfg["aes_key"], AES.MODE_CBC, self.cfg["aes_iv"])
        return unpad(cipher.decrypt(word), AES.block_size)

    # ================= PyQuery =================
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
# 注册爬虫
if __name__ == '__main__':
    from base.spider import Spider as BaseSpider
    BaseSpider.register(Spider())
