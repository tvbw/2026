# ============================================================
# 通用版 v2（51bl / 黑料718 双站兼容）
#   核心修正：
#   1. 封面提取改用 PyQuery 多路径（meta/img/script），不再被换行打挂
#   2. homeContent 自动抓取分类为主，default_classes 只保留"首页"
#   3. categoryContent 对 tid 做规范化：完整URL -> path；query 式始终带 ?page=N
#   4. 保留 102 原跳转识别 + ul.page-navigator 翻页修复
# ============================================================
import json
import re
import sys
import time
from base64 import b64decode, b64encode
from urllib.parse import urlparse, quote
import requests
from Crypto.Cipher import AES
from Crypto.Util.Padding import unpad
from pyquery import PyQuery as pq
sys.path.append('..')
from base.spider import Spider

SITE_CONFIG = {
    "name": "黑料718",
    "play_from": "黑料718",
    "style": {"type": "rect", "ratio": 1.33},

    # ===== 换站只改这 4 项 =====
    "publish_url": "https://www.hl718men.com/",
    "fallback_hosts": [
        "https://hover.jisouheiliao.com/",
        "https://flock.51henduoliuliang.com/",
    ],
    "page_style": "query",     # query: /category/x/?page=N ; path: /category/x/N/
    "img_proxy": False,        # 51bl=True(AES图走代理) ; 黑料718=False(普通图直链)

    # 发布页解码方式与探测选择器（Typecho+Mirages 通用）
    "publish_decode": "js_base64",
    "host_check_selector": "article a, #index article a",

    # ===== 列表页解析（自动抓取，不依赖手工分类） =====
    "list_selector": "article",
    "home_list_selector": "article",
    "category_selectors": [
        "#nav-menu li",
        ".nav-menu li",
        ".menu li",
        "nav ul li",
        ".category-list ul li",
    ],
    # 兜底分类：只放"首页"，其余自动抓取。想手工加就 append，但不利于模板通用
    "default_classes": [
        {"type_name": "首页", "type_id": "/"},
    ],
    "folder_id_marker": "/mrdg",

    # ===== 详情/播放（Typecho+Mirages 通用） =====
    "title_selector": ".post-title",
    "tag_selector": ".tags .keywords a",
    "player_selector": ".dplayer, [data-config]",
    "player_config_attr": "data-config",
    "player_heading_selector": "h2, h3, h4",

    "folder_content_selector": ".post-content[itemprop='articleBody']",
    "folder_remove_selectors": [".txt-apps", ".line", "blockquote", ".tags", ".content-tabs"],
    "folder_img_attr": "data-xkrkllgl",

    "img_regex": r"loadBannerDirect\('([^']+)'",
    "aes_key": b"f5d965df75336270",
    "aes_iv": b"97b60394abc2fbe1",

    "search_url_tpl": "{host}/search/{key}/",
    "search_url_tpl_paged": "{host}/search/{key}/?page={pg}",

    "headers": {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                      "AppleWebKit/537.36 (KHTML, like Gecko) "
                      "Chrome/134.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,"
                  "image/avif,image/webp,image/apng,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9",
        "Connection": "keep-alive",
        "Cache-Control": "no-cache",
    },
    "timeout": 15,
    "probe_timeout": 10,
}


def _clean(text):
    t = re.sub(r"<[^>]+>", " ", text or "")
    return re.sub(r"\s+", " ", t).strip()


class Spider(Spider):

    cfg = SITE_CONFIG

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
        print(f"使用站点: {self.host}")

    def getName(self):
        return SITE_CONFIG.get("name", "通用")

    def isVideoFormat(self, url):
        return any(ext in (url or "") for ext in [".m3u8", ".mp4", ".ts"])

    def manualVideoCheck(self):
        return False

    def destroy(self):
        pass

    # ================= 工具：tid 规范化 =================
    def _normalize_tid(self, href):
        """把任意形态的分类链接规范化为相对路径 /category/xxx/"""
        href = (href or "").strip()
        if not href or href == "#" or href.startswith("javascript:"):
            return ""
        if href.startswith("//"):
            href = "https:" + href
        if href.startswith("http"):
            try:
                return urlparse(href).path or "/"
            except Exception:
                return ""
        if not href.startswith("/"):
            href = "/" + href
        return href

    # ================= 首页 =================
    def homeContent(self, filter):
        try:
            r = requests.get(self.host, headers=self.headers,
                             proxies=self.proxies, timeout=self.cfg["timeout"])
            if r.status_code != 200:
                return {"class": [], "list": []}

            doc = self.getpq(r.text)
            classes = []
            seen_tid = set()
            for selector in self.cfg["category_selectors"]:
                for item in doc(selector).items():
                    a = item("a")
                    href = self._normalize_tid(a.attr("href"))
                    name = (a.text() or "").strip()
                    if not href or not name:
                        continue
                    if href in seen_tid:
                        continue
                    seen_tid.add(href)
                    classes.append({"type_name": name, "type_id": href})
                if len(classes) >= 2:
                    break

            # 自动抓不到（<2 条）才用兜底；兜底默认只含"首页"
            if len(classes) < 2:
                classes = list(self.cfg["default_classes"])

            print(f"[home] classes={len(classes)}, list_selector='{self.cfg['home_list_selector']}'")
            vods = self.getlist(doc(self.cfg["home_list_selector"]))
            print(f"[home] vods={len(vods)}, first_pic={vods[0]['vod_pic'][:60] if vods else ''}")
            return {"class": classes, "list": vods}
        except Exception as e:
            print(f"homeContent error: {e}")
            return {"class": [], "list": []}

    def homeVideoContent(self):
        try:
            r = requests.get(self.host, headers=self.headers,
                             proxies=self.proxies, timeout=self.cfg["timeout"])
            if r.status_code != 200:
                return {"list": []}
            return {"list": self.getlist(self.getpq(r.text)(self.cfg["list_selector"]))}
        except Exception as e:
            print(f"homeVideoContent error: {e}")
            return {"list": []}

    # ================= 分类 =================
    def categoryContent(self, tid, pg, filter, extend):
        try:
            if '@folder' in tid:
                vid = tid.replace('@folder', '')
                videos = self.getfod(vid)
                return {'list': videos, 'page': pg, 'pagecount': 1, 'limit': 90, 'total': len(videos)}

            pg = int(pg)
            tid = self._normalize_tid(tid)
            tid = tid.rstrip('/')
            style = self.cfg.get("page_style", "path")

            if not tid or tid == "":
                # 首页
                url = f"{self.host}/" if pg == 1 else f"{self.host}/page/{pg}/"
            elif style == "query":
                # 黑料718：始终带 ?page=N（与已验证代码一致）
                url = f"{self.host}{tid}/?page={pg}"
            else:
                # 51bl：path 式
                url = f"{self.host}{tid}/" if pg == 1 else f"{self.host}{tid}/{pg}/"

            print(f"[category] url={url}")
            rsp = requests.get(url, headers=self.headers, proxies=self.proxies, timeout=15)
            if rsp.status_code != 200:
                print(f"[category] HTTP {rsp.status_code}")
                return {'list': [], 'page': pg, 'pagecount': 1, 'limit': 90, 'total': 0}

            doc = self.getpq(rsp.text)
            arts = doc(self.cfg["list_selector"])
            videos = self.getlist(arts, tid)
            print(f"[category] articles={len(arts)}, vods={len(videos)}")

            # 翻页判定（ul.page-navigator 修复）
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
            elif videos:
                # 有内容但无翻页信息，允许试下一页
                pagecount = pg + 1
            else:
                pagecount = pg

            return {
                'list': videos,
                'page': pg,
                'pagecount': pagecount,
                'limit': 30,
                'total': pagecount * 30 if pagecount > 1 else len(videos),
            }
        except Exception as e:
            print(f"categoryContent error: {e}")
            return {'list': [], 'page': pg, 'pagecount': 1, 'limit': 90, 'total': 0}

    # ================= 详情 =================
    def detailContent(self, ids):
        try:
            raw_id = ids[0] if ids else ""
            if raw_id.startswith("http"):
                url = raw_id
            elif re.fullmatch(r"\d+", str(raw_id)):
                url = f"{self.host}/archives/{raw_id}"
            else:
                url = f"{self.host}{raw_id if str(raw_id).startswith('/') else '/' + str(raw_id)}"

            r = requests.get(url, headers=self.headers,
                             proxies=self.proxies, timeout=self.cfg["timeout"])
            if r.status_code != 200:
                return {"list": [{
                    "vod_play_from": self.cfg["play_from"],
                    "vod_play_url": f"页面加载失败${url}",
                }]}

            doc = self.getpq(r.text)
            vod = {"vod_play_from": self.cfg["play_from"]}

            title = (doc(self.cfg["title_selector"]).text() or "").strip()
            if not title:
                tm = re.search(r"<title>([^<]+)</title>", r.text)
                if tm:
                    title = _clean(tm.group(1)).split(" - ")[0]

            try:
                clist = []
                if self.cfg["tag_selector"]:
                    for k in doc(self.cfg["tag_selector"]).items():
                        t = k.text()
                        href = k.attr("href")
                        if t and href:
                            clist.append("[a=cr:" + json.dumps({"id": href, "name": t}) + "/]"
                                         + t + "[/a]")
                vod["vod_content"] = " ".join(clist) if clist else title
            except Exception:
                vod["vod_content"] = title or self.cfg["name"]

            try:
                plist = self._parse_players(doc, r.text)
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
            pg = int(pg)
            k = quote(str(key))
            style = self.cfg.get("page_style", "path")
            if style == "query":
                url = f"{self.host}/search/{k}/?page={pg}"
            else:
                url = (self.cfg["search_url_tpl"].format(host=self.host, key=k)
                       if pg == 1 else
                       self.cfg["search_url_tpl_paged"].format(host=self.host, key=k, pg=pg))

            r = requests.get(url, headers=self.headers,
                             proxies=self.proxies, timeout=self.cfg["timeout"])
            if r.status_code != 200:
                return {"list": [], "page": pg}

            videos = self.getlist(self.getpq(r.text)(self.cfg["list_selector"]))
            return {"list": videos, "page": pg, "pagecount": 50,
                    "total": 50 * 30, "limit": 30}
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
                m = re.search(r'URI="([^"]*)"', string)
                if m:
                    lines[index] = re.sub(r'URI="([^"]*)"',
                                          f'URI="{self.proxy(m.group(1), "mkey")}"', string)
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
        except Exception:
            return ""

    def d64(self, text):
        try:
            return b64decode(text.encode("utf-8")).decode("utf-8")
        except Exception:
            return ""

    # ================= 发布页 / 动态域名 =================
    def get_working_host(self):
        for url in self.extract_domains_from_publish_page():
            try:
                r = requests.get(url, headers=self.headers,
                                 proxies=self.proxies, timeout=self.cfg["probe_timeout"])
                if r.status_code == 200 and self.getpq(r.text)(self.cfg["host_check_selector"]):
                    print(f"动态解析到可用站点: {url}")
                    return url
            except Exception:
                continue

        for url in self.cfg["fallback_hosts"]:
            try:
                r = requests.get(url, headers=self.headers,
                                 proxies=self.proxies, timeout=self.cfg["probe_timeout"])
                if r.status_code == 200 and self.getpq(r.text)(self.cfg["host_check_selector"]):
                    print(f"回退选用可用站点: {url}")
                    return url
            except Exception:
                continue

        fallback = self.cfg["fallback_hosts"][0]
        print(f"未检测到可用站点，回退: {fallback}")
        return fallback

    def extract_domains_from_publish_page(self):
        try:
            r = requests.get(self.cfg["publish_url"], headers=self.headers,
                             proxies=self.proxies, timeout=self.cfg["probe_timeout"],
                             allow_redirects=True)
            if r.status_code != 200:
                return []
            html = self._decode_publish(r.text, self.cfg["publish_decode"])
            doc = self.getpq(html)
            domains = self._pick_domains(doc, self.cfg["publish_url"])

            if not domains:
                target = self._find_meta_refresh(r.text)
                if target:
                    domains = self._fetch_and_extract(target, self.cfg["publish_url"])
            if not domains:
                target = self._find_js_location(r.text)
                if target:
                    domains = self._fetch_and_extract(target, self.cfg["publish_url"])
            print(f"发布页解析到 {len(domains)} 个候选域名")
            return domains
        except Exception as e:
            print(f"解析发布页失败: {e}")
            return []

    def _find_meta_refresh(self, html):
        m = re.search(r'<meta[^>]+http-equiv=["\']?refresh["\']?[^>]+'
                      r'content=["\'][^"\']*url=([^"\'>\s]+)', html or "", re.I)
        return m.group(1).strip("'\"") if m else ""

    def _find_js_location(self, html):
        if not html:
            return ""
        for p in [r'window\.location(?:\.href)?\s*=\s*["\']([^"\']+)["\']',
                  r'document\.location(?:\.href)?\s*=\s*["\']([^"\']+)["\']',
                  r'location\.replace\(\s*["\']([^"\']+)["\']',
                  r'location\.assign\(\s*["\']([^"\']+)["\']']:
            m = re.search(p, html)
            if m:
                return m.group(1)
        return ""

    def _fetch_and_extract(self, target_url, base):
        try:
            if target_url.startswith("//"):
                target_url = "https:" + target_url
            elif target_url.startswith("/"):
                target_url = base.rstrip("/") + target_url
            elif not target_url.startswith("http"):
                return []
            r = requests.get(target_url, headers=self.headers, proxies=self.proxies,
                             timeout=self.cfg["probe_timeout"], allow_redirects=True)
            if r.status_code != 200:
                return []
            html = self._decode_publish(r.text, self.cfg["publish_decode"])
            return self._pick_domains(self.getpq(html), target_url)
        except Exception:
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

    # ================= 播放器解析 =================
    def _parse_players(self, doc, html=""):
        plist = []
        used_names = set()
        for idx, node in enumerate(doc(self.cfg["player_selector"]).items(), start=1):
            raw = node.attr(self.cfg["player_config_attr"])
            if not raw:
                continue
            try:
                cfg = json.loads(raw)
            except Exception:
                continue
            video = cfg.get("video", {}) or {}
            url = video.get("url2") or video.get("url", "")
            if not url:
                continue
            ep_name = ""
            try:
                parent = node.parents().eq(0)
                for _ in range(3):
                    if not parent:
                        break
                    h = (parent.find(self.cfg["player_heading_selector"]).eq(0).text() or "").strip()
                    if h:
                        ep_name = h
                        break
                    parent = parent.parents().eq(0)
            except Exception:
                pass
            base_name = ep_name or f"视频{idx}"
            name = base_name
            c = 2
            while name in used_names:
                name = f"{base_name} {c}"
                c += 1
            used_names.add(name)
            plist.append(f"{name}${url}")

        if not plist and html:
            for i, u in enumerate(re.findall(r'(https?://[^\s"\'<>]+\.m3u8[^\s"\'<>]*)', html), start=1):
                plist.append(f"视频{i}${u}")
        return plist

    # ================= 列表（按 article 解析 + PyQuery 提封面） =================
    def getlist(self, data, tid=""):
        videos = []
        seen = set()
        is_folder = bool(tid) and self.cfg["folder_id_marker"] in tid

        for art in data.items():
            # 跳过赞助广告卡片
            try:
                if 'rel="sponsored' in (art.html() or ""):
                    continue
            except Exception:
                pass

            # 标题：h2.post-card-title -> 第一个 h2 -> a[title]
            name = ""
            h2 = art("h2.post-card-title").eq(0)
            if not h2 or not h2.text():
                h2 = art("h2").eq(0)
            if h2 and h2.text():
                name = _clean(h2.text())
            if not name:
                at = art("a[title]").eq(0)
                if at:
                    name = (at.attr("title") or "").strip()
            if not name:
                continue

            # 文章链接：含 h2 的 a -> /archives/ -> 第一个 a
            href = ""
            for a in art("a[href]").items():
                h = (a.attr("href") or "").strip()
                if not h or h.startswith("#") or "javascript:" in h:
                    continue
                if a("h2") and a("h2").text():
                    href = h
                    break
            if not href:
                for a in art("a[href]").items():
                    h = (a.attr("href") or "").strip()
                    if "/archives/" in h:
                        href = h
                        break
            if not href:
                href = (art("a[href]").eq(0).attr("href") or "").strip()
            if not href or href in seen:
                continue
            seen.add(href)

            remark = (art("span[itemprop='datePublished']").text()
                      or art(".post-meta, .entry-meta, time").text() or "")

            videos.append({
                "vod_id": f"{href}{'@folder' if is_folder else ''}",
                "vod_name": name,
                "vod_pic": self._extract_pic(art),
                "vod_remarks": _clean(remark),
                "vod_tag": "folder" if is_folder else "",
                "style": self.cfg["style"],
            })
        return videos

    def _extract_pic(self, art):
        """多路径提封面：meta[itemprop=image] / img[data-pic] / img[src] / loadBannerDirect"""
        # 1. meta itemprop=image
        try:
            m = art('meta[itemprop="image"]').eq(0)
            if m:
                url = (m.attr("content") or "").strip()
                if url and "${" not in url:
                    return self._normalize_img(url)
        except Exception:
            pass
        # 2. img 的 data-pic / data-src / src
        try:
            for img in art("img").items():
                for attr in ("data-pic", "data-src", "data-original", "src"):
                    url = (img.attr(attr) or "").strip()
                    if url and "${" not in url and not url.startswith("data:"):
                        return self._normalize_img(url)
        except Exception:
            pass
        # 3. 51bl: loadBannerDirect('...')
        try:
            m = re.search(self.cfg["img_regex"], art.html() or "")
            if m:
                return self._normalize_img(m.group(1))
        except Exception:
            pass
        return ""

    def _normalize_img(self, url):
        url = (url or "").strip()
        if not url:
            return ""
        if url.startswith("//"):
            url = "https:" + url
        elif url.startswith("/"):
            url = self.host.rstrip("/") + url
        if self.cfg.get("img_proxy", False):
            return f"{self.getProxyUrl()}&url={url}&type=img"
        return url

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
        videos = []
        for i, x in enumerate(vdata("h2").items()):
            c = i * 2
            videos.append({
                "vod_id": p.eq(c)("a").attr("href"),
                "vod_name": p.eq(c).text(),
                "vod_pic": f"{self.getProxyUrl()}&url={p.eq(c + 1)('img').attr(self.cfg['folder_img_attr'])}&type=img",
                "vod_remarks": x.text(),
            })
        return videos

    def getimg(self, html):
        """兼容旧调用名"""
        return self._extract_pic(self.getpq(f"<article>{html}</article>").eq(0))

    def aesimg(self, word):
        cipher = AES.new(self.cfg["aes_key"], AES.MODE_CBC, self.cfg["aes_iv"])
        return unpad(cipher.decrypt(word), AES.block_size)

    def getpq(self, data):
        try:
            return pq(data)
        except Exception as e:
            print(f"{e}")
            return pq(data.encode("utf-8"))


# ==============  图片 CDN 加速  ==============
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
