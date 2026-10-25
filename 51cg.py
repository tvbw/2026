# ============================================================
# 通用发布页动态域名 Spider 模板（无 fallback，纯发布页驱动）
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

    # ============ 唯一入口：发布页域名（按可靠性降序） ============
    # 每个域名会同时被：
    #   (1) 当发布页解析，提取候选目标域名
    #   (2) 当候选站点直接探测（兼容某个 entry_host 本身就是目标站）
    # 不再有 fallback_hosts。只要有一个 entry_host 活着且能解析出目标域名，就能工作。
    "entry_hosts": [
        "https://51cge21.com",
        "https://51cgf20.com/",
        "https://51cge22.com",
        "https://51cgf18.com/",
        "https://51cgf20.com/",
    ],

    # 优先尝试的解码方式（解析器会自动 fallback 到其它策略，非必须）
    # js_base64 / js_atob / plain
    "publish_decode": "js_base64",

    # 判断“候选域名是不是目标站”的特征选择器
    "host_check_selector": "#index article a",

    # 调试开关：true 时打印发布页解析细节（上线后可关）
    "debug_publish": True,

    "list_selector": "#index article a, #archive article a",
    "home_list_selector": "#index article a",
    "category_selectors": [
        ".category-list ul li", ".nav-menu li", ".menu li", "nav ul li",
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
        print(f"使用站点: {self.host}")

    def getName(self):
        return SITE_CONFIG.get("name", "51爆料")

    def isVideoFormat(self, url):
        return any(ext in (url or "") for ext in [".m3u8", ".mp4", ".ts"])

    def manualVideoCheck(self):
        return False

    def destroy(self):
        pass

    # ================= 域名探测（纯发布页驱动，无 fallback） =================
    def get_working_host(self):
        entry_hosts = self.cfg.get("entry_hosts", [])
        if not entry_hosts:
            print("entry_hosts 为空，无法探测")
            return ""

        all_candidates, seen = [], set()

        def add(url):
            if url and url not in seen:
                seen.add(url)
                all_candidates.append(url)

        # 1. 从每个 entry_host 解析发布页，提取候选目标域名
        for pub_url in entry_hosts:
            cands = self._parse_publish_page(pub_url)
            if self.cfg.get("debug_publish"):
                print(f"[debug] 发布页 {pub_url} 解析到 {len(cands)} 个候选: {cands[:5]}")
            for c in cands:
                add(c)

        # 2. entry_hosts 本身也作为候选（有些“发布页”其实就是目标站）
        for url in entry_hosts:
            add(url)

        # 3. 逐个探测
        for url in all_candidates:
            if self._probe_site(url):
                print(f"可用站点: {url}")
                return url

        # 4. 全部失败：返回第一个 entry_host，让请求自然失败。
        #    不静默兜底，用户能在日志/异常里看到问题，知道需要更新 entry_hosts。
        print("所有候选域名均不可用，请更新 entry_hosts")
        return entry_hosts[0]

    def _probe_site(self, url):
        try:
            r = requests.get(url, headers=self.headers, proxies=self.proxies,
                             timeout=self.cfg["probe_timeout"])
            return r.status_code == 200 and bool(
                self.getpq(r.text)(self.cfg["host_check_selector"])
            )
        except Exception:
            return False

    def _parse_publish_page(self, publish_url):
        """多策略鲁棒解析发布页，返回候选目标域名列表（scheme://host/ 形式）。"""
        try:
            r = requests.get(publish_url, headers=self.headers, proxies=self.proxies,
                             timeout=self.cfg["probe_timeout"])
            if r.status_code != 200:
                if self.cfg.get("debug_publish"):
                    print(f"[debug] {publish_url} HTTP {r.status_code}")
                return []
            html = r.text
            if self.cfg.get("debug_publish"):
                print(f"[debug] {publish_url} HTML 长度 {len(html)}")

            # 先尝试配置指定的解码方式
            mode = self.cfg.get("publish_decode", "plain")
            if mode in ("js_base64", "js_atob"):
                decoded = self._decode_publish(html, mode)
                if decoded and decoded != html:
                    html = decoded
                    if self.cfg.get("debug_publish"):
                        print(f"[debug] 解码后 HTML 长度 {len(html)}")

            candidates, seen = [], set()
            doc = self.getpq(html)

            # 策略 A：<a href>
            for a in doc("a").items():
                self._add_candidate(a.attr("href"), publish_url, candidates, seen)

            # 策略 B：<meta http-equiv="refresh">
            for m in doc("meta").items():
                if (m.attr("http-equiv") or "").lower() == "refresh":
                    content = m.attr("content") or ""
                    match = re.search(r'url=([^;]+)', content, re.I)
                    if match:
                        self._add_candidate(match.group(1).strip(), publish_url, candidates, seen)

            # 策略 C：JS 跳转 / 变量
            for pattern in [
                r'(?:location\.href|window\.location|location\.replace|location)\s*[=(]\s*["\']([^"\']+)["\']',
                r'window\.open\(["\']([^"\']+)["\']',
                r'(?:var|let|const)\s+\w*(?:url|host|domain|site)\w*\s*=\s*["\']([^"\']+)["\']',
            ]:
                for match in re.finditer(pattern, html, re.I):
                    self._add_candidate(match.group(1), publish_url, candidates, seen)

            # 策略 D：直接正则提取所有 http URL（过滤静态资源）
            for match in re.finditer(r'https?://[^\s"\'<>)]+', html):
                self._add_candidate(match.group(0), publish_url, candidates, seen)

            return candidates
        except Exception as e:
            if self.cfg.get("debug_publish"):
                print(f"[debug] 解析 {publish_url} 异常: {e}")
            return []

    def _add_candidate(self, href, base, candidates, seen):
        if not href:
            return
        href = href.strip()
        if href.startswith("//"):
            href = "https:" + href
        if href.startswith("/") and base:
            href = base.rstrip("/") + href
        if not href.startswith("http") or "." not in href:
            return
        if any(x in href.lower() for x in ["javascript:", "mailto:", "#", "tel:"]):
            return
        # 过滤静态资源
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

    # ================= 首页 / 分类 / 搜索（与原版一致） =================
    def homeContent(self, filter):
        try:
            r = requests.get(self.host, headers=self.headers, proxies=self.proxies,
                             timeout=self.cfg["timeout"])
            if r.status_code != 200:
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
            return {"class": classes,
                    "list": self.getlist(doc(self.cfg["home_list_selector"]))}
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
            return {"list": self.getlist(doc(self.cfg["list_selector"]))}
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
            videos = self.getlist(doc(self.cfg["list_selector"]), tid)
            total_pages = 1
            page_info = doc(".pagination .pages, .page-nav, .pagenavi").text()
            if "共" in page_info and "页" in page_info:
                try:
                    total_pages = int(page_info.split("共")[-1].split("页")[0])
                except Exception:
                    pass
            has_next = bool(doc(
                'a.next, .pagination a.next, .pagenavi .next, a:contains("下一页")'
            ).attr("href"))
            return {"list": videos, "page": pg,
                    "pagecount": total_pages if total_pages > 1 else (99999 if has_next else pg),
                    "limit": 90, "total": 999999 if has_next else len(videos)}
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
            return {"list": self.getlist(doc(self.cfg["list_selector"])), "page": pg}
        except Exception as e:
            print(f"searchContent error: {e}")
            return {"list": [], "page": pg}

    # ================= 详情（关联播放挂载点） =================
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

            # ---------- 主视频 ----------
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
                main_vod["vod_play_url"] = "#".join(plist) if plist else f"未找到视频源${url}"
            except Exception:
                main_vod["vod_play_url"] = f"视频解析失败${url}"

            # ---------- 关联播放 ----------
            # ★ 把 02.txt 里生成关联视频列表的代码粘贴到这里，赋给 related_vods。
            #   每个元素是 dict：{"vod_id": ..., "vod_name": ..., "vod_pic": ...}
            #   FongMi 会把 related_vods 渲染成详情页下方的关联卡片。
            #
            # related_vods = [
            #     {"vod_id": "...", "vod_name": "...", "vod_pic": "..."},
            #     ...
            # ]
            related_vods = []   # ← 用 02.txt 的逻辑替换这一行

            return {"list": [main_vod] + related_vods}

        except Exception as e:
            print(f"detailContent error: {e}")
            return {"list": [{"vod_play_from": self.cfg["play_from"],
                              "vod_play_url": f"详情页加载失败${ids[0] if ids else ''}"}]}

    # ================= 播放 / 代理 / 工具（保持不变） =================
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

    def getlist(self, data, tid=""):
        videos = []
        is_folder = self.cfg["folder_id_marker"] in (tid or "")
        for k in data.items():
            href, name = k.attr("href"), k("h2").text()
            if not (href and name):
                continue
            remark = (k("span[itemprop='datePublished']").text()
                      or k(".post-meta, .entry-meta, time").text())
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


# ============== 万能一键加速（保留） ==============
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
