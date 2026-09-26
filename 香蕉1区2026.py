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
        self.host = "https://6182087.xyz"
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Connection': 'keep-alive',
            'Referer': self.host
        }
        self.log(f"爬虫初始化: {self.host}")

    def homeContent(self, filter):
        classes = [
            {'type_id': '618041.xyz_1', 'type_name': '全部视频'},
            {'type_id': '618041.xyz_13', 'type_name': '香蕉精品'},
            {'type_id': '618041.xyz_22', 'type_name': '制服诱惑'},
            {'type_id': '618041.xyz_6', 'type_name': '国产视频'},
            {'type_id': '618041.xyz_8', 'type_name': '清纯少女'},
            {'type_id': '618041.xyz_9', 'type_name': '辣妹大奶'},
            {'type_id': '618041.xyz_10', 'type_name': '女同专属'},
            {'type_id': '618041.xyz_11', 'type_name': '素人出演'},
            {'type_id': '618041.xyz_12', 'type_name': '角色扮演'},
            {'type_id': '618041.xyz_20', 'type_name': '人妻熟女'},
            {'type_id': '618041.xyz_23', 'type_name': '日韩剧情'},
            {'type_id': '618041.xyz_21', 'type_name': '经典伦理'},
            {'type_id': '618041.xyz_7', 'type_name': '成人动漫'},
            {'type_id': '618041.xyz_14', 'type_name': '精品二区'},
            {'type_id': '618041.xyz_53', 'type_name': '动漫中字'},
            {'type_id': '618041.xyz_52', 'type_name': '日本无码'},
            {'type_id': '618041.xyz_33', 'type_name': '中文字幕'},
            {'type_id': '618041.xyz_44', 'type_name': '国产传媒'},
            {'type_id': '618041.xyz_32', 'type_name': '国产自拍'}
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
# 注册爬虫
if __name__ == '__main__':
    from base.spider import Spider as BaseSpider
    BaseSpider.register(Spider())
