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

xurl = "https://www.fullhd.xxx/zh/"

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
            detail = requests.get(url=xurl, headers=headerx)
            detail.encoding = "utf-8"
            res = detail.text
            doc = BeautifulSoup(res, "lxml")

            # Get videos from different sections
            sections = {
                "latest-updates": "最新视频",
                "top-rated": "最佳视频",
                "most-popular": "热门影片"
            }
            
            for section_id, section_name in sections.items():
                section = doc.find('div', id=f"list_videos_videos_watched_right_now_items")
                if not section:
                    continue
                    
                vods = section.find_all('div', class_="item")
                for vod in vods:
                    names = vod.find_all('a')
                    name = names[0]['title'] if names and 'title' in names[0].attrs else section_name

                    ids = vod.find_all('a')
                    id = ids[0]['href'] if ids else ""

                    pics = vod.find('img', class_="lazyload")
                    pic = pics['data-src'] if pics and 'data-src' in pics.attrs else ""

                    if pic and 'http' not in pic:
                        pic = xurl + pic

                    remarks = vod.find('span', class_="duration")
                    remark = remarks.text.strip() if remarks else ""

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
                url = f'{xurl}/{cid}/{pg}/'
            else:
                url = f'{xurl}/{cid}/'

            detail = requests.get(url=url, headers=headerx)
            detail.encoding = "utf-8"
            res = detail.text
            doc = BeautifulSoup(res, "lxml")

            section = doc.find('div', class_="list-videos")
            if section:
                vods = section.find_all('div', class_="item")
                for vod in vods:
                    names = vod.find_all('a')
                    name = names[0]['title'] if names and 'title' in names[0].attrs else ""

                    ids = vod.find_all('a')
                    id = ids[0]['href'] if ids else ""

                    pics = vod.find('img', class_="lazyload")
                    pic = pics['data-src'] if pics and 'data-src' in pics.attrs else ""

                    if pic and 'http' not in pic:
                        pic = xurl + pic

                    remarks = vod.find('span', class_="duration")
                    remark = remarks.text.strip() if remarks else ""

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
        global pm
        did = ids[0]
        result = {}
        videos = []
        playurl = ''
        if 'http' not in did:
            did = xurl + did
        res1 = requests.get(url=did, headers=headerx)
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
            "vod_play_from": '💗4K💗',
            "vod_play_url": bofang
                     })

        result['list'] = videos
        return result

    def playerContent(self, flag, id, vipFlags):
        parts = id.split("http")
        xiutan = 0
        if xiutan == 0:
            if len(parts) > 1:
                before_https, after_https = parts[0], 'http' + parts[1]
            res = requests.get(url=after_https, headers=headerx)
            res = res.text

            url2 = self.extract_middle_text(res, '<video', '</video>', 0).replace('\\', '')
            soup = BeautifulSoup(url2, 'html.parser')
            first_source = soup.find('source')
            src_value = first_source.get('src')

            response = requests.head(src_value, allow_redirects=False)
            if response.status_code == 302:
                redirect_url = response.headers['Location']

            response = requests.head(redirect_url, allow_redirects=False)
            if response.status_code == 302:
                redirect_url = response.headers['Location']

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
        if page == '1':
            url = f'{xurl}/search/{key}/'
        else:
            url = f'{xurl}/search/{key}/{str(page)}/'

        try:
            detail = requests.get(url=url, headers=headerx)
            detail.encoding = "utf-8"
            res = detail.text
            doc = BeautifulSoup(res, "lxml")

            section = doc.find('div', class_="list-videos")
            if section:
                vods = section.find_all('div', class_="item")
                for vod in vods:
                    names = vod.find_all('a')
                    name = names[0]['title'] if names and 'title' in names[0].attrs else ""

                    ids = vod.find_all('a')
                    id = ids[0]['href'] if ids else ""

                    pics = vod.find('img', class_="lazyload")
                    pic = pics['data-src'] if pics and 'data-src' in pics.attrs else ""

                    if pic and 'http' not in pic:
                        pic = xurl + pic

                    remarks = vod.find('span', class_="duration")
                    remark = remarks.text.strip() if remarks else ""

                    video = {
                        "vod_id": id,
                        "vod_name": name,
                        "vod_pic": pic,
                        "vod_remarks": remark
                    }
                    videos.append(video)
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

# ===== PAGE_PLAYLIST_START =====
def _pl_install(_C):
    if getattr(_C, "_pl_patched", False):
        return _C
    _C._pl_patched = True
    _orig_init = getattr(_C, "init", None)
    _orig_home = getattr(_C, "homeContent", None)
    _orig_homev = getattr(_C, "homeVideoContent", None)
    _orig_cate = getattr(_C, "categoryContent", None)
    _orig_detail = getattr(_C, "detailContent", None)
    _orig_search = getattr(_C, "searchContent", None)
    _orig_searchp = getattr(_C, "searchContentPage", None)
    _orig_player = getattr(_C, "playerContent", None)

    def _ensure(self):
        if not hasattr(self, "page_cache"):
            self.page_cache = {}
            self.page_index = {}
            self.page_keys = []
            self._src_cache = {}

    def _clean(s):
        return str(s or "").replace("$", " ").replace("#", " ").strip()

    def _enc(s):
        try:
            from urllib.parse import quote
            return quote(str(s or ""), safe="")
        except Exception:
            return str(s or "")

    def _dec(s):
        try:
            from urllib.parse import unquote
            return unquote(str(s or ""))
        except Exception:
            return str(s or "")

    def _cache_page(self, key, items):
        _ensure(self)
        out = []
        for x in items or []:
            if isinstance(x, dict) and x.get("vod_id"):
                out.append(x)
        if not out:
            return
        self.page_cache[key] = out
        if key in self.page_keys:
            self.page_keys.remove(key)
        self.page_keys.append(key)
        for it in out:
            self.page_index[str(it["vod_id"])] = key
        while len(self.page_keys) > 30:
            old = self.page_keys.pop(0)
            self.page_cache.pop(old, None)

    def _page_of(self, vid):
        _ensure(self)
        key = self.page_index.get(str(vid))
        if key in self.page_cache:
            return list(self.page_cache[key])
        return []

    def _as_result(r):
        if r is None:
            return {}
        if isinstance(r, dict):
            return r
        if isinstance(r, (bytes, bytearray)):
            r = r.decode("utf-8", "ignore")
        if isinstance(r, str):
            s = r.strip()
            if s.startswith("{") or s.startswith("["):
                try:
                    import json as _j
                    return _j.loads(s)
                except Exception:
                    return {}
        return {}

    def _split_sources(vod):
        fr = str((vod or {}).get("vod_play_from") or "").split("$$$")
        ur = str((vod or {}).get("vod_play_url") or "").split("$$$")
        while len(ur) < len(fr):
            ur.append("")
        sources = []
        for i, name in enumerate(fr):
            parts = []
            for p in (ur[i] or "").split("#"):
                if not p:
                    continue
                if "$" in p:
                    n, u = p.split("$", 1)
                else:
                    n, u = str(i + 1), p
                parts.append((_clean(n), u))
            sources.append((_clean(name) or ("线路%d" % (i + 1)), parts))
        return [x for x in sources if x[1]]

    def _call_detail(self, vid):
        if not _orig_detail:
            return {}
        try:
            return _as_result(_orig_detail(self, [vid]))
        except TypeError:
            try:
                return _as_result(_orig_detail(self, vid))
            except Exception:
                return {}
        except Exception:
            return {}

    def _load_src(self, vid):
        _ensure(self)
        vid = str(vid)
        if vid in self._src_cache:
            return self._src_cache[vid]
        r = self._pl_call_detail(vid)
        vod = ((r.get("list") or [None])[0]) or {}
        sources = _split_sources(vod)
        self._src_cache[vid] = sources
        return sources

    def _item_parts(self, it, src_idx, current_sources, current_vid):
        iid = str(it.get("vod_id") or "")
        if not iid:
            return []
        name = _clean(it.get("vod_name") or iid) or iid
        if iid == str(current_vid):
            eps = []
            if current_sources:
                if src_idx < len(current_sources) and current_sources[src_idx][1]:
                    eps = current_sources[src_idx][1]
                else:
                    eps = current_sources[0][1]
            if len(eps) > 1:
                out = []
                for i, (en, u) in enumerate(eps):
                    label = _clean("%s %s" % (name, en or ("%02d" % (i + 1))))
                    out.append("%s$%s" % (label, u))
                return out
            if eps:
                return ["%s$%s" % (name, eps[0][1])]
            return ["%s$nid:%s" % (name, _enc(iid))]
        return ["%s$nid:%s" % (name, _enc(iid))]

    def _apply_playlist(self, vid, vod, items):
        sources = _split_sources(vod)
        _ensure(self)
        self._src_cache[str(vid)] = sources
        if not items:
            return vod
        ordered = [x for x in items if str(x.get("vod_id")) == str(vid)]
        ordered += [x for x in items if str(x.get("vod_id")) != str(vid)]
        plist, seen = [], set()
        for it in ordered:
            iid = str(it.get("vod_id") or "")
            if not iid or iid in seen:
                continue
            seen.add(iid)
            plist.append(it)
        if not plist:
            return vod
        if not sources:
            sources = [("线路1", [("播放", "nid:%s" % _enc(vid))])]
        play_from, play_urls = [], []
        for i, (sname, _eps) in enumerate(sources):
            parts = []
            for it in plist:
                parts.extend(self._pl_item_parts(it, i, sources, vid))
            if not parts:
                continue
            play_from.append(sname or ("线路%d" % (i + 1)))
            play_urls.append("#".join(parts))
        if not play_from:
            return vod
        vod = dict(vod)
        vod["vod_play_from"] = "$$$".join(play_from)
        vod["vod_play_url"] = "$$$".join(play_urls)
        return vod

    def init(self, *args, **kwargs):
        _ensure(self)
        if _orig_init:
            return _orig_init(self, *args, **kwargs)

    def homeContent(self, *args, **kwargs):
        _ensure(self)
        r = _orig_home(self, *args, **kwargs) if _orig_home else {}
        try:
            _cache_page(self, ("home",), _as_result(r).get("list"))
        except Exception:
            pass
        return r

    def homeVideoContent(self, *args, **kwargs):
        _ensure(self)
        r = _orig_homev(self, *args, **kwargs) if _orig_homev else {"list": []}
        try:
            _cache_page(self, ("homev",), _as_result(r).get("list"))
        except Exception:
            pass
        return r

    def categoryContent(self, *args, **kwargs):
        _ensure(self)
        r = _orig_cate(self, *args, **kwargs) if _orig_cate else {"list": []}
        try:
            tid = args[0] if args else kwargs.get("tid", "")
            pg = args[1] if len(args) > 1 else kwargs.get("pg", "1")
            ext = args[3] if len(args) > 3 else kwargs.get("extend", "")
            _cache_page(self, ("cate", str(tid), str(pg), str(ext)), _as_result(r).get("list"))
        except Exception:
            pass
        return r

    def searchContent(self, *args, **kwargs):
        _ensure(self)
        if not _orig_search:
            return {"list": []}
        r = _orig_search(self, *args, **kwargs)
        try:
            key = args[0] if args else kwargs.get("key", "")
            pg = args[2] if len(args) > 2 else kwargs.get("pg", "1")
            _cache_page(self, ("search", str(key), str(pg)), _as_result(r).get("list"))
        except Exception:
            pass
        return r

    def searchContentPage(self, *args, **kwargs):
        _ensure(self)
        if not _orig_searchp:
            return {"list": []}
        r = _orig_searchp(self, *args, **kwargs)
        try:
            key = args[0] if args else kwargs.get("key", "")
            pg = args[2] if len(args) > 2 else kwargs.get("page", kwargs.get("pg", "1"))
            _cache_page(self, ("searchp", str(key), str(pg)), _as_result(r).get("list"))
        except Exception:
            pass
        return r

    def detailContent(self, ids, *args, **kwargs):
        _ensure(self)
        if isinstance(ids, (list, tuple)):
            vid = str(ids[0]) if ids else ""
            call_ids = list(ids)
        else:
            vid = str(ids)
            call_ids = [vid]
        if vid.startswith("nid:"):
            vid = _dec(vid[4:])
            call_ids[0] = vid
        cached = _page_of(self, vid)
        if _orig_detail:
            try:
                r = _orig_detail(self, call_ids, *args, **kwargs)
            except TypeError:
                r = _orig_detail(self, call_ids)
        else:
            r = {"list": []}
        try:
            rr = _as_result(r)
            lst = rr.get("list") or []
            if not lst or not isinstance(lst[0], dict):
                return r
            vod = dict(lst[0])
            vod["vod_id"] = str(vod.get("vod_id") or vid)
            if not vod.get("vod_name"):
                hit = next((x for x in cached if str(x.get("vod_id")) == vid), None)
                if hit:
                    vod["vod_name"] = hit.get("vod_name") or vid
            if cached:
                vod = self._pl_apply_playlist(vid, vod, cached)
            rr = dict(rr)
            rr["list"] = [vod]
            if isinstance(r, dict) or r is None:
                return rr
            try:
                import json as _j
                return _j.dumps(rr, ensure_ascii=False)
            except Exception:
                return rr
        except Exception:
            return r

    def playerContent(self, flag, id, vipFlags=None, *args, **kwargs):
        _ensure(self)
        s = str(id)
        if s.startswith("nid:"):
            vid = _dec(s[4:])
            sources = self._pl_load_src(vid)
            real = ""
            if sources:
                picked = None
                for name, eps in sources:
                    if str(name) == str(flag) and eps:
                        picked = eps
                        break
                if not picked:
                    picked = sources[0][1]
                if picked:
                    real = picked[0][1]
            if real and not str(real).startswith("nid:"):
                id = real
            else:
                id = vid
        if not _orig_player:
            return {"parse": 0, "url": id}
        try:
            return _orig_player(self, flag, id, vipFlags, *args, **kwargs)
        except TypeError:
            try:
                return _orig_player(self, flag, id, vipFlags)
            except TypeError:
                return _orig_player(self, flag, id)

    _C._pl_call_detail = _call_detail
    _C._pl_load_src = _load_src
    _C._pl_item_parts = _item_parts
    _C._pl_apply_playlist = _apply_playlist
    if _orig_init:
        _C.init = init
    if _orig_home:
        _C.homeContent = homeContent
    if _orig_homev:
        _C.homeVideoContent = homeVideoContent
    if _orig_cate:
        _C.categoryContent = categoryContent
    if _orig_search:
        _C.searchContent = searchContent
    if _orig_searchp:
        _C.searchContentPage = searchContentPage
    if _orig_detail:
        _C.detailContent = detailContent
    if _orig_player:
        _C.playerContent = playerContent
    return _C

try:
    _pl_install(Spider)
except Exception:
    pass
# ===== PAGE_PLAYLIST_END =====