# ============================================================
# 红果短剧 Spider（适配 hongguoduanju.com 现有页面结构）
# ============================================================
import json
import re
import sys
from urllib.parse import quote

import requests
from pyquery import PyQuery as pq

sys.path.append('..')
from base.spider import Spider


SITE_CONFIG = {
    "name": "红果短剧",
    "play_from": "红果短剧",
    "style": {"type": "rect", "ratio": 1.33},
    "host": "https://hongguoduanju.com",

    # 卡片入口：只匹配真正的详情链接，避免把顶部下拉 nav 链接也抓进来
    "list_selector": 'a[href*="/detail?series_id="]',

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

    # 如果分类页/详情页需要登录，把浏览器里 hongguoduanju.com 的 Cookie 完整粘到这里即可
    # 例如: "cookie": "sessionid=xxx; uid=xxx; ..."
    "cookie": "",

    # 搜索 URL（不同站版本可能略有差异，下面会按多种候选依次尝试）
    "search_url_tpl": "{host}/search?keyword={key}",
}


class Spider(Spider):

    # 类属性，确保 init 前 getName 可访问
    cfg = SITE_CONFIG

    # ================= 生命周期 =================
    def init(self, extend=""):
        try:
            self.proxies = json.loads(extend) if extend else {}
        except Exception:
            self.proxies = {}

        self.cfg = SITE_CONFIG
        self.headers = dict(self.cfg["headers"])
        self.host = self.cfg["host"].rstrip("/")
        self.headers.update({
            "Origin": self.host,
            "Referer": f"{self.host}/",
        })
        if self.cfg.get("cookie"):
            self.headers["Cookie"] = self.cfg["cookie"]
        print(f"使用站点: {self.host}")

    def getName(self):
        return SITE_CONFIG.get("name", "红果短剧")

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
            return {
                "class": self._parse_classes(doc),
                "list": self.getlist(doc),
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
            return {"list": self.getlist(doc)}
        except Exception as e:
            print(f"homeVideoContent error: {e}")
            return {"list": []}

    def _parse_classes(self, doc):
        """
        优先使用 aria-label 显式标记的 nav，其次回退到所有 /category/ 链接。
        跳过 aria-haspopup="true"（顶部"分类"下拉触发器，文本没用）。
        """
        classes, seen = [], set()
        for sel in [
            'nav[aria-label="短剧分类"] a[href^="/category/"]',
            'nav[aria-label="内容分类"] a[href^="/category/"]',
            'nav a[href^="/category/"]',
        ]:
            for a in doc(sel).items():
                if a.attr("aria-haspopup") == "true":
                    continue
                href = (a.attr("href") or "").strip()
                name = (a.text() or "").strip()
                if not href or not name or href in seen:
                    continue
                seen.add(href)
                classes.append({"type_name": name, "type_id": href})
            if classes:
                break

        if not classes:
            classes = [
                {"type_name": "真人剧", "type_id": "/category/real-drama"},
                {"type_name": "漫剧",   "type_id": "/category/comic-drama"},
                {"type_name": "AI剧",   "type_id": "/category/ai-drama"},
                {"type_name": "漫画",   "type_id": "/category/comic"},
            ]
        return classes

    # ================= 分类 =================
    def categoryContent(self, tid, pg, filter, extend):
        try:
            pg = int(pg)
            tid = tid.rstrip("/")
            # 分类分页格式: /category/real-drama?page=N （从提供的 HTML 确认）
            url = f"{self.host}{tid}" + (f"?page={pg}" if pg > 1 else "")
            r = requests.get(url, headers=self.headers,
                             proxies=self.proxies, timeout=self.cfg["timeout"])
            doc = self.getpq(r.text)
            videos = self.getlist(doc)

            # 从分页区扫描最大页码
            total_pages = 1
            for a in doc('nav a[href*="page="]').items():
                m = re.search(r"page=(\d+)", a.attr("href") or "")
                if m:
                    total_pages = max(total_pages, int(m.group(1)))

            return {
                "list": videos, "page": pg, "pagecount": total_pages,
                "limit": 30, "total": total_pages * 30,
            }
        except Exception as e:
            print(f"categoryContent error: {e}")
            return {"list": [], "page": pg, "pagecount": 1, "limit": 30, "total": 0}

    # ================= 详情 =================
    def detailContent(self, ids):
        raw = ids[0] if ids else ""
        url = raw if raw.startswith("http") else f"{self.host}{raw}"
        try:
            r = requests.get(url, headers=self.headers,
                             proxies=self.proxies, timeout=self.cfg["timeout"])
            if r.status_code != 200:
                raise RuntimeError(f"HTTP {r.status_code}")
            doc = self.getpq(r.text)

            vod = {
                "vod_id": raw,
                "vod_name": self._extract_title(r.text),
                "vod_pic":  self._extract_poster(doc),
                "vod_content": "",
                "vod_play_from": self.cfg["play_from"],
                "vod_play_url": "",
            }

            plist = self._extract_playlist(doc, r.text, url)
            if plist:
                vod["vod_play_url"] = "#".join(plist)
            else:
                # 至少给一个可播的入口（有些剧详情页就是直接播放当前集）
                vod["vod_play_url"] = f"完整版${url}"

            return {"list": [vod]}
        except Exception as e:
            print(f"detailContent error: {e}")
            return {"list": [{
                "vod_id": raw,
                "vod_name": "详情失败",
                "vod_play_from": self.cfg["play_from"],
                "vod_play_url": f"详情加载失败${url}",
            }]}

    def _extract_title(self, html):
        m = re.search(r"<title>([^<]+)</title>", html)
        if m:
            # 去掉站点后缀 " - 红果短剧" / "_红果短剧" 等
            return re.split(r"[_\-|–]", m.group(1))[0].strip()
        return ""

    def _extract_poster(self, doc):
        img = doc('img[class*="image"]').eq(0).attr("src") or ""
        if not img:
            img = doc('meta[property="og:image"]').attr("content") or ""
        return img

    def _extract_playlist(self, doc, html, url):
        """多策略提取播放列表，按优先级依次尝试。"""
        seen = set()

        # ---- 1. __NEXT_DATA__（Next.js） ----
        nd = doc("script#__NEXT_DATA__").text()
        if nd:
            try:
                urls = self._collect_urls(json.loads(nd))
                if urls:
                    return [f"第{i+1}集${u}" for i, u in enumerate(urls)]
            except Exception:
                pass

        # ---- 2. window.__INITIAL_STATE__ / __DATA__ / __PRELOADED_STATE__ ----
        for pat in [
            r"window\.__INITIAL_STATE__\s*=\s*(\{.+?\})\s*;",
            r"window\.__DATA__\s*=\s*(\{.+?\})\s*;",
            r"window\.__PRELOADED_STATE__\s*=\s*(\{.+?\})\s*;",
        ]:
            m = re.search(pat, html, re.S)
            if m:
                try:
                    urls = self._collect_urls(json.loads(m.group(1)))
                    if urls:
                        return [f"第{i+1}集${u}" for i, u in enumerate(urls)]
                except Exception:
                    pass

        # ---- 3. 页面上的 episode / video / play 链接 ----
        plist = []
        for a in doc('a[href*="episode"], a[href*="video"], a[href*="play"]').items():
            href = a.attr("href")
            if href and href not in seen:
                seen.add(href)
                name = (a.text() or "").strip() or f"第{len(plist)+1}集"
                plist.append(f"{name}${href}")
        if plist:
            return plist

        # ---- 4. HTML 内出现的 m3u8 / mp4 直链 ----
        for m in re.finditer(r'https?://[^\s"\'<>\\]+\.(?:m3u8|mp4)[^\s"\'<>\\]*', html):
            u = m.group(0)
            if u not in seen:
                seen.add(u)
                plist.append(f"视频{len(plist)+1}${u}")
        if plist:
            return plist

        # ---- 5. 尝试常见 API 探测 ----
        m = re.search(r"series_id=(\d+)", url)
        if m:
            urls = self._try_api_episodes(m.group(1))
            if urls:
                return [f"第{i+1}集${u}" for i, u in enumerate(urls)]

        return []

    def _try_api_episodes(self, series_id):
        """探测常见 API 端点，红果短剧若采用 SPA 可能需要这个。"""
        candidates = [
            f"{self.host}/api/series/detail?series_id={series_id}",
            f"{self.host}/api/video/list?series_id={series_id}",
            f"{self.host}/api/episode/list?series_id={series_id}",
            f"{self.host}/api/series/{series_id}",
            f"{self.host}/api/detail?series_id={series_id}",
        ]
        for api in candidates:
            try:
                r = requests.get(api, headers=self.headers,
                                 proxies=self.proxies, timeout=self.cfg["timeout"])
                if r.status_code != 200:
                    continue
                try:
                    data = r.json()
                except Exception:
                    continue
                urls = self._collect_urls(data)
                if urls:
                    return urls
            except Exception:
                continue
        return []

    def _collect_urls(self, data):
        """递归扫描任意 JSON 结构里的 m3u8 / mp4 URL。"""
        urls = []

        def walk(obj):
            if isinstance(obj, dict):
                for v in obj.values():
                    if isinstance(v, str):
                        if v.startswith("http") and (".m3u8" in v or ".mp4" in v):
                            if v not in urls:
                                urls.append(v)
                    else:
                        walk(v)
            elif isinstance(obj, list):
                for item in obj:
                    walk(item)

        walk(data)
        return urls

    # ================= 搜索 =================
    def searchContent(self, key, quick, pg="1"):
        q = quote(key)
        candidates = [
            self.cfg["search_url_tpl"].format(host=self.host, key=q),
            f"{self.host}/search?q={q}",
            f"{self.host}/search/{q}",
            f"{self.host}/api/search?keyword={q}",
        ]
        for url in candidates:
            try:
                r = requests.get(url, headers=self.headers,
                                 proxies=self.proxies, timeout=self.cfg["timeout"])
                if r.status_code != 200:
                    continue
                # HTML 结构
                doc = self.getpq(r.text)
                videos = self.getlist(doc)
                if videos:
                    return {"list": videos, "page": pg}
                # JSON 结构
                try:
                    videos = self._parse_json_search(json.loads(r.text))
                    if videos:
                        return {"list": videos, "page": pg}
                except Exception:
                    pass
            except Exception:
                continue
        return {"list": [], "page": pg}

    def _parse_json_search(self, data):
        results, seen = [], set()

        def walk(obj):
            if isinstance(obj, dict):
                sid = obj.get("series_id") or obj.get("seriesId") or obj.get("id")
                name = obj.get("title") or obj.get("name") or obj.get("series_name")
                if sid and name:
                    vid = f"/detail?series_id={sid}"
                    if vid not in seen:
                        seen.add(vid)
                        results.append({
                            "vod_id": vid,
                            "vod_name": name,
                            "vod_pic": obj.get("cover") or obj.get("pic") or obj.get("image") or "",
                            "vod_remarks": obj.get("episode_count") or obj.get("total_episode") or "",
                            "style": self.cfg["style"],
                        })
                for v in obj.values():
                    walk(v)
            elif isinstance(obj, list):
                for item in obj:
                    walk(item)

        walk(data)
        return results

    # ================= 播放 =================
    def playerContent(self, flag, id, vipFlags):
        url = id
        parse = 0 if self.isVideoFormat(url) else 1
        headers = dict(self.headers)
        headers["Referer"] = f"{self.host}/"
        return {"parse": parse, "url": url, "header": headers}

    # ================= 列表解析 =================
    def getlist(self, doc):
        """
        红果短剧卡片结构（从 HTML 确认）：
          <a class="pc-card-xxx" href="/detail?series_id=...">
             <div class="pc-img-container-...">
                 <img class="image-xxx" src="...">
                 <p class="pc-episode-xxx">全86集</p>
             </div>
             <p class="pc-title-xxx">王妈在顾家当保姆后全家只会搞笑了</p>
             <div class="pc-tags-xxx"><span class="pc-tag-text-xxx">喜剧</span>...</div>
          </a>
        """
        videos, seen = [], set()
        for a in doc(self.cfg["list_selector"]).items():
            href = a.attr("href")
            if not href or href in seen:
                continue
            seen.add(href)

            title = (a('p[class*="pc-title"]').text() or "").strip()
            if not title:
                title = (a("img").attr("alt") or "").strip()
            if not title:
                continue

            episode = (a('p[class*="pc-episode"]').text() or "").strip()
            img = (a('img[class*="image"]').attr("src")
                   or a("img").attr("src")
                   or "")
            tags = [t.text().strip() for t in a('span[class*="pc-tag-text"]').items()
                    if t.text().strip()]

            videos.append({
                "vod_id": href,
                "vod_name": title,
                "vod_pic": img,
                "vod_remarks": episode,
                "vod_content": " / ".join(tags) if tags else "",
                "style": self.cfg["style"],
            })
        return videos

    # ================= 工具 =================
    def getpq(self, data):
        try:
            return pq(data)
        except Exception:
            return pq(data.encode("utf-8"))

    # ---------- 兼容旧框架的存根（如不需要可删） ----------
    def e64(self, text):
        from base64 import b64encode
        try:
            return b64encode(text.encode("utf-8")).decode("utf-8")
        except Exception:
            return ""

    def d64(self, text):
        from base64 import b64decode
        try:
            return b64decode(text.encode("utf-8")).decode("utf-8")
        except Exception:
            return ""

    def proxy(self, data, type="m3u8"):
        return data

    def localProxy(self, param):
        return [200, "text/plain", ""]


if __name__ == '__main__':
    from base.spider import Spider as BaseSpider
    BaseSpider.register(Spider())
