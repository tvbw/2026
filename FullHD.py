# -*- coding: utf-8 -*-
import sys
import re
import json
import time
import requests
from urllib.parse import quote

sys.path.append('..')
try:
    from base.spider import Spider
except ImportError:
    class Spider:
        def fetch(self, url, headers=None, **kw):
            import requests as rq
            kw.pop('timeout', None)
            r = rq.get(url, headers=headers, timeout=15, **kw)
            r.encoding = 'utf-8'
            return r

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"
HOSTS = ["https://www.fullhd.to", "https://www.fullhd.xxx"]
HOST = HOSTS[0]
_CATS = None
_SKIP = {'vr-virtual-reality', 'danish', 'iranian', 'shemale-3p', 'shemale-fuck', 'partner-show', 'shemale-threesome', 'chinese'}


class Spider(Spider):
    def init(self, extend=""):
        global HOST, _CATS
        _CATS = None
        self._sess = None
        self._pinfo = None
        ext = (extend or '').strip()
        if ext.startswith('http'):
            HOST = ext.rstrip('/')
            return
        for d in HOSTS:
            try:
                r = self.fetch(d + '/zh/', headers={"User-Agent": UA}, timeout=10000)
                u = getattr(r, 'url', '') or ''
                m = re.match(r'(https?://[^/]+)', u)
                if m:
                    HOST = m.group(1).rstrip('/')
                    return
                if getattr(r, 'status_code', 0) == 200:
                    HOST = d
                    return
            except:
                pass
        HOST = HOSTS[0]

    def _cats(self):
        global _CATS
        if _CATS:
            return _CATS
        try:
            r = self.fetch(f"{HOST}/zh/categories/", headers={"User-Agent": UA}, timeout=20000)
            h = r.text if hasattr(r, 'text') else str(r)
            cats, seen = [], set()
            for m in re.finditer(r'href="[^"]*/zh/categories/([a-z0-9-]+)/"[^>]*title="([^"]+)"', h):
                s, n = m.group(1), m.group(2).strip()
                if s in seen or s in _SKIP:
                    continue
                seen.add(s)
                if n.count('（') > n.count('）'):
                    n = n.split('（')[0].strip()
                if n.count('(') > n.count(')'):
                    n = n.split('(')[0].strip()
                if re.search(r'[\u3040-\u30ff]', n):
                    n = s.replace('-', ' ').title()
                if n:
                    cats.append({"type_id": s, "type_name": n})
            _CATS = cats[:40] or [{"type_id": "latest-updates", "type_name": "最新更新"}]
        except:
            _CATS = [{"type_id": "latest-updates", "type_name": "最新更新"}]
        return _CATS

    def homeContent(self, filter=False):
        return {"class": self._cats(), "list": []}

    def homeVideoContent(self):
        try:
            r = self.fetch(f"{HOST}/zh/latest-updates/", headers={"User-Agent": UA}, timeout=30000)
            h = r.text if hasattr(r, 'text') else str(r)
            return {"list": self._items(h)}
        except:
            return {"list": []}

    def categoryContent(self, tid, pg=1, filter=False, extend=""):
        pn = 1
        try:
            pn = max(int(str(pg)), 1)
        except:
            pass
        try:
            url = f"{HOST}/zh/categories/{tid}/" if pn <= 1 else f"{HOST}/zh/categories/{tid}/{pn}/"
            r = self.fetch(url, headers={"User-Agent": UA}, timeout=30000)
            h = r.text if hasattr(r, 'text') else str(r)
            items = self._items(h)
            return {
                "page": pn,
                "pagecount": self._pagecount(h, pn),
                "limit": 24,
                "total": len(items),
                "list": items
            }
        except:
            return {"page": pn, "pagecount": 1, "limit": 24, "total": 0, "list": []}

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