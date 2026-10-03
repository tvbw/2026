import requests
from bs4 import BeautifulSoup
import re
from base.spider import Spider
import sys
import json
import base64
import urllib.parse
from Crypto.Cipher import ARC4
from Crypto.Util.Padding import unpad
import binascii

sys.path.append('..')

xurl = "https://www.fullhd.to/br/"

headerx = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 6.1; WOW64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/50.0.2661.87 Safari/537.36'
}

pm = ''


class Spider(Spider):
    global xurl
    global headerx

    def getName(self):
        return "首页"

    def init(self, extend):
        pass

    def isVideoFormat(self, url):
        pass

    def manualVideoCheck(self):
        pass

    # ------------------------------------------------------------------
    # 通用工具：稳健取图（兼容 KVS 各类懒加载写法）
    # ------------------------------------------------------------------
    def _get_pic(self, vod):
        img = vod.find('img')
        if not img:
            return ""
        pic = ""
        for attr in ('data-src', 'data-original', 'data-lazy', 'data-url', 'src'):
            v = img.get(attr)
            if v:
                pic = v
                break
        if not pic:
            return ""
        if pic.startswith('//'):
            return 'https:' + pic
        if not pic.startswith('http'):
            pic = xurl + pic.lstrip('/')
        return pic

    # ------------------------------------------------------------------
    # 通用工具：取名字/ID/时长（各页面复用）
    # ------------------------------------------------------------------
    def _parse_item(self, vod):
        name = ""
        vid = ""
        remark = ""
        a = vod.find('a')
        if a:
            name = a.get('title', '') or a.get_text(strip=True)
            vid = a.get('href', '')
        if not vid:
            a2 = vod.find_all('a')
            if len(a2) > 0:
                vid = a2[0].get('href', '')
        dur = vod.find('span', class_="duration")
        if dur:
            remark = dur.text.strip()
        return {
            "vod_id": vid,
            "vod_name": name,
            "vod_pic": self._get_pic(vod),
            "vod_remarks": remark
        }

    def extract_middle_text(self, text, start_str, end_str, pl,
                            start_index1: str = '', end_index2: str = ''):
        if pl == 3:
            plx = []
            while True:
                start_index = text.find(start_str)
                if start_index == -1:
                    break
                end_index = text.find(end_str, start_index + len(start_str))
                if end_index == -1:
                    break
                middle_text = text[start_index + len(start_str):end_index]
                plx.append(middle_text)
                text = text.replace(start_str + middle_text + end_str, '')
            if len(plx) > 0:
                purl = ''
                for i in range(len(plx)):
                    matches = re.findall(start_index1, plx[i])
                    output = ""
                    for match in matches:
                        match3 = re.search(r'(?:^|[^0-9])(\d+)(?:[^0-9]|$)', match[1])
                        if match3:
                            number = match3.group(1)
                        else:
                            number = 0
                        if 'http' not in match[0]:
                            output += f"#{'📽️' + match[1]}${number}{xurl}{match[0]}"
                        else:
                            output += f"#{'📽️' + match[1]}${number}{match[0]}"
                    output = output[1:]
                    purl = purl + output + "$$$"
                purl = purl[:-3]
                return purl
            else:
                return ""
        else:
            start_index = text.find(start_str)
            if start_index == -1:
                return ""
            end_index = text.find(end_str, start_index + len(start_str))
            if end_index == -1:
                return ""

        if pl == 0:
            middle_text = text[start_index + len(start_str):end_index]
            return middle_text.replace("\\", "")

        if pl == 1:
            middle_text = text[start_index + len(start_str):end_index]
            matches = re.findall(start_index1, middle_text)
            if matches:
                jg = ' '.join(matches)
                return jg

        if pl == 2:
            middle_text = text[start_index + len(start_str):end_index]
            matches = re.findall(start_index1, middle_text)
            if matches:
                new_list = [f'✨{item}' for item in matches]
                jg = '$$$'.join(new_list)
                return jg

    # ------------------------------------------------------------------
    # 首页分类
    # ------------------------------------------------------------------
    def homeContent(self, filter):
        result = {}
        result = {"class": [
            {"type_id": "latest-updates", "type_name": "新"},
            {"type_id": "networks/naughtyamerica-com", "type_name": "Naug🌠"},
            {"type_id": "sites/sexmex", "type_name": "Sexmex🌠"},
            {"type_id": "categories/animation", "type_name": "Animation🌠"},
            {"type_id": "categories/18-years-old", "type_name": "Teen🌠"},
            {"type_id": "categories/pawg", "type_name": "Pawg🌠"},
            {"type_id": "categories/thong", "type_name": "Thong🌠"},
            {"type_id": "categories/stockings", "type_name": "Stockings🌠"},
            {"type_id": "categories/pantyhose", "type_name": "Pantyhose🌠"}
        ],
        }
        return result

    # ------------------------------------------------------------------
    # 首页视频
    # ------------------------------------------------------------------
    def homeVideoContent(self):
        videos = []
        try:
            detail = requests.get(url=xurl, headers=headerx, timeout=10)
            detail.encoding = "utf-8"
            res = detail.text
            doc = BeautifulSoup(res, "lxml")

            section = doc.find('div', id="list_videos_videos_watched_right_now_items")
            if section:
                vods = section.find_all(['div', 'article'], class_="item")
                for vod in vods:
                    videos.append(self._parse_item(vod))

            result = {'list': videos}
            return result
        except Exception as e:
            print(f"Error in homeVideoContent: {str(e)}")
            return {'list': []}

    # ------------------------------------------------------------------
    # 分类
    # ------------------------------------------------------------------
    def categoryContent(self, cid, pg, filter, ext):
        result = {}
        videos = []
        try:
            if pg and int(pg) > 1:
                url = f'{xurl}{cid}/{pg}/'
            else:
                url = f'{xurl}{cid}/'

            detail = requests.get(url=url, headers=headerx, timeout=10)
            detail.encoding = "utf-8"
            res = detail.text
            doc = BeautifulSoup(res, "lxml")

            section = doc.find('div', class_="list-videos")
            if section:
                vods = section.find_all(['div', 'article'], class_="item")
                for vod in vods:
                    videos.append(self._parse_item(vod))

        except Exception as e:
            print(f"Error in categoryContent: {str(e)}")

        result = {
            'list': videos,
            'page': pg,
            'pagecount': 9999,
            'limit': 90,
            'total': 999999
        }
        return result

    # ------------------------------------------------------------------
    # 详情
    # ------------------------------------------------------------------
    def detailContent(self, ids):
        global pm
        did = ids[0]
        result = {}
        videos = []
        if 'http' not in did:
            did = xurl + did
        res1 = requests.get(url=did, headers=headerx, timeout=10)
        res1.encoding = "utf-8"
        res = res1.text

        content = '👉' + self.extract_middle_text(res, '<h1>', '</h1>', 0)

        yanuan = self.extract_middle_text(
            res, '<span>Pornstars:</span>', '</div>', 1,
            'href=".*?">(.*?)</a>'
        )

        bofang = did

        videos.append({
            "vod_id": did,
            "vod_actor": yanuan,
            "vod_director": '',
            "vod_content": content,
            "vod_play_from": '💗FullHD💗',
            "vod_play_url": bofang
        })

        result['list'] = videos
        return result

    # ------------------------------------------------------------------
    # 播放（优化：Session 复用 + 正则解析 + 单连接跟跳转）
    # ------------------------------------------------------------------
    def playerContent(self, flag, id, vipFlags):
        if 'http' not in id:
            id = xurl + id

        headers = dict(headerx)
        headers['Referer'] = id

        try:
            with requests.Session() as s:
                s.headers.update(headers)

                res = s.get(id, timeout=10).text

                # 优先正则抓 source
                m = re.search(r'<source[^>]+src=["\']([^"\']+)["\']', res)
                if not m:
                    # KVS 兜底：flashvars 里的 video_url
                    m = re.search(r'video_url\s*[:=]\s*["\']([^"\']+)["\']', res)
                if not m:
                    return {"parse": 0, "playUrl": '', "url": '', "header": headerx}

                src_value = m.group(1)
                if src_value.startswith('//'):
                    src_value = 'https:' + src_value
                elif not src_value.startswith('http'):
                    src_value = xurl + src_value.lstrip('/')

                # 同一 Session 内最多跟 3 跳
                final_url = src_value
                for _ in range(3):
                    r = s.head(final_url, allow_redirects=False, timeout=5)
                    if r.status_code in (301, 302, 303, 307, 308):
                        loc = r.headers.get('Location')
                        if loc:
                            final_url = loc
                            continue
                    break

            return {
                "parse": 0,
                "playUrl": '',
                "url": final_url,
                "header": headerx
            }
        except Exception as e:
            print(f"Error in playerContent: {str(e)}")
            return {"parse": 0, "playUrl": '', "url": '', "header": headerx}

    # ------------------------------------------------------------------
    # 搜索
    # ------------------------------------------------------------------
    def searchContentPage(self, key, quick, page):
        result = {}
        videos = []
        if not page:
            page = '1'
        if page == '1':
            url = f'{xurl}search/{key}/'
        else:
            url = f'{xurl}search/{key}/{str(page)}/'

        try:
            detail = requests.get(url=url, headers=headerx, timeout=10)
            detail.encoding = "utf-8"
            res = detail.text
            doc = BeautifulSoup(res, "lxml")

            section = doc.find('div', class_="list-videos")
            if section:
                vods = section.find_all(['div', 'article'], class_="item")
                for vod in vods:
                    videos.append(self._parse_item(vod))
        except Exception as e:
            print(f"Error in searchContentPage: {str(e)}")

        result = {
            'list': videos,
            'page': page,
            'pagecount': 9999,
            'limit': 90,
            'total': 999999
        }
        return result

    def searchContent(self, key, quick):
        return self.searchContentPage(key, quick, '1')

    def localProxy(self, params):
        if params['type'] == "m3u8":
            return self.proxyM3u8(params)
        elif params['type'] == "media":
            return self.proxyMedia(params)
        elif params['type'] == "ts":
            return self.proxyTs(params)
        return None
