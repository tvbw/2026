# -*- coding: utf-8 -*-
"""
黑料718 TVBox 爬虫 - 修复版
=========================================================
基于原版结构做以下修复：
  1. 封面：相对路径 hl718/... 正确拼 host；走本地代理带 Referer 绕过 Cloudflare 防盗链
  2. 分类翻页：改用 path 式 /category/slug/N/，与真实 HTML 一致
  3. 页码：优先读 .page-info "5/55" 或 #pageNum[max]，精确取总页数
  4. 加速：requests.Session 复用连接 + 首页 5 分钟缓存 + 重试 sleep 从 1.5s 降至 0.3s
  5. 播放：明确 parse=0，让 TVBox 直接拉 m3u8
  6. 列表解析：改用 PyQuery（比逐条正则快且稳）
"""

import re
import json
import sys
import time
import urllib.parse

import requests

try:
    if '..' not in sys.path:
        sys.path.append('..')
    from base.spider import Spider as _BaseSpider
except Exception:
    _BaseSpider = object


# ============================ 基础配置 ============================
SITE = "https://clash.windowheiliao.com"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

# ===== 图片 =====
# True: 走本地代理带 Referer（推荐，绕过 Cloudflare 防盗链）
# False: 直连原图 URL（能显示就更快）
IMG_PROXY = True
# 图片是否需要 AES 解密：黑料718=False; 51bl=True
IMG_AES = False
AES_KEY = b"f5d965df75336270"
AES_IV = b"97b60394abc2fbe1"

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


# ============================ Spider 类 ============================
class Spider(_BaseSpider):

    def __init__(self):
        self.name = "黑料718"
        self.host = SITE
        self.ua = UA
        self.timeout = 15
        self.categories = [{"type_id": slug, "type_name": name} for name, slug in CATEGORIES]

        # Session 复用连接（加速关键）
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": UA,
            "Referer": SITE + "/",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9",
            "Connection": "keep-alive",
        })
        self.session.verify = False

        # 首页缓存
        self._home_html = ""
        self._home_ts = 0

    # ---------------- 元信息 / 生命周期 ----------------
    def getName(self):
        return "黑料718"

    def init(self, extend=""):
        return None

    def destroy(self):
        try:
            self.session.close()
        except Exception:
            pass

    def getDependence(self):
        return []

    def isVideoFormat(self, url):
        u = url or ""
        return ".m3u8" in u or ".mp4" in u

    def manualVideoCheck(self):
        return False

    # ---------------- 加速：缓存 GET ----------------
    def _fetch(self, url, retries=2):
        for i in range(retries):
            try:
                r = self.session.get(url, timeout=self.timeout)
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

    # ---------------- 图片 URL 规范化 + 代理 ----------------
    def _normalize_img(self, url):
        """
        - 'hl718/xxx/cover.webp'  -> host 拼接
        - '/xxx'                  -> host 拼接
        - '//xxx'                 -> https 前缀
        - 'http(s)://xxx'         -> 原样
        最终按 IMG_PROXY 决定是否走本地代理
        """
        url = (url or "").strip()
        if not url or "${" in url:
            return ""
        if url.startswith("//"):
            url = "https:" + url
        elif url.startswith("http"):
            pass
        elif url.startswith("/"):
            url = self.host.rstrip("/") + url
        else:
            # 关键修复：纯相对路径 hl718/... 需要补 "/"
            url = self.host.rstrip("/") + "/" + url

        if IMG_PROXY:
            # 走本地代理，服务端带 Referer 请求
            return f"{self.getProxyUrl()}&url={self.e64(url)}&type=img"
        return url

    # ---------------- 列表解析（PyQuery 加速） ----------------
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

            # 标题
            h2 = art("h2.post-card-title").eq(0)
            if not h2 or not h2.text():
                h2 = art("h2").eq(0)
            if not h2 or not h2.text():
                continue
            name = _clean(h2.text())
            if not name:
                continue

            # 封面：meta itemprop=image > [data-pic] > img
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

    # ---------------- TVBox 五大接口 ----------------
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

        # 首页 / 分类 URL
        if not tid or tid == "home":
            url = SITE + ("/page/%d/" % pg if pg > 1 else "/")
        else:
            # path 式，与 HTML 一致
            url = SITE + ("/category/%s/" % tid if pg == 1
                          else "/category/%s/%d/" % (tid, pg))

        html = ""
        try:
            html = self._fetch(url)
            vods = self._parse_list(html)
        except Exception as e:
            print(f"categoryContent error: {e}")
            vods = []

        # 精确页码：.page-info "5/55" 优先，其次 #pageNum[max]
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

        # 标题
        title = ""
        tm = re.search(r"<title>([^<]+)</title>", html)
        if tm:
            title = _clean(tm.group(1)).split(" - ")[0]

        # 封面
        pic = ""
        for pat in (r'itemprop="image" content="([^"]+)"',
                    r'data-pic=["\']([^"\']+)["\']'):
            im = re.search(pat, html)
            if im and "${" not in im.group(1):
                pic = self._normalize_img(im.group(1))
                break

        # 视频源
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
        # 关键修复：明确 parse=0 直接播放
        return {
            "parse": 0,
            "url": id,
            "header": {
                "User-Agent": UA,
                "Referer": SITE + "/",
            },
        }

    # ---------------- 本地代理（图片/视频流） ----------------
    def localProxy(self, param):
        t = param.get("type")
        if t == "img":
            try:
                # 关键：带 Referer 请求原图，绕过防盗链
                res = self.session.get(param["url"], timeout=10)
                content = res.content
                if IMG_AES:
                    try:
                        content = self.aesimg(content)
                    except Exception:
                        pass
                ct = res.headers.get("Content-Type", "image/jpeg")
                return [200, ct, content]
            except Exception as e:
                print(f"img proxy error: {e}")
                return [404, "text/plain", b""]
        if t == "m3u8":
            return self.m3Proxy(param["url"])
        return self.tsProxy(param["url"])

    def proxy(self, data, type="m3u8"):
        # 图片无条件走代理
        if type == "img":
            return f"{self.getProxyUrl()}&url={self.e64(data)}&type=img"
        # m3u8/ts 仅在用户配了代理时走
        if data and len(getattr(self, "proxies", {})) > 0:
            return f"{self.getProxyUrl()}&url={self.e64(data)}&type={type}"
        return data

    def m3Proxy(self, url):
        url = self.d64(url)
        try:
            ydata = self.session.get(url, allow_redirects=False, timeout=15)
            data = ydata.content.decode("utf-8", "ignore")
            if ydata.headers.get("Location"):
                url = ydata.headers["Location"]
                data = self.session.get(url, timeout=15).content.decode("utf-8", "ignore")
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
            r = self.session.get(url, timeout=15)
            return [200, r.headers.get("Content-Type", "video/mp2t"), r.content]
        except Exception:
            return [500, "text/plain", b""]

    # ---------------- Base64 ----------------
    def e64(self, text):
        from base64 import b64encode
        try:
            return b64encode(text.encode("utf-8")).decode("utf-8")
        except Exception:
            return ""

    def d64(self, text):
        from base64 import b64decode
        try:
            return b64decode(text.encode("utf-8")).decode("utf-8")
        except Exception:
            return ""

    def aesimg(self, word):
        from Crypto.Cipher import AES
        from Crypto.Util.Padding import unpad
        cipher = AES.new(AES_KEY, AES.MODE_CBC, AES_IV)
        return unpad(cipher.decrypt(word), AES.block_size)


if __name__ == "__main__":
    _sp = Spider()
    print("== getName:", _sp.getName())
    _h = _sp.homeContent()
    print("   分类数:", len(_h.get("class", [])), " 推荐数:", len(_h.get("list", [])))
    if _h.get("list"):
        print("   第一张封面代理URL:", _h["list"][0]["vod_pic"][:120])
    print("== categoryContent(internet-celebrities, 5) ==")
    _c = _sp.categoryContent("internet-celebrities", 5)
    print("   数量:", len(_c.get("list", [])), " page:", _c.get("page"),
          " pagecount:", _c.get("pagecount"))
    if _c.get("list"):
        print("   第一张封面代理URL:", _c["list"][0]["vod_pic"][:120])
