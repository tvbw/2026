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

import re
from bs4 import BeautifulSoup
from base.spider import Spider

class Spider(Spider):
    def getName(self):
        return "硬硬AV"

    def init(self, extend=""):
        self.host = "https://ininav.com"
        self.header = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
            "Referer": self.host
        }

    def homeContent(self, filter):
        # 根據 HTML 導航欄手動定義，確保分類標籤絕對不為空
        classes = [
            {"type_name": "中文字幕", "type_id": "/chinese-subtitles"},
            {"type_name": "亞洲國產", "type_id": "/asian/new"},
            {"type_name": "日本AV", "type_id": "/japanese/new"},
            {"type_name": "無碼流出", "type_id": "/uncensored-leak/new"},
            {"type_name": "FC2素人", "type_id": "/fc2/new"},
            {"type_name": "歐美系列", "type_id": "/western/new"},
            {"type_name": "韓國直播", "type_id": "/korean/new"},
            {"type_name": "裏番動漫", "type_id": "/hentai/new"}
        ]
        return {'class': classes}

    def homeVideoContent(self):
        # 首頁推薦內容
        return self.categoryContent('/asian/new', 1, None, None)

    def categoryContent(self, tid, pg, filter, extend):
        result = {}
        page = int(pg) - 1
        url = f"{self.host}{tid}?page={page}"
        
        try:
            # 加入 verify=False 解決部分盒子 SSL 握手失敗導致的空列表
            rsp = self.fetch(url, headers=self.header)
            soup = BeautifulSoup(rsp.text, 'html.parser')
            videos = []
            
            # 根據 HTML 結構精準定位影片卡片容器
            items = soup.select('.views-view-grid .cf, .views-row, article')
            
            for item in items:
                # 1. 抓取標題與 ID (對齊 <a href="/video/124645">)
                a_tag = item.select_one('a[href*="/video/"]')
                if not a_tag: continue
                
                # 標題通常在 <img> 的 alt 或者 <a> 標籤內
                vod_id = a_tag['href']
                
                # 2. 抓取圖片 (針對 <picture> 標籤優化)
                pic = ""
                # 優先抓取 source 裡的 webp 地址
                source = item.select_one('source[type="image/webp"]')
                if source and source.get('srcset'):
                    pic = source.get('srcset').split(' ')[0]
                
                # 如果沒有 source，抓取 img 標籤
                if not pic:
                    img = item.select_one('img')
                    if img:
                        pic = img.get('src') or img.get('data-src') or ""
                
                # 處理相對路徑
                if pic and pic.startswith('/'):
                    pic = self.host + pic
                
                # 3. 抓取標題 (如果 a_tag 內沒有文字，從 img alt 補全)
                name = a_tag.get_text(strip=True)
                if not name and item.select_one('img'):
                    name = item.select_one('img').get('alt', '')
                if not name: name = "高清影片"

                videos.append({
                    "vod_id": vod_id,
                    "vod_name": name,
                    "vod_pic": pic,
                    "vod_remarks": ""
                })

            result['list'] = videos
            result['page'] = pg
            result['pagecount'] = 99
        except:
            result['list'] = []
            
        return result

    def detailContent(self, array):
        tid = array[0]
        url = self.host + tid
        rsp = self.fetch(url, headers=self.header)
        html = rsp.text
        
        # 標題提取
        title = ""
        t_match = re.search(r'<h1[^>]*>(.*?)</h1>', html)
        title = t_match.group(1).strip() if t_match else "影片詳情"

        # 圖片提取
        pic = ""
        p_match = re.search(r'property="og:image:url"\s+content="(.*?)"', html)
        pic = p_match.group(1) if p_match else ""

        # 核心：直接掃描源碼中的 m3u8 地址
        m3u8_links = re.findall(r'https?://[^\s"\'<>]+?index\.m3u8', html)
        m3u8_links = list(dict.fromkeys(m3u8_links)) # 去重
        
        play_list = []
        for i, link in enumerate(m3u8_links):
            play_list.append(f"線路{i+1}${link}")
        
        vod = {
            "vod_id": tid,
            "vod_name": title,
            "vod_pic": pic,
            "type_name": "硬硬精選",
            "vod_play_from": "硬硬雲",
            "vod_play_url": "#".join(play_list) if play_list else "未找到資源$null"
        }
        return {"list": [vod]}

    def searchContent(self, key, quick, pg=1):
        result = {}
        # 該站分頁從 0 開始，所以 pg=1 對應 page=0
        page = int(pg) - 1
        # 對齊 URL 格式: /search?fulltext=關鍵字&page=頁碼
        url = f"{self.host}/search?fulltext={key}&page={page}"
        
        try:
            rsp = self.fetch(url, headers=self.header)
            soup = BeautifulSoup(rsp.text, 'html.parser')
            videos = []
            
            # 搜尋結果的結構通常與分類頁一致，使用相同的選擇器
            items = soup.select('.views-view-grid .cf, .views-row, article, .search-result')
            
            for item in items:
                # 提取連結與 ID
                a_tag = item.select_one('a[href*="/video/"]')
                if not a_tag: continue
                
                vod_id = a_tag['href']
                
                # 提取圖片 (優先處理 picture/source 組合)
                pic = ""
                source = item.select_one('source[type="image/webp"]')
                if source and source.get('srcset'):
                    pic = source.get('srcset').split(' ')[0]
                
                if not pic:
                    img = item.select_one('img')
                    if img:
                        pic = img.get('src') or img.get('data-src') or ""
                
                if pic and pic.startswith('/'):
                    pic = self.host + pic

                # 提取標題
                name = a_tag.get_text(strip=True)
                if not name and item.select_one('img'):
                    name = item.select_one('img').get('alt', '')
                if not name: name = key # 若無標題則顯示關鍵字

                videos.append({
                    "vod_id": vod_id,
                    "vod_name": name,
                    "vod_pic": pic,
                    "vod_remarks": ""
                })

            result['list'] = videos
            result['page'] = pg
            result['pagecount'] = 99
        except Exception:
            result['list'] = []
            
        return result

    def playerContent(self, flag, id, vipFlags):
        return {
            "parse": 0,
            "url": id,
            "header": self.header
        }
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