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
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
    'Accept-Language': 'en-US,en;q=0.9',
    'Referer': 'https://www.fullhd.to/'
          }

pm = ''

def _abs(u):
    if not u:
        return ''
    if u.startswith('http'):
        return u
    return 'https://www.fullhd.to/' + u.lstrip('/')

class Spider(Spider):
    global xurl
    global headerx

    def __init__(self):
        # 连接复用，显著降低请求延迟
        self.session = requests.Session()
        self.session.headers.update(headerx)

    def getName(self):
        return "首页"

    def init(self, extend):
        pass

    def isVideoFormat(self, url):
        pass

    def manualVideoCheck(self):
        pass

    def extract_middle_text(self, text, start_str, end_str, pl, start_index1: str = '', end_index2: str = ''):
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

    # ---------- 通用列表解析（修复分栏海报信息） ----------
    def parse_list(self, doc):
        videos = []
        section = doc.find('div', class_="list-videos")
        vods = section.find_all('div', class_="item") if section else doc.find_all('div', class_="item")
        for vod in vods:
            a = vod.find('a')
            if not a or not a.get('href'):
                continue
            vid = _abs(a['href'])
            # 标题：优先 title 属性，其次 h3/h2，最后链接文本
            name = a.get('title') or ''
            if not name:
                h = vod.find(['h3', 'h2'])
                name = h.get_text(strip=True) if h else a.get_text(strip=True)
            img = vod.find('img')
            pic = ''
            if img:
                pic = img.get('data-src') or img.get('data-original') or img.get('src') or ''
            pic = _abs(pic)
            # 时长角标：不限定标签名（分类页是 div.duration，首页是 span.duration）
            remark = ''
            rem = vod.find(class_="duration") or vod.find(class_="length")
            if rem:
                remark = rem.get_text(strip=True)
            if not remark:
                m = re.search(r'(\d{1,3}:\d{2})', vod.get_text())
                if m:
                    remark = m.group(1)
            videos.append({
                "vod_id": vid,
                "vod_name": name,
                "vod_pic": pic,
                "vod_remarks": remark
            })
        return videos

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

    def homeVideoContent(self):
        try:
            detail = self.session.get(url=xurl, timeout=15)
            detail.encoding = "utf-8"
            doc = BeautifulSoup(detail.text, "lxml")
            section = doc.find('div', id="list_videos_videos_watched_right_now_items")
            videos = self.parse_list(section) if section else []
            result = {'list': videos}
            return result
        except Exception as e:
            print(f"Error in homeVideoContent: {str(e)}")
            return {'list': []}

    def categoryContent(self, cid, pg, filter, ext):
        result = {}
        videos = []
        try:
            pg = int(pg) if pg else 1
            # 修复双斜杠 URL（原 xurl 末尾带 / 又拼 / 导致 br//xxx）
            base = xurl.rstrip('/')
            url = f'{base}/{cid}/' if pg <= 1 else f'{base}/{cid}/{pg}/'
            detail = self.session.get(url=url, timeout=15)
            detail.encoding = "utf-8"
            doc = BeautifulSoup(detail.text, "lxml")
            videos = self.parse_list(doc)
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

    def detailContent(self, ids):
        global pm
        did = ids[0]
        result = {}
        videos = []
        playurl = ''
        if 'http' not in did:
            did = _abs(did)
        res1 = self.session.get(url=did, timeout=15)
        res1.encoding = "utf-8"
        res = res1.text

        content = '👉' + self.extract_middle_text(res,'<h1>','</h1>', 0)

        yanuan = self.extract_middle_text(res, '<span>Pornstars:</span>','</div>',1, 'href=".*?">(.*?)</a>')

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

    def playerContent(self, flag, id, vipFlags):
        parts = id.split("http")
        xiutan = 0
        if len(parts) < 2:
            # 原代码此处未判空，非 http 链接会 NameError
            return {"parse": 1, "playUrl": "", "url": id, "header": headerx}
        after_https = 'http' + parts[1]
        res = self.session.get(url=after_https, timeout=15)
        res = res.text

        url2 = self.extract_middle_text(res, '<video', '</video>', 0).replace('\\', '')
        soup = BeautifulSoup(url2, 'html.parser')
        first_source = soup.find('source')
        src_value = first_source.get('src')

        # 优化：一次请求跟随全部重定向（原来是两次串行 HEAD，且每次新建 TCP 连接）
        redirect_url = src_value
        try:
            response = self.session.head(src_value, allow_redirects=True, timeout=15)
            redirect_url = response.url
        except Exception:
            try:
                response = self.session.get(src_value, allow_redirects=True, timeout=15, stream=True)
                redirect_url = response.url
            except Exception:
                redirect_url = src_value

        result = {}
        result["parse"] = xiutan
        result["playUrl"] = ''
        result["url"] = redirect_url
        result["header"] = headerx
        return result

    def searchContentPage(self, key, quick, page):
        result = {}
        videos = []
        if not page:
            page = '1'
        base = xurl.rstrip('/')
        url = f'{base}/search/{key}/' if page == '1' else f'{base}/search/{key}/{str(page)}/'

        try:
            detail = self.session.get(url=url, timeout=15)
            detail.encoding = "utf-8"
            doc = BeautifulSoup(detail.text, "lxml")
            videos = self.parse_list(doc)
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
