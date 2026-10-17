import sys
sys.path.append('..')
from base.spider import Spider
import urllib.parse
import re
import requests
from lxml import etree
from urllib.parse import urljoin

class Spider(Spider):
    
    def getName(self):
        return "菠萝七区"
    
    def init(self, extend=""):
        self.host = "https://618622.xyz"
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Connection': 'keep-alive',
            'Referer': self.host
        }
        self.log(f"爬虫初始化: {self.host}")

    def homeContent(self, filter):
        classes = [
            {'type_id': f'618622.xyz_{i}', 'type_name': n} for i, n in [
                ('37','国产AV'), ('43','探花AV'), ('40','网黄UP主'), ('49','绿帽淫妻'),
                ('44','国产传媒'), ('41','福利姬'), ('39','字幕'), ('45','水果派'),
                ('42','主播直播'), ('38','欧美'), ('66','FC2'), ('46','性爱教学'),
                ('48','三及片'), ('47','动漫')
            ]
        ]
        return {'class': classes, 'list': self._fetch_videos(self.host)}

    def homeVideoContent(self):
        return {'class': []}

    def categoryContent(self, tid, pg, filter, extend):
        type_id = tid.split('_')[1] if '_' in tid else tid
        url = f"{self.host}/index.php/vod/type/id/{type_id}.html"
        if pg != '1':
            url = url.replace('.html', f'/page/{pg}.html')
        return {'list': self._fetch_videos(url), 'page': int(pg), 'pagecount': 999, 'limit': 20, 'total': 9999}

    def searchContent(self, key, quick, pg="1"):
        url = f"{self.host}/index.php/vod/type/id/36/wd/{urllib.parse.quote(key)}/page/{pg}.html"
        return {'list': self._fetch_videos(url), 'page': int(pg), 'pagecount': 10, 'limit': 20, 'total': 100}

    def detailContent(self, ids):
        try:
            long_url = ids[0]
            params = urllib.parse.parse_qs(urllib.parse.urlparse(long_url).query)
            video_url = params.get('v', [''])[0]
            
            if not video_url: return {'list': []}

            title = self._extract_title(long_url)
            pic = params.get('b', [''])[0]
            if pic and not pic.startswith('http'): pic = urljoin(self.host, pic)
            
            return {'list': [{
                'vod_id': long_url, 'vod_name': title, 'vod_pic': pic,
                'vod_play_from': '屌牛逼', 'vod_play_url': f"大鸡无敌${video_url}",
                'vod_content': title
            }]}
        except:
            return {'list': []}

    def playerContent(self, flag, id, vipFlags):
        return {'parse': 0, 'playUrl': '', 'url': id} if '.m3u8' in id or 'v=' in id else {'parse': 1, 'url': id}

    def _fetch_videos(self, url):
        try:
            rsp = self.fetch(url)
            if not rsp or rsp.status_code != 200: return []
            
            videos = []
            html = etree.HTML(rsp.text)
            if html is None: return []

            for link in html.xpath('//a[@href]'):
                href = link.get('href', '')
                full_url = urljoin(self.host, href)
                
                if 'v=' in full_url and '.m3u8' in full_url:
                    title = self._extract_title(full_url)
                    
                    params = urllib.parse.parse_qs(urllib.parse.urlparse(full_url).query)
                    pic = params.get('b', [''])[0]
                    if not pic:
                        src = link.xpath('.//img/@src')
                        pic = src[0] if src else ''
                    if pic and not pic.startswith('http'): pic = urljoin(self.host, pic)
                    
                    videos.append({
                        'vod_id': full_url, 'vod_name': title, 'vod_pic': pic,
                        'vod_remarks': '', 'vod_year': ''
                    })
            return videos
        except:
            return []

    def _extract_title(self, url):
        try:
            match = re.search(r'/html/[^/]+/([^/]+)\.html', url)
            if match:
                raw = urllib.parse.unquote(match.group(1))
                return ''.join([chr(ord(c) ^ 128) for c in raw])
        except: pass
        return "未知标题"

    def log(self, msg):
        print(f"[苹果视频] {msg}")

    def fetch(self, url):
        try:
            return requests.get(url, headers=self.headers, timeout=10, verify=False)
        except:
            return None
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

import sys
sys.path.append('..')
from base.spider import Spider
import urllib.parse
import re
import requests
from lxml import etree
from urllib.parse import urljoin

class Spider(Spider):
    
    def getName(self):
        return "菠萝七区"
    
    def init(self, extend=""):
        self.host = "https://618622.xyz"
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Connection': 'keep-alive',
            'Referer': self.host
        }
        self.log(f"爬虫初始化: {self.host}")

    def homeContent(self, filter):
        classes = [
            {'type_id': f'618622.xyz_{i}', 'type_name': n} for i, n in [
                ('37','国产AV'), ('43','探花AV'), ('40','网黄UP主'), ('49','绿帽淫妻'),
                ('44','国产传媒'), ('41','福利姬'), ('39','字幕'), ('45','水果派'),
                ('42','主播直播'), ('38','欧美'), ('66','FC2'), ('46','性爱教学'),
                ('48','三及片'), ('47','动漫')
            ]
        ]
        return {'class': classes, 'list': self._fetch_videos(self.host)}

    def homeVideoContent(self):
        return {'class': []}

    def categoryContent(self, tid, pg, filter, extend):
        type_id = tid.split('_')[1] if '_' in tid else tid
        url = f"{self.host}/index.php/vod/type/id/{type_id}.html"
        if pg != '1':
            url = url.replace('.html', f'/page/{pg}.html')
        return {'list': self._fetch_videos(url), 'page': int(pg), 'pagecount': 999, 'limit': 20, 'total': 9999}

    def searchContent(self, key, quick, pg="1"):
        url = f"{self.host}/index.php/vod/type/id/36/wd/{urllib.parse.quote(key)}/page/{pg}.html"
        return {'list': self._fetch_videos(url), 'page': int(pg), 'pagecount': 10, 'limit': 20, 'total': 100}

    def detailContent(self, ids):
        try:
            long_url = ids[0]
            params = urllib.parse.parse_qs(urllib.parse.urlparse(long_url).query)
            video_url = params.get('v', [''])[0]
            
            if not video_url: return {'list': []}

            title = self._extract_title(long_url)
            pic = params.get('b', [''])[0]
            if pic and not pic.startswith('http'): pic = urljoin(self.host, pic)
            
            return {'list': [{
                'vod_id': long_url, 'vod_name': title, 'vod_pic': pic,
                'vod_play_from': '屌牛逼', 'vod_play_url': f"大鸡无敌${video_url}",
                'vod_content': title
            }]}
        except:
            return {'list': []}

    def playerContent(self, flag, id, vipFlags):
        return {'parse': 0, 'playUrl': '', 'url': id} if '.m3u8' in id or 'v=' in id else {'parse': 1, 'url': id}

    def _fetch_videos(self, url):
        try:
            rsp = self.fetch(url)
            if not rsp or rsp.status_code != 200: return []
            
            videos = []
            html = etree.HTML(rsp.text)
            if html is None: return []

            for link in html.xpath('//a[@href]'):
                href = link.get('href', '')
                full_url = urljoin(self.host, href)
                
                if 'v=' in full_url and '.m3u8' in full_url:
                    title = self._extract_title(full_url)
                    
                    params = urllib.parse.parse_qs(urllib.parse.urlparse(full_url).query)
                    pic = params.get('b', [''])[0]
                    if not pic:
                        src = link.xpath('.//img/@src')
                        pic = src[0] if src else ''
                    if pic and not pic.startswith('http'): pic = urljoin(self.host, pic)
                    
                    videos.append({
                        'vod_id': full_url, 'vod_name': title, 'vod_pic': pic,
                        'vod_remarks': '', 'vod_year': ''
                    })
            return videos
        except:
            return []

    def _extract_title(self, url):
        try:
            match = re.search(r'/html/[^/]+/([^/]+)\.html', url)
            if match:
                raw = urllib.parse.unquote(match.group(1))
                return ''.join([chr(ord(c) ^ 128) for c in raw])
        except: pass
        return "未知标题"

    def log(self, msg):
        print(f"[苹果视频] {msg}")

    def fetch(self, url):
        try:
            return requests.get(url, headers=self.headers, timeout=10, verify=False)
        except:
            return None
