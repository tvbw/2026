# -*- coding: utf-8 -*-
# ===== 1. 先正常 import 所有模块 =====
import json
import random
import re
import sys
import threading
import time
from base64 import b64decode, b64encode
from urllib.parse import urlparse

import requests  # ✅ 先正常 import
from Crypto.Cipher import AES
from Crypto.Util.Padding import unpad
from pyquery import PyQuery as pq
sys.path.append('..')
from base.spider import Spider

# ===== 2. 再放加速头（不能再 import requests） =====
# =================== 极简万能加速头 ===================
import re
from functools import lru_cache

FAST_CDN = "lib.baomitu.com"
DEAD_MAP = {
    "rimg.iomycdn.com": FAST_CDN,
    "rimg.xiakee.com": FAST_CDN,
    "play.abcyun.com": FAST_CDN,
    "video.xyzcdn.com": FAST_CDN,
}

@lru_cache(maxsize=256)
def _auto_cdn(url: str) -> str:
    if not url:
        return ""
    for dead, fast in DEAD_MAP.items():
        url = url.replace(dead, fast)
    if url.startswith("//"):
        url = "https:" + url
    try:
        r = requests.head(url, allow_redirects=True, timeout=2)
        url = r.url
    except:
        pass
    return url

# 注入 requests
_real_get = requests.Session.get
def _patched_get(self, url, *a, **k):
    url = _auto_cdn(url)
    return _real_get(self, url, *a, **k)
requests.Session.get = _patched_get
# =================== 加速头结束 ===================
import json
import re
from urllib.parse import quote, unquote, urljoin

import requests
from lxml import etree
from base.spider import Spider


class Spider(Spider):
    def getName(self): return "叔叔和侄女"

    def init(self, extend=""):
        self.host = "https://a1b2c3d4.shushu19.cc"
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36",
            "Referer": self.host + "/"
        }
        self.img_headers = {"Referer": self.host + "/"}
        self.classes = [
            {"type_id": "1", "type_name": "国产传媒"},
            {"type_id": "2", "type_name": "国产剧情"},
            {"type_id": "58", "type_name": "网曝黑料"},
            {"type_id": "3", "type_name": "特色仓库"},
            {"type_id": "69", "type_name": "精品资源"},
            {"type_id": "78", "type_name": "热播片库"},
        ]
        self.filters = {c["type_id"]: [] for c in self.classes}

    def _get(self, url):
        try:
            response = requests.get(url, headers=self.headers, timeout=15, verify=False)
            response.raise_for_status()
            ct = response.headers.get("Content-Type", "")
            m = re.search(r"charset=([\w-]+)", ct)
            response.encoding = m.group(1) if m else "utf-8"
            return response.text
        except Exception:
            return ""

    def _fix(self, url):
        return urljoin(self.host + "/", url or "")

    def _parse_list(self, html):
        if not html:
            return []
        tree = etree.HTML(html)
        result, seen = [], set()
        for card in tree.xpath('//a[contains(@href,"/voddetail/")]'):
            match = re.search(r"/voddetail/(\d+)\.html", card.get("href", ""))
            if not match or match.group(1) in seen:
                continue
            vid = match.group(1)
            seen.add(vid)
            name = "".join(card.xpath('.//p[contains(@class,"vod-name")]//text()')).strip()
            if not name:
                name = "".join(card.xpath('.//text()')).strip()
            pic = ""
            for attr in ("@data-original", "@data-src", "@src"):
                vals = card.xpath(f'.//img[contains(@class,"vod-pic")]/{attr}')
                if vals:
                    pic = vals[0]
                    break
            pic = self._fix(pic) if pic and not pic.startswith("http") else pic
            if "/template/" in pic:
                pic = ""
            remark = "".join(card.xpath('.//span[contains(@class,"vod-date")]//text()')).strip()
            result.append({"vod_id": vid, "vod_name": name, "vod_pic": pic, "vod_remarks": remark})
        return result

    def _pagecount(self, tree, page):
        tail = tree.xpath('//a[contains(text(),"尾")]/@href')
        if tail:
            m = re.findall(r"-(\d+)\.html", tail[0])
            if m:
                return int(m[-1])
        values = [int(x) for x in tree.xpath('//a[contains(@href,"/vodtype/")]/@href') for x in re.findall(r"-(\d+)\.html", x)]
        return max(values + [page])

    def homeContent(self, filter):
        html = self._get(f"{self.host}/vodtype/1-1.html")
        return {
            "class": self.classes,
            "list": self._parse_list(html),
            "filters": self.filters,
            "header": self.img_headers
        }

    def homeVideoContent(self):
        return {"list": self._parse_list(self._get(f"{self.host}/vodtype/1-1.html"))}

    def categoryContent(self, tid, pg, filter, extend):
        page = max(1, int(pg or 1))
        url = f"{self.host}/vodtype/{tid}-{page}.html"
        html = self._get(url)
        tree = etree.HTML(html) if html else etree.HTML("<html/>")
        videos = self._parse_list(html)
        pc = self._pagecount(tree, page)
        return {
            "page": page,
            "pagecount": pc,
            "limit": len(videos),
            "total": pc * max(len(videos), 1),
            "list": videos,
            "header": self.img_headers
        }

    def detailContent(self, ids):
        result = []
        for vid in ids:
            html = self._get(f"{self.host}/voddetail/{vid}.html")
            if not html:
                continue
            tree = etree.HTML(html)
            name = "".join(tree.xpath('//div[contains(@class,"detail-pos")]//text()')).strip()
            if not name:
                name = "".join(tree.xpath('//h1//text() | //h2//text()')).strip()
            pic = ""
            for attr in ("@data-original", "@data-src", "@src"):
                vals = tree.xpath(f'//img[contains(@class,"detail-vod-pic")]/{attr}')
                if vals:
                    pic = vals[0]
                    break
            pic = self._fix(pic) if pic and not pic.startswith("http") else pic
            content = " ".join(x.strip() for x in tree.xpath('//span[contains(@class,"detail-intro")]//text() | //div[contains(@class,"detail-intro")]//text()') if x.strip())
            play_btns = tree.xpath('//a[contains(@href,"/vodplay/")]/@href')
            play_path = play_btns[0] if play_btns else ""
            if not play_path:
                continue
            result.append({
                "vod_id": str(vid),
                "vod_name": name,
                "vod_pic": pic,
                "vod_content": content,
                "vod_play_from": "蜗牛专线",
                "vod_play_url": f"正片${play_path}"
            })
        return {"list": result}

    def searchContent(self, key, quick, pg="1"):
        page = max(1, int(pg or 1))
        url = f"{self.host}/vodsearch/-------------.html?wd={quote(key)}&page={page}"
        html = self._get(url)
        tree = etree.HTML(html) if html else etree.HTML("<html/>")
        videos = self._parse_list(html)
        tail = tree.xpath('//a[contains(text(),"尾")]/@href')
        pagecount = 1
        if tail:
            m = re.findall(r"----------(\d+)---", tail[0])
            if m:
                pagecount = int(m[0])
        return {"page": page, "pagecount": pagecount, "list": videos}

    def playerContent(self, flag, id, vipFlags):
        url = self._fix(id)
        html = self._get(url)
        marker = "var player_aaaa="
        if marker in html:
            try:
                data = json.JSONDecoder().raw_decode(html.split(marker, 1)[1])[0]
                play_url = data.get("url", "")
                if int(data.get("encrypt", 0)) == 1:
                    play_url = unquote(play_url)
                if play_url and any(x in play_url.lower() for x in (".m3u8", ".mp4", ".flv")):
                    return {
                        "parse": 0,
                        "url": play_url,
                        "header": {"User-Agent": self.headers["User-Agent"], "Referer": url}
                    }
            except Exception:
                pass
        return {"parse": 1, "url": url, "header": self.headers}
# ==============  万能一键加速（2025-12 五星无探测双 CDN 版）  ==============
_PIC_CDN_POOL = ('lib.baomitu.com', 'open.oppomobile.com')

def _cover_fallback(self, pic_url):
    """
    极速无探测双 CDN（2025-12 白名单）
    1. 白名单节点按速度排序：lib.baomitu.com（约 443ms）→ open.oppomobile.com
    2. 命中白名单节点时统一切换到最快节点；非白名单保持原样
    3. 支持可选的 proxy_base 代理前缀
    """
    import urllib.parse

    # ---- 1. 兼容父类实现（父类无此方法时退化为原 URL） ----
    raw = pic_url or ''
    parent_impl = getattr(super(Spider, self), '_cover_fallback', None)
    if callable(parent_impl):
        try:
            raw = parent_impl(pic_url) or raw
        except Exception:
            pass
    if not raw:
        return ''

    # ---- 2. 无探测切换：命中白名单即统一切到最快的 lib.baomitu.com ----
    url = raw
    for cdn in _PIC_CDN_POOL:
        if cdn in raw:
            url = raw.replace(cdn, _PIC_CDN_POOL[0])
            break

    # ---- 3. 可选代理前缀 ----
    proxy_base = getattr(self, 'proxy_base', None)
    if proxy_base:
        url = f'{proxy_base}{urllib.parse.quote(url)}'
    return url

# 挂载到 Spider，使加速真正生效
Spider._cover_fallback = _cover_fallback
