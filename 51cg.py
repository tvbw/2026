# ============================================================
# 通用发布页动态域名 Spider 模板（无 fallback，多重探测兜底）
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

    # ============ 唯一入口：发布页域名 ============
    "entry_hosts": [
        "https://51cge21.com",
        "https://51cgf20.com/",
        "https://51cge22.com",
        "https://51cgf18.com/",
    ],

    # 发布页解码方式（解析器会自动兜底，非必须）
    "publish_decode": "js_base64",

    # 探测选择器（可选强特征；不再作为唯一判断）
    "host_check_selector": "#index article a",

    # 调试开关：true 时打印解析细节
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

    # ================= 域名探测（发布页驱动 + 多重特征） =================
    def get_working_host(self):
        entry_hosts = self.cfg.get("entry_hosts", [])
        if not entry_hosts:
            print("entry_hosts 为空")
            return ""

        all_candidates, seen = [], set()

        def add(url):
            if url and url not in seen:
                seen.add(url)
                all_candidates.append(url)

        # 1. 解析每个发布页
        for pub_url in entry_hosts:
            cands = self._parse_publish_page(pub_url)
            if self.cfg.get("debug_publish"):
                print(f"[debug] 发布页 {pub_url} 解析到 {len(cands)} 个候选: {cands[:5]}")
            for c in cands:
                add(c)

        # 2. entry_hosts 本身也作为候选
        for url in entry_hosts:
            add(url)

        # 3. 逐个探测
        for url in all_candidates:
            if self._probe_site(url):
                print(f"可用站点: {url}")
                return url

        print("所有候选域名均不可用，请更新 entry_hosts 中的发布页地址")
        return entry_hosts[0]

    def _probe_site(self, url):
        try:
            r = requests.get(url, headers=self.headers, proxies=self.proxies,
                             timeout=self.cfg["probe_timeout"])
            if r.status_code != 200:
                return False

            doc = self.getpq(r.text)

            # 1. 强特征：用户配置的选择器命中
            sel = self.cfg.get("host_check_selector", "").strip()
            if sel and doc(sel):
                return True

            # 2. 标题关键词
            title = (doc("title").text() or "").strip()
            for kw in ["51吃瓜", "吃瓜网", "51爆料", "51cg"]:
                if kw in title:
                    return True

            # 3. 正文结构
            if doc("article").length >= 3 or doc(".post, .entry, .item").length >= 5:
                return True

            # 4. 文本兜底
            if len(r.text) > 5000 and "吃瓜" in r.text:
                return True

            return False
        except Exception:
            return False

    def _parse_publish_page(self, publish_url):
        try:
            r = requests.get(publish_url, headers=self.headers, proxies=self.proxies,
                             timeout=self.cfg["probe_timeout"])
            if r.status_code != 200:
                if self.cfg.get("debug_publish"):
                    print(f"[debug] {publish_url} HTTP {r.status_code}")
                return []
            html = r.text

            # 尝试解码
            mode = self.cfg.get("publish_decode", "plain")
            if mode in ("js_base64", "js_atob"):
                decoded = self._decode_publish(html, mode)
                if decoded and decoded != html:
                    html = decoded

            candidates, seen = [], set()
            doc = self.getpq(html)

            # 策略 A: <a href>
            for a in doc("a").items():
                self._add_candidate(a.attr("href"), publish_url, candidates, seen)

            # 策略 B: meta refresh
            for m in doc("meta").items():
                if (m.attr("http-equiv") or "").lower() == "refresh":
                    content = m.attr("content") or ""
                    match = re.search(r'url=([^;]+)', content, re.I)
                    if match:
                        self._add_candidate(match.group(1).strip(), publish_url, candidates, seen)

            # 策略 C: JS 跳转/变量
            for pattern in [
                r'(?:location\.href|window\.location|location\.replace)\s*[=(]\s*["\']([^"\']+)["\']',
                r'window\.open\(["\']([^"\']+)["\']',
                r'(?:var|let|const)\s+\w*(?:url|host|domain|site)\w*\s*=\s*["\']([^"\']+)["\']',
            ]:
                for match in re.finditer(pattern, html, re.I):
                    self._add_candidate(match.group(1), publish_url, candidates, seen)

            # 策略 D: 直接正则提取 URL
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
    # ...（此处省略 homeContent / homeVideoContent / categoryContent / searchContent，
    #      与上一版完全一致，无需改动）
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

            # ---------- 关联播放（直接粘贴 02.txt 逻辑） ----------
            # related_vods = ...  ← 用 02.txt 的代码替换这一行
            related_vods = []   # 暂为空，不影响主功能

            return {"list": [main_vod] + related_vods}

        except Exception as e:
            print(f"detailContent error: {e}")
            return {"list": [{"vod_play_from": self.cfg["play_from"],
                              "vod_play_url": f"详情页加载失败${ids[0] if ids else ''}"}]}

    # ================= 播放 / 代理 / 工具（保持不变） =================
    # ...（playerContent / localProxy / proxy / m3Proxy / tsProxy / e64 / d64 /
    #      _parse_players / getlist / getfod / getimg / aesimg / getpq
    #      与上一版完全一致，无需改动）
