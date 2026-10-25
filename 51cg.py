# ============================================================
# 通用发布页动态域名 Spider 模板（极简探测 + 多选择器轮询）
# ============================================================
import json
import re
import sys
from base64 import b64decode, b64encode
from urllib.parse import urlparse

import requests
from Crypto.Cipher import AES
from Crypto.Util.Padding import unpad
from pyquery import PyQuery as pq

sys.path.append('..')
from base.spider import Spider

SITE_CONFIG = {
    "name": "51通用模板",
    "play_from": "51通用模板",
    "style": {"type": "rect", "ratio": 1.33},

    # ============ 发布页入口（可以只放一个，也可以放多个） ============
    "entry_hosts": [
        "https://51cge21.com",
        "https://51cgf20.com/",
        "https://51cge22.com",
        "https://51cgf18.com/",
    ],

    # 发布页解码方式（解析器会自动兜底）
    "publish_decode": "js_base64",

    # ============ 首页/分类/搜索：多选择器轮询，命中即用 ============
    "home_list_selectors": [
        "#index article a",
        "#archive article a",
        ".post-list article a",
        ".entry-title a",
        ".post-title a",
        "article h2 a",
        "h2 a",
        ".item a",
        "a[rel='bookmark']",
    ],
    "category_selectors": [
        ".category-list ul li", ".nav-menu li", ".menu li", "nav ul li",
    ],
    "default_classes": [
        {"type_name": "首页", "type_id": "/"},
        {"type_name": "最新", "type_id": "/latest/"},
        {"type_name": "热门", "type_id": "/hot/"},
    ],
    "folder_id_marker": "/mrdg",

    "title_selector": ".post-title, .entry-title, h1",
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
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9",
        "Connection": "keep-alive",
        "Cache-Control": "no-cache",
    },
    "timeout": 15,
    "probe_timeout": 10,
}


class Spider(Spider):
    cfg = SITE_CONFIG

    def init(self, extend=""):
        try:
            self.proxies = json.loads(extend)
        except Exception:
            self.proxies = {}
        self.cfg = SITE_CONFIG
        self.headers = dict(self.cfg["headers"])
        self.host = self.get_working_host()
        self.headers.update({"Origin": self.host, "Referer": f"{self.host}/"})
        print(f"===== 最终使用站点: {self.host} =====")

    def getName(self):
        return SITE_CONFIG.get("name", "51爆料")

    def isVideoFormat(self, url):
        return any(ext in (url or "") for ext in [".m3u8", ".mp4", ".ts"])

    def manualVideoCheck(self):
        return False

    def destroy(self):
        pass

    # ================= 探测（极简版） =================
    def get_working_host(self):
        entry_hosts = self.cfg.get("entry_hosts", [])
        candidates, seen = [], set()

        def add(url):
            url = (url or "").rstrip("/") + "/"
            if url and url not in seen:
                seen.add(url)
                candidates.append(url)

        # 1. 从发布页解析
        for pub in entry_hosts:
            parsed = self._parse_publish_page(pub)
            print(f"[解析] 发布页 {pub} -> {len(parsed)} 个候选: {parsed}")
            for c in parsed:
                add(c)

        # 2. entry_hosts 本身也加入候选（有些配置本身就是目标站）
        for e in entry_hosts:
            add(e)

        print(f"[探测] 共 {len(candidates)} 个候选域名")

        # 3. 逐个探测
        for url in candidates:
            ok, reason = self._probe_site(url)
            print(f"[探测] {url} -> {'可用' if ok else '不可用'} ({reason})")
            if ok:
                return url

        print("[探测] 所有候选均不可用")
        return candidates[0] if candidates else ""

    def _probe_site(self, url):
        """极简探测：200 + 内容够长 + 不是发布页。返回 (bool, 原因)。"""
        try:
            r = requests.get(url, headers=self.headers, proxies=self.proxies,
                             timeout=self.cfg["probe_timeout"])
        except Exception as e:
            return False, f"请求异常: {type(e).__name__}"

        if r.status_code != 200:
            return False, f"HTTP {r.status_code}"

        html = r.text or ""
        if len(html) < 2000:
            return False, f"内容太短 {len(html)} 字节"

        # 发布页特征：同时出现"线路一""线路二"，说明这是导航页不是目标站
        if "线路一" in html and "线路二" in html:
            return False, "这是发布页，不是目标站"

        return True, f"OK, {len(html)} 字节"

    def _parse_publish_page(self, publish_url):
        """从发布页提取候选域名。"""
        try:
            r = requests.get(publish_url, headers=self.headers, proxies=self.proxies,
                             timeout=self.cfg["probe_timeout"])
            if r.status_code != 200:
                print(f"[解析] {publish_url} HTTP {r.status_code}")
                return []
            html = r.text

            mode = self.cfg.get("publish_decode", "plain")
            if mode in ("js_base64", "js_atob"):
                decoded = self._decode_publish(html, mode)
                if decoded and decoded != html:
                    html = decoded

            candidates, seen = [], set()
            doc = self.getpq(html)

            # <a href>
            for a in doc("a").items():
                self._add_candidate(a.attr("href"), publish_url, candidates, seen)

            # 正则兜底：所有 http URL
            for m in re.finditer(r'https?://[^\s"\'<>)]+', html):
                self._add_candidate(m.group(0), publish_url, candidates, seen)

            return candidates
        except Exception as e:
            print(f"[解析] {publish_url} 异常: {e}")
            return []

    def _add_candidate(self, href, base, candidates, seen):
        if not href:
            return
        href = href.strip()
        if href.startswith("//"):
            href = "https:" + href
        if not href.startswith("http") or "." not in href:
            return
        if any(x in href.lower() for x in ["javascript:", "mailto:", "#", "tel:"]):
            return
        lower = href.lower().split("?")[0].split("#")[0]
        if any(lower.endswith(ext) for ext in [
            ".css", ".js", ".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".svg",
            ".woff", ".woff2", ".ttf", ".eot", ".mp4", ".m3u8", ".ts", ".json", ".xml",
        ]):
            return
        try:
            parsed = urlparse(href)
            if not parsed.netloc:
                return
            # 只保留根域名
            host_url = f"{parsed.scheme}://{parsed.netloc}/"
        except Exception:
            return
        if host_url not in seen:
            seen.add(host_url)
            candidates.append(host_url)

    def _decode_publish(self, text, mode):
        if mode == "js_base64":
            m = re.search(r"Base64\.decode\(['\"]([^'\"]+)['\"]\)", text)
            if m:
                try:
                    return b64decode(m.group(1)).decode("utf-8", "ignore")
                except Exception:
                    pass
            return text
        if mode == "js_atob":
            m = re.search(r"atob\(['\"]([^'\"]+)['\"]\)", text)
            if m:
                try:
                    return b64decode(m.group(1)).decode("utf-8", "ignore")
                except Exception:
                    pass
            return text
        return text

    # ================= 首页 / 列表（多选择器轮询） =================
    def _find_list(self, doc):
        """依次尝试 home_list_selectors，返回 (选择器, 结果集)。"""
        for sel in self.cfg.get("home_list_selectors", []):
            items = doc(sel)
            if items and len(items) > 0:
                return sel, items
        return None, None

    def homeContent(self, filter):
        try:
            r = requests.get(self.host, headers=self.headers, proxies=self.proxies,
                             timeout=self.cfg["timeout"])
            if r.status_code != 200:
                print(f"[首页] HTTP {r.status_code}")
                return {"class": [], "list": []}

            doc = self.getpq(r.text)
            classes = []
            for selector in self.cfg["category_selectors"]:
                for item in doc(selector).items():
                    a = item("a")
                    href = (a.attr("href") or "").strip()
                    name = (a.text() or "").strip()
                    if href and href != "#" and name:
                        classes.append({"type_name": name, "type_id": href})
                if classes:
                    break
            if not classes:
                classes = list(self.cfg["default_classes"])

            sel, items = self._find_list(doc)
            print(f"[首页] 列表选择器命中: {sel}, 数量: {len(items) if items else 0}")
            videos = self.getlist(items) if items else []

            return {"class": classes, "list": videos}
        except Exception as e:
            print(f"homeContent error: {e}")
            return {"class": [], "list": []}

    def homeVideoContent(self):
        try:
            r = requests.get(self.host, headers=self.headers, proxies=self.proxies,
                             timeout=self.cfg["timeout"])
            if r.status_code != 200:
                return {"list": []}
            doc = self.getpq(r.text)
            sel, items = self._find_list(doc)
            return {"list": self.getlist(items) if items else []}
        except Exception as e:
            print(f"homeVideoContent error: {e}")
            return {"list": []}

    def categoryContent(self, tid, pg, filter, extend):
        try:
            if "@folder" in tid:
                videos = self.getfod(tid.replace("@folder", ""))
                return {"list": videos, "page": pg, "pagecount": 1,
                        "limit": 90, "total": len(videos)}
            pg = int(pg)
            tid = tid.rstrip("/")
            url = f"{self.host}{tid}/{pg}/" if pg > 1 else f"{self.host}{tid}/"
            r = requests.get(url, headers=self.headers, proxies=self.proxies,
                             timeout=self.cfg["timeout"])
            if r.status_code != 200:
                return {"list": [], "page": pg, "pagecount": 1, "limit": 90, "total": 0}
            doc = self.getpq(r.text)
            sel, items = self._find_list(doc)
            videos = self.getlist(items, tid) if items else []
            print(f"[分类] {tid} pg={pg} 选择器={sel} 数量={len(videos)}")
            return {"list": videos, "page": pg, "pagecount": 99999 if videos else 1,
                    "limit": 90, "total": len(videos) if not videos else 999999}
        except Exception as e:
            print(f"categoryContent error: {e}")
            return {"list": [], "page": pg, "pagecount": 1, "limit": 90, "total": 0}

    def searchContent(self, key, quick, pg="1"):
        try:
            tpl = self.cfg["search_url_tpl_paged"] if str(pg) != "1" else self.cfg["search_url_tpl"]
            url = tpl.format(host=self.host, key=key, pg=pg)
            r = requests.get(url, headers=self.headers, proxies=self.proxies,
                             timeout=self.cfg["timeout"])
            if r.status_code != 200:
                return {"list": [], "page": pg}
            doc = self.getpq(r.text)
            sel, items = self._find_list(doc)
            return {"list": self.getlist(items) if items else [], "page": pg}
        except Exception as e:
            print(f"searchContent error: {e}")
            return {"list": [], "page": pg}

    # ================= 详情 =================
    def detailContent(self, ids):
        try:
            raw_id = ids[0] if ids else ""
            url = raw_id if raw_id.startswith("http") else f"{self.host}{raw_id}"
            r = requests.get(url, headers=self.headers, proxies=self.proxies,
                             timeout=self.cfg["timeout"])
            if r.status_code != 200:
                return {"list": [{"vod_play_from": self.cfg["play_from"],
                                  "vod_play_url": f"页面加载失败${url}"}]}

            doc = self.getpq(r.text)

            main_vod = {"vod_play_from": self.cfg["play_from"]}
            try:
                clist = []
                tag_sel = self.cfg["tag_selector"]
                if tag_sel and doc(tag_sel):
                    for k in doc(tag_sel).items():
                        title, href = k.text(), k.attr("href")
                        if title and href:
                            clist.append(
                                "[a=cr:" + json.dumps({"id": href, "name": title}) + "/]"
                                + title + "[/a]"
                            )
                main_vod["vod_content"] = " ".join(clist) if clist else doc(self.cfg["title_selector"]).text()
            except Exception:
                main_vod["vod_content"] = doc(self.cfg["title_selector"]).text() or self.cfg["name"]

            try:
                plist = self._parse_players(doc)
                print(f"[详情] 解析到 {len(plist)} 个播放源")
                main_vod["vod_play_url"] = "#".join(plist) if plist else f"未找到视频源${url}"
            except Exception as e:
                print(f"[详情] 播放器解析异常: {e}")
                main_vod["vod_play_url"] = f"视频解析失败${url}"

            # ---------- 关联播放挂载点 ----------
            # related_vods = [...]  ← 用 02.txt 的逻辑替换这一行
            related_vods = []

            return {"list": [main_vod] + related_vods}

        except Exception as e:
            print(f"detailContent error: {e}")
            return {"list": [{"vod_play_from": self.cfg["play_from"],
                              "vod_play_url": f"详情页加载失败${ids[0] if ids else ''}"}]}

    # ================= 播放 / 代理 / 工具 =================
    def playerContent(self, flag, id, vipFlags):
        url, p = id, 1
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
        y = requests.get(url, headers=self.headers, proxies=self.proxies, allow_redirects=False)
        data = y.content.decode("utf-8")
        if y.headers.get("Location"):
            url = y.headers["Location"]
            data = requests.get(url, headers=self.headers, proxies=self.proxies).content.decode("utf-8")
        lines = data.strip().split("\n")
        last_r = url[:url.rfind("/")]
        durl = urlparse(url).scheme + "://" + urlparse(url).netloc
        iskey = True
        for i, s in enumerate(lines):
            if iskey and "URI" in s:
                m = re.search(r'URI="([^"]*)"', s)
                if m:
                    lines[i] = re.sub(r'URI="([^"]*)"', f'URI="{self.proxy(m.group(1), "mkey")}"', s)
                    iskey = False
                    continue
            if "#EXT" not in s:
                if "http" not in s:
                    domain = last_r if s.count("/") < 2 else durl
                    s = domain + ("" if s.startswith("/") else "/") + s
                lines[i] = self.proxy(s, s.split(".")[-1].split("?")[0])
        return [200, "application/vnd.apple.mpegur", "\n".join(lines)]

    def tsProxy(self, url):
        data = requests.get(self.d64(url), headers=self.headers,
                            proxies=self.proxies, stream=True)
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
        sel, attr = self.cfg["player_selector"], self.cfg["player_config_attr"]
        if not doc(sel):
            return plist
        for idx, node in enumerate(doc(sel).items(), 1):
            raw = node.attr(attr)
            if not raw:
                continue
            try:
                cfg = json.loads(raw)
            except Exception:
                continue
            vurl = cfg.get("video", {}).get("url", "")
            if not vurl:
                continue
            ep = ""
            try:
                parent = node.parents().eq(0)
                for _ in range(3):
                    if not parent:
                        break
                    h = (parent.find(self.cfg["player_heading_selector"]).eq(0).text() or "").strip()
                    if h:
                        ep = h
                        break
                    parent = parent.parents().eq(0)
            except Exception:
                pass
            base = ep or f"视频{idx}"
            name, c = base, 2
            while name in used:
                name, c = f"{base} {c}", c + 1
            used.add(name)
            plist.append(f"{name}${vurl}")
        return plist

    def getlist(self, items, tid=""):
        videos = []
        if not items:
            return videos
        is_folder = self.cfg["folder_id_marker"] in (tid or "")
        for k in items.items():
            href = k.attr("href")
            name = (k("h2").text() or k.text() or "").strip()
            if not (href and name):
                continue
            name = name.replace("\n", " ").strip()
            if len(name) > 80:
                name = name[:80]
            remark = (k("span[itemprop='datePublished']").text()
                      or k(".post-meta, .entry-meta, time").text())
            videos.append({
                "vod_id": f"{href}{'@folder' if is_folder else ''}",
                "vod_name": name,
                "vod_pic": self.getimg(k("script").text()),
                "vod_remarks": (remark or "").strip(),
                "vod_tag": "folder" if is_folder else "",
                "style": self.cfg["style"],
            })
        return videos

    def getfod(self, folder_id):
        url = f"{self.host}{folder_id}"
        r = requests.get(url, headers=self.headers, proxies=self.proxies,
                         timeout=self.cfg["timeout"])
        doc = self.getpq(r.text)
        vdata = doc(self.cfg["folder_content_selector"])
        for sel in self.cfg["folder_remove_selectors"]:
            vdata.remove(sel)
        p, img_attr, videos = vdata("p"), self.cfg["folder_img_attr"], []
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
        except Exception:
            return pq(data.encode("utf-8"))


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
    BaseSpider.register(Spider())
