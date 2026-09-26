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

xurl = "https://www.fullhd.to/zh/"

headerx = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 6.1; WOW64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/50.0.2661.87 Safari/537.36'
}

# 创建全局会话对象，复用连接
session = requests.Session()
session.headers.update(headerx)

pm = ''

class Spider(Spider):
    global xurl
    global headerx
    global session

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

    def get_image_url(self, vod_element):
        """统一处理图片URL获取，优化加载速度"""
        # 优先查找lazyload图片
        img = vod_element.find('img', class_="lazyload")
        if img and img.get('data-src'):
            pic = img['data-src']
        else:
            # 其次查找普通图片
            img = vod_element.find('img', class_="thumb_img")
            if img and img.get('src'):
                pic = img['src']
            else:
                # 最后查找任何图片标签
                img = vod_element.find('img')
                pic = img.get('src') if img else ""
        
        # 统一处理图片URL
        if pic:
            if pic.startswith('//'):
                pic = 'https:' + pic
            elif pic.startswith('/'):
                pic = xurl.rstrip('/') + pic
            elif not pic.startswith('http'):
                pic = xurl.rstrip('/') + '/' + pic.lstrip('/')
        
        return pic

    def homeContent(self, filter):
        result = {}
        result = {"class": [
       {"type_id": "latest-updates", "type_name": "新"},
        {"type_id": "top-rated", "type_name": "佳"},
        {"type_id": "most-popular", "type_name": "热"},
        {"type_id": "sites/kink-classics/", "type_name": "King"},
        {"type_id": "sites/vk-studio/", "type_name": "肛专"},
        {"type_id": "categories/anal-orgasm/", "type_name": "肛射"},
        {"type_id": "categories/anal/", "type_name": "休闲"},
        {"type_id": "sites/glory-hole/", "type_name": "墙洞"},
        {"type_id": "categories/gangbang/", "type_name": "群交"},
        {"type_id": "sites/kink-classics/", "type_name": "群干"},
        {"type_id": "categories/pov/", "type_name": "乳"},
        {"type_id": "categories/horror/", "type_name": "恐"},
        {"type_id": "sites/device-bondage/", "type_name": "虐"},
        {"type_id": "categories/pregnant/", "type_name": "孕"}, 
        {"type_id": "categories/19-years-old/", "type_name": "嫩"},
        {"type_id": "categories/granny/", "type_name": "奶"},
        {"type_id": "categories/grandpa/", "type_name": "爷"},
        {"type_id": "categories/gagging", "type_name": "重"},
        {"type_id": "categories/yoga", "type_name": "瑜伽"},
        {"type_id": "categories/maid", "type_name": "女佣"},
       {"type_id": "categories/rough-sex", "type_name": "粗暴"},
        {"type_id": "categories/mmf/", "type_name": "群3"},
        {"type_id": "categories/mmmf", "type_name": "群5"},
       {"type_id": "categories/oiled/", "type_name": "推油"},
        {"type_id": "sites/pure-mature/", "type_name": "追"}, 
        {"type_id": "categories/ass-to-mouth", "type_name": "肛口"},
       {"type_id": "categories/anal-play", "type_name": "肛游"},
        {"type_id": "categories/first-anal", "type_name": "肛初"},
        {"type_id": "categories/striptease", "type_name": "脱衣"},
        {"type_id": "categories/mom", "type_name": "妈妈"},
        {"type_id": "female-orgasm", "type_name": "高潮"},
        {"type_id": "categories/cougar", "type_name": "徐娘"},
        {"type_id": "categories/doctor", "type_name": "原画"},
        {"type_id": "categories/jav-uncensored", "type_name": "日本"},
        {"type_id": "categories/ffm", "type_name": "4人"},
        {"type_id": "categories/cheating", "type_name": "出轨"},
        {"type_id": "categories/threesome", "type_name": "三人"},
        {"type_id": "categories/public", "type_name": "公共"},
        {"type_id": "categories/swap", "type_name": "互换"},
        {"type_id": "categories/cumplay", "type_name": "多人"},
        {"type_id": "categories/stepmom", "type_name": "继母"},
        {"type_id": "categories/police", "type_name": "警察"},
        {"type_id": "categories/group-sex", "type_name": "集体"},
        {"type_id": "categories/flogging", "type_name": "鞭打"},
        {"type_id": "networks/brazzers-com/", "type_name": "Br"},
        {"type_id": "networks/private/", "type_name": "PR"},
        {"type_id": "networks/bangbros", "type_name": "Ba"},
        {"type_id": "networks/blacked/", "type_name": "Bl"},
        {"type_id": "networks/tushy-com/", "type_name": "Tu"},
        {"type_id": "networks/mylf-com", "type_name": "My"},
        {"type_id": "sites/my-dirty-maid/", "type_name": "Ma"},
        {"type_id": "categories/shaved/", "type_name": "剃毛"},
        {"type_id": "categories/slave/", "type_name": "奴"},
        {"type_id": "categories/cumshot/", "type_name": "内"},
        {"type_id": "categories/creampie/", "type_name": "体"},

        {"type_id": "sites/fake-taxi/", "type_name": "车"}, 
        {"type_id": "sites/passion-hd/", "type_name": "Pa"},
        {"type_id": "sites/lubed/", "type_name": "Lu"},
        {"type_id": "sites/tiny-4k/", "type_name": "T4K"},
        {"type_id": "sites/exotic-4k/", "type_name": "E4K"},
        {"type_id": "categories/jav-uncensored", "type_name": "JAV"},
        {"type_id": "categories/beach/", "type_name": "Be"},
        {"type_id": "networks/teamskeet-com", "type_name": "Tk"},
        {"type_id": "networks/tushy-com", "type_name": "Tu"},
        {"type_id": "networks/mofos-com", "type_name": "Mo"},
        {"type_id": "networks/private", "type_name": "Pr"},
        {"type_id": "networks/rk-com", "type_name": "Rk"},
        {"type_id": "sites/latina-girlx/", "type_name": "拉丁"},
        {"type_id": "sites/blacked/", "type_name": "黑白1"},
        {"type_id": "categories/bbc-big-black-cock/", "type_name": "黑白2"},
        {"type_id": "sites/stranded-teens/", "type_name": "外"},
        {"type_id": "categories/double-penetration/", "type_name": "双1"},
        {"type_id": "sites/dp-fanatics/", "type_name": "双2"},
        {"type_id": "categories/ass-fingering/", "type_name": "指"}, 
        {"type_id": "categories/fisting/", "type_name": "拳"},
        {"type_id": "categories/squirt/", "type_name": "潮"},
       {"type_id": "categories/double-pussy/", "type_name": "双"},
       {"type_id": "categories/bbc-big-black-cock/", "type_name": "屌"},
        {"type_id": "categories/rimming/", "type_name": "舔"},
        {"type_id": "categories/pussy-licking/", "type_name": "屄"},
        {"type_id": "sites/pure-mature/", "type_name": "白白"},
        {"type_id": "categories/gaping/", "type_name": "洞口"},
        {"type_id": "categories/shemale/", "type_name": "人妖"},
        {"type_id": "categories/shemale-fuck-guy/", "type_name": "干男"},
        {"type_id": "categories/shemale-fuck-shemale/", "type_name": "伪娘"},
        {"type_id": "categories/asian/", "type_name": "亚洲"},
        {"type_id": "categories/thai/", "type_name": "泰国"},
        {"type_id": "categories/jav-uncensored/", "type_name": "日本"},
        {"type_id": "categories/italian/", "type_name": "意哥"},
        {"type_id": "categories/brazilian/", "type_name": "巴西"},   
        {"type_id": "categories/mexican/", "type_name": "墨哥"},   
        {"type_id": "categories/latina/", "type_name": "拉美"},   
        {"type_id": "categories/hijab/", "type_name": "穆斯"},    
        {"type_id": "categories/cfnm", "type_name": "cfnm"}, 
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
        videos = []
        try:
            # 使用会话并设置超时
            detail = session.get(url=xurl, timeout=10)
            detail.encoding = "utf-8"
            res = detail.text
            # 使用更快的解析器
            doc = BeautifulSoup(res, "html.parser")

            # 获取视频列表
            section = doc.find('div', id="list_videos_videos_watched_right_now_items")
            if section:
                vods = section.find_all('div', class_="item")
                for vod in vods:
                    # 获取标题和链接
                    link = vod.find('a')
                    if not link:
                        continue
                    
                    name = link.get('title', '').strip()
                    id = link.get('href', '')
                    
                    # 获取图片
                    pic = self.get_image_url(vod)
                    
                    # 获取时长
                    remarks = vod.find('span', class_="duration")
                    remark = remarks.text.strip() if remarks else ""

                    if name:  # 只有有标题的才添加
                        video = {
                            "vod_id": id,
                            "vod_name": name,
                            "vod_pic": pic,
                            "vod_remarks": remark
                        }
                        videos.append(video)

            result = {'list': videos}
            return result
        except Exception as e:
            print(f"Error in homeVideoContent: {str(e)}")
            return {'list': []}

    def categoryContent(self, cid, pg, filter, ext):
        result = {}
        videos = []
        try:
            if pg and int(pg) > 1:
                url = f'{xurl.rstrip("/")}/{cid}/{pg}/'
            else:
                url = f'{xurl.rstrip("/")}/{cid}/'

            # 使用会话并设置超时
            detail = session.get(url=url, timeout=10)
            detail.encoding = "utf-8"
            res = detail.text
            doc = BeautifulSoup(res, "html.parser")

            section = doc.find('div', class_="list-videos")
            if section:
                vods = section.find_all('div', class_="item")
                for vod in vods:
                    link = vod.find('a')
                    if not link:
                        continue
                    
                    name = link.get('title', '').strip()
                    id = link.get('href', '')
                    
                    # 获取图片
                    pic = self.get_image_url(vod)
                    
                    # 获取时长
                    remarks = vod.find('span', class_="duration")
                    remark = remarks.text.strip() if remarks else ""

                    if name:
                        video = {
                            "vod_id": id,
                            "vod_name": name,
                            "vod_pic": pic,
                            "vod_remarks": remark
                        }
                        videos.append(video)

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
        did = ids[0]
        if 'http' not in did:
            did = xurl.rstrip('/') + '/' + did.lstrip('/')
        result = {}
        videos = []
        try:
            headers = dict(headerx)
            headers['Referer'] = xurl
            res1 = session.get(url=did, headers=headers, timeout=15)
            res1.encoding = "utf-8"
            res = res1.text
            doc = BeautifulSoup(res, "html.parser")

            # 标题
            h1 = doc.find('h1')
            name = h1.get_text(strip=True) if h1 else ''

            # 封面
            pic = ''
            m = re.search(r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)', res)
            if m:
                pic = m.group(1)

            # 演员（Pornstars）
            yanuan = ''
            for sp in doc.find_all('span'):
                if 'Pornstars' in sp.get_text():
                    p = sp.parent
                    if p:
                        yanuan = ' '.join(a.get_text(strip=True) for a in p.find_all('a'))
                    break

            # 简介/时长兜底
            content = '👉' + name
            dur = doc.find('span', class_='duration')
            if dur:
                content += '  ⏱' + dur.get_text(strip=True)

            # 关键：vod_play_url 必须 "名字$链接"
            videos.append({
                "vod_id": did,
                "vod_name": name,
                "vod_pic": pic,
                "vod_actor": yanuan,
                "vod_director": '',
                "vod_content": content,
                "vod_play_from": '老僧酿酒',
                "vod_play_url": '播放$' + did,
            })
            result['list'] = videos
            return result
        except Exception as e:
            print(f"Error in detailContent: {str(e)}")
            return {'list': []}

    def playerContent(self, flag, id, vipFlags):
        try:
            # 正确提取 URL
            idx = id.find('http')
            if idx == -1:
                page_url = xurl.rstrip('/') + '/' + id.lstrip('/')
            else:
                page_url = id[idx:]

            headers = dict(headerx)
            headers['Referer'] = page_url

            res = session.get(url=page_url, headers=headers, timeout=15)
            res.encoding = 'utf-8'
            html = res.text

            url = ''

            # 1) KVS flashvars: video_url
            m = re.search(r"video_url\s*[:=]\s*['\"]([^'\"]+)['\"]", html)
            if m:
                url = m.group(1)

            # 2) <source src="...">
            if not url:
                m = re.search(r'<source[^>]+src=["\']([^"\']+)["\']', html)
                if m:
                    url = m.group(1)

            # 3) 兜底：页面里的 m3u8 / mp4
            if not url:
                m = re.search(r'["\'](https?://[^"\']+?\.(?:m3u8|mp4)[^"\']*)["\']', html)
                if m:
                    url = m.group(1)

            if not url:
                print("playerContent: 未找到视频地址")
                return {}

            url = url.replace('\\/', '/').replace('\\', '')
            if url.startswith('//'):
                url = 'https:' + url

            # 跟随重定向
            for _ in range(3):
                try:
                    r = session.head(url, headers=headers, allow_redirects=False, timeout=5)
                    if r.status_code in (301, 302, 303, 307, 308) and 'Location' in r.headers:
                        nxt = r.headers['Location']
                        if nxt.startswith('//'):
                            nxt = 'https:' + nxt
                        elif nxt.startswith('/'):
                            from urllib.parse import urlparse
                            p = urlparse(url)
                            nxt = f"{p.scheme}://{p.netloc}{nxt}"
                        url = nxt
                    else:
                        break
                except Exception:
                    break

            return {
                "parse": 0,
                "playUrl": '',
                "url": url,
                "header": headers,
            }
        except Exception as e:
            print(f"Error in playerContent: {str(e)}")
            return {}

    def searchContentPage(self, key, quick, page):
        result = {}
        videos = []
        if not page:
            page = '1'
        if page == '1':
            url = f'{xurl.rstrip("/")}/search/{key}/'
        else:
            url = f'{xurl.rstrip("/")}/search/{key}/{str(page)}/'

        try:
            detail = session.get(url=url, timeout=10)
            detail.encoding = "utf-8"
            res = detail.text
            doc = BeautifulSoup(res, "html.parser")

            section = doc.find('div', class_="list-videos")
            if section:
                vods = section.find_all('div', class_="item")
                for vod in vods:
                    link = vod.find('a')
                    if not link:
                        continue
                    name = link.get('title', '').strip()
                    id = link.get('href', '')
                    pic = self.get_image_url(vod)
                    remarks = vod.find('span', class_="duration")
                    remark = remarks.text.strip() if remarks else ""
                    if name:
                        videos.append({
                            "vod_id": id,
                            "vod_name": name,
                            "vod_pic": pic,
                            "vod_remarks": remark
                        })
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