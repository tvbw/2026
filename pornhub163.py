#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Pornhub163  https://cn.pornhub163.net
需 cookie x-index-auth=authed，列表 /video，播放 /embed/{viewkey} 取 m3u8
"""
import json
import re
import subprocess
import urllib.parse
import urllib.request

try:
    import requests
except ImportError:
    requests = None

try:
    from base.spider import Spider as BaseSpider
except ImportError:
    class BaseSpider:
        def init(self, extend=""):
            pass


HOST = "https://cn.pornhub163.net"
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)

# 分类：常用 c= 与 path（静态保证有数据）
CHANNELS = [
    ("video", "最新"),
    ("video?o=ht", "当前热门"),
    ("video?o=mv", "最多观看"),
    ("video?o=tr", "最高评分"),
    ("video?c=27", "少女"),
    ("video?c=29", "熟女"),
    ("video?c=35", "女同"),
    ("video?c=65", "素人"),
    ("video?c=28", "亚洲"),
    ("video?c=17", "日本AV"),
    ("video?c=111", "中文"),
    ("video?c=8", "按摩"),
    ("video?c=22", "口交"),
    ("video?c=24", "三人"),
    ("video?c=10", "角色扮演"),
    ("video?c=15", "颜射"),
    ("video?c=7", "肛交"),
    ("video?c=69", "自慰"),
    ("video?c=80", "群交"),
    ("video?c=86", "双飞"),
    ("video?c=181", "幕后"),
    ("categories/teen", "Teen"),
    ("categories/hentai", "Hentai"),
    ("gayporn", "男同"),
    ("lesbian", "女同频道"),
    ("recommended", "推荐"),
    ("shorties", "短视频"),
]


class Spider(BaseSpider):
    def __init__(self):
        self.session = None

    def getName(self):
        return "Pornhub163"

    def init(self, extend=""):
        self.session = None

    def _sess(self):
        if self.session is not None:
            return self.session
        if requests is None:
            return None
        s = requests.Session()
        s.headers.update({
            "User-Agent": UA,
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Referer": HOST + "/enter",
        })
        s.cookies.set("x-index-auth", "authed", domain="cn.pornhub163.net", path="/")
        s.cookies.set("accessAgeDisclaimerPH", "1", domain="cn.pornhub163.net", path="/")
        s.cookies.set("accessAgeDisclaimerUA", "1", domain="cn.pornhub163.net", path="/")
        self.session = s
        return s

    def _headers(self):
        return {
            "User-Agent": UA,
            "Referer": HOST + "/enter",
            "Accept-Language": "zh-CN,zh;q=0.9",
            "Accept": "text/html,application/xhtml+xml,*/*",
        }

    def _solve_key(self, html):
        if not html or "leastFactor" not in html:
            return None
        m = re.search(r"<script[^>]*>([\s\S]*?leastFactor[\s\S]*?)</script>", html)
        if not m:
            return None
        js = m.group(1)
        js = js.replace("if (typeof phantom !== 'undefined') return 'phantom';", "")
        js = js.replace("if (typeof module !== 'undefined' && module.exports) return 'node';", "")
        js += (
            "\nvar cookieStore='';var document={set cookie(v){cookieStore=v;},"
            "get cookie(){return cookieStore;},location:{reload:function(){}}};"
            "go();console.log(cookieStore);"
        )
        try:
            out = subprocess.check_output(["node", "-e", js], text=True, timeout=10).strip()
            if "KEY=" in out:
                return out.split("KEY=")[-1].split(";")[0]
        except Exception as e:
            print("solve key err", e)
        return None

    def fetch_text(self, url, retry=2):
        if not url.startswith("http"):
            url = HOST + (url if url.startswith("/") else "/" + url)
        s = self._sess()
        for _ in range(retry + 1):
            try:
                if s is not None:
                    r = s.get(url, timeout=25, verify=False)
                    text = r.text or ""
                    if "leastFactor" in text and len(text) < 8000:
                        key = self._solve_key(text)
                        if key:
                            s.cookies.set("KEY", key, domain="cn.pornhub163.net", path="/")
                            continue
                    return text
                req = urllib.request.Request(url, headers=self._headers())
                with urllib.request.urlopen(req, timeout=25) as resp:
                    return resp.read().decode("utf-8", "ignore")
            except Exception as e:
                print("fetch err", url, e)
        return ""

    def _clean(self, t):
        t = re.sub(r"<[^>]+>", "", str(t or ""))
        t = (
            t.replace("&amp;", "&")
            .replace("&#039;", "'")
            .replace("&quot;", '"')
            .replace("&nbsp;", " ")
        )
        return re.sub(r"\s+", " ", t).strip()

    def     def _fix_pic(self, u):
        if not u:
            return ""
        u = str(u).strip().replace("\\/", "/").replace("&amp;", "&")
        if u.startswith("//"):
            u = "https:" + u
        elif u.startswith("/"):
            u = HOST + u
        elif not u.startswith("http"):
            u = HOST + "/" + u.lstrip("/")
        if u.startswith(("data:", "blob:")):
            return ""
        return u

    def _pick_pic(self, block):
        pats = [
            r'data-mediumthumb=["\']([^"\']+)',
            r'data-thumb_url=["\']([^"\']+)',
            r'data-image=["\']([^"\']+)',
            r'data-src=["\']([^"\']+)',
            r'data-original=["\']([^"\']+)',
            r'data-lazy-src=["\']([^"\']+)',
            r'data-webp=["\']([^"\']+)',
            r'poster=["\']([^"\']+)',
            r'srcset=["\']([^"\']+)',
            r'src=["\']([^"\']+)',
        ]
        bad = (
            "logo", "avatar", "blank", "placeholder",
            "spacer", "1x1", "data:image", "pixel"
        )
        for p in pats:
            for m in re.finditer(p, block or "", re.I):
                raw = m.group(1)
                if p.startswith("srcset"):
                    raw = raw.split(",")[-1].strip().split(" ")[0]
                u = self._fix_pic(raw)
                if u and not any(b in u.lower() for b in bad):
                    return u
        return ""

    def _list_url(self, tid, pg):
        pg = int(pg or 1)
        tid = str(tid or "video").strip()
        if tid in ("home", "latest", ""):
            tid = "video"
        if tid.startswith("http"):
            base = tid
        elif tid.startswith("/"):
            base = HOST + tid
        else:
            base = HOST + "/" + tid
        if pg <= 1:
            return base
        sep = "&" if "?" in base else "?"
        return base + sep + "page=%d" % pg

    def homeContent(self, filter=False):
        classes = [{"type_id": c[0], "type_name": c[1]} for c in CHANNELS]
        return {"class": classes, "list": [], "filters": {}}

    def homeVideoContent(self):
        html = self.fetch_text(HOST + "/video")
        if len(html) < 5000:
            html = self.fetch_text(HOST + "/enter")
        return {"list": self._parse_list(html)[:40]}

    def categoryContent(self, tid, pg, filter=False, extend=None):
        pg = int(pg or 1)
        url = self._list_url(tid, pg)
        html = self.fetch_text(url)
        videos = self._parse_list(html)
        return {
            "list": videos,
            "page": pg,
            "pagecount": pg + 1 if len(videos) >= 15 else max(pg, 1),
            "limit": 36,
            "total": 9999 if videos else 0,
        }

    def searchContent(self, key, quick=False, pg=1):
        return self.searchContentPage(key, quick, pg)

    def searchContentPage(self, key, quick=False, pg=1):
        pg = int(pg or 1)
        q = urllib.parse.quote(str(key or "").strip())
        if not q:
            return {"list": [], "page": 1, "pagecount": 1, "limit": 24, "total": 0}
        url = HOST + "/video/search?search=%s" % q
        if pg > 1:
            url += "&page=%d" % pg
        html = self.fetch_text(url)
        videos = self._parse_list(html)
        return {
            "list": videos,
            "page": pg,
            "pagecount": pg + 1 if len(videos) >= 15 else pg,
            "limit": 36,
            "total": 9999 if videos else 0,
        }

    def _extract_plays(self, html):
        parts, seen = [], set()
        # videoUrl fields
        for m in re.finditer(r'videoUrl["\']?\s*:\s*["\']([^"\']+)["\']', html or ""):
            u = m.group(1).replace("\\/", "/")
            if u in seen or not u.startswith("http"):
                continue
            seen.add(u)
            label = "HD"
            qm = re.search(r"/(\d{3,4})P_", u, re.I)
            if qm:
                label = qm.group(1) + "P"
            elif ".m3u8" in u:
                label = "HLS"
            elif ".mp4" in u:
                label = "MP4"
            parts.append("%s$%s" % (label, u))
        # plain m3u8
        for m in re.finditer(r"https?://[^\"'\s<>]+\.m3u8[^\"'\s<>]*", html or "", re.I):
            u = m.group(0).replace("\\/", "/")
            if u in seen:
                continue
            seen.add(u)
            parts.append("HLS$%s" % u)
        # get_media（可选）
        gm = re.search(
            r'(https?:\\?/\\?/cn\.pornhub163\.net\\?/video\\?/get_media[^"\']+)',
            html or "",
        )
        if not gm:
            gm = re.search(r'(https://cn\.pornhub163\.net/video/get_media[^"\']+)', html or "")
        if gm:
            gurl = gm.group(1).replace("\\/", "/")
            ghtml = self.fetch_text(gurl)
            if ghtml and ghtml.strip()[:1] in "[{":
                try:
                    data = json.loads(ghtml)
                    if isinstance(data, list):
                        for item in data:
                            if not isinstance(item, dict):
                                continue
                            u = (item.get("videoUrl") or "").replace("\\/", "/")
                            if not u or u in seen:
                                continue
                            seen.add(u)
                            q = str(item.get("quality") or "HD")
                            fmt = str(item.get("format") or "")
                            label = (q + "P" if q.isdigit() else q) + (("·" + fmt) if fmt else "")
                            parts.append("%s$%s" % (label, u))
                except Exception:
                    pass
        # 去重保序，清晰度高优先
        def score(p):
            n = p.split("$")[0]
            m = re.search(r"(\d{3,4})", n)
            return int(m.group(1)) if m else 0

        parts = sorted(parts, key=score, reverse=True)
        return parts

    def detailContent(self, ids):
        vk = str((ids or [""])[0]).strip()
        m = re.search(r"viewkey=([a-zA-Z0-9]+)", vk)
        if m:
            vk = m.group(1)
        if not vk:
            return {"list": []}
        # 优先 embed（更易出流）
        html = self.fetch_text(HOST + "/embed/" + vk)
        if len(html) < 5000:
            html = self.fetch_text(HOST + "/view_video.php?viewkey=" + vk)
        name = vk
        pic = ""
        m = re.search(r"<title>([^<]+)</title>", html or "", re.I)
        if m:
            name = self._clean(re.sub(r"\s*[-|].*$", "", m.group(1)))
        m = re.search(r'property=["\']og:title["\'][^>]*content=["\']([^"\']+)', html or "", re.I)
        if m:
            name = self._clean(m.group(1))
        m = re.search(r'property=["\']og:image["\'][^>]*content=["\']([^"\']+)', html or "", re.I)
        if m:
            pic = m.group(1)
        plays = self._extract_plays(html)
        # 播放项用 viewkey，避免 m3u8 签名过期；play 时实时解析
        # 自动原画：只给一个入口，播放时 playerContent 实时解析最高分辨率
        plays = ["原画$%s" % vk]
        # 标题兜底：embed 常为 Embed Player，用列表页名更好
        if not name or name.lower() in ("embed player", "pornhub", vk):
            name = vk
        return {"list": [{
            "vod_id": vk,
            "vod_name": name,
            "vod_pic": pic,
            "vod_remarks": "HD",
            "vod_content": "viewkey: " + vk,
            "vod_play_from": "PH163",
            "vod_play_url": "#".join(plays),
            "style": {"type": "rect", "ratio": 1.5},
        }]}


    def _resolve_m3u8(self, url):
        """把 master.m3u8 解析成媒体播放列表绝对地址"""
        from urllib.parse import urljoin
        u = str(url or '').strip()
        if not u or '.m3u8' not in u:
            return u
        if 'index-v' in u:
            return u
        try:
            cdn_m = re.match(r'https?://([^/]+)', u)
            cdn = cdn_m.group(1) if cdn_m else ''
            headers = {
                'User-Agent': UA,
                'Referer': ('https://%s/' % cdn) if cdn else (HOST + '/'),
                'Accept': '*/*',
            }
            s = self._sess()
            body = ''
            if s is not None:
                r = s.get(u, headers=headers, timeout=15, verify=False)
                body = r.text or ''
            else:
                body = self.fetch_text(u)
            if body and '#EXT-X-STREAM-INF' in body:
                for ln in body.splitlines():
                    ln = ln.strip()
                    if ln and not ln.startswith('#'):
                        return urljoin(u, ln)
        except Exception as e:
            print('resolve m3u8 err', e)
        return u

    def playerContent(self, flag, id, vipFlags=None):
        # 实时解析，优先 MP4，其次媒体 m3u8（非 master）
        play = str(id or '').strip()
        if '$' in play:
            play = play.split('$')[-1].strip()
        vk = play
        m = re.search(r'viewkey=([a-zA-Z0-9]+)', play)
        if m:
            vk = m.group(1)
        elif re.match(r'^[a-zA-Z0-9]+$', play) and 'http' not in play:
            vk = play
        elif play.startswith('http') and re.search(r'\.(m3u8|mp4)(\?|$)', play, re.I):
            u = play
            if '.m3u8' in u:
                u = self._resolve_m3u8(u)
            cdn_m = re.match(r'https?://([^/]+)', u)
            cdn = cdn_m.group(1) if cdn_m else ''
            header = {
                'User-Agent': UA,
                'Referer': ('https://%s/' % cdn) if cdn else (HOST + '/'),
                'Accept': '*/*',
            }
            return {
                'parse': 0, 'jx': 0, 'url': u, 'header': header,
                'format': 'application/x-mpegURL' if '.m3u8' in u.lower() else 'video/mp4',
            }
        else:
            vk = re.sub(r'[^a-zA-Z0-9]', '', play)

        html = self.fetch_text(HOST + '/embed/' + vk)
        if '站点维护' in (html or '') or len(html or '') < 1000:
            html = self.fetch_text(HOST + '/view_video.php?viewkey=' + vk)

        candidates = []  # (score, label, url)
        # 1) get_media
        gm = re.search(r'(https://cn\.pornhub163\.net/video/get_media[^"\']+)', (html or '').replace('\\/', '/'))
        if gm:
            ghtml = self.fetch_text(gm.group(1))
            if ghtml and ghtml.strip()[:1] in '[{':
                try:
                    data = json.loads(ghtml)
                    if isinstance(data, list):
                        for item in data:
                            if not isinstance(item, dict):
                                continue
                            u = (item.get('videoUrl') or '').replace('\\/', '/')
                            if not u:
                                continue
                            q = str(item.get('quality') or item.get('height') or '0')
                            try:
                                qi = int(re.search(r'\d+', q).group()) if re.search(r'\d+', q) else 0
                            except Exception:
                                qi = 0
                            fmt = str(item.get('format') or '')
                            lab = (str(qi) + 'P') if qi else 'HD'
                            if fmt:
                                lab += '·' + fmt
                            candidates.append((qi, 1 if '.m3u8' in u else 0, lab, u))
                except Exception as e:
                    print('get_media err', e)
        # 2) embed videoUrl
        for mm in re.finditer(r'videoUrl["\']?\s*:\s*["\']([^"\']+)["\']', html or ''):
            u = mm.group(1).replace('\\/', '/')
            if not u.startswith('http'):
                continue
            qm = re.search(r'/(\d{3,4})P_', u, re.I)
            qi = int(qm.group(1)) if qm else 480
            lab = str(qi) + 'P'
            candidates.append((qi, 1 if '.m3u8' in u else 0, lab, u))
        if not candidates:
            page = HOST + '/view_video.php?viewkey=' + vk
            return {'parse': 1, 'jx': 0, 'url': page, 'header': {
                'User-Agent': UA, 'Referer': HOST + '/',
            }}

        # 分辨率优先，同分辨率 m3u8 优先；也就是自动选最高原画
        candidates.sort(key=lambda x: (x[0], x[1]), reverse=True)
        chosen = candidates[0]

        # 只有 flag 明确带 720/1080 这种数字时才按清晰度匹配
        if flag and re.search(r'\d{3,4}', str(flag)):
            for c in candidates:
                if str(flag).split('·')[0] in c[2]:
                    chosen = c
                    break

        u = chosen[3]
        if '.m3u8' in u:
            u = self._resolve_m3u8(u)
        cdn_m = re.match(r'https?://([^/]+)', u)
        cdn = cdn_m.group(1) if cdn_m else ''
        header = {
            'User-Agent': UA,
            'Referer': ('https://%s/' % cdn) if cdn else (HOST + '/embed/' + vk),
            'Accept': '*/*',
        }
        # 不带 Origin，部分播放器会因 CORS/Origin 失败
        return {
            'parse': 0, 'jx': 0, 'url': u, 'header': header,
            'format': 'application/x-mpegURL' if '.m3u8' in u.lower() else 'video/mp4',
        }


    def isVideoFormat(self, url):
        return bool(url and re.search(r"\.(mp4|m3u8)(\?|$)", str(url), re.I))

    def manualVideoCheck(self):
        return False

    def localProxy(self, param):
        return None


if __name__ == "__main__":
    sp = Spider()
    sp.init()
    print("home", [c["type_name"] for c in sp.homeContent(False)["class"][:6]])
    hv = sp.homeVideoContent()
    print("homeVod", len(hv.get("list") or []))
    if hv.get("list"):
        print(" first", hv["list"][0].get("vod_name")[:40])
        d = sp.detailContent([hv["list"][0]["vod_id"]])
        main = (d.get("list") or [{}])[0]
        print("detail", main.get("vod_name"), (main.get("vod_play_url") or "")[:100])
        pu = (main.get("vod_play_url") or "").split("#")[0]
        if "$" in pu:
            p = sp.playerContent("PH163", pu.split("$", 1)[1], [])
            print("play", p.get("parse"), str(p.get("url"))[:90])
