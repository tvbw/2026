# ============================================================
# 51吃瓜 Spider —— 二级域名轮询 + 详情页关联推荐
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

    # ============ 二级域名（直接轮询，按可靠性降序） ============
    "site_hosts": [
        "https://album.hhhepogu.cc/",
        "https://battle.hhhepogu.cc/",
        "https://black.hhhepogu.cc/",
    ],

    # 判断“是不是目标站”的特征选择器（命中即认为可用）
    "host_check_selector": "#index article a",

    # ============ 列表 / 分类 ============
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

    # ============ 详情 / 播放器 ============
    "title_selector": ".post-title",
    "tag_selector": ".tags .keywords a",
    "player_selector": ".dplayer",
    "player_config_attr": "data-config",
    "player_heading_selector": "h2, h3, h4",

    # ============ 关联推荐 ============
    # 第 1 优先级：这些选择器命中的 <a> 直接当关联视频
    "related_selectors": [
        ".related-posts a",
        ".related a",
        ".recommend-list a",
        ".post-related a",
        ".related-content a",
        ".widget_related a",
    ],
    # 第 2 优先级（万能提取）：href 匹配任一即视为文章链接
    "article_href_patterns": [
        r"/mrdg\d+",
        r"/\d+\.html",
        r"/post/\d+",
        r"/archives/\d+",
    ],
    # 关联视频最大条数（FongMi 详情页下方会显示这些卡片）
    "related_limit": 10,

    # ============ 合集 ============
    "folder_content_selector": ".post-content[itemprop='articleBody']",
    "folder_remove_selectors": [".txt-apps", ".line", "blockquote", ".tags", ".content-tabs"],
    "folder_img_attr": "data-xkrkllgl",

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
        "Cache-Control": "no-cache",
    },
    "timeout": 15,
    "probe_timeout": 10,
}


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
        if self.host:
            self.headers.update({"Origin": self.host, "Referer": f"{self.host}/"})
        print(f"===== 使用站点: {self.host} =====")

    def getName(self):
        return SITE_CONFIG.get("name", "51爆料")

    def isVideoFormat(self, url):
        return any(ext in (url or "") for ext in [".m3u8", ".mp4", ".ts"])

    def manualVideoCheck(self):
        return False

    def destroy(self):
        pass

    # ================= 域名探测（纯二级域名轮询） =================
    def get_working_host(self):
        for url in self.cfg.get("site_hosts", []):
            if self._probe_site(url):
                print(f"探测通过: {url}")
                return url
        fallback = self.cfg["site_hosts"][0] if self.cfg.get("site_hosts") else ""
        print(f"所有域名不可用，使用第一个: {fallback}")
        return fallback

    def _probe_site(self, url):
        try:
            r = requests.get(url, headers=self.headers, proxies=self.proxies,
                             timeout=self.cfg["probe_timeout"])
            return r.status_code == 200 and bool(
                self.getpq(r.text)(self.cfg["host_check_selector"])
            )
        except Exception:
            return False

    # ================= 首页 / 分类 / 搜索（保持原样） =================
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

    # ================= 详情（主视频 + 关联推荐卡片） =================
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

            # ---------- 主视频 vod ----------
            vod = {"vod_play_from": self.cfg["play_from"]}
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
                vod["vod_content"] = " ".join(clist) if clist else doc(self.cfg["title_selector"]).text()
            except Exception:
                vod["vod_content"] = doc(self.cfg["title_selector"]).text() or self.cfg["name"]

            try:
                plist = self._parse_players(doc)
                vod["vod_play_url"] = "#".join(plist) if plist else f"未找到视频源${url}"
            except Exception:
                vod["vod_play_url"] = f"视频解析失败${url}"

            # ---------- 关联推荐（8-10 条卡片） ----------
            related_vods = self._extract_related_videos(doc, url)

            return {"list": [vod] + related_vods}
        except Exception as e:
            print(f"detailContent error: {e}")
            return {"list": [{"vod_play_from": self.cfg["play_from"],
                              "vod_play_url": f"详情页加载失败${ids[0] if ids else ''}"}]}

    def _extract_related_videos(self, doc, current_url):
        """从详情页提取 8-10 条关联视频，返回 vod dict 列表。
        策略：① related_selectors 命中 → ② 详情页所有 <a> 匹配文章模式 → ③ 首页兜底
        """
        limit = int(self.cfg.get("related_limit", 10))
        results, seen = [], set()
        current_norm = current_url.rstrip("/").split("?")[0]

        patterns = [re.compile(p) for p in self.cfg.get("article_href_patterns", [])]

        def _norm(href):
            if not href:
                return ""
            if href.startswith("/"):
                href = self.host.rstrip("/") + href
            return href.rstrip("/").split("?")[0]

        def _add(href, name, pic=""):
            if len(results) >= limit:
                return
            href_n = _norm(href)
            if not href_n or href_n == current_norm or href_n in seen:
                return
            if not href.startswith("http"):
                return
            name = (name or "").replace("\n", " ").strip()
            if len(name) < 2 or len(name) > 100:
                return
            seen.add(href_n)
            results.append({
                "vod_id": href,
                "vod_name": name,
                "vod_pic": pic,
                "vod_remarks": "",
                "style": self.cfg["style"],
            })

        # 策略 1：related_selectors
        for sel in self.cfg.get("related_selectors", []):
            if len(results) >= limit:
                break
            for a in doc(sel).items():
                href = (a.attr("href") or "").strip()
                name = (a("h2").text() or a.attr("title") or a.text() or "").strip()
                _add(href, name)

        # 策略 2：详情页所有 <a> 中匹配文章模式
        if len(results) < limit and patterns:
            for a in doc("a").items():
                if len(results) >= limit:
                    break
                href = (a.attr("href") or "").strip()
                if not href:
                    continue
                if not any(p.search(href) for p in patterns):
                    continue
                name = (a("h2").text() or a.attr("title") or a.text() or "").strip()
                _add(href, name)

        # 策略 3：首页兜底
        if len(results) < limit:
            try:
                hr = requests.get(self.host, headers=self.headers, proxies=self.proxies,
                                  timeout=self.cfg["timeout"])
                if hr.status_code == 200:
                    hdoc = self.getpq(hr.text)
                    for a in hdoc(self.cfg["home_list_selector"]).items():
                        if len(results) >= limit:
                            break
                        href = (a.attr("href") or "").strip()
                        name = (a("h2").text() or "").strip()
                        pic = self.getimg(a("script").text())
                        _add(href, name, pic)
            except Exception:
                pass

        print(f"[关联] 提取到 {len(results)} 条关联视频")
        return results

    # ================= 播放 / 代理 =================
    def playerContent(self, flag, id, vipFlags):
        url, p = id, 1
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

    # ================= 播放器解析 =================
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

    # ================= 列表 =================
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

    # ================= 合集 =================
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

    # ================= 图片 =================
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
