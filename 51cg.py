# ============================================================
# 51吃瓜 Spider —— 发布页 → 中转域名 → 跟随302/JS → 最终目标站
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
    "name": "51吃瓜",
    "play_from": "51吃瓜",
    "style": {"type": "rect", "ratio": 1.33},

    # ============ 发布页入口（默认一个，可自行加多个） ============
    "publish_urls": [
        "https://51cge21.com",
    ],

    # ============ 列表提取（多策略轮询） ============
    "home_list_selectors": [
        "#index article a",
        "#archive article a",
        "article h2 a",
        "article a",
        ".post-list a",
        ".entry-title a",
    ],

    # 万能提取：href 匹配任一即视为文章链接
    "article_href_patterns": [
        r"/mrdg\d+",
        r"/\d+\.html",
        r"/post/\d+",
        r"/archives/\d+",
    ],

    # ============ 详情 / 播放器 ============
    "title_selector": ".post-title, .entry-title, h1",
    "player_selector": ".dplayer",
    "player_config_attr": "data-config",
    "player_heading_selector": "h2, h3, h4",

    # ============ 图片 / AES ============
    "img_regex": r"loadBannerDirect\('([^']+)'",
    "aes_key": b"f5d965df75336270",
    "aes_iv": b"97b60394abc2fbe1",

    # ============ 搜索 ============
    "search_url_tpl": "{host}/search/{key}/",
    "search_url_tpl_paged": "{host}/search/{key}/{pg}/",

    "headers": {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                      "AppleWebKit/537.36 (KHTML, like Gecko) "
                      "Chrome/134.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9",
        "Connection": "keep-alive",
    },
    "timeout": 15,
    "probe_timeout": 15,
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
        if self.host:
            self.headers.update({"Origin": self.host, "Referer": f"{self.host}/"})
        print(f"===== 最终使用站点: {self.host} =====")

    def getName(self):
        return SITE_CONFIG.get("name", "51吃瓜")

    def isVideoFormat(self, url):
        return any(ext in (url or "") for ext in [".m3u8", ".mp4", ".ts"])

    def manualVideoCheck(self):
        return False

    def destroy(self):
        pass

    # ================= 核心：解析发布页 + 跟随跳转到最终目标站 =================
    def get_working_host(self):
        publish_urls = self.cfg.get("publish_urls", [])
        all_cands, seen = [], set()

        def add(u):
            u = (u or "").rstrip("/") + "/"
            if u and u not in seen:
                seen.add(u)
                all_cands.append(u)

        print(f"\n===== [1/3] 解析发布页 =====")
        for pub in publish_urls:
            try:
                r = requests.get(pub, headers=self.headers, proxies=self.proxies,
                                 timeout=self.cfg["probe_timeout"], allow_redirects=True)
            except Exception as e:
                print(f"[发布页] {pub} 请求失败: {type(e).__name__}: {e}")
                continue
            print(f"[发布页] {pub} -> {r.url}, HTTP {r.status_code}, 长度 {len(r.text)}")
            if r.status_code != 200:
                continue
            for c in self._extract_candidates(r.text, r.url):
                add(c)

        print(f"[发布页] 汇总候选: {all_cands}")
        if not all_cands:
            return ""

        print(f"\n===== [2/3] 解析中转域名（跟随 302/JS 跳转） =====")
        for url in all_cands:
            final_url, final_html = self._resolve_redirect(url)
            if not final_url:
                continue
            # 排除仍是发布页
            if "线路一" in final_html and "线路二" in final_html:
                print(f"[中转] {final_url} 仍是发布页，跳过")
                continue
            if len(final_html) < 3000:
                print(f"[中转] {final_url} 内容太短（{len(final_html)}），跳过")
                continue
            try:
                p = urlparse(final_url)
                host = f"{p.scheme}://{p.netloc}"
            except Exception:
                host = final_url.rstrip("/")
            print(f"[采用] 最终目标站: {host}")
            return host

        print("[中转] 所有候选不可用")
        return ""

    def _resolve_redirect(self, url, max_hops=5):
        """跟随 HTTP 302 和 JS/meta 跳转，返回 (最终URL, 最终HTML)。"""
        current = url
        last_html = ""
        for hop in range(max_hops):
            try:
                r = requests.get(current, headers=self.headers, proxies=self.proxies,
                                 timeout=self.cfg["probe_timeout"], allow_redirects=True)
            except Exception as e:
                print(f"[跳转] hop{hop} 请求失败 {current}: {type(e).__name__}: {e}")
                return current, last_html

            final_url = r.url
            html = r.text or ""
            last_html = html
            print(f"[跳转] hop{hop}: {current} -> {final_url}, HTTP {r.status_code}, 长度 {len(html)}")

            if r.status_code != 200:
                return final_url, html

            js_target = self._extract_js_redirect(html)
            if js_target:
                if js_target.startswith("//"):
                    js_target = "https:" + js_target
                elif js_target.startswith("/"):
                    p = urlparse(final_url)
                    js_target = f"{p.scheme}://{p.netloc}{js_target}"
                if js_target != final_url and js_target != current:
                    print(f"[跳转] hop{hop} 发现 JS/meta 跳转 -> {js_target}")
                    current = js_target
                    continue

            return final_url, html

        return current, last_html

    def _extract_js_redirect(self, html):
        """提取 JS / meta 跳转目标。"""
        if not html:
            return None
        doc = self.getpq(html)
        # meta refresh
        for m in doc("meta").items():
            if (m.attr("http-equiv") or "").lower() == "refresh":
                content = m.attr("content") or ""
                match = re.search(r'url\s*=\s*["\']?([^"\';\s>]+)', content, re.I)
                if match:
                    return match.group(1).strip().strip("'\"")
        # JS 跳转
        for p in [
            r'location\.href\s*=\s*["\']([^"\']+)["\']',
            r'location\.replace\s*\(\s*["\']([^"\']+)["\']',
            r'window\.location\s*=\s*["\']([^"\']+)["\']',
            r'location\.assign\s*\(\s*["\']([^"\']+)["\']',
        ]:
            m = re.search(p, html, re.I)
            if m:
                return m.group(1).strip()
        return None

    def _extract_candidates(self, html, base):
        cands, seen = [], set()

        def add(href):
            if not href:
                return
            href = href.strip()
            if href.startswith("//"):
                href = "https:" + href
            if not href.startswith("http") or "." not in href:
                return
            if any(x in href.lower() for x in ["javascript:", "mailto:", "#"]):
                return
            low = href.lower().split("?")[0].split("#")[0]
            if any(low.endswith(ext) for ext in [
                ".css", ".js", ".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".svg",
                ".woff", ".woff2", ".ttf", ".mp4", ".m3u8", ".ts", ".json", ".xml",
            ]):
                return
            try:
                p = urlparse(href)
                if not p.netloc:
                    return
                root = f"{p.scheme}://{p.netloc}/"
            except Exception:
                return
            if root not in seen:
                seen.add(root)
                cands.append(root)

        doc = self.getpq(html)
        for a in doc("a").items():
            add(a.attr("href"))
        for m in re.finditer(r'https?://[^\s"\'<>)]+', html):
            add(m.group(0))
        return cands

    # ================= 首页 / 列表 =================
    def homeContent(self, filter):
        try:
            r = requests.get(self.host, headers=self.headers, proxies=self.proxies,
                             timeout=self.cfg["timeout"], allow_redirects=True)
            if r.status_code != 200:
                print(f"[首页] HTTP {r.status_code}")
                return {"class": [], "list": []}
            # 首页若再次跳转，更新 host
            if r.url and not r.url.startswith(self.host):
                p = urlparse(r.url)
                new_host = f"{p.scheme}://{p.netloc}"
                print(f"[首页] 再次跳转 {self.host} -> {new_host}，已更新")
                self.host = new_host
                self.headers.update({"Origin": self.host, "Referer": f"{self.host}/"})

            doc = self.getpq(r.text)
            print(f"\n===== [3/3] 首页列表提取 =====")
            classes = [
                {"type_name": "首页", "type_id": "/"},
                {"type_name": "最新", "type_id": "/latest/"},
                {"type_name": "热门", "type_id": "/hot/"},
            ]
            videos = self._extract_videos(doc)
            print(f"[首页] 提取到 {len(videos)} 个视频")
            if videos:
                print(f"[首页] 前3个: {[v['vod_name'] for v in videos[:3]]}")
                print(f"[首页] 第一个 vod_id: {videos[0]['vod_id']}")
            return {"class": classes, "list": videos}
        except Exception as e:
            print(f"homeContent error: {e}")
            return {"class": [], "list": []}

    def homeVideoContent(self):
        return self.homeContent(False)

    def _extract_videos(self, doc):
        for sel in self.cfg["home_list_selectors"]:
            items = doc(sel)
            if items and len(items) > 0:
                videos = self._items_to_videos(items)
                if videos:
                    print(f"[首页] 选择器 {sel} 命中 {len(videos)} 个")
                    return videos

        print(f"[首页] 已知选择器全部失效，启用万能提取")
        patterns = [re.compile(p) for p in self.cfg["article_href_patterns"]]
        videos, seen = [], set()
        for a in doc("a").items():
            href = (a.attr("href") or "").strip()
            if not href or href in seen:
                continue
            if not any(p.search(href) for p in patterns):
                continue
            name = (a("h2").text() or a.attr("title") or a.text() or "").strip()
            name = name.replace("\n", " ").strip()
            if len(name) < 2 or len(name) > 100:
                continue
            seen.add(href)
            videos.append({
                "vod_id": href, "vod_name": name, "vod_pic": "",
                "vod_remarks": "", "style": self.cfg["style"],
            })
        if videos:
            print(f"[首页] 万能提取到 {len(videos)} 个")
        else:
            sample = []
            for a in doc("a").items():
                h = a.attr("href")
                if h and len(sample) < 15:
                    sample.append(h)
            print(f"[首页] 万能提取也为 0，前15个 href: {sample}")
        return videos

    def _items_to_videos(self, items):
        videos = []
        for k in items.items():
            href = k.attr("href")
            name = (k("h2").text() or k.attr("title") or k.text() or "").strip()
            name = name.replace("\n", " ").strip()
            if href and name:
                videos.append({
                    "vod_id": href, "vod_name": name,
                    "vod_pic": self.getimg(k("script").text()),
                    "vod_remarks": (k(".post-meta, .entry-meta, time").text() or "").strip(),
                    "style": self.cfg["style"],
                })
        return videos

    def categoryContent(self, tid, pg, filter, extend):
        try:
            pg = int(pg)
            tid = tid.rstrip("/")
            url = f"{self.host}{tid}/{pg}/" if pg > 1 else f"{self.host}{tid}/"
            r = requests.get(url, headers=self.headers, proxies=self.proxies,
                             timeout=self.cfg["timeout"], allow_redirects=True)
            if r.status_code != 200:
                return {"list": [], "page": pg, "pagecount": 1, "limit": 90, "total": 0}
            doc = self.getpq(r.text)
            videos = self._extract_videos(doc)
            return {"list": videos, "page": pg,
                    "pagecount": 99999 if videos else 1,
                    "limit": 90, "total": len(videos) if not videos else 999999}
        except Exception as e:
            print(f"categoryContent error: {e}")
            return {"list": [], "page": pg, "pagecount": 1, "limit": 90, "total": 0}

    def searchContent(self, key, quick, pg="1"):
        try:
            tpl = self.cfg["search_url_tpl_paged"] if str(pg) != "1" else self.cfg["search_url_tpl"]
            url = tpl.format(host=self.host, key=key, pg=pg)
            r = requests.get(url, headers=self.headers, proxies=self.proxies,
                             timeout=self.cfg["timeout"], allow_redirects=True)
            if r.status_code != 200:
                return {"list": [], "page": pg}
            doc = self.getpq(r.text)
            return {"list": self._extract_videos(doc), "page": pg}
        except Exception as e:
            print(f"searchContent error: {e}")
            return {"list": [], "page": pg}

    def detailContent(self, ids):
        try:
            raw_id = ids[0] if ids else ""
            url = raw_id if raw_id.startswith("http") else f"{self.host}{raw_id}"
            r = requests.get(url, headers=self.headers, proxies=self.proxies,
                             timeout=self.cfg["timeout"], allow_redirects=True)
            if r.status_code != 200:
                return {"list": [{"vod_play_from": self.cfg["play_from"],
                                  "vod_play_url": f"页面加载失败${url}"}]}

            doc = self.getpq(r.text)
            main_vod = {"vod_play_from": self.cfg["play_from"]}
            main_vod["vod_content"] = doc(self.cfg["title_selector"]).text() or self.cfg["name"]

            try:
                plist = self._parse_players(doc)
                print(f"[详情] 解析到 {len(plist)} 个播放源")
                main_vod["vod_play_url"] = "#".join(plist) if plist else f"未找到视频源${url}"
            except Exception as e:
                print(f"[详情] 播放器解析异常: {e}")
                main_vod["vod_play_url"] = f"视频解析失败${url}"

            related_vods = []  # ← 用 02.txt 的关联逻辑替换这一行

            return {"list": [main_vod] + related_vods}
        except Exception as e:
            print(f"detailContent error: {e}")
            return {"list": [{"vod_play_from": self.cfg["play_from"],
                              "vod_play_url": f"详情页加载失败${ids[0] if ids else ''}"}]}

    # ================= 播放 / 代理 =================
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
            res = requests.get(param["url"], headers=self.headers, proxies=self.proxies, timeout=10)
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
        data = requests.get(self.d64(url), headers=self.headers, proxies=self.proxies, stream=True)
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
            name, c = f"视频{idx}", 2
            while name in used:
                name, c = f"视频{idx} {c}", c + 1
            used.add(name)
            plist.append(f"{name}${vurl}")
        return plist

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


if __name__ == '__main__':
    from base.spider import Spider as BaseSpider
    BaseSpider.register(Spider())
