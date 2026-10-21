# -*- coding: utf-8 -*-
"""
黑料718 TVBox 爬虫 - 海报终极方案
=========================================================
核心策略：
  1. 图片请求逐字模拟浏览器 fetch（完整 CORS 头：Origin/Referer/Sec-Fetch-*）
  2. 多条域名+路径组合探测，第一个有效即固化
  3. weserv 第三方图片代理兜底（Cloudflare 信任，通常能过防盗链）
  4. 全失败返回 1x1 透明 PNG

【TVBox 日志会打印】
  [probe] pass.saxinx.cn/hl718/... -> 200 ✅图片 len=84210
  [probe] 采用: pass.saxinx.cn+fetch-cors
  [img] ✅ fetch-cors 命中 len=84210

  或：
  [probe] pass.saxinx.cn -> 200 ❌非图片 ct=text/html len=157
  [weserv] pass.saxinx.cn ✅ len=84210
"""

import base64
import json
import re
import sys
import threading
import time
import urllib.parse

import requests

try:
    if '..' not in sys.path:
        sys.path.append('..')
    from base.spider import Spider as _BaseSpider
except Exception:
    _BaseSpider = object


# ============================ 配置 ============================
SITE = "https://clash.windowheiliao.com"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36")

_TRANSPARENT_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII="
)

CATEGORIES = [
    ("每日黑料", "daily-gossip"),
    ("黑料热榜", "top-stories"),
    ("娱乐黑料", "entertainment-news"),
    ("明星黑料", "celebrity-scandals"),
    ("黑料精华", "hljh"),
    ("网黄合集", "wanghuang"),
    ("网红吃瓜", "internet-celebrities"),
    ("福利姬料", "model-photos"),
    ("每日大赛", "daily-contest"),
    ("社会吃瓜", "trending-news"),
    ("反差婊们", "contrast-reveal"),
    ("真实乱伦", "zsll"),
    ("AI短剧成人", "AICG"),
]


def _clean(text):
    t = re.sub(r"<[^>]+>", " ", text or "")
    return re.sub(r"\s+", " ", t).strip()


def _from_pyquery(html):
    try:
        from pyquery import PyQuery as pq
        return pq(html)
    except Exception:
        return None


class Spider(_BaseSpider):

    def __init__(self):
        self.name = "黑料718"
        self.host = SITE
        self.timeout = 15
        self.categories = [{"type_id": slug, "type_name": name} for name, slug in CATEGORIES]

        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": UA,
            "Referer": SITE + "/",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9",
            "Connection": "keep-alive",
        })
        self.session.verify = False
        try:
            import urllib3
            urllib3.disable_warnings()
        except Exception:
            pass

        self.proxies = {}
        self._home_html = ""
        self._home_ts = 0
        self._img_strategy = None
        self._img_lock = threading.Lock()

    def init(self, extend=""):
        try:
            self.proxies = json.loads(extend) if extend else {}
        except Exception:
            self.proxies = {}
        print(f"[init] 配置代理: {self.proxies or '无'}")

    def getName(self):
        return "黑料718"

    def destroy(self):
        try:
            self.session.close()
        except Exception:
            pass

    def getDependence(self):
        return []

    def isVideoFormat(self, url):
        return any(ext in (url or "") for ext in [".m3u8", ".mp4", ".ts"])

    def manualVideoCheck(self):
        return False

    # ---------------- GET 加速 ----------------
    def _fetch(self, url, retries=2):
        for i in range(retries):
            try:
                r = self.session.get(url, timeout=self.timeout,
                                     proxies=self.proxies or None)
                if r.status_code == 200:
                    return r.text
            except Exception:
                if i < retries - 1:
                    time.sleep(0.3)
        return ""

    def _get_home(self):
        now = time.time()
        if self._home_html and now - self._home_ts < 300:
            return self._home_html
        self._home_html = self._fetch(SITE + "/")
        self._home_ts = now
        return self._home_html

    # ---------------- 图片 URL 规范化为 相对路径 编码 ----------------
    def _normalize_img(self, url):
        """存成 'rel:hl718/...' 的 base64 形式，实际域名在 localProxy 里探测"""
        url = (url or "").strip()
        if not url or "${" in url:
            return ""
        if url.startswith("//"):
            url = "https:" + url
        if url.startswith("http"):
            from urllib.parse import urlparse
            rel = urlparse(url).path.lstrip("/")
        elif url.startswith("/hl718/") or url.startswith("hl718/"):
            rel = url.lstrip("/")
        elif url.startswith("/"):
            rel = url.lstrip("/")
        else:
            rel = url
        # 用 "rel:" 前缀标记，避免 localProxy 还要判断
        encoded = self.e64("rel:" + rel)
        return f"{self.getProxyUrl()}&url={encoded}&type=img"

    # ---------------- 列表解析 ----------------
    def _parse_list(self, html):
        vods = []
        seen = set()
        if not html:
            return vods
        doc = _from_pyquery(html)
        if doc is None:
            return vods

        for art in doc("article").items():
            try:
                art_html = art.html() or ""
            except Exception:
                continue
            if 'rel="sponsored' in art_html:
                continue
            mid = re.search(r"/archives/(\d+)", art_html)
            if not mid:
                continue
            aid = mid.group(1)
            if aid in seen:
                continue
            h2 = art("h2.post-card-title").eq(0)
            if not h2 or not h2.text():
                h2 = art("h2").eq(0)
            if not h2 or not h2.text():
                continue
            name = _clean(h2.text())
            if not name:
                continue

            pic = ""
            for sel, attr in (
                ('meta[itemprop="image"]', 'content'),
                ('[data-pic]', 'data-pic'),
                ('img[data-src]', 'data-src'),
                ('img[src]', 'src'),
            ):
                el = art(sel).eq(0)
                if not el:
                    continue
                v = (el.attr(attr) or "").strip()
                if v and "${" not in v and not v.startswith("data:"):
                    pic = self._normalize_img(v)
                    break

            seen.add(aid)
            vods.append({
                "vod_id": aid,
                "vod_name": name,
                "vod_pic": pic,
                "vod_remarks": "",
            })
        return vods

    # ---------------- TVBox 接口 ----------------
    def homeContent(self, filter=True):
        try:
            html = self._get_home()
            vods = self._parse_list(html)
        except Exception as e:
            print(f"homeContent error: {e}")
            vods = []
        return {"class": self.categories, "list": vods[:30]}

    def homeVideoContent(self):
        try:
            html = self._get_home()
            return {"list": self._parse_list(html)[:30]}
        except Exception:
            return {"list": []}

    def categoryContent(self, tid, pg=1, filter=1, extend=None):
        try:
            pg = int(pg)
        except Exception:
            pg = 1
        if not tid or tid == "home":
            url = SITE + ("/page/%d/" % pg if pg > 1 else "/")
        else:
            url = SITE + ("/category/%s/" % tid if pg == 1
                          else "/category/%s/%d/" % (tid, pg))

        html = ""
        try:
            html = self._fetch(url)
            vods = self._parse_list(html)
        except Exception as e:
            print(f"categoryContent error: {e}")
            vods = []

        total_pages = 999
        if html:
            doc = _from_pyquery(html)
            if doc is not None:
                pinfo = doc('.page-jump .page-info').text() or ''
                if '/' in pinfo:
                    try:
                        total_pages = int(pinfo.split('/')[-1].strip())
                    except Exception:
                        pass
                if total_pages == 999:
                    mx = (doc('#pageNum').attr('max') or '').strip()
                    if mx.isdigit():
                        total_pages = int(mx)

        return {
            "list": vods,
            "page": pg,
            "pagecount": total_pages,
            "total": total_pages * 30 if total_pages > 0 else 0,
            "limit": 30,
        }

    def detailContent(self, ids):
        aid = ids[0] if isinstance(ids, (list, tuple)) else str(ids)
        aid = str(aid)
        html = ""
        try:
            html = self._fetch(SITE + "/archives/%s" % aid)
        except Exception:
            pass
        if not html:
            return {"list": [{
                "vod_id": aid, "vod_name": "详情获取失败", "vod_pic": "",
                "vod_play_from": "黑料", "vod_play_url": "",
                "vod_remarks": "详情页无法访问",
            }]}

        title = ""
        tm = re.search(r"<title>([^<]+)</title>", html)
        if tm:
            title = _clean(tm.group(1)).split(" - ")[0]

        pic = ""
        for pat in (r'itemprop="image" content="([^"]+)"',
                    r'data-pic=["\']([^"\']+)["\']'):
            im = re.search(pat, html)
            if im and "${" not in im.group(1):
                pic = self._normalize_img(im.group(1))
                break

        sources = []
        for cfg in re.findall(r"data-config='(\{.*?\})'", html, re.S):
            try:
                d = json.loads(cfg)
            except Exception:
                continue
            v = d.get("video", {}) or {}
            url = v.get("url2") or v.get("url")
            if url and url not in sources:
                sources.append(url)
        if not sources:
            sources = re.findall(r'(https?://[^\s"\'<>]+\.m3u8[^\s"\'<>]*)', html)

        if not sources:
            return {"list": [{
                "vod_id": aid, "vod_name": title or "图文内容", "vod_pic": pic,
                "vod_play_url": "", "vod_remarks": "该条为图文, 无视频源",
            }]}

        episodes = ["第%d集$%s" % (i, s) for i, s in enumerate(sources, 1)]
        return {"list": [{
            "vod_id": aid, "vod_name": title, "vod_pic": pic,
            "vod_play_from": "黑料",
            "vod_play_url": "#".join(episodes),
            "vod_remarks": "%d个视频" % len(sources),
        }]}

    def searchContent(self, key, quick=False, pg=1):
        try:
            pg = int(pg)
        except Exception:
            pg = 1
        q = urllib.parse.quote(key)
        url = (SITE + "/search/%s/" % q) if pg == 1 else (SITE + "/search/%s/%d/" % (q, pg))
        try:
            html = self._fetch(url)
            vods = self._parse_list(html)
        except Exception:
            vods = []
        return {"list": vods, "page": pg, "pagecount": 50, "total": 50 * 30, "limit": 30}

    def playerContent(self, flag, id, vipFlags=None):
        return {
            "parse": 0,
            "url": id,
            "header": {"User-Agent": UA, "Referer": SITE + "/"},
        }

    # ==================== 图片代理核心 ====================
    def localProxy(self, param):
        t = param.get("type")
        if t == "img":
            return self._img_proxy(param)
        if t == "m3u8":
            return self.m3Proxy(param["url"])
        return self.tsProxy(param["url"])

    def _img_proxy(self, param):
        encoded = param.get("url") or ""
        # 解码
        try:
            decoded = self.d64(encoded) if not encoded.startswith("rel:") else encoded
        except Exception:
            decoded = encoded

        # 提取相对路径
        if decoded.startswith("rel:"):
            rel = decoded[4:]
        elif decoded.startswith("http"):
            from urllib.parse import urlparse
            rel = urlparse(decoded).path.lstrip("/")
        else:
            rel = decoded.lstrip("/")

        if not rel:
            return [200, "image/png", _TRANSPARENT_PNG]

        # 用缓存策略
        with self._img_lock:
            strat = self._img_strategy

        if strat:
            content = self._apply_strategy(rel, strat)
            if content:
                return [200, "image/webp", content]
            print(f"[img] 缓存策略失效，重新探测")
            with self._img_lock:
                self._img_strategy = None

        # 探测
        content, strat = self._probe(rel)
        if content:
            with self._img_lock:
                self._img_strategy = strat
            print(f"[img] ✅ 采用 {strat['label']} -> len={len(content)}")
            return [200, "image/webp", content]

        # weserv 兜底
        content = self._try_weserv(rel)
        if content:
            with self._img_lock:
                self._img_strategy = {"is_weserv": True, "label": "weserv"}
            print(f"[img] ✅ weserv 成功 -> len={len(content)}")
            return [200, "image/webp", content]

        print(f"[img] ❌ 全部失败，返回透明占位")
        return [200, "image/png", _TRANSPARENT_PNG]

    # ---------------- 完整浏览器 fetch 头（对照抓包逐字复制） ----------------
    def _h_fetch_cors(self):
        return {
            "User-Agent": UA,
            "Accept": "*/*",
            "Accept-Language": "zh-CN,zh;q=0.9",
            "Origin": "https://clash.windowheiliao.com",
            "Referer": "https://clash.windowheiliao.com/category/internet-celebrities/5/",
            "Sec-Ch-Ua": '"Not A(Brand";v="8", "Chromium";v="132", "Google Chrome";v="132"',
            "Sec-Ch-Ua-Mobile": "?0",
            "Sec-Ch-Ua-Platform": '"Windows"',
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "cross-site",
        }

    def _h_img_minimal(self):
        return {
            "User-Agent": UA,
            "Referer": SITE + "/",
            "Accept": "image/webp,image/*,*/*;q=0.8",
        }

    # ---------------- 探测：多域名 × 多路径 × 多头 ----------------
    def _probe(self, rel):
        # 域名
        domains = [
            "https://pass.saxinx.cn/",
            "https://www.hl718.com/",
            "https://hl718.com/",
        ]
        html = self._home_html or ""
        for d in re.findall(r'https?://([a-z0-9.-]+\.saxinx\.cn)', html, re.I):
            u = f"https://{d}/"
            if u not in domains:
                domains.append(u)

        # 路径前缀（针对 rel 已含 hl718/... 的情况，可能真实路径还有一层）
        prefixes = ["", "usr/uploads/", "usr/upload/", "upload/", "uploads/", "usr/"]

        headers = self._h_fetch_cors()
        proxies = self.proxies or None

        tried = 0
        for dom in domains:
            for pre in prefixes:
                # 避免重复
                if rel.startswith(pre) and pre:
                    continue
                url = dom + pre + rel
                host = dom.split("//")[1].rstrip("/")
                label = f"{host}/{pre}{rel}" if pre else f"{host}/{rel}"
                tried += 1

                try:
                    r = requests.get(url, headers=headers, proxies=proxies,
                                     timeout=8, verify=False)
                    ct = (r.headers.get("content-type") or "").lower()
                    valid = self._is_image(r.content)
                    short = label[:60]
                    if valid:
                        print(f"[probe] {short} -> 200 ✅图片 len={len(r.content)}")
                        return r.content, {
                            "url": url, "headers": headers,
                            "proxies": proxies,
                            "label": f"{host}+fetch-cors",
                        }
                    print(f"[probe] {short} -> {r.status_code} ❌ ct={ct[:20]} len={len(r.content)}")
                except Exception as e:
                    print(f"[probe] {label[:60]} -> {type(e).__name__}: {str(e)[:40]}")

                if tried >= 18:  # 防止太长
                    break
            if tried >= 18:
                break

        return None, None

    def _apply_strategy(self, rel, strat):
        if strat.get("is_weserv"):
            return self._try_weserv(rel)
        try:
            r = requests.get(strat["url"], headers=strat["headers"],
                             proxies=strat["proxies"],
                             timeout=10, verify=False)
            if r.status_code == 200 and self._is_image(r.content):
                return r.content
        except Exception:
            pass
        return None

    def _try_weserv(self, rel):
        candidates = [
            "https://pass.saxinx.cn/" + rel,
            "https://www.hl718.com/" + rel,
        ]
        for src in candidates:
            wurl = f"https://images.weserv.nl/?url={urllib.parse.quote(src, safe='')}&w=400"
            try:
                r = requests.get(wurl, timeout=15, verify=False,
                                 proxies=self.proxies or None)
                if r.status_code == 200 and self._is_image(r.content):
                    print(f"[weserv] {src.split('//')[1][:40]} ✅ len={len(r.content)}")
                    return r.content
                print(f"[weserv] {src.split('//')[1][:40]} -> {r.status_code} ct={r.headers.get('content-type','')[:20]}")
            except Exception as e:
                print(f"[weserv] {src.split('//')[1][:40]} -> {type(e).__name__}")
        return None

    def _is_image(self, content):
        if not content or len(content) < 100:
            return False
        if content[:4] == b'RIFF' and content[8:12] == b'WEBP':
            return True
        if content[:8] == b'\x89PNG\r\n\x1a\n':
            return True
        if content[:3] == b'\xff\xd8\xff':
            return True
        if content[:6] in (b'GIF87a', b'GIF89a'):
            return True
        return False

    # ==================== M3U8 / TS ====================
    def proxy(self, data, type="m3u8"):
        if type == "img":
            return f"{self.getProxyUrl()}&url={self.e64(data)}&type=img"
        if data and len(getattr(self, "proxies", {})) > 0:
            return f"{self.getProxyUrl()}&url={self.e64(data)}&type={type}"
        return data

    def m3Proxy(self, url):
        url = self.d64(url)
        try:
            ydata = self.session.get(url, allow_redirects=False, timeout=15,
                                     proxies=self.proxies or None)
            data = ydata.content.decode("utf-8", "ignore")
            if ydata.headers.get("Location"):
                url = ydata.headers["Location"]
                data = self.session.get(url, timeout=15,
                                        proxies=self.proxies or None).content.decode("utf-8", "ignore")
        except Exception:
            return [500, "text/plain", b""]

        from urllib.parse import urlparse
        lines = data.strip().split("\n")
        last_r = url[:url.rfind("/")]
        parsed = urlparse(url)
        durl = parsed.scheme + "://" + parsed.netloc
        iskey = True
        for i, s in enumerate(lines):
            if iskey and "URI" in s:
                m = re.search(r'URI="([^"]*)"', s)
                if m:
                    lines[i] = re.sub(r'URI="([^"]*)"',
                                      f'URI="{self.proxy(m.group(1), "mkey")}"', s)
                    iskey = False
                    continue
            if "#EXT" not in s:
                if "http" not in s:
                    domain = last_r if s.count("/") < 2 else durl
                    s = domain + ("" if s.startswith("/") else "/") + s
                lines[i] = self.proxy(s, s.split(".")[-1].split("?")[0])
        return [200, "application/vnd.apple.mpegur", "\n".join(lines)]

    def tsProxy(self, url):
        url = self.d64(url)
        try:
            r = self.session.get(url, timeout=15, proxies=self.proxies or None)
            return [200, r.headers.get("Content-Type", "video/mp2t"), r.content]
        except Exception:
            return [500, "text/plain", b""]

    # ==================== Base64 ====================
    def e64(self, text):
        try:
            return base64.b64encode(text.encode("utf-8")).decode("utf-8")
        except Exception:
            return ""

    def d64(self, text):
        try:
            return base64.b64decode(text.encode("utf-8")).decode("utf-8")
        except Exception:
            return ""
