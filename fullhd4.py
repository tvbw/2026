import requests
from bs4 import BeautifulSoup
import re
from base.spider import Spider
import sys
import json
import base64
import urllib.parse
import concurrent.futures

sys.path.append('..')

xurl = "https://www.fullhd.to/br/"

headerx = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 6.1; WOW64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/50.0.2661.87 Safari/537.36'
}

pm = ''


class Spider(Spider):
    global xurl
    global headerx

    # 详情页 HTML 缓存 与 直链缓存
    _html_cache = {}
    _src_cache = {}

    def getName(self):
        return "首页"

    def init(self, extend):
        pass

    def isVideoFormat(self, url):
        pass

    def manualVideoCheck(self):
        pass

    # ------------------------------------------------------------------
    # 取图
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
    # 列表项解析
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

    # ------------------------------------------------------------------
    # 并发探活工具
    # ------------------------------------------------------------------
    def _probe_source(self, session, url, headers):
        """用 Range 只取 1 字节，验证该源是否可用；返回 (url, ok)"""
        try:
            r = session.get(
                url,
                headers={**headers, 'Range': 'bytes=0-1'},
                timeout=5,
                stream=True,
                allow_redirects=True,
            )
            code = r.status_code
            r.close()
            return url, code in (200, 206)
        except Exception:
            return url, False

    def _resolve_sources(self, res, page_url, headers):
        """
        从详情页 HTML 中提取所有候选直链，
        多个候选时并发探活，选最先可用的一个返回。
        """
        # 优先 <source src=...>
        urls = re.findall(r'<source[^>]+src=["\']([^"\']+)["\']', res)
        if not urls:
            # KVS 兜底
            urls = re.findall(r'video_url\s*[:=]\s*["\']([^"\']+)["\']', res)

        norm = []
        for u in urls:
            if u.startswith('//'):
                u = 'https:' + u
            elif not u.startswith('http'):
                u = xurl + u.lstrip('/')
            if u not in norm:
                norm.append(u)

        if not norm:
            return ""
        if len(norm) == 1:
            return norm[0]

        # 并发探活，谁先可用用谁
        best = norm[0]
        with requests.Session() as s:
            s.headers.update(headers)
            workers = min(4, len(norm))
            with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as ex:
                futs = {ex.submit(self._probe_source, s, u, headers): u for u in norm}
                for f in concurrent.futures.as_completed(futs):
                    u, ok = f.result()
                    if ok:
                        best = u
                        break
        return best

    # ------------------------------------------------------------------
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
        ]}

    # ------------------------------------------------------------------
    # 首页视频
    # ------------------------------------------------------------------
    def homeVideoContent(self):
        videos = []
        try:
            detail = requests.get(url=xurl, headers=headerx, timeout=10)
            detail.encoding = "utf-8"
            doc = BeautifulSoup(detail.text, "lxml")
            section = doc.find('div', id="list_videos_videos_watched_right_now_items")
            if section:
                for vod in section.find_all(['div', 'article'], class_="item"):
                    videos.append(self._parse_item(vod))
            return {'list': videos}
        except Exception as e:
            print(f"Error in homeVideoContent: {str(e)}")
            return {'list': []}

    # ------------------------------------------------------------------
    # 分类
    # ------------------------------------------------------------------
    def categoryContent(self, cid, pg, filter, ext):
        videos = []
        try:
            url = f'{xurl}{cid}/{pg}/' if (pg and int(pg) > 1) else f'{xurl}{cid}/'
            detail = requests.get(url=url, headers=headerx, timeout=10)
            detail.encoding = "utf-8"
            doc = BeautifulSoup(detail.text, "lxml")
            section = doc.find('div', class_="list-videos")
            if section:
                for vod in section.find_all(['div', 'article'], class_="item"):
                    videos.append(self._parse_item(vod))
        except Exception as e:
            print(f"Error in categoryContent: {str(e)}")

        return {
            'list': videos,
            'page': pg,
            'pagecount': 9999,
            'limit': 90,
            'total': 999999
        }

    # ------------------------------------------------------------------
    # 详情：这里就把直链抓出来缓存
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

        self._html_cache[did] = res

        # 关键：此刻并发探活所有候选源，把直链缓存好
        play_headers = {**headerx, 'Referer': did}
        src = self._resolve_sources(res, did, play_headers)
        self._src_cache[did] = src

        content = '👉' + self.extract_middle_text(res, '<h1>', '</h1>', 0)

        yanuan = self.extract_middle_text(
            res, '<span>Pornstars:</span>', '</div>', 1,
            'href=".*?">(.*?)</a>'
        )

        videos.append({
            "vod_id": did,
            "vod_actor": yanuan,
            "vod_director": '',
            "vod_content": content,
            "vod_play_from": '💗FullHD💗',
            "vod_play_url": f'正片${did}'   # 只显示「正片」按钮
        })

        result['list'] = videos
        return result

    # ------------------------------------------------------------------
    # 播放：零网络请求，直接吐缓存的直链
    # ------------------------------------------------------------------
    def playerContent(self, flag, id, vipFlags):
        if 'http' not in id:
            id = xurl + id

        headers = dict(headerx)
        headers['Referer'] = id
        headers['Origin'] = 'https://www.fullhd.to'

        # 1) 优先用详情页阶段缓存好的直链
        src = self._src_cache.get(id)

        # 2) 缓存失效（比如框架只调了 playerContent）时兜底现场抓一次
        if not src:
            try:
                res = self._html_cache.get(id)
                if res is None:
                    res = requests.get(id, headers=headers, timeout=10).text
                    self._html_cache[id] = res
                src = self._resolve_sources(res, id, headers)
                self._src_cache[id] = src
            except Exception as e:
                print(f"Error resolving src: {str(e)}")
                src = ""

        if not src:
            return {"parse": 0, "playUrl": '', "url": '', "header": headers}

        # 3) 直链返回：parse=0 jx=0 让框架走直连，不再解析不再代理
        return {
            "parse": 0,
            "playUrl": '',
            "url": src,
            "header": headers,
            "jx": 0,
        }

    # ------------------------------------------------------------------
    # 搜索
    # ------------------------------------------------------------------
    def searchContentPage(self, key, quick, page):
        videos = []
        if not page:
            page = '1'
        url = f'{xurl}search/{key}/' if page == '1' else f'{xurl}search/{key}/{str(page)}/'
        try:
            detail = requests.get(url=url, headers=headerx, timeout=10)
            detail.encoding = "utf-8"
            doc = BeautifulSoup(detail.text, "lxml")
            section = doc.find('div', class_="list-videos")
            if section:
                for vod in section.find_all(['div', 'article'], class_="item"):
                    videos.append(self._parse_item(vod))
        except Exception as e:
            print(f"Error in searchContentPage: {str(e)}")

        return {
            'list': videos,
            'page': page,
            'pagecount': 9999,
            'limit': 90,
            'total': 999999
        }

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
